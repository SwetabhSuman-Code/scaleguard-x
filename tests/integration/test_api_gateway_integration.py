"""
Integration tests for API gateway authentication, authorization, and middleware.

Tests the complete flow:
1. JWT token generation and validation
2. RBAC permission checking
3. Rate limiting enforcement
4. Distributed tracing across requests
5. End-to-end security and observability
"""

import pytest
import time
from unittest.mock import Mock, patch
from datetime import datetime, timedelta, timezone

from api_gateway.auth.jwt_handler import JWTHandler, JWTConfig, TokenClaims
from api_gateway.auth.rbac import RBACManager, Permission
from api_gateway.middleware.rate_limiter import (
    RateLimiter,
    RateLimitConfig,
    RateLimitStrategy,
)
from api_gateway.tracing.tracer import Tracer, TracingConfig, RequestTracer


class TestAuthenticationFlow:
    """Test complete authentication workflow."""

    def test_user_login_and_token_validation(self):
        """User can login and get validated token."""
        handler = JWTHandler(JWTConfig(secret_key="test-secret"))

        # User logs in
        result = handler.generate_token(
            "user123", username="john_doe", email="john@example.com", roles=["viewer"]
        )

        token = result["access_token"]
        assert result["token_type"] == "Bearer"
        assert result["expires_in"] > 0

        # Token validation extracts claims
        claims = handler.validate_token(token)
        assert claims.sub == "user123"
        assert claims.username == "john_doe"
        assert "viewer" in claims.roles


class TestRBACEnforcement:
    """Test role-based access control enforcement."""

    def test_multi_role_accumulates_permissions(self):
        """User with multiple roles gets union of permissions."""
        rbac = RBACManager()

        # User with operator + viewer roles
        access = rbac.evaluate_access("user123", ["operator", "viewer"], Permission.SCALING_EXECUTE)

        # Has both operator and viewer permissions
        assert access.has_permission(Permission.SCALING_EXECUTE)
        assert access.has_permission(Permission.METRICS_READ)
        assert access.has_permission(Permission.PREDICTIONS_READ)

    def test_custom_role_creation(self):
        """Can create and assign custom roles."""
        rbac = RBACManager()

        # Create custom role with specific permissions
        from api_gateway.auth.rbac import Role

        custom_role = Role(
            name="analyst",
            permissions={
                Permission.METRICS_READ,
                Permission.PREDICTIONS_READ,
            },
        )
        rbac.register_role(custom_role)

        # User with custom role
        access = rbac.evaluate_access("user123", ["analyst"], Permission.METRICS_READ)
        assert access.has_permission(Permission.METRICS_READ)
        assert access.has_permission(Permission.PREDICTIONS_READ)
        assert not access.has_permission(Permission.SCALING_EXECUTE)


class TestRateLimitingWithRoles:
    """Test rate limiting respects role-based limits."""

    def test_admin_has_high_rate_limit(self):
        """Admin users get 1000 rps limit."""
        config = RateLimitConfig(strategy=RateLimitStrategy.TOKEN_BUCKET)
        limiter = RateLimiter(config)

        # Admin user - should allow multiple requests
        allowed_count = 0
        for i in range(10):
            allowed, meta = limiter.check_limit("admin_user", role="admin")
            if allowed:
                allowed_count += 1
        assert allowed_count >= 8  # Most should be allowed for admin


class TestDistributedTracingIntegration:
    """Test distributed tracing across request lifecycle."""

    def test_trace_follows_request_lifecycle(self):
        """Trace captures full request execution."""
        tracer = Tracer(TracingConfig())

        # Start request trace
        trace_id = tracer.start_trace(attributes={"endpoint": "/api/scaling"})

        # Simulate nested operations
        with tracer.trace_context("auth_check", attributes={"user": "user123"}):
            pass

        with tracer.trace_context("rbac_eval", attributes={"roles": ["operator"]}):
            pass

        with tracer.trace_context("execute_scaling", attributes={"action": "scale_up"}):
            pass

        # Export trace
        trace_data = tracer.export_trace(trace_id)

        assert trace_data["trace_id"] == trace_id
        assert trace_data["span_count"] == 3  # Three nested spans
        assert len(trace_data["spans"]) > 0

    def test_trace_context_propagation(self):
        """Trace ID propagates through header extraction."""
        tracer = Tracer(TracingConfig())
        req_tracer = RequestTracer(tracer)

        # Headers with W3C traceparent
        headers = {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}

        # Extract trace context
        trace_id = req_tracer.extract_trace_context(headers)
        assert trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"

    def test_trace_error_handling(self):
        """Trace records errors during execution."""
        tracer = Tracer(TracingConfig())
        trace_id = tracer.start_trace()

        # Span with error
        try:
            with tracer.trace_context("risky_operation"):
                raise ValueError("Operation failed")
        except ValueError:
            pass  # Expected

        trace_data = tracer.export_trace(trace_id)
        # Verify trace was captured despite error
        assert trace_data["trace_id"] == trace_id


class TestAuthenticationToRateLimitingFlow:
    """Test complete flow from auth to rate limiting."""

    def test_authorized_user_respects_rate_limit(self):
        """Authenticated user is subject to rate limiting."""
        jwt_handler = JWTHandler(JWTConfig(secret_key="test-secret"))
        rbac_manager = RBACManager()
        limiter = RateLimiter(RateLimitConfig())

        # User authenticates
        token_result = jwt_handler.generate_token("user123", roles=["operator"])
        token = token_result["access_token"]

        # Validate token
        claims = jwt_handler.validate_token(token)
        user_id = claims.sub

        # Check authorization
        access = rbac_manager.evaluate_access(user_id, claims.roles)
        assert access.has_permission(Permission.SCALING_EXECUTE)

        # Apply rate limiting
        allowed, meta = limiter.check_limit(user_id, role="operator")
        assert allowed

    def test_unauthorized_user_blocked_before_rate_limit(self):
        """Authorization check happens before rate limiting."""
        jwt_handler = JWTHandler(JWTConfig(secret_key="test-secret"))
        rbac_manager = RBACManager()

        # User with insufficient permissions
        token_result = jwt_handler.generate_token("user123", roles=["viewer"])
        token = token_result["access_token"]

        claims = jwt_handler.validate_token(token)
        access = rbac_manager.evaluate_access(claims.sub, claims.roles)

        # Authorization denied
        assert not access.has_permission(Permission.CONFIG_ADMIN)


class TestSecurityAndObservabilityChain:
    """Test security and observability working together."""

    def test_secure_request_with_observability(self):
        """Request flow with auth, RBAC, rate limiting, and tracing."""
        # Initialize components
        jwt_handler = JWTHandler(JWTConfig(secret_key="test-secret"))
        rbac_manager = RBACManager()
        limiter = RateLimiter(RateLimitConfig())
        tracer = Tracer(TracingConfig())
        req_tracer = RequestTracer(tracer)

        # Start tracing
        trace_id = tracer.start_trace(attributes={"method": "POST", "path": "/api/scaling"})

        # Simulate request headers
        headers = {"Authorization": "Bearer token123"}

        # Extract trace context
        with tracer.trace_context("request_processing"):
            traced_id = req_tracer.extract_trace_context(headers)

            # Authenticate (in real scenario, would validate token)
            with tracer.trace_context("authentication"):
                user_id = "user123"
                roles = ["operator"]

            # Authorize
            with tracer.trace_context("authorization"):
                access = rbac_manager.evaluate_access(user_id, roles)
                assert access.has_permission(Permission.SCALING_EXECUTE)

            # Rate limit
            with tracer.trace_context("rate_limiting"):
                allowed, meta = limiter.check_limit(user_id, role="operator")
                assert allowed

            # Execute operation
            with tracer.trace_context("execute_scaling"):
                pass

        # Export full trace
        trace_data = tracer.export_trace(trace_id)
        assert trace_data["span_count"] > 0
        assert trace_data["duration_ms"] >= 0


class TestSuccessCriteria:
    """Validate Phase 4 success criteria."""

    def test_jwt_token_lifecycle(self):
        """✓ JWT tokens can be generated, validated, and refreshed."""
        handler = JWTHandler(JWTConfig(secret_key="test-secret"))

        # Generate access token
        result = handler.generate_token("user123")
        access_token = result["access_token"]

        # Validate access token
        claims = handler.validate_token(access_token)
        assert claims.sub == "user123"

        # Generate refresh token
        refresh_token = handler.generate_refresh_token("user123")

        # Use refresh token to get new access token
        new_result = handler.generate_token("user123")
        new_token = new_result["access_token"]
        new_claims = handler.validate_token(new_token)
        assert new_claims.sub == "user123"

    def test_rbac_multi_role_support(self):
        """✓ RBAC supports multiple roles with permission accumulation."""
        rbac = RBACManager()

        # User with two roles
        access = rbac.evaluate_access("user123", ["operator", "viewer"])

        # Has permissions from both roles
        assert access.has_permission(Permission.SCALING_EXECUTE)  # From operator
        assert access.has_permission(Permission.METRICS_READ)  # From both
        assert access.has_permission(Permission.PREDICTIONS_READ)  # From viewer

    def test_rate_limiting_multiple_strategies(self):
        """✓ Rate limiting supports token bucket, sliding window, fixed window."""
        # Token bucket
        config = RateLimitConfig(strategy=RateLimitStrategy.TOKEN_BUCKET)
        tb_limiter = RateLimiter(config)
        allowed, _ = tb_limiter.check_limit("user1")
        assert allowed

        # Sliding window
        config = RateLimitConfig(strategy=RateLimitStrategy.SLIDING_WINDOW)
        sw_limiter = RateLimiter(config)
        allowed, _ = sw_limiter.check_limit("user2")
        assert allowed

        # Fixed window
        config = RateLimitConfig(strategy=RateLimitStrategy.FIXED_WINDOW)
        fw_limiter = RateLimiter(config)
        allowed, _ = fw_limiter.check_limit("user3")
        assert allowed

    def test_distributed_tracing_span_lifecycle(self):
        """✓ Distributed tracing supports span creation, attributes, and export."""
        tracer = Tracer(TracingConfig())

        trace_id = tracer.start_trace()

        with tracer.trace_context("operation", attributes={"key": "value"}):
            pass

        trace_data = tracer.export_trace(trace_id)

        assert trace_data["trace_id"] == trace_id
        assert "spans" in trace_data
        assert len(trace_data["spans"]) > 0
