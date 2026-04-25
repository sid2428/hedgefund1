"""Pydantic schemas for Filings and ExtractedFacts."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class FilingBase(BaseModel):
    filing_type: str = Field(..., max_length=20)
    accession_number: str = Field(..., max_length=50)
    filed_date: date
    period_of_report: date | None = None
    edgar_url: str | None = None


class FilingCreate(FilingBase):
    company_id: uuid.UUID
    raw_text: str | None = None


class FilingResponse(FilingBase):
    id: uuid.UUID
    company_id: uuid.UUID
    processed: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FilingListResponse(BaseModel):
    filings: list[FilingResponse]
    total: int


class ExtractedFactCreate(BaseModel):
    fact_type: str
    subject: str | None = None
    value: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_section: str | None = None
    source_text: str | None = None


class ExtractedFactResponse(ExtractedFactCreate):
    id: uuid.UUID
    filing_id: uuid.UUID
    company_id: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FilingDeltaCreate(BaseModel):
    delta_type: str
    section: str | None = None
    description: str
    significance_score: float | None = Field(default=None, ge=0.0, le=1.0)
    previous_text: str | None = None
    current_text: str | None = None


class FilingDeltaResponse(FilingDeltaCreate):
    id: uuid.UUID
    company_id: uuid.UUID
    current_filing_id: uuid.UUID
    prior_filing_id: uuid.UUID | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
