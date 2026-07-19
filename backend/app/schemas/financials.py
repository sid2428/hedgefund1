"""Response schemas for XBRL-reported financials."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class FinancialFactResponse(BaseModel):
    """One reported value, with both time axes exposed.

    `filed_date` is included deliberately. A consumer needs to be able to see
    when a number became known, not just which period it describes — otherwise
    an original and its restatement are indistinguishable in the response.
    """

    model_config = ConfigDict(from_attributes=True)

    concept: str
    tag: str
    unit: str
    value: float

    period_start: date
    period_end: date
    is_instant: bool

    filed_date: date = Field(
        description="When this value was filed with the SEC, i.e. when it became known."
    )
    accession_number: str
    form: str | None = None
    fiscal_year: int | None = None
    fiscal_period: str | None = None


class FinancialSeriesResponse(BaseModel):
    ticker: str
    concept: str

    as_of: date = Field(
        description=(
            "Point-in-time cutoff. Only values filed on or before this date are "
            "included, so the response reflects what was knowable then."
        )
    )

    basis: str = Field(
        description=(
            "'as_reported' collapses restatements to the figure originally "
            "published for each period; 'all' returns every filed version."
        )
    )

    facts: list[FinancialFactResponse]
    total: int
