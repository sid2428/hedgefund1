"""ExtractorAgent — pulls structured facts from a single filing chunk."""
from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.db.models import Company, Filing
from app.schemas.filing import ExtractedFactCreate
from app.utils.grounding import CitationGrounder

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

        return self._validate_and_filter(
            parsed,
            section_name=section_name,
            grounder=CitationGrounder(filing_text),
            ticker=company.ticker,
        )

    def _validate_and_filter(
        self,
        items: list[Any],
        *,
        section_name: str,
        grounder: CitationGrounder,
        ticker: str | None = None,
    ) -> list[ExtractedFactCreate]:
        out: list[ExtractedFactCreate] = []
        rejected: dict[str, int] = {}

        def reject(reason: str) -> None:
            rejected[reason] = rejected.get(reason, 0) + 1

        for item in items:
            if not isinstance(item, dict):
                reject("not_an_object")
                continue
            fact_type = (item.get("fact_type") or "").strip().upper()
            if fact_type not in ALLOWED_FACT_TYPES:
                reject("unknown_fact_type")
                continue
            value = (item.get("value") or "").strip()
            source_text = (item.get("source_text") or "").strip()
            if not value or not source_text:
                reject("missing_value_or_source")
                continue

            # Citation grounding. A quote the model returned that does not
            # occur in the filing is not evidence of anything, so the fact is
            # discarded here rather than persisted with a fabricated citation.
            grounding = grounder.verify(source_text)
            if not grounding.verified:
                reject(grounding.reason or "ungrounded")
                self.log.debug(
                    "fact_rejected_ungrounded",
                    ticker=ticker,
                    section=section_name,
                    fact_type=fact_type,
                    reason=grounding.reason,
                    quote_preview=source_text[:120],
                )
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
                reject("schema_validation_failed")
                self.log.warning("extractor_validation_dropped", error=str(e), item=item)
                continue
            out.append(fact)

        proposed = len(items)
        if proposed:
            ungrounded = rejected.get("not_found_in_source", 0)
            self.log.info(
                "extractor_grounding",
                ticker=ticker,
                section=section_name,
                proposed=proposed,
                kept=len(out),
                rejected=proposed - len(out),
                ungrounded=ungrounded,
                # The headline number: share of model-proposed facts whose
                # citation could not be found in the source document.
                ungrounded_rate=round(ungrounded / proposed, 4),
                reasons=rejected or None,
            )
        return out
