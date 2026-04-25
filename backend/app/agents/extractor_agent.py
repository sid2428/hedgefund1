"""ExtractorAgent — pulls structured facts from a single filing chunk."""
from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.db.models import Company, Filing
from app.schemas.filing import ExtractedFactCreate

ALLOWED_FACT_TYPES = {
    "NAMED_CUSTOMER",
    "NAMED_SUPPLIER",
    "CUSTOMER_CONCENTRATION",
    "SUPPLIER_CONCENTRATION",
    "CAPEX_GUIDANCE",
    "GUIDANCE_LANGUAGE",
    "NEW_RISK",
    "GEOGRAPHIC_EXPOSURE",
    "REGULATORY_RISK",
    "MANAGEMENT_UNCERTAINTY",
}


class ExtractorAgent(BaseAgent):
    """Stateless extractor. One call per filing chunk."""

    PROMPT = "extractor.j2"

    async def extract(
        self,
        filing_text: str,
        company: Company,
        filing: Filing,
        section_name: str,
    ) -> list[ExtractedFactCreate]:
        if not filing_text or not filing_text.strip():
            return []

        prompt = self.render_prompt(
            self.PROMPT,
            company_name=company.name,
            ticker=company.ticker,
            filing_type=filing.filing_type,
            period=str(filing.period_of_report or filing.filed_date),
            section_name=section_name,
            filing_text=filing_text,
        )

        try:
            raw = await self.call_claude(prompt)
        except Exception as e:  # noqa: BLE001
            self.log.error(
                "extractor_call_failed",
                ticker=company.ticker,
                section=section_name,
                error=str(e),
            )
            return []

        parsed = self.parse_json_response(raw)
        if not isinstance(parsed, list):
            self.log.warning(
                "extractor_parse_failed",
                ticker=company.ticker,
                section=section_name,
                raw_preview=raw[:200] if raw else "",
            )
            return []

        return self._validate_and_filter(parsed, section_name=section_name)

    def _validate_and_filter(
        self, items: list[Any], *, section_name: str
    ) -> list[ExtractedFactCreate]:
        out: list[ExtractedFactCreate] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            fact_type = (item.get("fact_type") or "").strip().upper()
            if fact_type not in ALLOWED_FACT_TYPES:
                continue
            value = (item.get("value") or "").strip()
            source_text = (item.get("source_text") or "").strip()
            if not value or not source_text:
                continue
            confidence = item.get("confidence")
            try:
                confidence = float(confidence) if confidence is not None else 0.7
            except (TypeError, ValueError):
                confidence = 0.7
            confidence = max(0.0, min(1.0, confidence))

            try:
                fact = ExtractedFactCreate(
                    fact_type=fact_type,
                    subject=(item.get("subject") or "")[:255] or None,
                    value=value,
                    confidence=confidence,
                    source_section=item.get("source_section") or section_name,
                    source_text=source_text[:1000],
                )
            except Exception as e:  # noqa: BLE001
                self.log.warning("extractor_validation_dropped", error=str(e), item=item)
                continue
            out.append(fact)
        return out
