"""Pydantic schemas for Theses — the user-facing output of the pipeline."""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ThesisType(str, Enum):
    SUPPLY_CHAIN_CONTAGION = "supply_chain_contagion"
    SECTOR_READ_THROUGH = "sector_read_through"
    STRATEGIC_PIVOT = "strategic_pivot"
    PEER_COMPARISON = "peer_comparison"


class ThesisDirection(str, Enum):
    LONG = "long"
    SHORT = "short"
    LONG_SHORT_PAIR = "long_short_pair"


class ThesisStatus(str, Enum):
    PENDING = "pending"
    VALIDATED = "validated"
    DISMISSED = "dismissed"
    EXPIRED = "expired"


class EvidenceStep(BaseModel):
    step: int = Field(..., ge=1)
    description: str
    source_company: str
    source_filing: str
    quote: str


class ThesisCreate(BaseModel):
    title: str = Field(..., max_length=500)
    summary: str
    thesis_type: ThesisType
    direction: ThesisDirection
    confidence_score: float = Field(..., ge=0.0, le=1.0)

    trigger_company_id: uuid.UUID
    affected_company_ids: list[uuid.UUID] = Field(default_factory=list)

    evidence_chain: list[EvidenceStep] = Field(default_factory=list)
    competing_thesis: str | None = None
    invalidation_criteria: list[str] = Field(default_factory=list)

    catalyst: str | None = None
    time_horizon: str | None = None

    trigger_delta_ids: list[uuid.UUID] = Field(default_factory=list)
    trigger_fact_ids: list[uuid.UUID] = Field(default_factory=list)


class ThesisUpdate(BaseModel):
    status: ThesisStatus | None = None
    pm_notes: str | None = None


class ThesisResponse(BaseModel):
    id: uuid.UUID
    title: str
    summary: str
    thesis_type: ThesisType
    direction: ThesisDirection
    confidence_score: float

    trigger_company_id: uuid.UUID
    affected_company_ids: list[uuid.UUID]
    trigger_ticker: str | None = None
    affected_tickers: list[str] = Field(default_factory=list)

    evidence_chain: list[EvidenceStep]
    competing_thesis: str | None
    invalidation_criteria: list[str]

    catalyst: str | None
    time_horizon: str | None

    status: ThesisStatus
    pm_notes: str | None = None

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ThesisListResponse(BaseModel):
    theses: list[ThesisResponse]
    total: int
    limit: int
    offset: int


class ThesisStatsResponse(BaseModel):
    total: int
    pending: int
    validated: int
    dismissed: int
    expired: int


class ValidateRequest(BaseModel):
    notes: str | None = None


class DismissRequest(BaseModel):
    reason: str | None = None
