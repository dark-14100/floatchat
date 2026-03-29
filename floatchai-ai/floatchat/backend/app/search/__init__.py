"""
FloatChat Metadata Search Engine

Feature 3: Semantic search and dataset discovery layer.

Modules:
    embeddings  — OpenAI embedding API calls and text builders
    indexer     — Build embedding texts from DB records, persist to DB
    search      — Semantic similarity search with hybrid scoring
    discovery   — Float discovery, fuzzy region matching, dataset summaries
    tasks       — Celery task for post-ingestion indexing
"""
