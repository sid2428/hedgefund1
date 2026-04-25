"""GraphAgent — turns extracted facts into company-relationship graph edges.

Mostly rule-based:
  - NAMED_CUSTOMER fact      -> filer --(customer)--> named entity
  - NAMED_SUPPLIER fact      -> named entity --(supplier)--> filer
  - companies in same sector -> sector_peer (low strength)

Company-name -> ticker resolution uses a local dict built from the seed
universe plus rapidfuzz partial matching above a confidence threshold.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Iterable

from rapidfuzz import fuzz, process
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.config import settings
from app.db.models import Company, ExtractedFact
from app.db.repositories.company_repo import CompanyRepository
from app.db.repositories.graph_repo import GraphRepository

SEED_UNIVERSE_PATH = Path("/data/seed/semiconductor_universe.json")
LOCAL_SEED_UNIVERSE_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "seed" / "semiconductor_universe.json"
)


def _load_seed_universe() -> list[dict[str, str]]:
    """Load the seed universe from /data (in Docker) or repo-relative path."""
    for candidate in (SEED_UNIVERSE_PATH, LOCAL_SEED_UNIVERSE_PATH):
        if candidate.exists():
            with candidate.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
    return []


class GraphAgent(BaseAgent):
    """Builds graph edges from facts. Calls no LLM directly, but inherits BaseAgent
    so behaviour is uniform (logging, etc.)."""

    PROMPT = "graph_builder.j2"

    def __init__(self) -> None:
        super().__init__()
        seed = _load_seed_universe()
        # name -> ticker (case-insensitive). Includes simple aliases.
        self.company_lookup: dict[str, str] = {}
        for entry in seed:
            ticker = entry["ticker"].upper()
            self.company_lookup[entry["name"].lower()] = ticker
            self.company_lookup[ticker.lower()] = ticker
            # crude alias: drop "Corporation", "Inc.", etc.
            short = (
                entry["name"]
                .lower()
                .replace(" corporation", "")
                .replace(" corp", "")
                .replace(" inc.", "")
                .replace(" inc", "")
                .replace(",", "")
                .strip()
            )
            if short:
                self.company_lookup[short] = ticker

    # ---- Resolution ------------------------------------------------------
    def resolve_company_name(self, name: str) -> str | None:
        if not name:
            return None
        key = name.strip().lower()
        if key in self.company_lookup:
            return self.company_lookup[key]
        # Fuzzy match
        best = process.extractOne(
            key, self.company_lookup.keys(), scorer=fuzz.WRatio
        )
        if best is None:
            return None
        match_key, score, _ = best
        if score >= settings.GRAPH_FUZZY_MATCH_THRESHOLD:
            return self.company_lookup[match_key]
        return None

    # ---- Graph update ----------------------------------------------------
    async def update_graph(
        self,
        facts: Iterable[ExtractedFact],
        session: AsyncSession,
    ) -> int:
        """Process facts -> graph edges. Returns the count of edges upserted."""
        company_repo = CompanyRepository(session)
        graph_repo = GraphRepository(session)
        edges_added = 0

        for fact in facts:
            ftype = (fact.fact_type or "").upper()
            if ftype not in ("NAMED_CUSTOMER", "NAMED_SUPPLIER"):
                continue
            subject = fact.subject or ""
            target_ticker = self.resolve_company_name(subject)
            if target_ticker is None:
                self.log.debug(
                    "graph_unresolved_subject", subject=subject, fact_type=ftype
                )
                continue
            target = await company_repo.get_by_ticker(target_ticker)
            if target is None or target.id == fact.company_id:
                continue

            confidence = float(fact.confidence or 0.7)
            strength = max(0.3, min(1.0, confidence))

            if ftype == "NAMED_CUSTOMER":
                # filer -> target: target is a customer of the filer
                source_id, target_id, rel = fact.company_id, target.id, "customer"
            else:  # NAMED_SUPPLIER
                # target -> filer: target is a supplier to the filer
                source_id, target_id, rel = target.id, fact.company_id, "supplier"

            await graph_repo.upsert_relationship(
                source_id=source_id,
                target_id=target_id,
                relationship_type=rel,
                strength=strength,
                evidence_text=(fact.source_text or "")[:1000] or None,
                source_filing_id=fact.filing_id,
            )
            edges_added += 1

        # Add sector-peer edges for companies in the same sector (low strength).
        edges_added += await self._add_sector_peer_edges(session)
        return edges_added

    async def _add_sector_peer_edges(self, session: AsyncSession) -> int:
        """Idempotent sector-peer edges for companies sharing a sector."""
        company_repo = CompanyRepository(session)
        graph_repo = GraphRepository(session)
        companies = await company_repo.get_all()

        # Group by sector
        by_sector: dict[str, list[Company]] = {}
        for c in companies:
            if not c.sector:
                continue
            by_sector.setdefault(c.sector, []).append(c)

        added = 0
        for peers in by_sector.values():
            for i, a in enumerate(peers):
                for b in peers[i + 1 :]:
                    await graph_repo.upsert_relationship(
                        source_id=a.id,
                        target_id=b.id,
                        relationship_type="sector_peer",
                        strength=0.3,
                    )
                    await graph_repo.upsert_relationship(
                        source_id=b.id,
                        target_id=a.id,
                        relationship_type="sector_peer",
                        strength=0.3,
                    )
                    added += 2
        return added
