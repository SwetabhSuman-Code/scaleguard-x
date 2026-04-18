"""
JWT (JSON Web Token) authentication handler.

Provides secure token generation, validation, and claims extraction for
API authentication. Supports symmetric (HS256) and asymmetric (RS256) algorithms.

Security Features:
  - Token expiration validation
  - Signature verification
  - Claims validation
  - Token refresh support
  - Algorithm enforcement (prevent "none" algorithm attack)
"""

import jwt
import os
import logging
from typing import Dict, Optional, Any
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)


class TokenAlgorithm(str, Enum):
    """Supported JWT algorithms."""
    HS256 = "HS256"  # HMAC with SHA-256 (symmetric)
    HS512 = "HS512"  # HMAC with SHA-512 (symmetric)
    RS256 = "RS256"  # RSA with SHA-256 (asymmetric)
    RS512 = "RS512"  # RSA with SHA-512 (asymmetric)


@dataclass
class TokenClaims:
    """Standard JWT claims with custom extensions."""
    sub: str                              # Subject (user ID)
    iss: str = "scaleguard-api"          # Issuer
    aud: str = "scaleguard-services"     # Audience
    exp: Optional[int] = None            # Expiration time (epoch)
    iat: Optional[int] = None            # Issued at (epoch)
    
    # Custom claims
    username: Optional[str] = None
    email: Optional[str] = None
    roles: list = None                   # List of role names
    scopes: list = None                  # List of permission scopes
    
    def __post_init__(self):
        if self.roles is None:
            self.roles = []
        if self.scopes is None:
            self.scopes = []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JWT encoding."""
        claims = asdict(self)
        # Remove None values to keep JWT compact
        return {k: v for k, v in claims.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TokenClaims":
        """Create from decoded JWT payload."""
        return cls(
            sub=data.get("sub", ""),
            iss=data.get("iss", "scaleguard-api"),
            aud=data.get("aud", "scaleguard-services"),
            exp=data.get("exp"),
            iat=data.get("iat"),
            username=data.get("username"),
            email=data.get("email"),
            roles=data.get("roles", []),
            scopes=data.get("scopes", []),
        )


@dataclass
class JWTConfig:
    """JWT handler configuration."""
    secret_key: str                    # Signing key (symmetric) or private key (asymmetric)
    algorithm: str = TokenAlgorithm.HS256.value
    expiration_minutes: int = 60       # Token lifetime
    refresh_expiration_days: int = 7   # Refresh token lifetime
    issuer: str = "scaleguard-api"
    audience: str = "scaleguard-services"
    # Optional public key for RS256 verification (asymmetric)
    public_key: Optional[str] = None


class JWTHandler:
    """
    JWT token generation and validation.
    
    Supports multiple algorithms and token refresh patterns. Implements
    security best practices including signature verification and claims
    validation.
    
    Attributes:
        config: JWTConfig with algorithm and key settings
        algorithm: Currently configured algorithm (HS256, RS256, etc.)
    """

    def __init__(self, config: JWTConfig):
        """
        Initialize JWT handler.
        
        Args:
            config: JWTConfig instance with signing parameters
        
        Raises:
            ValueError: If secret_key is empty or algorithm not supported
        """
        if not config.secret_key:
            raise ValueError("secret_key is required")
        
        if config.algorithm not in [e.value for e in TokenAlgorithm]:
            raise ValueError(f"Unsupported algorithm: {config.algorithm}")

        self.config = config
        self.algorithm = config.algorithm
        logger.info(
            f"JWT Handler initialized: algorithm={self.algorithm}, "
            f"expiration={self.config.expiration_minutes}min"
        )

    def generate_token(
        self,
        subject: str,
        username: Optional[str] = None,
        email: Optional[str] = None,
        roles: Optional[list] = None,
        scopes: Optional[list] = None,
        expiration_minutes: Optional[int] = None,
    ) -> Dict[str, str]:
        """
        Generate a new JWT token.
        
        Args:
            subject: User ID (required, goes in 'sub' claim)
            username: Optional username
            email: Optional email address
            roles: Optional list of role names
            scopes: Optional list of permission scopes
            expiration_minutes: Override default expiration
        
        Returns:
            Dict with keys:
                - access_token: JWT token string
                - token_type: "Bearer"
                - expires_in: Expiration time in seconds
        """
        now = datetime.now(timezone.utc)
        exp_minutes = expiration_minutes or self.config.expiration_minutes
        expiration = now + timedelta(minutes=exp_minutes)

        claims = TokenClaims(
            sub=subject,
            iss=self.config.issuer,
            aud=self.config.audience,
            exp=int(expiration.timestamp()),
            iat=int(now.timestamp()),
            username=username,
            email=email,
            roles=roles or [],
            scopes=scopes or [],
        )

        token = jwt.encode(
            claims.to_dict(),
            self.config.secret_key,
            algorithm=self.algorithm
        )

        logger.debug(
            f"JWT generated for subject={subject}, "
            f"expires_in={exp_minutes}min"
        )

        return {
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": exp_minutes * 60,
        }

    def generate_refresh_token(
        self,
        subject: str,
        username: Optional[str] = None,
    ) -> str:
        """
        Generate a long-lived refresh token.
        
        Args:
            subject: User ID
            username: Optional username
        
        Returns:
            Refresh token (JWT string)
        """
        now = datetime.now(timezone.utc)
        expiration = now + timedelta(days=self.config.refresh_expiration_days)

        claims = TokenClaims(
            sub=subject,
            username=username,
            iss=self.config.issuer,
            aud=self.config.audience,
            exp=int(expiration.timestamp()),
            iat=int(now.timestamp()),
        )

        token = jwt.encode(
            claims.to_dict(),
            self.config.secret_key,
            algorithm=self.algorithm
        )

        logger.debug(
            f"Refresh token generated for subject={subject}, "
            f"expires_in={self.config.refresh_expiration_days}d"
        )

        return token

    def validate_token(self, token: str) -> TokenClaims:
        """
        Validate and decode JWT token.
        
        Args:
            token: JWT token string (without "Bearer " prefix)
        
        Returns:
            TokenClaims with validated claims
        
        Raises:
            jwt.InvalidTokenError: If token is invalid, expired, or has bad signature
            jwt.DecodeError: If token cannot be decoded
            jwt.ExpiredSignatureError: If token is expired
        """
        try:
            # Determine key for verification
            key = self.config.public_key if self.config.public_key else self.config.secret_key
            
            payload = jwt.decode(
                token,
                key,
                algorithms=[self.algorithm],  # Only allow configured algorithm
                issuer=self.config.issuer,
                audience=self.config.audience,
            )

            claims = TokenClaims.from_dict(payload)
            logger.debug(f"Token validated for subject={claims.sub}")
            return claims

        except jwt.ExpiredSignatureError:
            logger.warning("Token validation failed: expired signature")
            raise

        except jwt.InvalidTokenError as e:
            logger.warning(f"Token validation failed: {e}")
            raise

    def refresh_access_token(self, refresh_token: str) -> Dict[str, str]:
        """
        Generate new access token from refresh token.
        
        Args:
            refresh_token: Valid refresh token
        
        Returns:
            Dict with new access_token and metadata
        
        Raises:
            jwt.InvalidTokenError: If refresh token is invalid
        """
        claims = self.validate_token(refresh_token)
        
        new_token = self.generate_token(
            subject=claims.sub,
            username=claims.username,
            email=claims.email,
            roles=claims.roles,
            scopes=claims.scopes,
        )
        
        logger.info(f"Access token refreshed for subject={claims.sub}")
        return new_token

    def extract_token_from_header(self, auth_header: str) -> str:
        """
        Extract JWT token from "Bearer <token>" header.
        
        Args:
            auth_header: Authorization header value
        
        Returns:
            Token string (without "Bearer " prefix)
        
        Raises:
            ValueError: If header format is invalid
        """
        parts = auth_header.split()
        
        if len(parts) != 2:
            raise ValueError("Invalid authorization header format")
        
        scheme, token = parts
        
        if scheme.lower() != "bearer":
            raise ValueError(f"Invalid scheme: {scheme}, expected Bearer")
        
        return token

    def get_token_info(self, token: str) -> Dict[str, Any]:
        """
        Get token information without strict validation (for debugging).
        
        Args:
            token: JWT token string
        
        Returns:
            Dict with token metadata (no signature verification)
        """
        try:
            payload = jwt.decode(
                token,
                options={"verify_signature": False}
            )
            
            claims = TokenClaims.from_dict(payload)
            
            # Calculate expiration info
            now = datetime.utcnow()
            if claims.exp:
                exp_dt = datetime.fromtimestamp(claims.exp)
                remaining = (exp_dt - now).total_seconds()
                
                return {
                    "subject": claims.sub,
                    "username": claims.username,
                    "email": claims.email,
                    "roles": claims.roles,
                    "scopes": claims.scopes,
                    "issued_at": datetime.fromtimestamp(claims.iat).isoformat() if claims.iat else None,
                    "expires_at": exp_dt.isoformat(),
                    "remaining_seconds": max(0, int(remaining)),
                    "is_expired": remaining < 0,
                }
            
            return {
                "subject": claims.sub,
                "username": claims.username,
                "email": claims.email,
                "roles": claims.roles,
                "scopes": claims.scopes,
            }
        
        except Exception as e:
            logger.warning(f"Token info extraction failed: {e}")
            return {"error": str(e)}
