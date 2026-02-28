"""
004 - Chat Interface

Feature 5: Creates chat_sessions and chat_messages tables for the
conversational chat interface.

New tables:
    - chat_sessions  — one row per conversation session
    - chat_messages  — one row per message in a conversation

Indexes:
    - Composite index on chat_messages(session_id, created_at)
    - Index on chat_sessions(user_identifier)

Revision ID: 004
Revises: 003
Create Date: 2026-02-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# Revision identifiers
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create chat_sessions and chat_messages tables."""

    # =========================================================================
    # Step 1: Create chat_sessions table
    # =========================================================================
    op.create_table(
        "chat_sessions",
        sa.Column("session_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_identifier", sa.String(255), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_active_at",
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
        sa.Column(
            "message_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )

    # Index on user_identifier for filtering sessions by user
    op.create_index(
        "ix_chat_sessions_user_identifier",
        "chat_sessions",
        ["user_identifier"],
    )

    # =========================================================================
    # Step 2: Create chat_messages table
    # =========================================================================
    op.create_table(
        "chat_messages",
        sa.Column("message_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("nl_query", sa.Text(), nullable=True),
        sa.Column("generated_sql", sa.Text(), nullable=True),
        sa.Column("result_metadata", JSONB, nullable=True),
        sa.Column("follow_up_suggestions", JSONB, nullable=True),
        sa.Column("error", JSONB, nullable=True),
        sa.Column("status", sa.String(30), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.session_id"],
            ondelete="CASCADE",
        ),
    )

    # Composite index for efficient message history retrieval
    op.create_index(
        "ix_chat_messages_session_created",
        "chat_messages",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    """Drop chat_messages first (FK dependency), then chat_sessions."""
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
