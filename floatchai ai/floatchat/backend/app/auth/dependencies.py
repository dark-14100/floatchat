"""FastAPI auth dependencies for current user and admin user resolution."""

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.jwt import InvalidTokenError, decode_token
from app.db.models import User
from app.db.session import get_db


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


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
