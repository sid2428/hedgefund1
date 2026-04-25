"""PipelineOrchestrator — wires the four agents into an end-to-end pipeline."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.connector_agent import ConnectorAgent
from app.agents.delta_agent import DeltaAgent
from app.agents.extractor_agent import ExtractorAgent
from app.agents.graph_agent import GraphAgent
from app.config import settings
from app.data.preprocessor import preprocess_filing
from app.db.models import (
    AgentJob,
    Company,
    ExtractedFact,
    Filing,
    FilingDelta,
    Thesis,
)
from app.db.repositories.company_repo import CompanyRepository
from app.db.repositories.filing_repo import FilingRepository
from app.db.repositories.graph_repo import GraphRepository
from app.db.repositories.thesis_repo import ThesisRepository
from app.utils.logger import get_logger

log = get_logger(__name__)


class PipelineOrchestrator:
    """Runs CHUNK -> EXTRACT -> DELTA -> GRAPH -> CONNECT for a filing.

    Each step is wrapped so a single failure doesn't kill the whole pipeline;
    the orchestrator returns a summary dict suitable for AgentJob.result.
    """

    def __init__(self) -> None:
        self.extractor = ExtractorAgent()
        self.delta_agent = DeltaAgent()
        self.graph_agent = GraphAgent()
        self.connector = ConnectorAgent()

    # -------------------------------------------------------------------
    # Public entry points
    # -------------------------------------------------------------------
    async def run_for_filing(
        self,
        filing_id: uuid.UUID,
        session: AsyncSession,
        job_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "filing_id": str(filing_id),
            "facts_extracted": 0,
            "deltas_generated": 0,
            "edges_added": 0,
            "theses_generated": 0,
            "errors": [],
        }
        await self._update_job(session, job_id, status="running", started=True)

        filing_repo = FilingRepository(session)
        filing = await filing_repo.get_by_id(filing_id)
        if filing is None:
            summary["errors"].append("filing_not_found")
            await self._update_job(session, job_id, status="failed", result=summary)
            return summary

        company = await CompanyRepository(session).get_by_id(filing.company_id)
        if company is None:
            summary["errors"].append("company_not_found")
            await self._update_job(session, job_id, status="failed", result=summary)
            return summary

        # 1) Extract -----------------------------------------------------
        try:
            facts = await self._extract_facts(filing, company, session)
            summary["facts_extracted"] = len(facts)
        except Exception as e:  # noqa: BLE001
            log.exception("orchestrator_extract_failed", filing_id=str(filing_id))
            summary["errors"].append(f"extract: {e}")
            facts = []

        # 2) Delta -------------------------------------------------------
        deltas: list[FilingDelta] = []
        try:
            deltas = await self._compute_deltas(filing, company, facts, session)
            summary["deltas_generated"] = len(deltas)
        except Exception as e:  # noqa: BLE001
            log.exception("orchestrator_delta_failed", filing_id=str(filing_id))
            summary["errors"].append(f"delta: {e}")

        # 3) Graph -------------------------------------------------------
        try:
            edges = await self.graph_agent.update_graph(facts, session)
            summary["edges_added"] = edges
        except Exception as e:  # noqa: BLE001
            log.exception("orchestrator_graph_failed", filing_id=str(filing_id))
            summary["errors"].append(f"graph: {e}")

        # 4) Connect -----------------------------------------------------
        try:
            theses = await self._generate_theses(deltas, company, session)
            summary["theses_generated"] = len(theses)
            summary["thesis_ids"] = [str(t.id) for t in theses]
        except Exception as e:  # noqa: BLE001
            log.exception("orchestrator_connect_failed", filing_id=str(filing_id))
            summary["errors"].append(f"connect: {e}")

        # Mark filing processed and commit
        await filing_repo.mark_processed(filing_id)
        await session.commit()

        await self._update_job(
            session,
            job_id,
            status="completed",
            result=summary,
        )
        return summary

    async def run_for_company(
        self,
        ticker: str,
        session: AsyncSession,
        filing_types: tuple[str, ...] = ("10-K", "10-Q"),
    ) -> dict[str, Any]:
        company = await CompanyRepository(session).get_by_ticker(ticker)
        if company is None:
            return {"error": "company_not_found", "ticker": ticker}

        filing_repo = FilingRepository(session)
        all_summaries: list[dict[str, Any]] = []
        for ft in filing_types:
            filings = await filing_repo.get_for_company(company.id, filing_type=ft, limit=4)
            for f in filings:
                if f.processed:
                    continue
                summary = await self.run_for_filing(f.id, session)
                all_summaries.append(summary)
        return {
            "ticker": ticker,
            "filings_processed": len(all_summaries),
            "totals": {
                "facts": sum(s.get("facts_extracted", 0) for s in all_summaries),
                "deltas": sum(s.get("deltas_generated", 0) for s in all_summaries),
                "theses": sum(s.get("theses_generated", 0) for s in all_summaries),
            },
            "details": all_summaries,
        }

    # -------------------------------------------------------------------
    # Pipeline steps
    # -------------------------------------------------------------------
    async def _extract_facts(
        self, filing: Filing, company: Company, session: AsyncSession
    ) -> list[ExtractedFact]:
        if not filing.raw_text:
            return []

        sections = preprocess_filing(
            filing.raw_text,
            filing_type=filing.filing_type,
            max_tokens=settings.EXTRACTOR_MAX_TOKENS_PER_CHUNK,
        )
        all_facts: list[ExtractedFact] = []

        for section in sections:
            facts = await self.extractor.extract(
                filing_text=section.text,
                company=company,
                filing=filing,
                section_name=section.name,
            )
            for f in facts:
                row = ExtractedFact(
                    filing_id=filing.id,
                    company_id=company.id,
                    fact_type=f.fact_type,
                    subject=f.subject,
                    value=f.value,
                    confidence=f.confidence,
                    source_section=f.source_section,
                    source_text=f.source_text,
                )
                session.add(row)
                all_facts.append(row)
            await session.flush()

        return all_facts

    async def _compute_deltas(
        self,
        filing: Filing,
        company: Company,
        current_facts: list[ExtractedFact],
        session: AsyncSession,
    ) -> list[FilingDelta]:
        prior = await FilingRepository(session).get_prior_period(
            company.id, filing.filing_type, filing.filed_date
        )
        if prior is None or not current_facts:
            return []

        prior_facts = list(
            (
                await session.execute(
                    select(ExtractedFact).where(ExtractedFact.filing_id == prior.id)
                )
            )
            .scalars()
            .all()
        )

        deltas = await self.delta_agent.compute_delta(
            current_facts=current_facts,
            prior_facts=prior_facts,
            company=company,
            current_filing=filing,
            prior_filing=prior,
        )

        rows: list[FilingDelta] = []
        for d in deltas:
            row = FilingDelta(
                company_id=company.id,
                current_filing_id=filing.id,
                prior_filing_id=prior.id,
                delta_type=d.delta_type,
                section=d.section,
                description=d.description,
                significance_score=d.significance_score,
                previous_text=d.previous_text,
                current_text=d.current_text,
            )
            session.add(row)
            rows.append(row)
        await session.flush()
        return rows

    async def _generate_theses(
        self,
        deltas: list[FilingDelta],
        trigger_company: Company,
        session: AsyncSession,
    ) -> list[Thesis]:
        if not deltas:
            return []
        graph_repo = GraphRepository(session)
        thesis_repo = ThesisRepository(session)
        out: list[Thesis] = []

        for delta in deltas:
            if (delta.significance_score or 0) < settings.DELTA_SIGNIFICANCE_THRESHOLD:
                continue
            neighbors = await graph_repo.get_neighbors(trigger_company.id, max_degree=2)
            thesis_create = await self.connector.generate_thesis(
                trigger_delta=delta,
                trigger_company=trigger_company,
                connected_companies=neighbors,
                session=session,
            )
            if thesis_create is None:
                continue

            row = await thesis_repo.create(
                {
                    "title": thesis_create.title,
                    "summary": thesis_create.summary,
                    "thesis_type": thesis_create.thesis_type.value,
                    "direction": thesis_create.direction.value,
                    "confidence_score": thesis_create.confidence_score,
                    "trigger_company_id": thesis_create.trigger_company_id,
                    "affected_company_ids": thesis_create.affected_company_ids,
                    "evidence_chain": [
                        s.model_dump() for s in thesis_create.evidence_chain
                    ],
                    "competing_thesis": thesis_create.competing_thesis,
                    "invalidation_criteria": thesis_create.invalidation_criteria,
                    "catalyst": thesis_create.catalyst,
                    "time_horizon": thesis_create.time_horizon,
                    "trigger_delta_ids": thesis_create.trigger_delta_ids,
                    "trigger_fact_ids": thesis_create.trigger_fact_ids,
                }
            )
            out.append(row)
        return out

    # -------------------------------------------------------------------
    # Job tracking
    # -------------------------------------------------------------------
    async def _update_job(
        self,
        session: AsyncSession,
        job_id: uuid.UUID | None,
        status: str,
        result: dict[str, Any] | None = None,
        started: bool = False,
        error: str | None = None,
    ) -> None:
        if job_id is None:
            return
        job = await session.get(AgentJob, job_id)
        if job is None:
            return
        job.status = status
        if started:
            job.started_at = datetime.utcnow()
        if status in ("completed", "failed"):
            job.completed_at = datetime.utcnow()
        if result is not None:
            job.result = result
        if error is not None:
            job.error = error
        await session.flush()
