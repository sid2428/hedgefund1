"""Seed the `companies` table from data/seed/semiconductor_universe.json.

Looks for the file at /data/seed/semiconductor_universe.json (Docker mount)
or repo-relative `data/seed/...` (local). Upserts each row and best-effort
fetches market_cap from yfinance.

Usage:
  docker-compose exec backend python /scripts/seed_companies.py
  # or, locally:
  python scripts/seed_companies.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Ensure 'app' package is importable when this script is run as __main__.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.data.market_data import get_market_cap  # noqa: E402
from app.db.repositories.company_repo import CompanyRepository  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.utils.logger import configure_logging, get_logger  # noqa: E402

SEED_PATHS = [
    Path("/data/seed/semiconductor_universe.json"),
    ROOT / "data" / "seed" / "semiconductor_universe.json",
]


def _load_seed() -> list[dict]:
    for p in SEED_PATHS:
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError(f"Could not locate seed JSON in: {SEED_PATHS}")


async def main() -> int:
    configure_logging()
    log = get_logger("seed")

    universe = _load_seed()
    log.info("seed_loaded", count=len(universe))

    async with AsyncSessionLocal() as session:
        repo = CompanyRepository(session)
        for entry in universe:
            ticker = entry["ticker"].upper()
            cik = str(entry["cik"]).lstrip("0") or "0"
            data = {
                "ticker": ticker,
                "cik": cik,
                "name": entry["name"],
                "sector": entry.get("sector"),
                "industry": entry.get("industry"),
            }
            # Best-effort market cap; never block seed if yfinance fails.
            try:
                cap = await get_market_cap(ticker)
                if cap:
                    data["market_cap"] = cap
            except Exception as e:  # noqa: BLE001
                log.warning("market_cap_failed", ticker=ticker, error=str(e))

            company = await repo.upsert(data)
            log.info("company_upserted", ticker=company.ticker, id=str(company.id))
        await session.commit()

    log.info("seed_complete", count=len(universe))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
