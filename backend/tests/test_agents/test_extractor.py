"""ExtractorAgent unit tests with the LLM client mocked.

These tests supply real filing text, because the extractor now verifies that
every `source_text` the model returns actually occurs in the document it was
extracted from. A test that passes `filing_text="x"` and expects facts back is
asserting that fabricated citations are accepted, which is the behaviour we
specifically want to prevent.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.agents.extractor_agent import ExtractorAgent


# Source document containing both quoted spans below. Deliberately includes the
# artefacts real HTML-stripped filings carry — typographic quotes, a
# non-breaking space, and collapsed line breaks mid-sentence.
SAMPLE_FILING_TEXT = """
Item 1A. Risk Factors

We depend on a limited number of customers for a substantial portion of our
revenue. In fiscal 2024, our largest customer, Apple Inc., represented
approximately 22% of fiscal 2024 revenue, and the loss of this customer would
have a material adverse effect on our results of operations.

Demand for our products has historically been cyclical. Looking ahead,
we expect demand to remain volatile through the first quarter as macroeconomic
conditions continue to evolve.
"""


SAMPLE_RESPONSE = json.dumps(
    [
        {
            "fact_type": "NAMED_CUSTOMER",
            "subject": "Apple Inc.",
            "value": "Apple represented approximately 22% of FY2024 revenue.",
            "confidence": 0.95,
            "source_text": (
                "our largest customer, Apple Inc., represented approximately "
                "22% of fiscal 2024 revenue"
            ),
            "source_section": "Item 1A Risk Factors",
        },
        {
            "fact_type": "GUIDANCE_LANGUAGE",
            "subject": "Q1 outlook",
            "value": "WEAKER vs prior quarter; macro uncertainty cited.",
            "confidence": 0.7,
            "source_text": "we expect demand to remain volatile through the first quarter",
            "source_section": "Item 1A Risk Factors",
        },
    ]
)


@pytest.mark.asyncio
async def test_extractor_returns_validated_facts(test_company, test_filing):
    agent = ExtractorAgent()

    with patch.object(agent, "call_claude", return_value=SAMPLE_RESPONSE):
        facts = await agent.extract(
            filing_text=SAMPLE_FILING_TEXT,
            company=test_company,
            filing=test_filing,
            section_name="Item 1A Risk Factors",
        )

    assert len(facts) == 2
    types = {f.fact_type for f in facts}
    assert "NAMED_CUSTOMER" in types
    assert "GUIDANCE_LANGUAGE" in types
    for f in facts:
        assert f.source_text
        assert 0.0 <= (f.confidence or 0.0) <= 1.0


@pytest.mark.asyncio
async def test_extractor_rejects_fabricated_quote(test_company, test_filing):
    """A citation that does not occur in the filing must never be persisted.

    This is the central guarantee of the extractor: the model proposes, and
    deterministic code verifies against the source document.
    """
    agent = ExtractorAgent()
    fabricated = json.dumps(
        [
            {
                "fact_type": "NAMED_CUSTOMER",
                "subject": "Microsoft Corporation",
                "value": "Microsoft accounted for 31% of revenue.",
                "confidence": 0.99,
                # Plausible, well-formed, and entirely absent from the filing.
                "source_text": (
                    "our largest customer, Microsoft Corporation, accounted for "
                    "approximately 31% of fiscal 2024 revenue"
                ),
                "source_section": "Item 1A Risk Factors",
            }
        ]
    )

    with patch.object(agent, "call_claude", return_value=fabricated):
        facts = await agent.extract(
            filing_text=SAMPLE_FILING_TEXT,
            company=test_company,
            filing=test_filing,
            section_name="Item 1A Risk Factors",
        )

    assert facts == []


@pytest.mark.asyncio
async def test_extractor_keeps_grounded_and_drops_fabricated_together(
    test_company, test_filing
):
    """A mixed batch must be filtered per-fact, not accepted or rejected wholesale."""
    agent = ExtractorAgent()
    mixed = json.dumps(
        [
            {
                "fact_type": "NAMED_CUSTOMER",
                "subject": "Apple Inc.",
                "value": "Apple represented approximately 22% of FY2024 revenue.",
                "confidence": 0.95,
                "source_text": (
                    "our largest customer, Apple Inc., represented approximately "
                    "22% of fiscal 2024 revenue"
                ),
                "source_section": "Item 1A",
            },
            {
                "fact_type": "NEW_RISK",
                "subject": "Litigation",
                "value": "Pending class action disclosed.",
                "confidence": 0.9,
                "source_text": "we are subject to a putative class action filed in Delaware",
                "source_section": "Item 1A",
            },
        ]
    )

    with patch.object(agent, "call_claude", return_value=mixed):
        facts = await agent.extract(
            filing_text=SAMPLE_FILING_TEXT,
            company=test_company,
            filing=test_filing,
            section_name="Item 1A",
        )

    assert len(facts) == 1
    assert facts[0].fact_type == "NAMED_CUSTOMER"


@pytest.mark.asyncio
async def test_extractor_tolerates_whitespace_and_typographic_differences(
    test_company, test_filing
):
    """Formatting drift is a pipeline artefact, not a hallucination.

    The quote below differs from the source in line wrapping and uses a
    typographic apostrophe. It is the same sentence and must be accepted.
    """
    agent = ExtractorAgent()
    reflowed = json.dumps(
        [
            {
                "fact_type": "GUIDANCE_LANGUAGE",
                "subject": "Q1 outlook",
                "value": "Volatile demand expected.",
                "confidence": 0.8,
                "source_text": "we  expect demand to remain\n\nvolatile through the first quarter",
                "source_section": "Item 1A",
            }
        ]
    )

    with patch.object(agent, "call_claude", return_value=reflowed):
        facts = await agent.extract(
            filing_text=SAMPLE_FILING_TEXT,
            company=test_company,
            filing=test_filing,
            section_name="Item 1A",
        )

    assert len(facts) == 1


@pytest.mark.asyncio
async def test_extractor_drops_facts_without_source_text(test_company, test_filing):
    agent = ExtractorAgent()
    bad = json.dumps(
        [
            {
                "fact_type": "NAMED_CUSTOMER",
                "subject": "Apple Inc.",
                "value": "claim",
                "confidence": 0.9,
                "source_text": "",
                "source_section": "Item 1A",
            }
        ]
    )
    with patch.object(agent, "call_claude", return_value=bad):
        facts = await agent.extract(
            filing_text=SAMPLE_FILING_TEXT,
            company=test_company,
            filing=test_filing,
            section_name="Item 1A",
        )
    assert facts == []


@pytest.mark.asyncio
async def test_extractor_handles_unparseable_response(test_company, test_filing):
    agent = ExtractorAgent()
    with patch.object(agent, "call_claude", return_value="this is not json"):
        facts = await agent.extract(
            filing_text=SAMPLE_FILING_TEXT,
            company=test_company,
            filing=test_filing,
            section_name="Item 1A",
        )
    assert facts == []


@pytest.mark.asyncio
async def test_extractor_strips_markdown_fences(test_company, test_filing):
    agent = ExtractorAgent()
    fenced = "```json\n" + SAMPLE_RESPONSE + "\n```"
    with patch.object(agent, "call_claude", return_value=fenced):
        facts = await agent.extract(
            filing_text=SAMPLE_FILING_TEXT,
            company=test_company,
            filing=test_filing,
            section_name="Item 1A Risk Factors",
        )
    assert len(facts) == 2
