"""
Unit tests for JWT authentication and RBAC.

Tests cover:
1. JWT token generation and validation
2. Token expiration handling
3. Claims extraction and custom fields
4. RBAC permission checking
5. Multi-role permission accumulation
6. Role hierarchy
"""

import pytest
import time
import jwt as pyjwt
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from api_gateway.auth.jwt_handler import (
    JWTHandler, JWTConfig, TokenClaims, TokenAlgorithm
)
from api_gateway.auth.rbac import (
    RBACManager, Role, Permission, AccessControl
)


class TestTokenClaims:
    """Test JWT claims data structure."""

    def test_claims_initialization(self):
        """TokenClaims initializes with required fields."""
        claims = TokenClaims(sub="user123", username="john")
        assert claims.sub == "user123"
        assert claims.username == "john"
        assert claims.roles == []
        assert claims.scopes == []

    def test_claims_to_dict(self):
        """Claims convert to dictionary for JWT encoding."""
        claims = TokenClaims(
            sub="user123",
            username="john",
            roles=["operator"],
            scopes=["metrics:read"]
        )
        d = claims.to_dict()
        assert d["sub"] == "user123"
        assert d["username"] == "john"
        assert "roles" in d

    def test_claims_from_dict(self):
        """Claims reconstructed from JWT payload."""
        data = {
            "sub": "user123",
            "username": "john",
            "roles": ["operator"],
        }
        claims = TokenClaims.from_dict(data)
        assert claims.sub == "user123"
        assert claims.roles == ["operator"]

    def test_none_values_excluded(self):
        """None values excluded from JWT to keep compact."""
        claims = TokenClaims(sub="user123", email=None)
        d = claims.to_dict()
        assert "email" not in d
        assert "sub" in d


class TestJWTHandlerInitialization:
    """Test JWT handler creation."""

    def test_initialization_with_defaults(self):
        """Handler initializes with sensible defaults."""
        config = JWTConfig(secret_key="test-secret")
        handler = JWTHandler(config)
        assert handler.algorithm == TokenAlgorithm.HS256.value
        assert handler.config.expiration_minutes == 60

    def test_initialization_with_custom_config(self):
        """Handler accepts custom configuration."""
        config = JWTConfig(
            secret_key="test-secret",
            algorithm=TokenAlgorithm.HS512.value,
            expiration_minutes=120,
        )
        handler = JWTHandler(config)
        assert handler.algorithm == TokenAlgorithm.HS512.value

    def test_initialization_rejects_empty_secret(self):
        """Handler rejects empty secret key."""
        with pytest.raises(ValueError):
            JWTHandler(JWTConfig(secret_key=""))

    def test_initialization_rejects_invalid_algorithm(self):
        """Handler rejects unsupported algorithm."""
        with pytest.raises(ValueError):
            JWTHandler(JWTConfig(
                secret_key="test-secret",
                algorithm="INVALID"
            ))


class TestJWTGeneration:
    """Test JWT token generation."""

    def test_generate_basic_token(self):
        """Generates valid JWT token."""
        handler = JWTHandler(JWTConfig(secret_key="test-secret"))
        result = handler.generate_token("user123")
        
        assert "access_token" in result
        assert result["token_type"] == "Bearer"
        assert "expires_in" in result

    def test_generate_token_with_claims(self):
        """Token includes username, email, roles, scopes."""
        handler = JWTHandler(JWTConfig(secret_key="test-secret"))
        result = handler.generate_token(
            "user123",
            username="john",
            email="john@example.com",
            roles=["operator"],
            scopes=["metrics:read"]
        )
        
        token = result["access_token"]
        # Decode without verification
        payload = pyjwt.decode(token, options={"verify_signature": False})
        
        assert payload["sub"] == "user123"
        assert payload["username"] == "john"
        assert payload["email"] == "john@example.com"
        assert "operator" in payload["roles"]

    def test_token_expiration_time(self):
        """Token includes correct expiration."""
        handler = JWTHandler(
            JWTConfig(secret_key="test-secret", expiration_minutes=120)
        )
        result = handler.generate_token("user123")
        
        # Should be ~120 minutes in seconds
        assert 7190 < result["expires_in"] < 7210  # 120 * 60 ± tolerance

    def test_token_with_custom_expiration(self):
        """Token respects custom expiration override."""
        handler = JWTHandler(JWTConfig(secret_key="test-secret"))
        result = handler.generate_token("user123", expiration_minutes=30)
        
        # Should be ~30 minutes in seconds
        assert 1790 < result["expires_in"] < 1810


class TestJWTValidation:
    """Test JWT token validation."""

    def test_validate_valid_token(self):
        """Valid token passes validation."""
        handler = JWTHandler(JWTConfig(secret_key="test-secret"))
        result = handler.generate_token("user123", username="john")
        token = result["access_token"]
        
        claims = handler.validate_token(token)
        assert claims.sub == "user123"
        assert claims.username == "john"

    def test_validate_token_with_roles(self):
        """Token validation extracts roles."""
        handler = JWTHandler(JWTConfig(secret_key="test-secret"))
        result = handler.generate_token(
            "user123",
            roles=["operator", "viewer"]
        )
        token = result["access_token"]
        
        claims = handler.validate_token(token)
        assert "operator" in claims.roles
        assert "viewer" in claims.roles

    def test_validate_expired_token(self):
        """Expired token raises ExpiredSignatureError."""
        config = JWTConfig(secret_key="test-secret", expiration_minutes=0)
        handler = JWTHandler(config)
        result = handler.generate_token("user123")
        
        time.sleep(0.1)  # Ensure expiration
        token = result["access_token"]
        
        with pytest.raises(pyjwt.ExpiredSignatureError):
            handler.validate_token(token)

    def test_validate_invalid_signature(self):
        """Token with invalid signature raises error."""
        handler1 = JWTHandler(JWTConfig(secret_key="secret1"))
        handler2 = JWTHandler(JWTConfig(secret_key="secret2"))
        
        result = handler1.generate_token("user123")
        token = result["access_token"]
        
        with pytest.raises(pyjwt.InvalidTokenError):
            handler2.validate_token(token)

    def test_validate_tampered_token(self):
        """Tampered token raises error."""
        handler = JWTHandler(JWTConfig(secret_key="test-secret"))
        result = handler.generate_token("user123")
        token = result["access_token"]
        
        # Tamper with token
        tampered = token[:-10] + "tampered00"
        
        with pytest.raises(pyjwt.InvalidTokenError):
            handler.validate_token(tampered)


class TestRefreshTokens:
    """Test refresh token functionality."""

    def test_generate_refresh_token(self):
        """Generate long-lived refresh token."""
        handler = JWTHandler(
            JWTConfig(secret_key="test-secret", refresh_expiration_days=7)
        )
        refresh_token = handler.generate_refresh_token("user123")
        
        assert isinstance(refresh_token, str)
        assert len(refresh_token) > 50  # JWT tokens are long strings

    def test_refresh_token_has_long_expiration(self):
        """Refresh token has longer expiration than access token."""
        handler = JWTHandler(
            JWTConfig(secret_key="test-secret", refresh_expiration_days=7)
        )
        refresh_token = handler.generate_refresh_token("user123")
        claims = handler.validate_token(refresh_token)
        
        # Should have expiration time in future
        now = datetime.now(timezone.utc)
        exp_dt = datetime.fromtimestamp(claims.exp, tz=timezone.utc)
        assert exp_dt > now

    def test_refresh_access_token(self):
        """Generate new access token from refresh token."""
        handler = JWTHandler(JWTConfig(secret_key="test-secret"))
        refresh_token = handler.generate_refresh_token("user123", username="john")
        
        new_access = handler.refresh_access_token(refresh_token)
        
        assert "access_token" in new_access
        assert new_access["token_type"] == "Bearer"


class TestAuthorizationHeader:
    """Test Authorization header parsing."""

    def test_extract_bearer_token(self):
        """Extract token from 'Bearer <token>' header."""
        handler = JWTHandler(JWTConfig(secret_key="test-secret"))
        result = handler.generate_token("user123")
        token = result["access_token"]
        
        header = f"Bearer {token}"
        extracted = handler.extract_token_from_header(header)
        
        assert extracted == token

    def test_rejects_malformed_header(self):
        """Rejects improperly formatted header."""
        handler = JWTHandler(JWTConfig(secret_key="test-secret"))
        
        with pytest.raises(ValueError):
            handler.extract_token_from_header("JustAToken")

    def test_rejects_wrong_scheme(self):
        """Rejects non-Bearer schemes."""
        handler = JWTHandler(JWTConfig(secret_key="test-secret"))
        
        with pytest.raises(ValueError):
            handler.extract_token_from_header("Basic dXNlcjp0b2tlbg==")


class TestRBACInitialization:
    """Test RBAC manager setup."""

    def test_manager_initializes_with_default_roles(self):
        """Manager creates default roles on init."""
        rbac = RBACManager()
        
        assert rbac.get_role("admin") is not None
        assert rbac.get_role("operator") is not None
        assert rbac.get_role("viewer") is not None
        assert rbac.get_role("service") is not None
        assert rbac.get_role("guest") is not None

    def test_admin_has_all_permissions(self):
        """Admin role has all permissions."""
        rbac = RBACManager()
        admin = rbac.get_role("admin")
        
        for perm in Permission:
            assert admin.has_permission(perm)

    def test_viewer_has_read_only(self):
        """Viewer role has only read permissions."""
        rbac = RBACManager()
        viewer = rbac.get_role("viewer")
        
        assert viewer.has_permission(Permission.METRICS_READ)
        assert viewer.has_permission(Permission.SCALING_READ)
        assert not viewer.has_permission(Permission.SCALING_WRITE)


class TestRBACPermissions:
    """Test permission checking."""

    def test_operator_can_scale(self):
        """Operator role can execute scaling."""
        rbac = RBACManager()
        
        has_access = rbac.has_access(
            "user123",
            ["operator"],
            Permission.SCALING_EXECUTE
        )
        assert has_access

    def test_viewer_cannot_scale(self):
        """Viewer role cannot execute scaling."""
        rbac = RBACManager()
        
        has_access = rbac.has_access(
            "user123",
            ["viewer"],
            Permission.SCALING_EXECUTE
        )
        assert not has_access

    def test_multi_role_accumulation(self):
        """Permissions accumulate from multiple roles."""
        rbac = RBACManager()
        
        # Create roles with different permissions
        viewer_perms = [Permission.METRICS_READ]
        operator_perms = [Permission.SCALING_READ, Permission.SCALING_EXECUTE]
        
        rbac.add_custom_role("custom_viewer", "Custom", viewer_perms)
        rbac.add_custom_role("custom_operator", "Custom", operator_perms)
        
        # User with both roles
        perms = rbac.get_user_permissions(["custom_viewer", "custom_operator"])
        
        # Should have permissions from both
        assert Permission.METRICS_READ in perms
        assert Permission.SCALING_EXECUTE in perms

    def test_guest_has_limited_access(self):
        """Guest role has minimal permissions."""
        rbac = RBACManager()
        guest = rbac.get_role("guest")
        
        assert guest.has_permission(Permission.METRICS_READ)
        assert guest.has_permission(Permission.SERVICE_HEALTH)
        assert not guest.has_permission(Permission.SCALING_WRITE)
        assert not guest.has_permission(Permission.CONFIG_ADMIN)


class TestRBACCustomRoles:
    """Test custom role creation."""

    def test_add_custom_role(self):
        """Create and register custom role."""
        rbac = RBACManager()
        perms = [Permission.METRICS_READ, Permission.LOGS_READ]
        
        role = rbac.add_custom_role("auditor", "Audit logs", perms)
        
        assert role.name == "auditor"
        assert len(role.permissions) == 2

    def test_register_role(self):
        """Register custom role directly."""
        rbac = RBACManager()
        role = Role("custom", "Custom role")
        role.add_permission(Permission.METRICS_READ)
        
        rbac.register_role(role)
        
        assert rbac.get_role("custom") == role

    def test_unregister_role(self):
        """Remove a role."""
        rbac = RBACManager()
        rbac.unregister_role("guest")
        
        assert rbac.get_role("guest") is None


class TestAccessControl:
    """Test AccessControl evaluation."""

    def test_access_control_initialization(self):
        """AccessControl tracks user and roles."""
        access = AccessControl("user123", ["viewer"])
        
        assert access.user_id == "user123"
        assert "viewer" in access.roles

    def test_permission_grants(self):
        """Granted permissions return true."""
        access = AccessControl("user123", ["viewer"])
        access.add_permissions({Permission.METRICS_READ})
        
        assert access.has_permission(Permission.METRICS_READ)

    def test_missing_permission_denied(self):
        """Missing permission returns false."""
        access = AccessControl("user123", ["viewer"])
        access.add_permissions({Permission.METRICS_READ})
        
        assert not access.has_permission(Permission.SCALING_WRITE)

    def test_any_permission_check(self):
        """Check for any matching permission."""
        access = AccessControl("user123", ["viewer"])
        access.add_permissions({Permission.METRICS_READ, Permission.LOGS_READ})
        
        required = [Permission.SCALING_WRITE, Permission.METRICS_READ]
        assert access.has_any_permission(required)

    def test_all_permissions_check(self):
        """Check for all matching permissions."""
        access = AccessControl("user123", ["operator"])
        access.add_permissions({Permission.METRICS_READ, Permission.SCALING_WRITE})
        
        required = [Permission.METRICS_READ, Permission.SCALING_WRITE]
        assert access.has_all_permissions(required)


class TestRBACListingAndIntrospection:
    """Test RBAC introspection methods."""

    def test_list_roles(self):
        """List all registered roles."""
        rbac = RBACManager()
        roles = rbac.list_roles()
        
        assert len(roles) >= 5  # At least default roles
        assert any(r.name == "admin" for r in roles)

    def test_list_permissions(self):
        """List all available permissions."""
        rbac = RBACManager()
        perms = rbac.list_permissions()
        
        assert Permission.METRICS_READ in perms
        assert Permission.SCALING_EXECUTE in perms

    def test_role_graph(self):
        """Get role definitions in graph format."""
        rbac = RBACManager()
        graph = rbac.get_role_graph()
        
        assert "admin" in graph
        assert "description" in graph["admin"]
        assert "permissions" in graph["admin"]
        assert "permission_count" in graph["admin"]
