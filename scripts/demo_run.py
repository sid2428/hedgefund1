"""End-to-end demo: seed (if needed) -> backfill NVDA -> run pipeline -> print theses.

Usage:
  docker-compose exec backend python /scripts/demo_run.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agents.orchestrator import PipelineOrchestrator  # noqa: E402
from app.data.edgar import EDGARClient, list_recent_filings  # noqa: E402
from app.db.repositories.company_repo import CompanyRepository  # noqa: E402
from app.db.repositories.filing_repo import FilingRepository  # noqa: E402
from app.db.repositories.thesis_repo import ThesisRepository  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.graph.builder import get_graph  # noqa: E402
from app.utils.logger import configure_logging, get_logger  # noqa: E402

DEMO_TICKER = "NVDA"


async def ensure_filings() -> None:
    """Make sure NVDA has the last 2 annual 10-Ks stored."""
    log = get_logger("demo")
    async with EDGARClient() as edgar, AsyncSessionLocal() as session:
        company = await CompanyRepository(session).get_by_ticker(DEMO_TICKER)
        if company is None:
            log.error("nvda_not_seeded")
            return

        submissions = await edgar.get_company_submissions(company.cik)
        recent = list_recent_filings(submissions, form_types=("10-K",), limit=2)
        repo = FilingRepository(session)

        from datetime import date as _date

        for entry in recent:
            if await repo.get_by_accession(entry["accession_number"]) is not None:
                continue
            text = await edgar.get_filing_document(
                company.cik, entry["accession_number"]
            )
            await repo.create(
                {
                    "company_id": company.id,
                    "filing_type": entry["filing_type"],
                    "accession_number": entry["accession_number"],
                    "filed_date": _date.fromisoformat(entry["filed_date"]),
                    "period_of_report": (
                        _date.fromisoformat(entry["period_of_report"])
                        if entry.get("period_of_report")
                        else None
                    ),
                    "raw_text": text,
                    "edgar_url": "",
                    "processed": False,
                }
            )
            log.info("demo_filing_stored", accession=entry["accession_number"])
        await session.commit()


async def run_pipeline() -> None:
    log = get_logger("demo")
    orchestrator = PipelineOrchestrator()

    async with AsyncSessionLocal() as session:
        company = await CompanyRepository(session).get_by_ticker(DEMO_TICKER)
        if company is None:
            return
        filings = await FilingRepository(session).get_for_company(
            company.id, filing_type="10-K", limit=2
        )

    for filing in filings:
        log.info("demo_running_pipeline", filing_id=str(filing.id))
        async with AsyncSessionLocal() as session:
            summary = await orchestrator.run_for_filing(filing.id, session)
        log.info("demo_pipeline_summary", **summary)


async def print_results() -> None:
    log = get_logger("demo")
    g = get_graph()
    async with AsyncSessionLocal() as session:
        await g.load_from_db(session)
        theses = await ThesisRepository(session).get_all(limit=20)

    print("\n" + "=" * 70)
    print("DEMO RESULTS")
    print("=" * 70)
    print(f"Graph: {g.node_count()} nodes, {g.edge_count()} edges")
    print(f"Theses generated: {len(theses)}")
    for t in theses:
        print("\n" + "-" * 70)
        print(f"  [{t.direction.upper()} | confidence {t.confidence_score:.2f}] {t.title}")
        print(f"  {t.summary[:300]}{'...' if len(t.summary) > 300 else ''}")
        ev = t.evidence_chain or []
        print(f"  Evidence steps: {len(ev)}")
        if t.invalidation_criteria:
            print(f"  Invalidation: {json.dumps(t.invalidation_criteria[0])[:120]}")
    print()


async def main() -> int:
    configure_logging()
    log = get_logger("demo")
    log.info("demo_start", ticker=DEMO_TICKER)

    try:
        await ensure_filings()
    except Exception as e:  # noqa: BLE001
        log.error("demo_ensure_filings_failed", error=str(e))

    try:
        await run_pipeline()
    except Exception as e:  # noqa: BLE001
        log.error("demo_pipeline_failed", error=str(e))

    await print_results()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
