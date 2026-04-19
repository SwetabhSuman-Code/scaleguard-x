"""
ScaleGuard X — Structured JSON Logging
Provides a single setup_json_logging() call that all services invoke on startup.

JSON log fields:
  timestamp   ISO-8601 UTC timestamp
  service     Service name (e.g. "api_gateway")
  level       Log level name
  message     Log message
  request_id  Optional request ID (populated by middleware)
  trace_id    Optional trace ID (OpenTelemetry span)
  thread_id   OS thread ID for concurrency debugging
  module      Python module name
  line        Source line number

Usage:
    from lib.logging_config import setup_json_logging, get_logger

    setup_json_logging("api_gateway")
    log = get_logger(__name__)
    log.info("Service started", extra={"request_id": "abc123"})
"""

from __future__ import annotations

import logging
import logging.config
import os
import sys
import threading
import traceback
from datetime import datetime, timezone
from typing import Any, MutableMapping, Optional


_SERVICE_NAME: str = "unknown"


class JsonFormatter(logging.Formatter):
    """
    Custom log formatter that emits each record as a single JSON object.
    Uses stdlib json to avoid extra deps; pythonjsonlogger is preferred in
    production but this works without installing anything extra.
    """

    # Fields to always include (in order)
    ALWAYS_FIELDS = (
        "timestamp",
        "service",
        "level",
        "message",
        "module",
        "line",
        "thread_id",
    )

    def format(self, record: logging.LogRecord) -> str:
        import json  # local import keeps top-level deps minimal

        record.message = record.getMessage()

        doc: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "service": _SERVICE_NAME,
            "level": record.levelname,
            "message": record.message,
            "module": record.module,
            "line": record.lineno,
            "thread_id": threading.get_ident(),
        }

        # Optional enrichment fields (from extra={} or context vars)
        for field in ("request_id", "trace_id", "span_id", "node_id", "worker_id"):
            value = getattr(record, field, None)
            if value:
                doc[field] = value

        # Exception info
        if record.exc_info:
            doc["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]),
                "traceback": self.formatException(record.exc_info),
            }

        # Any extra keys attached via `extra={}` on the log call
        skip = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "taskName",
        }
        for key, val in record.__dict__.items():
            if key not in skip and not key.startswith("_"):
                doc.setdefault(key, val)

        return json.dumps(doc, default=str)


class _ContextFilter(logging.Filter):
    """
    Injects context vars (request_id, trace_id) into every log record if they
    are stored in thread-local storage.  Services that use asyncio should
    populate _context via set_log_context().
    """

    _local = threading.local()

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = getattr(self._local, "ctx", {})
        for key, val in ctx.items():
            if not hasattr(record, key):
                setattr(record, key, val)
        return True


_context_filter = _ContextFilter()


def set_log_context(**kwargs: Any) -> None:
    """
    Set per-request context fields that will be injected into all subsequent
    log records on the current thread.

    Example:
        set_log_context(request_id="abc123", trace_id="xyz789")
    """
    if not hasattr(_ContextFilter._local, "ctx"):
        _ContextFilter._local.ctx = {}
    _ContextFilter._local.ctx.update(kwargs)


def clear_log_context() -> None:
    """Clear the per-thread logging context (call at end of request)."""
    _ContextFilter._local.ctx = {}


def setup_json_logging(
    service_name: str,
    level: str | None = None,
) -> None:
    """
    Configure root logger to emit structured JSON to stdout.

    Parameters
    ----------
    service_name:  Will appear as the "service" field in every log line.
    level:         Override log level (default: LOG_LEVEL env var, else INFO).
    """
    global _SERVICE_NAME
    _SERVICE_NAME = service_name

    log_level = level or os.getenv("LOG_LEVEL", "INFO").upper()

    formatter = JsonFormatter()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(_context_filter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # Silence noisy third-party loggers in production
    for noisy in ("uvicorn.access", "asyncpg", "docker"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Announce startup
    root.info(
        "Structured JSON logging initialised",
        extra={"service": service_name, "log_level": log_level},
    )


def get_logger(name: str) -> logging.Logger:
    """
    Convenience wrapper — same as logging.getLogger() but documents intent.

    Usage:
        log = get_logger(__name__)
    """
    return logging.getLogger(name)
