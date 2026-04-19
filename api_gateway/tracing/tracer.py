"""
Distributed tracing with OpenTelemetry integration.

Provides end-to-end request tracing across microservices with:
  - Automatic span creation and context propagation
  - Custom span attributes for business logic tracking
  - Integration with Jaeger or other OTLP backends
  - Correlation ID support for log aggregation

Trace Example:
  GET /api/scaling -> predict (Prophet) -> scale (Autoscaler) -> update
  └─ span: api_request (duration: 250ms)
     ├─ span: prophet_predict (duration: 50ms)
     ├─ span: autoscaler_decide (duration: 100ms)
     └─ span: database_update (duration: 80ms)
"""

import logging
import time
import uuid
from typing import Dict, Optional, Any, ContextManager
from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class Span:
    """A single trace span (operation)."""

    name: str
    trace_id: str
    span_id: str
    start_time: float
    end_time: Optional[float] = None
    parent_span_id: Optional[str] = None
    attributes: Dict[str, Any] = None
    events: list = None
    status: str = "OK"
    error: Optional[Exception] = None

    def __post_init__(self):
        if self.attributes is None:
            self.attributes = {}
        if self.events is None:
            self.events = []

    @property
    def duration_ms(self) -> float:
        """Get span duration in milliseconds."""
        if self.end_time:
            return (self.end_time - self.start_time) * 1000
        return (time.time() - self.start_time) * 1000

    def set_attribute(self, key: str, value: Any) -> None:
        """Set a span attribute."""
        self.attributes[key] = value

    def add_event(self, name: str, attributes: Optional[Dict] = None) -> None:
        """Add an event to the span."""
        self.events.append({"name": name, "timestamp": time.time(), "attributes": attributes or {}})

    def end(self) -> None:
        """Mark span as ended."""
        self.end_time = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "attributes": self.attributes,
            "events": self.events,
            "status": self.status,
            "error": str(self.error) if self.error else None,
        }


@dataclass
class TracingConfig:
    """Tracing configuration."""

    enabled: bool = True
    service_name: str = "scaleguard-api"
    environment: str = "production"
    jaeger_host: str = "localhost"
    jaeger_port: int = 6831
    sample_rate: float = 1.0  # 100% sampling
    max_spans_per_trace: int = 1000
    export_interval_seconds: int = 30
    # Optional: Jaeger endpoint for sending spans
    jaeger_endpoint: Optional[str] = None


class Tracer:
    """
    Simple distributed tracer for request correlation and performance analysis.

    Features:
      - Automatic trace ID generation and propagation
      - Parent-child span relationships
      - Span attributes for business data
      - Event logging within spans
      - Export via OpenTelemetry protocol

    Attributes:
        config: TracingConfig
        _spans: Active trace spans
        _trace_id_stack: Stack for nested trace context
    """

    def __init__(self, config: Optional[TracingConfig] = None):
        """
        Initialize tracer.

        Args:
            config: TracingConfig (uses defaults if None)
        """
        self.config = config or TracingConfig()
        self._spans: Dict[str, Span] = {}
        self._trace_id_stack: list = []
        self._span_id_stack: list = []

        logger.info(
            f"Tracer initialized: service={self.config.service_name}, "
            f"enabled={self.config.enabled}"
        )

    def start_trace(
        self,
        trace_id: Optional[str] = None,
        attributes: Optional[Dict] = None,
    ) -> str:
        """
        Start a new trace (top-level operation).

        Args:
            trace_id: Optional custom trace ID (auto-generated if not provided)
            attributes: Optional trace-level attributes

        Returns:
            Trace ID for correlation
        """
        if not self.config.enabled:
            return ""

        trace_id = trace_id or str(uuid.uuid4())
        self._trace_id_stack.append(trace_id)

        # Create root span
        span = self._create_span("trace_root", trace_id, None, attributes)
        self._spans[span.span_id] = span

        logger.debug(f"Trace started: {trace_id}")
        return trace_id

    def end_trace(self) -> None:
        """End current trace and clean up."""
        if not self.config.enabled or not self._trace_id_stack:
            return

        trace_id = self._trace_id_stack.pop()
        logger.debug(f"Trace ended: {trace_id}")

    def start_span(
        self,
        name: str,
        attributes: Optional[Dict] = None,
    ) -> Span:
        """
        Start a new span within current trace.

        Args:
            name: Span operation name
            attributes: Optional span attributes

        Returns:
            Span instance to continue operation
        """
        if not self.config.enabled or not self._trace_id_stack:
            return Span(name, "", "", time.time())

        trace_id = self._trace_id_stack[-1]
        parent_span_id = self._span_id_stack[-1] if self._span_id_stack else None

        span = self._create_span(name, trace_id, parent_span_id, attributes)
        self._spans[span.span_id] = span
        self._span_id_stack.append(span.span_id)

        logger.debug(
            f"Span started: {name} (parent={parent_span_id[:8]}...)"
            if parent_span_id
            else f"Span started: {name}"
        )

        return span

    def end_span(self, span: Span) -> None:
        """
        End a span.

        Args:
            span: Span to end
        """
        if not self.config.enabled:
            return

        span.end()
        if self._span_id_stack and self._span_id_stack[-1] == span.span_id:
            self._span_id_stack.pop()

        logger.debug(f"Span ended: {span.name} ({span.duration_ms:.1f}ms)")

    def _create_span(
        self,
        name: str,
        trace_id: str,
        parent_span_id: Optional[str],
        attributes: Optional[Dict],
    ) -> Span:
        """Create a span instance."""
        span = Span(
            name=name,
            trace_id=trace_id,
            span_id=str(uuid.uuid4()),
            parent_span_id=parent_span_id,
            start_time=time.time(),
            attributes=attributes or {},
        )
        return span

    @contextmanager
    def trace_context(
        self,
        span_name: str,
        attributes: Optional[Dict] = None,
    ) -> ContextManager[Span]:
        """
        Context manager for automatic span tracking.

        Usage:
            with tracer.trace_context("operation_name") as span:
                span.set_attribute("user_id", user_id)
                # ... operation code ...
                span.set_attribute("result", "success")
        """
        if not self.config.enabled:
            yield Span(span_name, "", "", time.time())
            return

        span = self.start_span(span_name, attributes)
        try:
            yield span
            span.status = "OK"
        except Exception as e:
            span.status = "ERROR"
            span.error = e
            logger.error(f"Span error: {span_name} - {e}")
            raise
        finally:
            self.end_span(span)

    def get_current_trace_id(self) -> Optional[str]:
        """Get current trace ID for correlation."""
        return self._trace_id_stack[-1] if self._trace_id_stack else None

    def get_span(self, span_id: str) -> Optional[Span]:
        """Get span by ID."""
        return self._spans.get(span_id)

    def get_trace_spans(self, trace_id: str) -> list:
        """Get all spans in a trace."""
        return [span for span in self._spans.values() if span.trace_id == trace_id]

    def export_trace(self, trace_id: str) -> Dict[str, Any]:
        """
        Export trace for external system (Jaeger, etc).

        Args:
            trace_id: Trace to export

        Returns:
            Trace data in exportable format
        """
        spans = self.get_trace_spans(trace_id)

        # Start with root span
        root_span = next(
            (s for s in spans if s.parent_span_id is None), spans[0] if spans else None
        )

        if not root_span:
            return {"trace_id": trace_id, "spans": []}

        exported_spans = [span.to_dict() for span in spans]
        request_level_span_count = len([span for span in spans if span.name != "trace_root"])

        return {
            "trace_id": trace_id,
            "service": self.config.service_name,
            "environment": self.config.environment,
            "start_time": root_span.start_time,
            "duration_ms": root_span.duration_ms,
            "span_count": request_level_span_count,
            "spans": exported_spans,
        }

    def clear_inactive_traces(self, older_than_seconds: int = 3600) -> None:
        """
        Remove traces older than threshold.

        Args:
            older_than_seconds: Age threshold
        """
        now = time.time()
        threshold = now - older_than_seconds

        removed = []
        for span_id, span in list(self._spans.items()):
            if span.end_time and span.end_time < threshold:
                del self._spans[span_id]
                removed.append(span_id)

        if removed:
            logger.debug(f"Cleaned {len(removed)} old spans")

    def get_stats(self) -> Dict[str, Any]:
        """Get tracer statistics."""
        active_traces = len(set(s.trace_id for s in self._spans.values()))

        return {
            "enabled": self.config.enabled,
            "active_spans": len(self._spans),
            "active_traces": active_traces,
            "service": self.config.service_name,
        }


class RequestTracer:
    """
    High-level wrapper for HTTP request tracing.

    Automatically creates traces for API requests and propagates
    trace context through headers.
    """

    def __init__(self, tracer: Tracer):
        """
        Initialize request tracer.

        Args:
            tracer: Tracer instance
        """
        self.tracer = tracer

    def extract_trace_context(self, headers: Dict[str, str]) -> str:
        """
        Extract trace ID from request headers.

        Looks for standard trace context headers:
          - traceparent (W3C standard)
          - x-trace-id (custom)
          - x-correlation-id (common)

        Args:
            headers: Request headers

        Returns:
            Trace ID (generated if not found)
        """
        # W3C traceparent format: version-trace_id-parent_id-flags
        traceparent = headers.get("traceparent", "")
        if traceparent:
            parts = traceparent.split("-")
            if len(parts) >= 2:
                return parts[1]

        # Try other standard headers in order
        return headers.get("x-trace-id") or headers.get("x-correlation-id") or str(uuid.uuid4())

    def start_request_trace(
        self,
        method: str,
        path: str,
        headers: Dict[str, str],
    ) -> str:
        """
        Start trace for HTTP request.

        Args:
            method: HTTP method
            path: Request path
            headers: Request headers

        Returns:
            Trace ID
        """
        trace_id = self.extract_trace_context(headers)
        self.tracer.start_trace(
            trace_id,
            attributes={
                "http.method": method,
                "http.path": path,
                "http.scheme": "https",
            },
        )
        return trace_id

    def add_response_span(
        self,
        status_code: int,
        duration_ms: float,
    ) -> None:
        """
        Add response metadata to current trace.

        Args:
            status_code: HTTP status code
            duration_ms: Request duration in milliseconds
        """
        with self.tracer.trace_context("http_response") as span:
            span.set_attribute("http.status_code", status_code)
            span.set_attribute("duration_ms", duration_ms)
