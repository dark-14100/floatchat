"""
006 - RAG Pipeline

Feature 14: Adds query_history table for tenant-isolated query-learning retrieval.

New table:
    - query_history

Indexes:
    - HNSW index on query_history.embedding (cosine distance)
    - B-tree index on query_history.user_id
    - B-tree index on query_history.created_at

Revision ID: 006
Revises: 005
Create Date: 2026-03-07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# Revision identifiers
revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create query_history table and indexes."""

    # =========================================================================
    # Step 1: Create query_history table
    # =========================================================================
    op.create_table(
        "query_history",
        sa.Column(
            "query_id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("nl_query", sa.Text(), nullable=False),
        sa.Column("generated_sql", sa.Text(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
            ondelete="CASCADE",
            name="fk_query_history_user_id",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.session_id"],
            ondelete="SET NULL",
            name="fk_query_history_session_id",
        ),
    )

    # Add pgvector vector(1536) column via raw SQL
    op.execute(
        """
        ALTER TABLE query_history
        ADD COLUMN embedding vector(1536) NOT NULL
        """
    )

    # =========================================================================
    # Step 2: Create indexes
    # =========================================================================
    op.create_index(
        "ix_query_history_user_id",
        "query_history",
        ["user_id"],
    )
    op.create_index(
        "ix_query_history_created_at",
        "query_history",
        ["created_at"],
    )

    # HNSW index must be created via raw SQL for pgvector
    op.execute(
        """
        CREATE INDEX idx_query_history_embedding
        ON query_history
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )

    # Explicit readonly access grant for the new table.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'floatchat_readonly'
            ) THEN
                GRANT SELECT ON TABLE query_history TO floatchat_readonly;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    """Drop query_history table and indexes."""

    op.execute("DROP INDEX IF EXISTS idx_query_history_embedding")
    op.drop_index("ix_query_history_created_at", table_name="query_history")
    op.drop_index("ix_query_history_user_id", table_name="query_history")
    op.drop_table("query_history")
