"""Structured logging configuration using structlog.

Outputs JSON in production (machine-readable) and pretty console renders in dev.
Call `configure_logging()` once at process startup before creating loggers.
"""
from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.config import settings


def configure_logging() -> None:
    """Configure stdlib logging and structlog. Idempotent."""
    timestamper = structlog.processors.TimeStamper(fmt="iso")

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
    ]

    renderer: Any
    if settings.ENVIRONMENT == "development":
        # ConsoleRenderer formats exceptions itself and warns if handed
        # already-formatted output, so `format_exc_info` is added only for the
        # JSON path, where the traceback does need flattening to a string.
        renderer = structlog.dev.ConsoleRenderer(colors=False)
    else:
        shared_processors.append(structlog.processors.format_exc_info)
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.LOG_LEVEL, logging.INFO)
        ),
        context_class=dict,
        # Must be the stdlib factory, not PrintLoggerFactory: the
        # `add_logger_name` processor above reads `.name` off the underlying
        # logger, and PrintLogger has no such attribute — every log call would
        # raise AttributeError. Routing through stdlib also makes the
        # basicConfig and library-quieting below actually apply.
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=settings.LOG_LEVEL,
        force=True,
    )

    # Quiet noisy libraries.
    for noisy in ("httpx", "httpcore", "asyncio", "urllib3", "yfinance"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)
