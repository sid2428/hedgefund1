"""XBRL companyfacts parsing and concept normalisation.

SEC filers have tagged their financial statements in XBRL since 2009, and the
`companyfacts` endpoint returns every fact a company has ever reported as JSON.
Those numbers do not need to be inferred by a language model: they are the
values the company filed, and reading them directly is faster, free, and exact.

Two properties of the raw payload make it awkward to use as-is, and this module
exists to handle both.

**Concepts are not uniform.** "Revenue" appears under several different us-gaap
tags depending on the filer and the era, so a caller asking for revenue needs a
precedence order rather than a single tag name.

**Facts are bitemporal, and the payload flattens that.** Every entry carries
both the period it describes (`start`/`end`) and the date the filing that
reported it was submitted (`filed`). The same period is frequently reported more
than once, because restatements re-report prior periods with corrected numbers.
Selecting on the wrong axis silently introduces lookahead bias: a backtest that
reads a restated 2019 figure is using a number nobody had in 2019.

The default here is therefore *as-reported* — the earliest filing for a given
period — and any as-of query filters on `filed`, never on `end`.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

# Canonical concept -> us-gaap tags in descending order of preference.
#
# Order matters. `RevenueFromContractWithCustomer*` is the post-ASC-606 tag and
# is preferred where present; `Revenues` and `SalesRevenueNet` are the older
# forms and appear in historical filings. A filer may report several of these in
# the same document, so the first tag with data wins rather than merging them.
CONCEPT_TAGS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ),
    "cost_of_revenue": (
        "CostOfGoodsAndServicesSold",
        "CostOfRevenue",
        "CostOfGoodsSold",
    ),
    "gross_profit": ("GrossProfit",),
    "operating_income": (
        "OperatingIncomeLoss",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    ),
    "net_income": (
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ),
    "research_and_development": ("ResearchAndDevelopmentExpense",),
    "total_assets": ("Assets",),
    "total_liabilities": ("Liabilities",),
    "stockholders_equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "cash_and_equivalents": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "operating_cash_flow": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ),
    "capital_expenditure": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ),
    "shares_outstanding": (
        "CommonStockSharesOutstanding",
        "EntityCommonStockSharesOutstanding",
    ),
    "inventory": ("InventoryNet",),
    "long_term_debt": ("LongTermDebtNoncurrent", "LongTermDebt"),
}

# Reverse index, built once: tag -> canonical concept.
_TAG_TO_CONCEPT: dict[str, str] = {
    tag: concept for concept, tags in CONCEPT_TAGS.items() for tag in tags
}

# Taxonomies worth reading. "dei" carries entity-level facts such as shares
# outstanding; everything else of interest is us-gaap.
_TAXONOMIES = ("us-gaap", "dei")


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class XBRLFact:
    """One reported value, with both of its time axes preserved."""

    concept: str
    """Canonical concept name, e.g. `revenue`."""

    tag: str
    """The us-gaap/dei tag this came from, kept for provenance."""

    taxonomy: str
    unit: str
    value: float

    period_start: date | None
    """None for instant facts (balance-sheet items have a date, not a range)."""

    period_end: date
    """Valid time — the period the number describes."""

    filed: date
    """Transaction time — when this number became public knowledge.

    Every as-of query must filter on this field. Filtering on `period_end`
    instead is precisely the mistake that introduces lookahead bias.
    """

    accession: str
    form: str
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    frame: str | None = None

    @property
    def is_instant(self) -> bool:
        return self.period_start is None

    @property
    def duration_days(self) -> int | None:
        if self.period_start is None:
            return None
        return (self.period_end - self.period_start).days

    @property
    def period_key(self) -> tuple[str, str, date | None, date]:
        """Identity of the *period* being described, ignoring who reported it.

        Two entries sharing this key are the same fact reported by different
        filings — an original and a restatement.
        """
        return (self.concept, self.unit, self.period_start, self.period_end)


def parse_company_facts(
    payload: dict[str, Any],
    *,
    concepts: Iterable[str] | None = None,
) -> list[XBRLFact]:
    """Parse an SEC `companyfacts` payload into normalised facts.

    Only tags mapped in `CONCEPT_TAGS` are returned; the raw payload contains
    hundreds of tags, the large majority of which are not useful here. Entries
    that are malformed or missing a required field are skipped rather than
    raising, because a single bad entry should not discard an entire company.
    """
    wanted: set[str] | None = set(concepts) if concepts is not None else None
    facts_root = (payload or {}).get("facts") or {}
    out: list[XBRLFact] = []

    for taxonomy in _TAXONOMIES:
        tags = facts_root.get(taxonomy) or {}
        if not isinstance(tags, dict):
            continue

        for tag, tag_body in tags.items():
            concept = _TAG_TO_CONCEPT.get(tag)
            if concept is None:
                continue
            if wanted is not None and concept not in wanted:
                continue
            if not isinstance(tag_body, dict):
                continue

            for unit, entries in (tag_body.get("units") or {}).items():
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    fact = _build_fact(entry, concept=concept, tag=tag, taxonomy=taxonomy, unit=unit)
                    if fact is not None:
                        out.append(fact)

    return out


def _build_fact(
    entry: Any, *, concept: str, tag: str, taxonomy: str, unit: str
) -> XBRLFact | None:
    if not isinstance(entry, dict):
        return None

    period_end = _parse_date(entry.get("end"))
    filed = _parse_date(entry.get("filed"))
    raw_value = entry.get("val")
    accession = entry.get("accn")

    # `end`, `filed` and `val` are non-negotiable: without them the fact cannot
    # be placed in time or used.
    if period_end is None or filed is None or raw_value is None or not accession:
        return None

    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None

    fiscal_year = entry.get("fy")
    return XBRLFact(
        concept=concept,
        tag=tag,
        taxonomy=taxonomy,
        unit=unit,
        value=value,
        period_start=_parse_date(entry.get("start")),
        period_end=period_end,
        filed=filed,
        accession=str(accession),
        form=str(entry.get("form") or ""),
        fiscal_year=int(fiscal_year) if isinstance(fiscal_year, (int, float)) else None,
        fiscal_period=entry.get("fp") or None,
        frame=entry.get("frame") or None,
    )


def known_as_of(facts: Sequence[XBRLFact], cutoff: date) -> list[XBRLFact]:
    """Restrict to facts that had actually been filed by `cutoff`.

    This is the lookahead guard. It filters on `filed`, so a fact describing
    Q1 2019 that was not reported until a 2021 restatement is correctly absent
    from a query as of mid-2019.
    """
    return [f for f in facts if f.filed <= cutoff]


def as_reported(facts: Sequence[XBRLFact]) -> list[XBRLFact]:
    """Collapse restatements, keeping the value originally reported.

    Where a period appears more than once, the earliest filing wins. This is
    the point-in-time correct choice: it is the number the market actually had.
    Backtests run on restated figures systematically outperform the same
    backtests run on as-reported figures, because the corrections encode
    information that did not exist at the time.
    """
    return _dedupe(facts, latest=False)


def as_restated(facts: Sequence[XBRLFact]) -> list[XBRLFact]:
    """Collapse restatements, keeping the most recently reported value.

    Appropriate for describing what is true now. Not appropriate for anything
    evaluating a decision made in the past.
    """
    return _dedupe(facts, latest=True)


def _dedupe(facts: Sequence[XBRLFact], *, latest: bool) -> list[XBRLFact]:
    chosen: dict[tuple[str, str, date | None, date], XBRLFact] = {}
    for fact in facts:
        current = chosen.get(fact.period_key)
        if current is None:
            chosen[fact.period_key] = fact
            continue
        if (fact.filed > current.filed) if latest else (fact.filed < current.filed):
            chosen[fact.period_key] = fact
    return sorted(chosen.values(), key=lambda f: (f.concept, f.period_end))


def resolve_concept(facts: Sequence[XBRLFact], concept: str) -> list[XBRLFact]:
    """Reduce a concept to a single tag, using the precedence in `CONCEPT_TAGS`.

    A filer may report both `Revenues` and `RevenueFromContractWithCustomer...`.
    Summing or interleaving them double-counts, so the highest-precedence tag
    that has any data is used and the others are dropped.
    """
    candidates = [f for f in facts if f.concept == concept]
    if not candidates:
        return []

    present = {f.tag for f in candidates}
    for tag in CONCEPT_TAGS.get(concept, ()):
        if tag in present:
            return sorted(
                (f for f in candidates if f.tag == tag),
                key=lambda f: f.period_end,
            )
    return sorted(candidates, key=lambda f: f.period_end)


def annual_facts(facts: Sequence[XBRLFact], *, tolerance_days: int = 20) -> list[XBRLFact]:
    """Keep duration facts covering roughly a year.

    Fiscal years are not exactly 365 days — 52/53-week retail calendars drift by
    up to a week, and filers round period boundaries — so this matches on a
    window rather than an exact length.
    """
    lo, hi = 365 - tolerance_days, 365 + tolerance_days
    return [f for f in facts if (d := f.duration_days) is not None and lo <= d <= hi]


def quarterly_facts(facts: Sequence[XBRLFact], *, tolerance_days: int = 15) -> list[XBRLFact]:
    """Keep duration facts covering roughly a quarter."""
    lo, hi = 91 - tolerance_days, 91 + tolerance_days
    return [f for f in facts if (d := f.duration_days) is not None and lo <= d <= hi]
