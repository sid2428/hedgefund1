"""DeltaAgent — compares facts from two consecutive filings of the same company."""
from __future__ import annotations

import json
from typing import Any

from app.agents.base import BaseAgent
from app.db.models import Company, ExtractedFact, Filing
from app.schemas.filing import FilingDeltaCreate

ALLOWED_DELTA_TYPES = {
    "CUSTOMER_ADDED",
    "CUSTOMER_REMOVED",
    "SUPPLIER_ADDED",
    "SUPPLIER_REMOVED",
    "RISK_ESCALATED",
    "RISK_NEW",
    "RISK_REMOVED",
    "GUIDANCE_WEAKENED",
    "GUIDANCE_STRENGTHENED",
    "CONCENTRATION_INCREASED",
    "CONCENTRATION_DECREASED",
}


class DeltaAgent(BaseAgent):
    PROMPT = "delta.j2"

    async def compute_delta(
        self,
        current_facts: list[ExtractedFact],
        prior_facts: list[ExtractedFact],
        company: Company,
        current_filing: Filing,
        prior_filing: Filing,
    ) -> list[FilingDeltaCreate]:
        if not current_facts and not prior_facts:
            return []

        prior_payload = [self._fact_summary(f) for f in prior_facts]
        current_payload = [self._fact_summary(f) for f in current_facts]

        prompt = self.render_prompt(
            self.PROMPT,
            company_name=company.name,
            ticker=company.ticker,
            prior_period=str(prior_filing.period_of_report or prior_filing.filed_date),
            current_period=str(current_filing.period_of_report or current_filing.filed_date),
            prior_facts_json=json.dumps(prior_payload, ensure_ascii=False, indent=2),
            current_facts_json=json.dumps(current_payload, ensure_ascii=False, indent=2),
        )

        try:
            raw = await self.call_claude(prompt, max_tokens=4096)
        except Exception as e:  # noqa: BLE001
            self.log.error("delta_call_failed", ticker=company.ticker, error=str(e))
            return []

        parsed = self.parse_json_response(raw)
        if not isinstance(parsed, list):
            self.log.warning(
                "delta_parse_failed",
                ticker=company.ticker,
                raw_preview=raw[:200] if raw else "",
            )
            return []

        return self._validate(parsed)

    @staticmethod
    def _fact_summary(fact: ExtractedFact) -> dict[str, Any]:
        return {
            "fact_type": fact.fact_type,
            "subject": fact.subject,
            "value": fact.value,
            "section": fact.source_section,
            "source_text": fact.source_text,
        }

    def _validate(self, items: list[Any]) -> list[FilingDeltaCreate]:
        out: list[FilingDeltaCreate] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            delta_type = (item.get("delta_type") or "").strip().upper()
            if delta_type not in ALLOWED_DELTA_TYPES:
                continue
            description = (item.get("description") or "").strip()
            if not description:
                continue
            try:
                significance = float(item.get("significance_score") or 0.5)
            except (TypeError, ValueError):
                significance = 0.5
            significance = max(0.0, min(1.0, significance))
            try:
                delta = FilingDeltaCreate(
                    delta_type=delta_type,
                    section=item.get("section") or None,
                    description=description,
                    significance_score=significance,
                    previous_text=(item.get("previous_text") or "")[:2000] or None,
                    current_text=(item.get("current_text") or "")[:2000] or None,
                )
            except Exception as e:  # noqa: BLE001
                self.log.warning("delta_validation_dropped", error=str(e), item=item)
                continue
            out.append(delta)
        return out
