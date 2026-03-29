"""FastAPI auth dependencies for current user and admin user resolution."""

from datetime import datetime, timezone
import hashlib
import hmac
import threading
import uuid

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.jwt import InvalidTokenError, decode_token
from app.db.models import ApiKey, User
from app.db.session import SessionLocal, get_db


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
oauth2_optional_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve authenticated user from access token."""
    try:
        payload = decode_token(token, expected_type="access")
        user_id_str = payload.get("sub")
        if not user_id_str:
            raise _CREDENTIALS_EXCEPTION
        user_id = uuid.UUID(user_id_str)
    except (InvalidTokenError, ValueError):
        raise _CREDENTIALS_EXCEPTION

    user = db.scalar(select(User).where(User.user_id == user_id))
    if user is None or not user.is_active:
        raise _CREDENTIALS_EXCEPTION

    return user


def get_current_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """Resolve current user and ensure admin role."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


def _touch_api_key_last_used(key_id: uuid.UUID) -> None:
    """Fire-and-forget update for API key last_used_at timestamp."""
    db = SessionLocal()
    try:
        api_key = db.scalar(select(ApiKey).where(ApiKey.key_id == key_id))
        if api_key is None:
            return
        api_key.last_used_at = datetime.now(timezone.utc)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _resolve_user_from_api_key(
    request: Request,
    db: Session,
    x_api_key: str,
) -> User:
    key_hash = hashlib.sha256(x_api_key.encode("utf-8")).hexdigest()
    api_key = db.scalar(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
    )

    if api_key is None or not hmac.compare_digest(api_key.key_hash, key_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key",
        )

    user = db.scalar(select(User).where(User.user_id == api_key.user_id))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key",
        )

    request.state.api_key_scoped = True
    request.state.api_key_id = str(api_key.key_id)
    request.state.rate_limit_key = f"apikey:{api_key.key_id}"
    setattr(user, "api_key_scoped", True)
    setattr(user, "api_key_id", api_key.key_id)

    threading.Thread(
        target=_touch_api_key_last_used,
        args=(api_key.key_id,),
        daemon=True,
    ).start()

    return user


def get_api_key_or_user(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    token: str | None = Depends(oauth2_optional_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve user from API key first, else fallback to JWT."""
    if x_api_key:
        return _resolve_user_from_api_key(request=request, db=db, x_api_key=x_api_key)

    if not token:
        raise _CREDENTIALS_EXCEPTION

    current_user = get_current_user(token=token, db=db)
    request.state.api_key_scoped = False
    request.state.rate_limit_key = f"user:{current_user.user_id}"
    setattr(current_user, "api_key_scoped", False)
    return current_user


def get_optional_api_key_or_user(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    token: str | None = Depends(oauth2_optional_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    """Resolve user from API key or JWT, but allow anonymous requests."""
    if x_api_key:
        return _resolve_user_from_api_key(request=request, db=db, x_api_key=x_api_key)

    if not token:
        request.state.api_key_scoped = False
        request.state.rate_limit_key = None
        return None

    current_user = get_current_user(token=token, db=db)
    request.state.api_key_scoped = False
    request.state.rate_limit_key = f"user:{current_user.user_id}"
    setattr(current_user, "api_key_scoped", False)
    return current_user
