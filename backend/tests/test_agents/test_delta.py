"""DeltaAgent unit tests."""
from __future__ import annotations

import json
import uuid
from datetime import date
from unittest.mock import patch

import pytest

from app.agents.delta_agent import DeltaAgent
from app.db.models import ExtractedFact, Filing


def _fact(filing_id, company_id, **kw) -> ExtractedFact:
    base = dict(
        id=uuid.uuid4(),
        filing_id=filing_id,
        company_id=company_id,
        fact_type="NAMED_CUSTOMER",
        subject="Apple Inc.",
        value="Apple was 22% of FY24 revenue.",
        confidence=0.9,
        source_section="Item 1A",
        source_text="Apple represented 22%",
    )
    base.update(kw)
    return ExtractedFact(**base)


SAMPLE_DELTAS = json.dumps(
    [
        {
            "delta_type": "CUSTOMER_REMOVED",
            "section": "Item 1A",
            "description": "Apple no longer disclosed as 10% customer.",
            "significance_score": 0.85,
            "previous_text": "Apple represented 22%",
            "current_text": "",
        }
    ]
)


@pytest.mark.asyncio
async def test_delta_detects_customer_removed(test_company, test_filing):
    agent = DeltaAgent()
    prior_filing = Filing(
        id=uuid.uuid4(),
        company_id=test_company.id,
        filing_type="10-K",
        accession_number=f"prior-{uuid.uuid4()}",
        filed_date=date(2024, 2, 15),
        period_of_report=date(2024, 1, 26),
    )
    prior_facts = [_fact(prior_filing.id, test_company.id)]
    current_facts: list[ExtractedFact] = []  # Apple gone

    with patch.object(agent, "call_claude", return_value=SAMPLE_DELTAS):
        deltas = await agent.compute_delta(
            current_facts=current_facts,
            prior_facts=prior_facts,
            company=test_company,
            current_filing=test_filing,
            prior_filing=prior_filing,
        )

    assert len(deltas) == 1
    assert deltas[0].delta_type == "CUSTOMER_REMOVED"
    assert deltas[0].significance_score is not None
    assert deltas[0].significance_score > 0.6


@pytest.mark.asyncio
async def test_delta_returns_empty_on_invalid_json(test_company, test_filing):
    agent = DeltaAgent()
    with patch.object(agent, "call_claude", return_value="garbage"):
        deltas = await agent.compute_delta(
            current_facts=[], prior_facts=[], company=test_company,
            current_filing=test_filing, prior_filing=test_filing,
        )
    assert deltas == []
