"""
ScaleGuard X — Unit Tests: Structured Logging
"""
from __future__ import annotations

import json
import logging

import pytest

from lib.logging_config import (
    clear_log_context,
    get_logger,
    set_log_context,
    setup_json_logging,
)


@pytest.mark.unit
class TestJsonLogging:
    def setup_method(self) -> None:
        clear_log_context()

    def test_setup_does_not_crash(self) -> None:
        setup_json_logging("test_service")
        log = get_logger("test_service")
        log.info("setup test")

    def test_get_logger_returns_logger(self) -> None:
        log = get_logger("my.module")
        assert isinstance(log, logging.Logger)

    def test_set_and_clear_context(self) -> None:
        from lib.logging_config import _ContextFilter
        set_log_context(request_id="abc123", trace_id="xyz")
        ctx = getattr(_ContextFilter._local, "ctx", {})
        assert ctx.get("request_id") == "abc123"
        assert ctx.get("trace_id") == "xyz"

        clear_log_context()
        ctx_after = getattr(_ContextFilter._local, "ctx", {})
        assert ctx_after == {}

    def test_log_produces_json(self, capsys) -> None:
        setup_json_logging("json_test")
        log = get_logger("json_test")
        log.info("hello structured world")
        captured = capsys.readouterr()
        # At least one line should be valid JSON
        lines = [l for l in captured.out.strip().splitlines() if l]
        parsed = json.loads(lines[-1])
        assert parsed["service"] == "json_test"
        assert "timestamp" in parsed
        assert "level" in parsed
        assert "message" in parsed
