"""
003 - Metadata Search Engine

Feature 3: Adds pgvector extension and embedding tables for semantic search.

New tables:
    - dataset_embeddings — one embedding per dataset for semantic search
    - float_embeddings   — one embedding per float for semantic search

Indexes:
    - HNSW index on dataset_embeddings.embedding (cosine distance)
    - HNSW index on float_embeddings.embedding (cosine distance)

IMPORTANT: HNSW indexes are created via op.execute() with raw SQL because
Alembic's op.create_index does not support pgvector index types natively.

Revision ID: 003
Revises: 002
Create Date: 2026-02-26
"""

from alembic import op
import sqlalchemy as sa

# Revision identifiers
revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create pgvector extension, embedding tables, and HNSW indexes."""

    # =========================================================================
    # Step 1: Enable pgvector extension
    # =========================================================================
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # =========================================================================
    # Step 2: Create dataset_embeddings table
    # =========================================================================
    op.create_table(
        "dataset_embeddings",
        sa.Column("embedding_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("embedding_text", sa.Text(), nullable=False),
        # embedding column added below via raw SQL (vector type)
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'indexed'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("embedding_id"),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.dataset_id"],
            name="fk_dataset_embeddings_dataset_id",
        ),
        sa.UniqueConstraint("dataset_id", name="uq_dataset_embeddings_dataset_id"),
        sa.CheckConstraint(
            "status IN ('indexed', 'embedding_failed')",
            name="ck_dataset_embeddings_status",
        ),
    )

    # Add pgvector vector(1536) column
    op.execute("""
        ALTER TABLE dataset_embeddings
        ADD COLUMN embedding vector(1536) NOT NULL
    """)

    # =========================================================================
    # Step 3: Create float_embeddings table
    # =========================================================================
    op.create_table(
        "float_embeddings",
        sa.Column("embedding_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("float_id", sa.Integer(), nullable=False),
        sa.Column("embedding_text", sa.Text(), nullable=False),
        # embedding column added below via raw SQL (vector type)
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'indexed'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("embedding_id"),
        sa.ForeignKeyConstraint(
            ["float_id"],
            ["floats.float_id"],
            name="fk_float_embeddings_float_id",
        ),
        sa.UniqueConstraint("float_id", name="uq_float_embeddings_float_id"),
        sa.CheckConstraint(
            "status IN ('indexed', 'embedding_failed')",
            name="ck_float_embeddings_status",
        ),
    )

    # Add pgvector vector(1536) column
    op.execute("""
        ALTER TABLE float_embeddings
        ADD COLUMN embedding vector(1536) NOT NULL
    """)

    # =========================================================================
    # Step 4: Create HNSW indexes on embedding columns
    # These MUST use op.execute() — Alembic's op.create_index does not
    # support pgvector index types natively.
    # Parameters: m=16, ef_construction=64, cosine distance (vector_cosine_ops)
    # =========================================================================
    op.execute("""
        CREATE INDEX idx_dataset_embeddings_embedding
        ON dataset_embeddings
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)

    op.execute("""
        CREATE INDEX idx_float_embeddings_embedding
        ON float_embeddings
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)


def downgrade() -> None:
    """Drop HNSW indexes, embedding tables, and pgvector extension."""

    # =========================================================================
    # Step 1: Drop HNSW indexes
    # =========================================================================
    op.execute("DROP INDEX IF EXISTS idx_float_embeddings_embedding")
    op.execute("DROP INDEX IF EXISTS idx_dataset_embeddings_embedding")

    # =========================================================================
    # Step 2: Drop embedding tables
    # =========================================================================
    op.drop_table("float_embeddings")
    op.drop_table("dataset_embeddings")

    # =========================================================================
    # Step 3: Drop pgvector extension
    # =========================================================================
    op.execute("DROP EXTENSION IF EXISTS vector")
