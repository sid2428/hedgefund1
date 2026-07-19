"""ConnectorAgent unit tests, focused on quality_gate + JSON parsing."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from unittest.mock import patch

import pytest

from app.agents.connector_agent import ConnectorAgent
from app.db.models import Company, FilingDelta


VALID_THESIS_JSON = json.dumps(
    {
        "title": "TSMC capacity tightening implies AMD/NVDA gross-margin pressure",
        "summary": "TSMC has signalled tighter advanced-node capacity in CY25. Customers reliant on N3/N5 (NVDA, AMD) likely face higher wafer prices, compressing gross margins. Pricing leverage skews to TSMC.",
        "thesis_type": "supply_chain_contagion",
        "direction": "long_short_pair",
        "confidence_score": 0.72,
        "affected_tickers": ["NVDA", "AMD"],
        "long_candidates": ["TSM"],
        "short_candidates": [],
        "evidence_chain": [
            {
                "step": 1,
                "description": "TSMC notes tighter capacity",
                "source_company": "TSM",
                "source_filing": "10-K FY24",
                "quote": "advanced-node capacity remains constrained",
            }
        ],
        "competing_thesis": "TSMC may discount to win volume.",
        "invalidation_criteria": ["NVDA reports flat or rising gross margin in next earnings."],
        "catalyst": "Next NVDA earnings report",
        "time_horizon": "quarters",
    }
)


def test_quality_gate_accepts_well_formed_thesis():
    agent = ConnectorAgent()
    parsed = json.loads(VALID_THESIS_JSON)
    assert agent.quality_gate(parsed) is True


def test_quality_gate_rejects_low_confidence():
    agent = ConnectorAgent()
    parsed = json.loads(VALID_THESIS_JSON)
    parsed["confidence_score"] = 0.3
    assert agent.quality_gate(parsed) is False


def test_quality_gate_rejects_empty_evidence_chain():
    agent = ConnectorAgent()
    parsed = json.loads(VALID_THESIS_JSON)
    parsed["evidence_chain"] = []
    assert agent.quality_gate(parsed) is False


def test_quality_gate_rejects_missing_invalidation():
    agent = ConnectorAgent()
    parsed = json.loads(VALID_THESIS_JSON)
    parsed["invalidation_criteria"] = []
    assert agent.quality_gate(parsed) is False


@pytest.mark.asyncio
async def test_connector_returns_none_when_rejected(test_company, async_session):
    """Rejection envelope from the model -> agent returns None (no thesis).

    A real session is required. The agent loads recent facts for each connected
    company in order to build the prompt, so the database is necessarily touched
    before the model can return anything to reject.
    """
    agent = ConnectorAgent()
    delta = FilingDelta(
        id=uuid.uuid4(),
        company_id=test_company.id,
        current_filing_id=uuid.uuid4(),
        delta_type="CUSTOMER_REMOVED",
        section="Item 1A",
        description="Apple removed",
        significance_score=0.9,
        previous_text="Apple represented 22%",
        current_text="",
        created_at=datetime.utcnow(),
    )
    with patch.object(
        agent,
        "call_claude",
        return_value=json.dumps({"reject": True, "reason": "insufficient evidence"}),
    ):
        # Fake a connected company so we don't early-return on empty neighbors.
        result = await agent.generate_thesis(
            trigger_delta=delta,
            trigger_company=test_company,
            connected_companies=[
                {
                    "ticker": "AMD",
                    "name": "Advanced Micro Devices",
                    "company_id": test_company.id,
                    "relationship_type": "competitor",
                    "degree": 1,
                }
            ],
            session=async_session,
        )
    assert result is None
