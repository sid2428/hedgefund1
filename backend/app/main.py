"""FastAPI application entry point."""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.config import settings
from app.db.session import close_engine, create_all_tables
from app.graph.builder import get_graph
from app.utils.logger import configure_logging, get_logger

configure_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info("startup", env=settings.ENVIRONMENT)
    if settings.is_sqlite:
        # In tests / lightweight dev we let SQLAlchemy create tables.
        await create_all_tables()
    # Warm the in-memory company graph from DB.
    try:
        graph = get_graph()
        await graph.load_from_db()
        log.info("graph_loaded", nodes=graph.node_count(), edges=graph.edge_count())
    except Exception as e:  # noqa: BLE001
        log.warning("graph_load_failed", error=str(e))
    yield
    log.info("shutdown")
    await close_engine()


app = FastAPI(
    title="Mosaic API",
    description="AI-Native Cross-Company Investment Thesis Engine",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    log.info(
        "request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=round(duration_ms, 1),
    )
    return response


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "mosaic", "environment": settings.ENVIRONMENT}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_exception", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "detail": str(exc)},
    )


app.include_router(api_router, prefix="/api")
