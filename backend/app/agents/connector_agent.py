"""ConnectorAgent — the headline agent that generates cross-company theses."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.config import settings
from app.db.models import Company, ExtractedFact, Filing, FilingDelta
from app.db.repositories.company_repo import CompanyRepository
from app.db.repositories.graph_repo import GraphRepository
from app.schemas.thesis import (
    EvidenceStep,
    ThesisCreate,
    ThesisDirection,
    ThesisType,
)


class ConnectorAgent(BaseAgent):
    """The 'mosaic' agent: traverses the graph and synthesises a thesis."""

    PROMPT = "connector.j2"

    async def generate_thesis(
        self,
        trigger_delta: FilingDelta,
        trigger_company: Company,
        connected_companies: list[dict[str, Any]],
        session: AsyncSession,
        market_context: str = "No external market context available.",
    ) -> ThesisCreate | None:
        if not connected_companies:
            self.log.info(
                "connector_no_neighbors", trigger_ticker=trigger_company.ticker
            )
            return None

        # Hydrate recent facts for each neighbor (LLM input).
        enriched = []
        for neighbor in connected_companies:
            facts = await self._recent_facts_for_company(session, neighbor["company_id"])
            enriched.append(
                {
                    "ticker": neighbor["ticker"],
                    "name": neighbor["name"],
                    "relationship_type": neighbor["relationship_type"],
                    "degree": neighbor.get("degree", 1),
                    "recent_facts": [
                        {
                            "fact_type": f.fact_type,
                            "value": f.value,
                            "source_text": (f.source_text or "")[:200],
                            "source_filing": (
                                f"filing:{f.filing_id}" if f.filing_id else "unknown"
                            ),
                        }
                        for f in facts
                    ],
                }
            )

        prompt = self.render_prompt(
            self.PROMPT,
            trigger_company_name=trigger_company.name,
            trigger_ticker=trigger_company.ticker,
            delta_type=trigger_delta.delta_type,
            delta_description=trigger_delta.description,
            evidence_text=trigger_delta.current_text or trigger_delta.previous_text or "",
            period=str(trigger_delta.created_at.date()),
            connected_companies=enriched,
            market_context=market_context,
        )

        try:
            raw = await self.call_claude(prompt, max_tokens=4096)
        except Exception as e:  # noqa: BLE001
            self.log.error(
                "connector_call_failed",
                trigger_ticker=trigger_company.ticker,
                error=str(e),
            )
            return None

        parsed = self.parse_json_response(raw)
        if not isinstance(parsed, dict):
            self.log.warning(
                "connector_parse_failed",
                trigger_ticker=trigger_company.ticker,
                raw_preview=raw[:200] if raw else "",
            )
            return None

        if parsed.get("reject") is True:
            self.log.info(
                "connector_rejected",
                trigger_ticker=trigger_company.ticker,
                reason=parsed.get("reason"),
            )
            return None

        if not self.quality_gate(parsed):
            self.log.info(
                "connector_quality_gate_failed",
                trigger_ticker=trigger_company.ticker,
                confidence=parsed.get("confidence_score"),
            )
            return None

        return await self._build_thesis(
            parsed=parsed,
            trigger_delta=trigger_delta,
            trigger_company=trigger_company,
            session=session,
        )

    @staticmethod
    def quality_gate(thesis_json: dict[str, Any]) -> bool:
        """Reject low-quality theses before they reach the user."""
        if not isinstance(thesis_json, dict):
            return False
        try:
            confidence = float(thesis_json.get("confidence_score", 0))
        except (TypeError, ValueError):
            return False
        if confidence < settings.THESIS_MIN_CONFIDENCE:
            return False
        evidence = thesis_json.get("evidence_chain") or []
        if not isinstance(evidence, list) or len(evidence) == 0:
            return False
        invalidation = thesis_json.get("invalidation_criteria") or []
        if not isinstance(invalidation, list) or len(invalidation) == 0:
            return False
        if not (thesis_json.get("title") and thesis_json.get("summary")):
            return False
        return True

    async def _recent_facts_for_company(
        self, session: AsyncSession, company_id: uuid.UUID, limit: int = 8
    ) -> list[ExtractedFact]:
        stmt = (
            select(ExtractedFact)
            .where(ExtractedFact.company_id == company_id)
            .order_by(desc(ExtractedFact.created_at))
            .limit(limit)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def _build_thesis(
        self,
        parsed: dict[str, Any],
        trigger_delta: FilingDelta,
        trigger_company: Company,
        session: AsyncSession,
    ) -> ThesisCreate | None:
        company_repo = CompanyRepository(session)
        affected_tickers = parsed.get("affected_tickers") or []
        affected_ids: list[uuid.UUID] = []
        for tk in affected_tickers:
            if not isinstance(tk, str):
                continue
            c = await company_repo.get_by_ticker(tk)
            if c is not None:
                affected_ids.append(c.id)

        evidence_steps: list[EvidenceStep] = []
        for i, step in enumerate(parsed.get("evidence_chain") or [], start=1):
            if not isinstance(step, dict):
                continue
            try:
                evidence_steps.append(
                    EvidenceStep(
                        step=int(step.get("step", i)),
                        description=step.get("description", "")[:1000],
                        source_company=step.get("source_company", "")[:50],
                        source_filing=step.get("source_filing", "")[:200],
                        quote=(step.get("quote", "") or "")[:500],
                    )
                )
            except Exception as e:  # noqa: BLE001
                self.log.warning("connector_evidence_step_skipped", error=str(e))

        try:
            return ThesisCreate(
                title=parsed["title"][:500],
                summary=parsed["summary"],
                thesis_type=ThesisType(parsed["thesis_type"]),
                direction=ThesisDirection(parsed["direction"]),
                confidence_score=float(parsed["confidence_score"]),
                trigger_company_id=trigger_company.id,
                affected_company_ids=affected_ids,
                evidence_chain=evidence_steps,
                competing_thesis=parsed.get("competing_thesis"),
                invalidation_criteria=[
                    str(c)[:500]
                    for c in (parsed.get("invalidation_criteria") or [])
                    if c
                ],
                catalyst=parsed.get("catalyst"),
                time_horizon=parsed.get("time_horizon"),
                trigger_delta_ids=[trigger_delta.id],
                trigger_fact_ids=[],
            )
        except (KeyError, ValueError) as e:
            self.log.warning("connector_thesis_build_failed", error=str(e))
            return None
