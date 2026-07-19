"""Tests for XBRL companyfacts parsing and point-in-time selection.

The payload shape mirrors the SEC `companyfacts` endpoint. The cases that
matter most are the temporal ones: a restatement must not leak backwards into a
period where it was not yet known, and an as-of query must filter on the date a
fact was *filed* rather than the period it describes.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.data.xbrl import (
    CONCEPT_TAGS,
    annual_facts,
    as_reported,
    as_restated,
    known_as_of,
    parse_company_facts,
    quarterly_facts,
    resolve_concept,
)


def _entry(*, start, end, val, filed, accn, form="10-K", fy=None, fp="FY"):
    e = {"end": end, "val": val, "filed": filed, "accn": accn, "form": form, "fp": fp}
    if start is not None:
        e["start"] = start
    if fy is not None:
        e["fy"] = fy
    return e


PAYLOAD = {
    "cik": 1045810,
    "entityName": "NVIDIA CORP",
    "facts": {
        "us-gaap": {
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "units": {
                    "USD": [
                        # FY2023, as originally reported.
                        _entry(
                            start="2022-01-31", end="2023-01-29", val=26974000000,
                            filed="2023-02-24", accn="0001045810-23-000017", fy=2023,
                        ),
                        # FY2023 again, restated in the following year's filing.
                        _entry(
                            start="2022-01-31", end="2023-01-29", val=26900000000,
                            filed="2024-02-21", accn="0001045810-24-000029", fy=2024,
                        ),
                        # FY2024.
                        _entry(
                            start="2023-01-30", end="2024-01-28", val=60922000000,
                            filed="2024-02-21", accn="0001045810-24-000029", fy=2024,
                        ),
                        # A quarter, to exercise duration filtering.
                        _entry(
                            start="2023-10-30", end="2024-01-28", val=22103000000,
                            filed="2024-02-21", accn="0001045810-24-000029",
                            form="10-Q", fp="Q4",
                        ),
                    ]
                }
            },
            # Legacy tag for the same canonical concept; lower precedence.
            "Revenues": {
                "units": {
                    "USD": [
                        _entry(
                            start="2023-01-30", end="2024-01-28", val=60922000000,
                            filed="2024-02-21", accn="0001045810-24-000029",
                        )
                    ]
                }
            },
            # Instant fact: balance-sheet item, no `start`.
            "Assets": {
                "units": {
                    "USD": [
                        _entry(
                            start=None, end="2024-01-28", val=65728000000,
                            filed="2024-02-21", accn="0001045810-24-000029",
                        )
                    ]
                }
            },
        },
        # Not in CONCEPT_TAGS — must be ignored rather than crash the parse.
        "srt": {"UnmappedConcept": {"units": {"USD": [_entry(
            start=None, end="2024-01-28", val=1, filed="2024-02-21", accn="x")]}}},
    },
}


# --- parsing ----------------------------------------------------------------


def test_parses_known_concepts_only():
    facts = parse_company_facts(PAYLOAD)
    assert {f.concept for f in facts} == {"revenue", "total_assets"}


def test_unmapped_taxonomy_is_ignored():
    """A tag we do not model must not appear, and must not raise."""
    facts = parse_company_facts(PAYLOAD)
    assert all(f.tag != "UnmappedConcept" for f in facts)


def test_both_time_axes_are_preserved():
    facts = resolve_concept(parse_company_facts(PAYLOAD), "revenue")
    fy2024 = next(f for f in facts if f.period_end == date(2024, 1, 28) and not f.is_instant
                  and f.duration_days and f.duration_days > 300)
    assert fy2024.period_end == date(2024, 1, 28)   # valid time
    assert fy2024.filed == date(2024, 2, 21)        # transaction time


def test_instant_fact_has_no_start():
    facts = parse_company_facts(PAYLOAD, concepts=["total_assets"])
    assert len(facts) == 1
    assert facts[0].is_instant
    assert facts[0].duration_days is None


def test_concepts_filter_restricts_output():
    facts = parse_company_facts(PAYLOAD, concepts=["total_assets"])
    assert {f.concept for f in facts} == {"total_assets"}


@pytest.mark.parametrize(
    "payload", [{}, {"facts": {}}, {"facts": {"us-gaap": None}}, {"facts": {"us-gaap": {}}}]
)
def test_empty_and_malformed_payloads_return_empty(payload):
    assert parse_company_facts(payload) == []


def test_entry_missing_required_field_is_skipped():
    payload = {"facts": {"us-gaap": {"Assets": {"units": {"USD": [
        {"end": "2024-01-28", "val": 1},                      # no filed/accn
        {"val": 1, "filed": "2024-02-21", "accn": "a"},        # no end
        {"end": "2024-01-28", "filed": "2024-02-21", "accn": "b"},  # no val
        {"end": "2024-01-28", "val": "not-a-number",
         "filed": "2024-02-21", "accn": "c"},                  # unparseable
    ]}}}}}
    assert parse_company_facts(payload) == []


# --- point-in-time ----------------------------------------------------------


def test_as_reported_keeps_the_original_not_the_restatement():
    """The number the market actually had, not the corrected one."""
    facts = as_reported(resolve_concept(parse_company_facts(PAYLOAD), "revenue"))
    fy2023 = next(f for f in facts if f.period_end == date(2023, 1, 29))
    assert fy2023.value == 26974000000
    assert fy2023.filed == date(2023, 2, 24)


def test_as_restated_keeps_the_correction():
    facts = as_restated(resolve_concept(parse_company_facts(PAYLOAD), "revenue"))
    fy2023 = next(f for f in facts if f.period_end == date(2023, 1, 29))
    assert fy2023.value == 26900000000


def test_known_as_of_excludes_facts_filed_later():
    """The central lookahead guard."""
    facts = resolve_concept(parse_company_facts(PAYLOAD), "revenue")
    visible = known_as_of(facts, date(2023, 6, 1))
    assert {f.value for f in visible} == {26974000000}


def test_known_as_of_filters_on_filed_not_period_end():
    """A period can be long over while its restatement is still in the future.

    FY2023 ended in January 2023, but the restated figure was not filed until
    February 2024. Filtering on period_end would wrongly admit it.
    """
    facts = resolve_concept(parse_company_facts(PAYLOAD), "revenue")
    visible = known_as_of(facts, date(2023, 6, 1))
    assert all(f.filed <= date(2023, 6, 1) for f in visible)
    assert 26900000000 not in {f.value for f in visible}


def test_as_of_before_any_filing_returns_nothing():
    facts = parse_company_facts(PAYLOAD)
    assert known_as_of(facts, date(2020, 1, 1)) == []


def test_point_in_time_pipeline_composes():
    """as-of then as-reported is the combination a backtest should use."""
    facts = resolve_concept(parse_company_facts(PAYLOAD), "revenue")
    result = as_reported(known_as_of(facts, date(2024, 3, 1)))
    by_period = {f.period_end: f.value for f in result}
    assert by_period[date(2023, 1, 29)] == 26974000000  # original, not restated
    assert by_period[date(2024, 1, 28)] == 60922000000


# --- concept resolution -----------------------------------------------------


def test_resolve_concept_prefers_higher_precedence_tag():
    """Revenues and RevenueFromContractWithCustomer both present; one must win."""
    facts = resolve_concept(parse_company_facts(PAYLOAD), "revenue")
    assert {f.tag for f in facts} == {"RevenueFromContractWithCustomerExcludingAssessedTax"}


def test_resolve_concept_does_not_double_count():
    facts = resolve_concept(parse_company_facts(PAYLOAD), "revenue")
    fy2024 = [f for f in facts if f.period_end == date(2024, 1, 28)
              and (f.duration_days or 0) > 300]
    assert len(fy2024) == 1


def test_resolve_concept_falls_back_when_only_legacy_tag_present():
    payload = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [_entry(
        start="2023-01-30", end="2024-01-28", val=100, filed="2024-02-21", accn="a")]}}}}}
    facts = resolve_concept(parse_company_facts(payload), "revenue")
    assert len(facts) == 1
    assert facts[0].tag == "Revenues"


def test_resolve_unknown_concept_is_empty():
    assert resolve_concept(parse_company_facts(PAYLOAD), "nonexistent") == []


def test_every_mapped_tag_resolves_to_its_concept():
    """Guards against a typo in CONCEPT_TAGS silently orphaning a tag."""
    for concept, tags in CONCEPT_TAGS.items():
        for tag in tags:
            payload = {"facts": {"us-gaap": {tag: {"units": {"USD": [_entry(
                start=None, end="2024-01-28", val=1,
                filed="2024-02-21", accn="a")]}}}}}
            parsed = parse_company_facts(payload)
            assert parsed, f"{tag} produced no facts"
            assert parsed[0].concept == concept


# --- period filtering -------------------------------------------------------


def test_annual_facts_keeps_only_year_length_periods():
    facts = annual_facts(resolve_concept(parse_company_facts(PAYLOAD), "revenue"))
    assert len(facts) == 3  # FY2023 original, FY2023 restated, FY2024
    assert all(340 <= (f.duration_days or 0) <= 390 for f in facts)


def test_quarterly_facts_keeps_only_quarter_length_periods():
    facts = quarterly_facts(resolve_concept(parse_company_facts(PAYLOAD), "revenue"))
    assert len(facts) == 1
    assert facts[0].value == 22103000000


def test_instant_facts_are_excluded_from_period_filters():
    facts = parse_company_facts(PAYLOAD, concepts=["total_assets"])
    assert annual_facts(facts) == []
    assert quarterly_facts(facts) == []
