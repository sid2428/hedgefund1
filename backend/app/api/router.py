"""Top-level API router that mounts every sub-router."""
from __future__ import annotations

from fastapi import APIRouter

from app.api import companies, filings, graph, jobs, theses

api_router = APIRouter()
api_router.include_router(theses.router, prefix="/theses", tags=["theses"])
api_router.include_router(companies.router, prefix="/companies", tags=["companies"])
api_router.include_router(filings.router, prefix="/filings", tags=["filings"])
api_router.include_router(graph.router, prefix="/graph", tags=["graph"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
