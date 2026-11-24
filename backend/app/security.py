"""Security helpers: bcrypt password hashing, JWT issue/verify, and the
get_current_user / require_role FastAPI dependencies.

Secrets come from the environment (JWT_SECRET) — never hard-coded and never
logged.
"""

import os
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import PyJWTError
import jwt

from app.database import get_users_collection

_ALGORITHM = "HS256"
_TOKEN_TTL = timedelta(hours=24)

_bearer = HTTPBearer()


def _get_secret() -> str:
    secret = os.environ.get("JWT_SECRET", "").strip()
    if not secret:
        raise RuntimeError("JWT_SECRET is not configured.")
    return secret


def hash_password(password: str) -> str:
    """Return a bcrypt hash of *password* as a str."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Return True iff *password* matches *password_hash*."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_token(email: str, role: str) -> str:
    """Return a JWT for *email*/*role* expiring in 24 hours."""
    now = datetime.now(timezone.utc)
    payload = {"sub": email, "role": role, "iat": now, "exp": now + _TOKEN_TTL}
    return jwt.encode(payload, _get_secret(), algorithm=_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, _get_secret(), algorithms=[_ALGORITHM])


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """Resolve the bearer token to the matching user document, or 401."""
    token = credentials.credentials
    try:
        payload = decode_token(token)
    except PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    email = payload.get("sub")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
        )
    user = get_users_collection().find_one({"email": email})
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
        )
    return user


def require_role(role: str):
    """Return a dependency that allows only users with the given role."""

    def _checker(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") != role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized for this resource.",
            )
        return user

    return _checker



def user_from_token(token: str) -> dict:
    """Decode a token supplied as a query parameter and return the user.

    Used by the video-file endpoint, which the HTML5 <video> tag fetches
    without custom headers, so the token arrives as ?token=...
    """
    try:
        payload = decode_token(token)
    except PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )
    email = payload.get("sub")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
        )
    user = get_users_collection().find_one({"email": email})
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
        )
    return user
