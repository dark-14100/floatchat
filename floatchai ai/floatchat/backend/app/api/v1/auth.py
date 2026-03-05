"""Feature 13 Authentication API router."""

from datetime import datetime, timedelta, timezone
import hashlib
import re
import secrets
import uuid

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.email import send_password_reset_email
from app.auth.jwt import InvalidTokenError, create_token, decode_token
from app.auth.passwords import hash_password, verify_password
from app.config import settings
from app.db.models import ChatSession, PasswordResetToken, User
from app.db.session import get_db
from app.rate_limiter import limiter

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])

# Admin role assignment is database-only for v1.

_REFRESH_COOKIE_NAME = "floatchat_refresh"
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _validate_email(email: str) -> str:
    normalized = _normalize_email(email)
    if not _EMAIL_PATTERN.match(normalized):
        raise ValueError("Invalid email format")
    return normalized


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=_REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=not settings.DEBUG,
        samesite="lax",
        path="/api/v1/auth",
        max_age=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=_REFRESH_COOKIE_NAME,
        path="/api/v1/auth",
        secure=not settings.DEBUG,
        httponly=True,
        samesite="lax",
    )


def _serialize_user(user: User) -> dict:
    return {
        "user_id": str(user.user_id),
        "name": user.name,
        "email": user.email,
        "role": user.role,
    }


def _create_access_token(user: User) -> str:
    return create_token(
        {
            "sub": str(user.user_id),
            "email": user.email,
            "role": user.role,
        },
        token_type="access",
    )


def _create_refresh_token(user: User) -> str:
    return create_token(
        {
            "sub": str(user.user_id),
        },
        token_type="refresh",
    )


def _migrate_anonymous_sessions(db: Session, browser_user_id: str | None, user_id: uuid.UUID) -> int:
    if not browser_user_id:
        return 0

    try:
        result = db.execute(
            update(ChatSession)
            .where(ChatSession.user_identifier == browser_user_id)
            .values(user_identifier=str(user_id))
        )
        db.commit()
        migrated_count = int(result.rowcount or 0)
        if migrated_count > 0:
            log.info("anonymous_sessions_migrated", migrated_sessions_count=migrated_count)
        return migrated_count
    except Exception as exc:
        db.rollback()
        log.warning("session_migration_failed", error=str(exc))
        return 0


class UserResponse(BaseModel):
    user_id: str
    name: str
    email: str
    role: str


class MeResponse(UserResponse):
    created_at: datetime


class AuthResponse(UserResponse):
    access_token: str
    migrated_sessions_count: int = 0


class RefreshResponse(BaseModel):
    access_token: str
    user: UserResponse


class MessageResponse(BaseModel):
    message: str


class SignupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8)

    @field_validator("email")
    @classmethod
    def validate_email_field(cls, value: str) -> str:
        return _validate_email(value)


class LoginRequest(BaseModel):
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=1)

    @field_validator("email")
    @classmethod
    def validate_email_field(cls, value: str) -> str:
        return _validate_email(value)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., max_length=255)

    @field_validator("email")
    @classmethod
    def validate_email_field(cls, value: str) -> str:
        return _validate_email(value)


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


@router.post("/signup", response_model=AuthResponse)
@limiter.limit("10/minute")
def signup(
    request: Request,
    payload: SignupRequest,
    response: Response,
    db: Session = Depends(get_db),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
):
    del request

    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        name=payload.name.strip(),
        role="researcher",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    migrated_sessions_count = _migrate_anonymous_sessions(db, x_user_id, user.user_id)

    access_token = _create_access_token(user)
    refresh_token = _create_refresh_token(user)
    _set_refresh_cookie(response, refresh_token)

    return AuthResponse(
        **_serialize_user(user),
        access_token=access_token,
        migrated_sessions_count=migrated_sessions_count,
    )


@router.post("/login", response_model=AuthResponse)
@limiter.limit("10/minute")
def login(
    request: Request,
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
):
    del request

    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    migrated_sessions_count = _migrate_anonymous_sessions(db, x_user_id, user.user_id)

    access_token = _create_access_token(user)
    refresh_token = _create_refresh_token(user)
    _set_refresh_cookie(response, refresh_token)

    return AuthResponse(
        **_serialize_user(user),
        access_token=access_token,
        migrated_sessions_count=migrated_sessions_count,
    )


@router.post("/logout", response_model=MessageResponse)
def logout(
    response: Response,
    current_user: User = Depends(get_current_user),
):
    del current_user
    _clear_refresh_cookie(response)
    return MessageResponse(message="Logged out successfully")


@router.get("/me", response_model=MeResponse)
def me(current_user: User = Depends(get_current_user)):
    return MeResponse(
        **_serialize_user(current_user),
        created_at=current_user.created_at,
    )


@router.post("/refresh", response_model=RefreshResponse)
def refresh(request: Request, db: Session = Depends(get_db)):
    refresh_token = request.cookies.get(_REFRESH_COOKIE_NAME)
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    try:
        payload = decode_token(refresh_token, expected_type="refresh")
        user_id_raw = payload.get("sub")
        if not user_id_raw:
            raise InvalidTokenError("Missing subject")
        user_id = uuid.UUID(user_id_raw)
    except (InvalidTokenError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user = db.scalar(select(User).where(User.user_id == user_id))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    access_token = _create_access_token(user)
    return RefreshResponse(access_token=access_token, user=UserResponse(**_serialize_user(user)))


@router.post("/forgot-password", response_model=MessageResponse)
@limiter.limit("10/minute")
def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    del request

    user = db.scalar(select(User).where(User.email == payload.email))

    if user is not None:
        try:
            raw_token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
            expires_at = datetime.now(timezone.utc) + timedelta(
                minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
            )

            reset_token = PasswordResetToken(
                user_id=user.user_id,
                token_hash=token_hash,
                expires_at=expires_at,
                used=False,
            )
            db.add(reset_token)
            db.commit()

            reset_link = f"{settings.FRONTEND_URL.rstrip('/')}/reset-password?token={raw_token}"
            send_password_reset_email(user.email, reset_link)
        except Exception as exc:
            db.rollback()
            log.warning("forgot_password_processing_failed", error=str(exc))

    return MessageResponse(
        message="If an account exists for that email, you'll receive a reset link shortly."
    )


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(
    payload: ResetPasswordRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    token_hash = hashlib.sha256(payload.token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)

    reset_token = db.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )

    expires_at = None
    if reset_token is not None:
        expires_at = reset_token.expires_at
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

    if reset_token is None or reset_token.used or expires_at is None or expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link is invalid or has expired.",
        )

    user = db.scalar(select(User).where(User.user_id == reset_token.user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link is invalid or has expired.",
        )

    user.hashed_password = hash_password(payload.new_password)
    reset_token.used = True
    db.commit()

    _clear_refresh_cookie(response)
    return MessageResponse(message="Password updated successfully")
