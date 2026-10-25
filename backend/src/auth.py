"""Better Auth JWT verification for the FastAPI backend.

The Next.js client authenticates users with Better Auth (GitHub/Google) and
the ``jwt()`` plugin issues short-lived EdDSA-signed JWTs
(``GET /api/auth/token``). Browsers call this backend with::

    Authorization: Bearer <jwt>

Every route except ``GET /health`` requires a valid token. Verification is
stateless: the public keys are fetched from the Better Auth JWKS endpoint
(``GET /api/auth/jwks``) and cached in memory.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

BETTER_AUTH_URL = os.getenv("BETTER_AUTH_URL", "http://localhost:3000").rstrip("/")
JWKS_URL = os.getenv(
    "BETTER_AUTH_JWKS_URL", f"{BETTER_AUTH_URL}/api/auth/jwks"
)
EXPECTED_ISSUER = os.getenv("BETTER_AUTH_ISSUER", BETTER_AUTH_URL)
EXPECTED_AUDIENCE = os.getenv("BETTER_AUTH_AUDIENCE", BETTER_AUTH_URL)
ALLOWED_ALGORITHMS = ["EdDSA"]

_bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


@lru_cache(maxsize=1)
def get_jwks_client() -> jwt.PyJWKClient:
    """Cached JWKS client (fetches and caches signing keys by ``kid``)."""
    return jwt.PyJWKClient(JWKS_URL)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """FastAPI dependency: verify the Better Auth JWT, return its claims.

    Raises 401 when the header is missing, malformed, expired, has an
    unknown ``kid``, a bad signature, or a wrong issuer/audience.
    """
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not credentials.credentials
    ):
        raise _unauthorized()

    token = credentials.credentials

    try:
        signing_key = await run_in_threadpool(
            get_jwks_client().get_signing_key_from_jwt, token
        )
    except Exception as exc:  # unknown kid, JWKS unreachable, malformed token
        logger.debug("JWKS key lookup failed: %s", exc)
        raise _unauthorized("Invalid token") from exc

    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            signing_key.key,
            algorithms=ALLOWED_ALGORITHMS,
            issuer=EXPECTED_ISSUER,
            audience=EXPECTED_AUDIENCE,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        logger.debug("JWT verification failed: %s", exc)
        raise _unauthorized("Invalid token") from exc

    return payload


__all__ = [
    "ALLOWED_ALGORITHMS",
    "BETTER_AUTH_URL",
    "EXPECTED_AUDIENCE",
    "EXPECTED_ISSUER",
    "JWKS_URL",
    "get_current_user",
    "get_jwks_client",
]
