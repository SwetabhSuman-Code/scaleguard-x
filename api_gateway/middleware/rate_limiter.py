"""
Rate limiting middleware for API requests.

Implements multiple rate limiting strategies:
  - Token Bucket: Smooth rate limiting with burst capacity
  - Sliding Window: Per-user/IP rate limiting with time windows
  - Fixed Window: Simple per-second/minute rate limits

Supports role-based rate limits (admins get higher limits than guests).
"""

import logging
import time
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from collections import defaultdict

logger = logging.getLogger(__name__)


class RateLimitStrategy(str, Enum):
    """Rate limiting algorithm choice."""

    TOKEN_BUCKET = "token_bucket"  # Best for smooth limits
    SLIDING_WINDOW = "sliding_window"  # Per-user tracking
    FIXED_WINDOW = "fixed_window"  # Simple per-timeframe


@dataclass
class RateLimitConfig:
    """Rate limiting configuration."""

    strategy: str = RateLimitStrategy.TOKEN_BUCKET.value

    # Global limits (requests per second)
    global_rps: float = 1000.0

    # Per-user limits (requests per minute)
    user_rps: Dict[str, float] = None  # role -> rps mapping

    # Token bucket parameters
    bucket_capacity: float = 100.0  # Max burst
    refill_rate: float = 10.0  # Tokens per second

    # Sliding window parameters
    window_size_seconds: int = 60  # 1-minute windows

    # Cleanup
    cleanup_interval_seconds: int = 300  # Remove stale entries every 5 min

    def __post_init__(self):
        if self.user_rps is None:
            # Default: different limits by role
            self.user_rps = {
                "admin": 10000.0,  # High limit
                "operator": 5000.0,
                "viewer": 1000.0,
                "service": 5000.0,
                "guest": 3000.0,  # Increased for load testing
            }


class TokenBucket:
    """Token bucket rate limiter (allows bursts)."""

    def __init__(self, capacity: float, refill_rate: float):
        """
        Initialize token bucket.

        Args:
            capacity: Max tokens in bucket
            refill_rate: Tokens added per second
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill = time.time()

    def allow_request(self, tokens: int = 1) -> bool:
        """
        Check if request can be allowed.

        Args:
            tokens: Tokens required (default 1)

        Returns:
            True if request allowed, False if rate limited
        """
        now = time.time()
        elapsed = now - self.last_refill

        # Refill tokens
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

        # Check if we have enough tokens
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True

        return False

    def get_reset_after(self) -> float:
        """Get seconds until next token available."""
        if self.tokens >= 1:
            return 0.0

        tokens_needed = 1 - self.tokens
        return tokens_needed / self.refill_rate


class SlidingWindowCounter:
    """Sliding window rate limiter (precise per-user)."""

    def __init__(self, window_size: int):
        """
        Initialize sliding window.

        Args:
            window_size: Window size in seconds
        """
        self.window_size = window_size
        self.requests = []

    def allow_request(self, limit: int) -> bool:
        """
        Check if request allowed within limit.

        Args:
            limit: Max requests per window

        Returns:
            True if allowed
        """
        now = time.time()
        cutoff = now - self.window_size

        # Remove old requests outside window
        self.requests = [t for t in self.requests if t > cutoff]

        if len(self.requests) < limit:
            self.requests.append(now)
            return True

        return False

    def get_reset_after(self) -> float:
        """Get seconds until oldest request leaves window."""
        if not self.requests:
            return 0.0

        oldest = self.requests[0]
        reset_time = oldest + self.window_size
        return max(0.0, reset_time - time.time())


class FixedWindowCounter:
    """Fixed window rate limiter (simple, synchronized)."""

    def __init__(self, window_seconds: int = 60):
        """
        Initialize fixed window.

        Args:
            window_seconds: Window size in seconds
        """
        self.window_seconds = window_seconds
        self.window_start = int(time.time() / window_seconds) * window_seconds
        self.count = 0

    def allow_request(self, limit: int) -> bool:
        """
        Check if request allowed within limit.

        Args:
            limit: Max requests per window

        Returns:
            True if allowed
        """
        now = time.time()
        current_window = int(now / self.window_seconds) * self.window_seconds

        # New window started
        if current_window > self.window_start:
            self.window_start = current_window
            self.count = 0

        if self.count < limit:
            self.count += 1
            return True

        return False

    def get_reset_after(self) -> float:
        """Get seconds until window resets."""
        next_window = self.window_start + self.window_seconds
        return max(0.0, next_window - time.time())


class RateLimiter:
    """
    Rate limiting for API requests.

    Tracks per-user/IP usage and enforces limits. Supports multiple
    strategies and role-based limits.

    Attributes:
        config: RateLimitConfig with limits and strategy
        strategy: Currently configured strategy
    """

    def __init__(self, config: Optional[RateLimitConfig] = None):
        """
        Initialize rate limiter.

        Args:
            config: RateLimitConfig (uses defaults if None)
        """
        self.config = config or RateLimitConfig()
        self.strategy = self.config.strategy

        # Per-identity trackers
        self.buckets: Dict[str, TokenBucket] = {}
        self.windows: Dict[str, SlidingWindowCounter] = {}
        self.fixed_windows: Dict[str, FixedWindowCounter] = {}

        # Cleanup tracking
        self.last_cleanup = time.time()

        logger.info(
            f"RateLimiter initialized: strategy={self.strategy}, "
            f"global_rps={self.config.global_rps}"
        )

    def check_limit(
        self,
        identifier: str,
        role: str = "guest",
        tokens: int = 1,
    ) -> Tuple[bool, Dict[str, any]]:
        """
        Check if request is within rate limits.

        Args:
            identifier: User ID, IP address, or API key
            role: User role (for role-based limits)
            tokens: Tokens required (default 1)

        Returns:
            Tuple of (allowed: bool, metadata: dict)
            metadata keys:
                - limit: Request limit
                - remaining: Requests remaining
                - reset_after: Seconds until reset
        """
        # Periodic cleanup
        self._cleanup_stale_entries()

        # Get role-based limit
        rps_limit = self.config.user_rps.get(role, 10.0)

        if self.strategy == RateLimitStrategy.TOKEN_BUCKET.value:
            allowed, metadata = self._check_token_bucket(identifier, rps_limit, tokens)
        elif self.strategy == RateLimitStrategy.SLIDING_WINDOW.value:
            allowed, metadata = self._check_sliding_window(identifier, rps_limit)
        elif self.strategy == RateLimitStrategy.FIXED_WINDOW.value:
            allowed, metadata = self._check_fixed_window(identifier, rps_limit)
        else:
            logger.error(f"Unknown rate limit strategy: {self.strategy}")
            allowed, metadata = True, {"error": "Unknown strategy"}

        log_level = logging.DEBUG if allowed else logging.WARNING
        logger.log(
            log_level,
            f"Rate limit check: id={identifier}, role={role}, "
            f"allowed={allowed}, remaining={metadata.get('remaining')}",
        )

        return allowed, metadata

    def _check_token_bucket(self, identifier: str, limit: float, tokens: int) -> Tuple[bool, Dict]:
        """Check using token bucket strategy."""
        if identifier not in self.buckets:
            # Create new bucket with limit capacity and limit RPS
            self.buckets[identifier] = TokenBucket(
                capacity=self.config.bucket_capacity, refill_rate=limit
            )

        bucket = self.buckets[identifier]
        allowed = bucket.allow_request(tokens)

        return allowed, {
            "limit": limit,
            "remaining": int(bucket.tokens),
            "reset_after": bucket.get_reset_after(),
        }

    def _check_sliding_window(self, identifier: str, limit: float) -> Tuple[bool, Dict]:
        """Check using sliding window strategy."""
        if identifier not in self.windows:
            self.windows[identifier] = SlidingWindowCounter(
                window_size=self.config.window_size_seconds
            )

        window = self.windows[identifier]
        limit_int = int(limit * self.config.window_size_seconds)
        allowed = window.allow_request(limit_int)

        remaining = max(0, limit_int - len(window.requests))

        return allowed, {
            "limit": limit_int,
            "remaining": remaining,
            "reset_after": window.get_reset_after(),
        }

    def _check_fixed_window(self, identifier: str, limit: float) -> Tuple[bool, Dict]:
        """Check using fixed window strategy."""
        if identifier not in self.fixed_windows:
            self.fixed_windows[identifier] = FixedWindowCounter(
                window_seconds=self.config.window_size_seconds
            )

        window = self.fixed_windows[identifier]
        limit_int = int(limit * self.config.window_size_seconds)
        allowed = window.allow_request(limit_int)

        remaining = max(0, limit_int - window.count)

        return allowed, {
            "limit": limit_int,
            "remaining": remaining,
            "reset_after": window.get_reset_after(),
        }

    def _cleanup_stale_entries(self) -> None:
        """Remove stale rate limit entries."""
        now = time.time()

        if now - self.last_cleanup < self.config.cleanup_interval_seconds:
            return

        # For token buckets: remove inactive ones
        stale_keys = {
            k: v for k, v in self.buckets.items() if now - v.last_refill > 3600  # 1 hour inactive
        }
        for key in stale_keys:
            del self.buckets[key]

        # For windows: remove empty ones
        if self.windows:
            removed = 0
            for k in list(self.windows.keys()):
                if len(self.windows[k].requests) == 0:
                    del self.windows[k]
                    removed += 1

        self.last_cleanup = now

        if stale_keys:
            logger.debug(f"Cleaned up {len(stale_keys)} stale rate limit entries")

    def reset_identifier(self, identifier: str) -> None:
        """Reset rate limit for an identifier (for testing/admin)."""
        self.buckets.pop(identifier, None)
        self.windows.pop(identifier, None)
        self.fixed_windows.pop(identifier, None)
        logger.info(f"Rate limit reset for: {identifier}")

    def get_stats(self) -> Dict[str, any]:
        """Get rate limiter statistics."""
        return {
            "strategy": self.strategy,
            "tracked_identifiers": {
                "buckets": len(self.buckets),
                "windows": len(self.windows),
                "fixed_windows": len(self.fixed_windows),
            },
            "config": {
                "global_rps": self.config.global_rps,
                "user_roles": list(self.config.user_rps.keys()),
            },
        }
