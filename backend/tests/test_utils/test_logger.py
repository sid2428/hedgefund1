"""Logging configuration tests.

These exist because a mismatched processor/factory pair made every log call
raise AttributeError at runtime — `structlog.stdlib.add_logger_name` reads
`.name` off the underlying logger, which `PrintLogger` does not have. Nothing
in the suite exercised a successful log call, so the whole application logged
nothing and nobody noticed.

The assertion is deliberately unglamorous: logging must not raise.
"""
from __future__ import annotations

import pytest

from app.utils.logger import configure_logging, get_logger


@pytest.fixture(autouse=True)
def _configured():
    configure_logging()


@pytest.mark.parametrize("level", ["debug", "info", "warning", "error"])
def test_log_call_does_not_raise(level):
    log = get_logger(__name__)
    getattr(log, level)("test_event", key="value", number=1)


def test_log_call_with_no_kwargs_does_not_raise():
    get_logger(__name__).info("bare_event")


def test_exception_logging_does_not_raise():
    log = get_logger(__name__)
    try:
        raise ValueError("boom")
    except ValueError:
        log.error("caught", exc_info=True)


def test_configure_logging_is_repeatable():
    """Called at import in some paths and explicitly in others."""
    configure_logging()
    configure_logging()
    get_logger(__name__).info("still_fine")


def test_logger_name_is_available_to_processors():
    """The regression itself: add_logger_name must find a `.name` to read."""
    log = get_logger("mosaic.test.named")
    log.info("named_event")
