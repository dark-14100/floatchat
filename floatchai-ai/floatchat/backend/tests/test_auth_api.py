"""Tests for Feature 13 auth endpoints and auth-protected route behavior."""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt
from sqlalchemy import select

from app.auth.jwt import create_token
from app.auth.passwords import hash_password, verify_password
from app.config import settings
from app.db.models import ChatSession, PasswordResetToken, User


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_user(
    db_session,
    *,
    email: str = "user@example.com",
    password: str = "Password123!",
    name: str = "Test User",
    role: str = "researcher",
    is_active: bool = True,
) -> User:
    user = User(
        user_id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password(password),
        name=name,
        role=role,
        is_active=is_active,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _create_access_token_for_user(user: User) -> str:
    return create_token(
        {
            "sub": str(user.user_id),
            "email": user.email,
            "role": user.role,
        },
        token_type="access",
    )


def _create_refresh_token_for_user(user: User) -> str:
    return create_token(
        {
            "sub": str(user.user_id),
        },
        token_type="refresh",
    )


class TestSignup:
    def test_signup_valid_creates_user_and_returns_token(self, client, db_session):
        resp = client.post(
            "/api/v1/auth/signup",
            json={
                "name": "New User",
                "email": "NewUser@Example.com",
                "password": "Password123!",
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "New User"
        assert body["email"] == "newuser@example.com"
        assert body["role"] == "researcher"
        assert body["access_token"]
        assert body["migrated_sessions_count"] == 0
        assert "floatchat_refresh" in resp.headers.get("set-cookie", "")

        saved = db_session.scalar(select(User).where(User.email == "newuser@example.com"))
        assert saved is not None
        assert saved.hashed_password != "Password123!"

    def test_signup_duplicate_email_returns_409(self, client, db_session):
        _create_user(db_session, email="dup@example.com")

        resp = client.post(
            "/api/v1/auth/signup",
            json={
                "name": "Dup User",
                "email": "dup@example.com",
                "password": "Password123!",
            },
        )

        assert resp.status_code == 409
        assert resp.json()["detail"] == "An account with this email already exists"

    def test_signup_short_password_returns_422(self, client):
        resp = client.post(
            "/api/v1/auth/signup",
            json={
                "name": "Short Pass",
                "email": "short@example.com",
                "password": "short",
            },
        )

        assert resp.status_code == 422


class TestLogin:
    def test_login_correct_credentials_returns_token_and_cookie(self, client, db_session):
        _create_user(db_session, email="login@example.com", password="Password123!")

        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "login@example.com", "password": "Password123!"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == "login@example.com"
        assert body["access_token"]
        assert "floatchat_refresh" in resp.headers.get("set-cookie", "")

    def test_login_wrong_password_returns_401(self, client, db_session):
        _create_user(db_session, email="wrongpass@example.com", password="Password123!")

        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "wrongpass@example.com", "password": "WrongPassword!"},
        )

        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid email or password"

    def test_login_unknown_email_returns_401_same_message(self, client):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "missing@example.com", "password": "Password123!"},
        )

        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid email or password"

    def test_login_deactivated_account_returns_403(self, client, db_session):
        _create_user(
            db_session,
            email="inactive@example.com",
            password="Password123!",
            is_active=False,
        )

        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "inactive@example.com", "password": "Password123!"},
        )

        assert resp.status_code == 403
        assert resp.json()["detail"] == "Account is deactivated"


class TestMe:
    def test_me_with_valid_token_returns_profile(self, client, db_session):
        user = _create_user(db_session, email="me@example.com")
        token = _create_access_token_for_user(user)

        resp = client.get("/api/v1/auth/me", headers=_auth_header(token))

        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == str(user.user_id)
        assert body["email"] == user.email
        assert "hashed_password" not in body

    def test_me_with_expired_token_returns_401(self, client, db_session):
        user = _create_user(db_session, email="expired@example.com")
        now = datetime.now(timezone.utc)
        expired_token = jwt.encode(
            {
                "sub": str(user.user_id),
                "email": user.email,
                "role": user.role,
                "type": "access",
                "iat": int((now - timedelta(minutes=10)).timestamp()),
                "exp": int((now - timedelta(minutes=1)).timestamp()),
            },
            settings.JWT_SECRET_KEY,
            algorithm="HS256",
        )

        resp = client.get("/api/v1/auth/me", headers=_auth_header(expired_token))
        assert resp.status_code == 401

    def test_me_without_token_returns_401(self, client):
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401


class TestRefreshAndLogout:
    def test_refresh_with_valid_cookie_returns_new_access_token_and_user(self, client, db_session):
        user = _create_user(db_session, email="refresh@example.com")
        refresh_token = _create_refresh_token_for_user(user)

        resp = client.post(
            "/api/v1/auth/refresh",
            cookies={"floatchat_refresh": refresh_token},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["access_token"]
        assert body["user"]["user_id"] == str(user.user_id)
        assert body["user"]["email"] == user.email

    def test_refresh_missing_cookie_returns_401(self, client):
        resp = client.post("/api/v1/auth/refresh")
        assert resp.status_code == 401

    def test_logout_clears_refresh_cookie(self, client, db_session):
        user = _create_user(db_session, email="logout@example.com")
        access_token = _create_access_token_for_user(user)

        resp = client.post("/api/v1/auth/logout", headers=_auth_header(access_token))

        assert resp.status_code == 200
        assert resp.json()["message"] == "Logged out successfully"
        set_cookie = resp.headers.get("set-cookie", "")
        assert "floatchat_refresh=" in set_cookie


class TestForgotPassword:
    def test_forgot_password_known_email_returns_200_and_stores_token(self, client, db_session):
        user = _create_user(db_session, email="forgot-known@example.com")

        resp = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "forgot-known@example.com"},
        )

        assert resp.status_code == 200
        assert "If an account exists for that email" in resp.json()["message"]

        token_row = db_session.scalar(
            select(PasswordResetToken).where(PasswordResetToken.user_id == user.user_id)
        )
        assert token_row is not None
        assert token_row.used is False

    def test_forgot_password_unknown_email_returns_200_same_message(self, client, db_session):
        before_count = db_session.query(PasswordResetToken).count()

        resp = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "forgot-unknown@example.com"},
        )

        assert resp.status_code == 200
        assert "If an account exists for that email" in resp.json()["message"]
        after_count = db_session.query(PasswordResetToken).count()
        assert after_count == before_count


class TestResetPassword:
    def test_reset_password_valid_token_updates_password_and_marks_used(self, client, db_session):
        user = _create_user(db_session, email="reset-valid@example.com", password="OldPassword123!")

        raw_token = "valid-reset-token"
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        reset_token = PasswordResetToken(
            token_id=uuid.uuid4(),
            user_id=user.user_id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            used=False,
        )
        db_session.add(reset_token)
        db_session.commit()

        resp = client.post(
            "/api/v1/auth/reset-password",
            json={"token": raw_token, "new_password": "NewPassword123!"},
        )

        assert resp.status_code == 200
        assert resp.json()["message"] == "Password updated successfully"

        db_session.refresh(user)
        db_session.refresh(reset_token)
        assert verify_password("NewPassword123!", user.hashed_password)
        assert reset_token.used is True

    def test_reset_password_expired_token_returns_400(self, client, db_session):
        user = _create_user(db_session, email="reset-expired@example.com")

        raw_token = "expired-reset-token"
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        reset_token = PasswordResetToken(
            token_id=uuid.uuid4(),
            user_id=user.user_id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            used=False,
        )
        db_session.add(reset_token)
        db_session.commit()

        resp = client.post(
            "/api/v1/auth/reset-password",
            json={"token": raw_token, "new_password": "NewPassword123!"},
        )

        assert resp.status_code == 400

    def test_reset_password_used_token_returns_400(self, client, db_session):
        user = _create_user(db_session, email="reset-used@example.com")

        raw_token = "used-reset-token"
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        reset_token = PasswordResetToken(
            token_id=uuid.uuid4(),
            user_id=user.user_id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            used=True,
        )
        db_session.add(reset_token)
        db_session.commit()

        resp = client.post(
            "/api/v1/auth/reset-password",
            json={"token": raw_token, "new_password": "NewPassword123!"},
        )

        assert resp.status_code == 400


class TestProtectedRoutes:
    def test_protected_chat_endpoint_without_token_returns_401(self, client):
        resp = client.get("/api/v1/chat/sessions")
        assert resp.status_code == 401

    def test_protected_chat_endpoint_with_valid_token_returns_data(self, client, db_session):
        user = _create_user(db_session, email="protected@example.com")
        token = _create_access_token_for_user(user)

        resp = client.get("/api/v1/chat/sessions", headers=_auth_header(token))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestSessionMigration:
    def test_login_migrates_anonymous_sessions(self, client, db_session):
        browser_uuid = "browser-uuid-123"
        user = _create_user(
            db_session,
            email="migrate@example.com",
            password="Password123!",
        )

        session = ChatSession(
            session_id=uuid.uuid4(),
            user_identifier=browser_uuid,
            name="Old anonymous session",
            is_active=True,
            message_count=0,
        )
        db_session.add(session)
        db_session.commit()

        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "migrate@example.com", "password": "Password123!"},
            headers={"X-User-ID": browser_uuid},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["migrated_sessions_count"] == 1

        db_session.refresh(session)
        assert session.user_identifier == str(user.user_id)
