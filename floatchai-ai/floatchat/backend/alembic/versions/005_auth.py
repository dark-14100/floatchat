"""
005 - Authentication & User Management

Feature 13: Creates users and password_reset_tokens tables.

New tables:
    - users
    - password_reset_tokens

Indexes:
    - Unique index on users(email)
    - Index on password_reset_tokens(token_hash)

Revision ID: 005
Revises: 004
Create Date: 2026-03-05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# Revision identifiers
revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create users and password_reset_tokens tables."""

    # =========================================================================
    # Step 1: Create users table
    # =========================================================================
    op.create_table(
        "users",
        sa.Column("user_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "role",
            sa.String(20),
            server_default=sa.text("'researcher'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('researcher', 'admin')", name="ck_users_role"),
    )

    op.create_index(
        "ix_users_email",
        "users",
        ["email"],
        unique=True,
    )

    # =========================================================================
    # Step 2: Create password_reset_tokens table
    # =========================================================================
    op.create_table(
        "password_reset_tokens",
        sa.Column("token_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "used",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
            ondelete="CASCADE",
        ),
    )

    op.create_index(
        "ix_password_reset_tokens_token_hash",
        "password_reset_tokens",
        ["token_hash"],
    )

    # NOTE:
    # FK on chat_sessions.user_identifier deferred to v2 pending full anonymous
    # session cleanup. The column currently stores both browser UUIDs and user IDs.


def downgrade() -> None:
    """Drop password_reset_tokens first (FK dependency), then users."""
    op.drop_index("ix_password_reset_tokens_token_hash", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
