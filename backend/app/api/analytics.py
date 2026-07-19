"""Analytics and data-control endpoints over `financial_facts`.

Every route is bounded by `as_of`, and the aggregation runs in SQL rather than
in the application. See `app.db.repositories.analytics_repo` for the queries.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.xbrl import CONCEPT_TAGS
from app.db.repositories.analytics_repo import ANNUAL, AnalyticsRepository
from app.db.repositories.company_repo import CompanyRepository
from app.db.session import get_db

router = APIRouter()


# --- schemas ----------------------------------------------------------------
class GrowthPointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    period_start: date
    period_end: date
    value: float
    filed_date: date
    accession_number: str
    prior_value: float | None
    prior_period_end: date | None
    growth: float | None = Field(description="Fractional change, e.g. 0.126 for +12.6%.")


class GrowthSeriesResponse(BaseModel):
    ticker: str
    concept: str
    as_of: date
    fiscal_period: str | None
    points: list[GrowthPointResponse]
    total: int


class RestatementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    period_end: date
    original_value: float
    original_filed: date
    original_accession: str
    latest_value: float
    latest_filed: date
    latest_accession: str
    delta: float
    delta_pct: float | None
    revision_count: int


class RestatementReportResponse(BaseModel):
    ticker: str
    concept: str
    as_of: date
    min_delta_pct: float
    restatements: list[RestatementResponse]
    total: int


class CoverageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    concept: str
    fact_count: int
    period_count: int
    earliest_period: date | None
    latest_period: date | None
    latest_filed: date | None


class BalanceSheetCheckRow(BaseModel):
    period_end: date
    assets: float
    liabilities_plus_equity: float
    difference: float
    passed: bool


class BalanceSheetCheckResponse(BaseModel):
    ticker: str
    as_of: date
    tolerance: float
    rows: list[BalanceSheetCheckRow]
    failures: int


# --- helpers ----------------------------------------------------------------
async def _company_or_404(ticker: str, session: AsyncSession):
    company = await CompanyRepository(session).get_by_ticker(ticker)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


def _validate_concept(concept: str) -> None:
    if concept not in CONCEPT_TAGS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown concept. Known concepts: {sorted(CONCEPT_TAGS)}",
        )


_AS_OF = Query(
    default=None,
    description=(
        "Point-in-time cutoff on filing date. Results reflect what was knowable "
        "on this date. Defaults to today."
    ),
)


# --- routes -----------------------------------------------------------------
@router.get("/{ticker}/growth/{concept}", response_model=GrowthSeriesResponse)
async def growth(
    ticker: str,
    concept: str,
    as_of: date | None = _AS_OF,
    fiscal_period: str | None = Query(
        default=ANNUAL,
        description="XBRL fiscal period code: FY, Q1-Q4. Null for all periods.",
    ),
    unit: str = Query(default="USD"),
    session: AsyncSession = Depends(get_db),
) -> GrowthSeriesResponse:
    """Period-over-period growth, computed with a window function.

    Growth is measured against the figure originally reported for the prior
    period, not a later restatement of it.
    """
    _validate_concept(concept)
    company = await _company_or_404(ticker, session)
    cutoff = as_of or date.today()

    points = await AnalyticsRepository(session).growth_series(
        company.id, concept, as_of=cutoff, unit=unit, fiscal_period=fiscal_period
    )
    return GrowthSeriesResponse(
        ticker=company.ticker,
        concept=concept,
        as_of=cutoff,
        fiscal_period=fiscal_period,
        points=[GrowthPointResponse.model_validate(p) for p in points],
        total=len(points),
    )


@router.get("/{ticker}/restatements/{concept}", response_model=RestatementReportResponse)
async def restatements(
    ticker: str,
    concept: str,
    as_of: date | None = _AS_OF,
    min_delta_pct: float = Query(
        default=0.0,
        ge=0.0,
        description=(
            "Materiality threshold as a fraction, e.g. 0.01 for 1%. Filters out "
            "rounding and reclassification noise."
        ),
    ),
    unit: str = Query(default="USD"),
    session: AsyncSession = Depends(get_db),
) -> RestatementReportResponse:
    """Figures that changed after first publication, with magnitude and source.

    A lineage view: which numbers moved, by how much, and in which filing.
    """
    _validate_concept(concept)
    company = await _company_or_404(ticker, session)
    cutoff = as_of or date.today()

    rows = await AnalyticsRepository(session).restatement_report(
        company.id, concept, as_of=cutoff, unit=unit, min_delta_pct=min_delta_pct
    )
    return RestatementReportResponse(
        ticker=company.ticker,
        concept=concept,
        as_of=cutoff,
        min_delta_pct=min_delta_pct,
        restatements=[RestatementResponse.model_validate(r) for r in rows],
        total=len(rows),
    )


@router.get("/{ticker}/coverage", response_model=list[CoverageResponse])
async def coverage(
    ticker: str,
    as_of: date | None = _AS_OF,
    session: AsyncSession = Depends(get_db),
) -> list[CoverageResponse]:
    """Per-concept completeness. A thin series and a deep one are different claims."""
    company = await _company_or_404(ticker, session)
    rows = await AnalyticsRepository(session).coverage(
        company.id, as_of=as_of or date.today()
    )
    return [CoverageResponse.model_validate(r) for r in rows]


@router.get("/{ticker}/controls/balance-sheet", response_model=BalanceSheetCheckResponse)
async def balance_sheet_control(
    ticker: str,
    as_of: date | None = _AS_OF,
    tolerance: float = Query(
        default=0.01, gt=0, le=1, description="Relative tolerance, as a fraction of assets."
    ),
    session: AsyncSession = Depends(get_db),
) -> BalanceSheetCheckResponse:
    """Reconciliation control: assets must equal liabilities plus equity.

    A failing period means the concept mapping resolved the wrong tag, or the
    filer used a combination the mapping does not model. Either way the derived
    figures for that period should not be trusted.
    """
    company = await _company_or_404(ticker, session)
    cutoff = as_of or date.today()

    raw = await AnalyticsRepository(session).balance_sheet_check(
        company.id, as_of=cutoff, tolerance=tolerance
    )
    rows = [
        BalanceSheetCheckRow(
            period_end=period_end,
            assets=assets,
            liabilities_plus_equity=rhs,
            difference=diff,
            passed=ok,
        )
        for period_end, assets, rhs, diff, ok in raw
    ]
    return BalanceSheetCheckResponse(
        ticker=company.ticker,
        as_of=cutoff,
        tolerance=tolerance,
        rows=rows,
        failures=sum(1 for r in rows if not r.passed),
    )
