"""ExtractorAgent unit tests with the Anthropic client mocked."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.agents.extractor_agent import ExtractorAgent


SAMPLE_RESPONSE = json.dumps(
    [
        {
            "fact_type": "NAMED_CUSTOMER",
            "subject": "Apple Inc.",
            "value": "Apple represented approximately 22% of FY2024 revenue.",
            "confidence": 0.95,
            "source_text": "our largest customer, Apple Inc., represented approximately 22% of fiscal 2024 revenue",
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
            filing_text="some text containing Apple",
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
            filing_text="x", company=test_company, filing=test_filing, section_name="Item 1A"
        )
    assert facts == []


@pytest.mark.asyncio
async def test_extractor_handles_unparseable_response(test_company, test_filing):
    agent = ExtractorAgent()
    with patch.object(agent, "call_claude", return_value="this is not json"):
        facts = await agent.extract(
            filing_text="x", company=test_company, filing=test_filing, section_name="Item 1A"
        )
    assert facts == []


@pytest.mark.asyncio
async def test_extractor_strips_markdown_fences(test_company, test_filing):
    agent = ExtractorAgent()
    fenced = "```json\n" + SAMPLE_RESPONSE + "\n```"
    with patch.object(agent, "call_claude", return_value=fenced):
        facts = await agent.extract(
            filing_text="x", company=test_company, filing=test_filing, section_name="Item 1A"
        )
    assert len(facts) == 2
