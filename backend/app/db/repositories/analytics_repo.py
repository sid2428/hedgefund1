"""Analytical queries over `financial_facts`, computed in SQL.

Everything here runs in the database rather than in Python. That is a
deliberate choice, not a stylistic one:

* **Correctness lives next to the data.** Point-in-time collapsing of
  restatements is expressed once, as a window function, instead of being
  re-implemented by every caller that pulls rows out.
* **Volume.** A company has tens of thousands of tagged facts and the corpus
  is every filer on EDGAR. Streaming that into the application to compute a
  growth rate is the wrong shape; the aggregation belongs where the index is.
* **Auditability.** A single statement that can be `EXPLAIN`ed is far easier to
  reason about — and to defend — than a pipeline of list comprehensions.

Every query is bounded by `as_of` on `filed_date`, so results reflect what was
knowable on that date rather than what is known now.

Portability: window functions are used throughout, which requires PostgreSQL or
SQLite 3.25+. Both are satisfied by this project's targets.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Float, and_, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FinancialFact

# Fiscal period codes as reported in XBRL. "FY" is an annual figure; Q1-Q4 are
# quarterly. Used instead of computing period length in SQL, because date
# arithmetic is one of the least portable corners of the language.
ANNUAL = "FY"


@dataclass(frozen=True)
class GrowthPoint:
    """One period, its value, and its change from the comparable prior period."""

    period_end: date
    period_start: date
    value: float
    filed_date: date
    accession_number: str
    prior_value: float | None
    prior_period_end: date | None
    growth: float | None
    """Fractional change, e.g. 0.126 for +12.6%. None where there is no prior."""


@dataclass(frozen=True)
class RestatementPoint:
    """A period whose reported value changed between filings."""

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


@dataclass(frozen=True)
class CoveragePoint:
    concept: str
    fact_count: int
    period_count: int
    earliest_period: date | None
    latest_period: date | None
    latest_filed: date | None


class AnalyticsRepository:
    """Aggregate reads over financial_facts."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ----- shared building block -----------------------------------------
    @staticmethod
    def _as_reported_cte(
        company_id: uuid.UUID,
        *,
        as_of: date,
        concept: str | None = None,
        unit: str | None = None,
        fiscal_period: str | None = None,
    ):
        """Rows reduced to one per period — the originally reported figure.

        A period can be reported several times: once when first published, then
        again in any filing that restates it. `ROW_NUMBER` partitioned by the
        period's identity and ordered by `filed_date` numbers those versions,
        and taking the first keeps the value the market actually had.

        Doing this in SQL rather than after the fact means a caller cannot
        forget it, and the database never has to return the rows being
        discarded.
        """
        conditions = [
            FinancialFact.company_id == company_id,
            FinancialFact.filed_date <= as_of,
        ]
        if concept is not None:
            conditions.append(FinancialFact.concept == concept)
        if unit is not None:
            conditions.append(FinancialFact.unit == unit)
        if fiscal_period is not None:
            conditions.append(FinancialFact.fiscal_period == fiscal_period)

        version = (
            func.row_number()
            .over(
                partition_by=(
                    FinancialFact.concept,
                    FinancialFact.unit,
                    FinancialFact.period_start,
                    FinancialFact.period_end,
                ),
                order_by=FinancialFact.filed_date.asc(),
            )
            .label("version")
        )

        ranked = (
            select(
                FinancialFact.concept,
                FinancialFact.unit,
                FinancialFact.period_start,
                FinancialFact.period_end,
                FinancialFact.value,
                FinancialFact.filed_date,
                FinancialFact.accession_number,
                version,
            )
            .where(and_(*conditions))
            .cte("ranked")
        )

        return (
            select(ranked)
            .where(ranked.c.version == 1)
            .cte("as_reported")
        )

    # ----- growth ---------------------------------------------------------
    async def growth_series(
        self,
        company_id: uuid.UUID,
        concept: str,
        *,
        as_of: date,
        unit: str = "USD",
        fiscal_period: str | None = ANNUAL,
    ) -> list[GrowthPoint]:
        """Period-over-period growth for one concept.

        `LAG` reads the previous row in period order, so the comparison is made
        inside the database in a single pass rather than by pulling the series
        into Python and zipping it against itself.

        Division guards against a zero prior value with `NULLIF`, which yields
        NULL rather than raising — a company can genuinely report zero revenue
        for a period, and that should produce "no growth figure", not an error.
        """
        base = self._as_reported_cte(
            company_id,
            as_of=as_of,
            concept=concept,
            unit=unit,
            fiscal_period=fiscal_period,
        )

        prior_value = func.lag(base.c.value).over(order_by=base.c.period_end).label("prior_value")
        prior_end = (
            func.lag(base.c.period_end).over(order_by=base.c.period_end).label("prior_period_end")
        )

        windowed = select(base, prior_value, prior_end).cte("windowed")

        growth = (
            cast(windowed.c.value - windowed.c.prior_value, Float)
            / func.nullif(windowed.c.prior_value, 0.0)
        ).label("growth")

        stmt = select(
            windowed.c.period_start,
            windowed.c.period_end,
            windowed.c.value,
            windowed.c.filed_date,
            windowed.c.accession_number,
            windowed.c.prior_value,
            windowed.c.prior_period_end,
            growth,
        ).order_by(windowed.c.period_end)

        rows = (await self.session.execute(stmt)).all()
        return [
            GrowthPoint(
                period_end=r.period_end,
                period_start=r.period_start,
                value=float(r.value),
                filed_date=r.filed_date,
                accession_number=r.accession_number,
                prior_value=float(r.prior_value) if r.prior_value is not None else None,
                prior_period_end=r.prior_period_end,
                growth=float(r.growth) if r.growth is not None else None,
            )
            for r in rows
        ]

    # ----- ratios ---------------------------------------------------------
    async def ratio_series(
        self,
        company_id: uuid.UUID,
        numerator: str,
        denominator: str,
        *,
        as_of: date,
        unit: str = "USD",
        fiscal_period: str | None = ANNUAL,
    ) -> list[tuple[date, float | None]]:
        """A ratio between two concepts, aligned on period.

        Net margin is `ratio_series(..., "net_income", "revenue")`. The join is
        on the full period bounds rather than the end date alone, because a
        fiscal year and its fourth quarter share an end date and would otherwise
        cross-match — silently dividing a quarter's earnings by a year's revenue.
        """
        num = self._as_reported_cte(
            company_id, as_of=as_of, concept=numerator, unit=unit, fiscal_period=fiscal_period
        )
        den = self._as_reported_cte(
            company_id, as_of=as_of, concept=denominator, unit=unit, fiscal_period=fiscal_period
        )

        stmt = (
            select(
                num.c.period_end,
                (cast(num.c.value, Float) / func.nullif(den.c.value, 0.0)).label("ratio"),
            )
            .select_from(
                num.join(
                    den,
                    and_(
                        num.c.period_start == den.c.period_start,
                        num.c.period_end == den.c.period_end,
                    ),
                )
            )
            .order_by(num.c.period_end)
        )

        rows = (await self.session.execute(stmt)).all()
        return [(r.period_end, float(r.ratio) if r.ratio is not None else None) for r in rows]

    # ----- data quality ---------------------------------------------------
    async def restatement_report(
        self,
        company_id: uuid.UUID,
        concept: str,
        *,
        as_of: date,
        unit: str = "USD",
        min_delta_pct: float = 0.0,
    ) -> list[RestatementPoint]:
        """Periods whose reported figure changed after first publication.

        This is a data-lineage question, and the sort of thing that has to be
        answerable on demand: which numbers moved, by how much, and in which
        filing. Aggregating with `MIN`/`MAX` over `filed_date` and correlating
        the value at each end gives the original and current figure per period
        in one pass.

        `min_delta_pct` filters out immaterial revisions — rounding and
        reclassification produce a long tail of sub-basis-point changes that
        obscure the ones that matter.
        """
        base_conditions = [
            FinancialFact.company_id == company_id,
            FinancialFact.concept == concept,
            FinancialFact.unit == unit,
            FinancialFact.filed_date <= as_of,
        ]

        # Number each version of a period both ascending and descending by
        # filing date; row 1 of each is the original and the latest.
        asc_rank = func.row_number().over(
            partition_by=(FinancialFact.period_start, FinancialFact.period_end),
            order_by=FinancialFact.filed_date.asc(),
        ).label("asc_rank")
        desc_rank = func.row_number().over(
            partition_by=(FinancialFact.period_start, FinancialFact.period_end),
            order_by=FinancialFact.filed_date.desc(),
        ).label("desc_rank")
        total = func.count().over(
            partition_by=(FinancialFact.period_start, FinancialFact.period_end)
        ).label("total")

        ranked = (
            select(
                FinancialFact.period_start,
                FinancialFact.period_end,
                FinancialFact.value,
                FinancialFact.filed_date,
                FinancialFact.accession_number,
                asc_rank,
                desc_rank,
                total,
            )
            .where(and_(*base_conditions))
            .cte("ranked")
        )

        first = select(ranked).where(ranked.c.asc_rank == 1).cte("first_reported")
        last = select(ranked).where(ranked.c.desc_rank == 1).cte("last_reported")

        delta = (cast(last.c.value, Float) - first.c.value).label("delta")
        delta_pct = (
            (cast(last.c.value, Float) - first.c.value) / func.nullif(first.c.value, 0.0)
        ).label("delta_pct")

        stmt = (
            select(
                first.c.period_end,
                first.c.value.label("original_value"),
                first.c.filed_date.label("original_filed"),
                first.c.accession_number.label("original_accession"),
                last.c.value.label("latest_value"),
                last.c.filed_date.label("latest_filed"),
                last.c.accession_number.label("latest_accession"),
                first.c.total.label("revision_count"),
                delta,
                delta_pct,
            )
            .select_from(
                first.join(
                    last,
                    and_(
                        first.c.period_start == last.c.period_start,
                        first.c.period_end == last.c.period_end,
                    ),
                )
            )
            # Only periods that actually changed.
            .where(first.c.total > 1)
            .where(first.c.value != last.c.value)
            .order_by(first.c.period_end)
        )

        rows = (await self.session.execute(stmt)).all()
        out = [
            RestatementPoint(
                period_end=r.period_end,
                original_value=float(r.original_value),
                original_filed=r.original_filed,
                original_accession=r.original_accession,
                latest_value=float(r.latest_value),
                latest_filed=r.latest_filed,
                latest_accession=r.latest_accession,
                delta=float(r.delta),
                delta_pct=float(r.delta_pct) if r.delta_pct is not None else None,
                revision_count=int(r.revision_count),
            )
            for r in rows
        ]

        if min_delta_pct > 0:
            out = [
                p for p in out
                if p.delta_pct is not None and abs(p.delta_pct) >= min_delta_pct
            ]
        return out

    async def coverage(
        self, company_id: uuid.UUID, *, as_of: date
    ) -> list[CoveragePoint]:
        """Per-concept completeness, for spotting gaps before they reach a model.

        A thesis built on a concept with two data points is not the same claim
        as one built on forty, and nothing downstream can tell the difference
        unless coverage is measured.
        """
        stmt = (
            select(
                FinancialFact.concept,
                func.count().label("fact_count"),
                func.count(func.distinct(FinancialFact.period_end)).label("period_count"),
                func.min(FinancialFact.period_end).label("earliest_period"),
                func.max(FinancialFact.period_end).label("latest_period"),
                func.max(FinancialFact.filed_date).label("latest_filed"),
            )
            .where(
                FinancialFact.company_id == company_id,
                FinancialFact.filed_date <= as_of,
            )
            .group_by(FinancialFact.concept)
            .order_by(FinancialFact.concept)
        )

        rows = (await self.session.execute(stmt)).all()
        return [
            CoveragePoint(
                concept=r.concept,
                fact_count=int(r.fact_count),
                period_count=int(r.period_count),
                earliest_period=r.earliest_period,
                latest_period=r.latest_period,
                latest_filed=r.latest_filed,
            )
            for r in rows
        ]

    async def balance_sheet_check(
        self, company_id: uuid.UUID, *, as_of: date, tolerance: float = 0.01
    ) -> list[tuple[date, float, float, float, bool]]:
        """Assets ≈ Liabilities + Equity, per period.

        The fundamental accounting identity, used here as a reconciliation
        control: if it does not hold, either the concept mapping is picking up
        the wrong tag or the filer used a tag combination the mapping does not
        model. Either way the numbers downstream are not trustworthy, and it is
        far better to detect that here than to discover it in a thesis.

        Returns `(period_end, assets, liabilities_plus_equity, difference, ok)`.
        """
        assets = self._as_reported_cte(company_id, as_of=as_of, concept="total_assets")
        liabilities = self._as_reported_cte(
            company_id, as_of=as_of, concept="total_liabilities"
        )
        equity = self._as_reported_cte(
            company_id, as_of=as_of, concept="stockholders_equity"
        )

        rhs = (cast(liabilities.c.value, Float) + equity.c.value).label("rhs")
        diff = (cast(assets.c.value, Float) - (liabilities.c.value + equity.c.value)).label(
            "diff"
        )
        ok = case(
            (
                func.abs(assets.c.value - (liabilities.c.value + equity.c.value))
                <= tolerance * func.abs(func.nullif(assets.c.value, 0.0)),
                True,
            ),
            else_=False,
        ).label("ok")

        stmt = (
            select(assets.c.period_end, assets.c.value.label("assets"), rhs, diff, ok)
            .select_from(
                assets.join(liabilities, assets.c.period_end == liabilities.c.period_end).join(
                    equity, assets.c.period_end == equity.c.period_end
                )
            )
            .order_by(assets.c.period_end)
        )

        rows = (await self.session.execute(stmt)).all()
        return [
            (r.period_end, float(r.assets), float(r.rhs), float(r.diff), bool(r.ok))
            for r in rows
        ]
