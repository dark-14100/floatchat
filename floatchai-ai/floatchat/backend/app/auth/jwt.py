"""JWT utility functions for Feature 13 authentication."""

from datetime import datetime, timedelta, timezone
from typing import Literal

from jose import JWTError, ExpiredSignatureError, jwt

from app.config import settings


TokenType = Literal["access", "refresh"]


class InvalidTokenError(Exception):
    """Raised when a JWT token is invalid, expired, or has unexpected type."""


def _get_expiry(token_type: TokenType) -> datetime:
    now = datetime.now(timezone.utc)
    if token_type == "access":
        return now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    return now + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)


def create_token(payload: dict, token_type: TokenType) -> str:
    """Create a signed JWT with required type/iat/exp claims."""
    now = datetime.now(timezone.utc)
    to_encode = dict(payload)
    to_encode.update(
        {
            "type": token_type,
            "iat": int(now.timestamp()),
            "exp": int(_get_expiry(token_type).timestamp()),
        }
    )
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm="HS256")


def decode_token(token: str, expected_type: TokenType) -> dict:
    """Decode JWT and validate expected token type."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=["HS256"])
    except ExpiredSignatureError as exc:
        raise InvalidTokenError("Token has expired") from exc
    except JWTError as exc:
        raise InvalidTokenError("Token is invalid") from exc

    token_type = payload.get("type")
    if token_type != expected_type:
        raise InvalidTokenError("Token type mismatch")

    return payload
