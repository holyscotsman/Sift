"""Async API clients (Plex, Radarr, Tautulli, TMDB) on a shared resilient base."""

from .base import (
    BaseClient,
    ClientAuthError,
    ClientError,
    ClientHTTPError,
    ClientUnavailableError,
    HealthStatus,
    RateLimiter,
    RetryPolicy,
)

__all__ = [
    "BaseClient",
    "ClientError",
    "ClientAuthError",
    "ClientHTTPError",
    "ClientUnavailableError",
    "HealthStatus",
    "RateLimiter",
    "RetryPolicy",
]
