"""
API module for endpoint routes and authentication.

Exports:
    get_current_user: FastAPI dependency for authenticated endpoints
    get_current_admin_user: FastAPI dependency for admin-only endpoints
    create_access_token: Test utility for generating JWT tokens
"""

from app.api.auth import (
    create_access_token,
    get_current_admin_user,
    get_current_user,
)

__all__ = [
    "get_current_user",
    "get_current_admin_user",
    "create_access_token",
]
