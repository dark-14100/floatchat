"""Password hashing utilities for Feature 13 authentication."""

from passlib.context import CryptContext


_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash plain-text password using bcrypt via passlib."""
    return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plain-text password against stored hash."""
    return _pwd_context.verify(plain_password, hashed_password)
