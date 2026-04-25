"""Pydantic schemas for Company I/O."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CompanyBase(BaseModel):
    ticker: str = Field(..., max_length=10)
    cik: str = Field(..., max_length=20)
    name: str = Field(..., max_length=255)
    sector: str | None = Field(default=None, max_length=100)
    industry: str | None = Field(default=None, max_length=100)
    market_cap: int | None = None


class CompanyCreate(CompanyBase):
    pass


class CompanyResponse(CompanyBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CompanyListResponse(BaseModel):
    companies: list[CompanyResponse]
    total: int
