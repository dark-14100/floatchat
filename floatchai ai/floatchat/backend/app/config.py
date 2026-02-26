"""
FloatChat Application Configuration

Uses pydantic-settings to load configuration from environment variables and .env file.
All settings are validated on application startup.
"""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    
    All settings can be overridden via environment variables or a .env file.
    Required settings will raise validation errors if not provided.
    """
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # =========================================================================
    # Database
    # =========================================================================
    DATABASE_URL: str = "postgresql+psycopg2://floatchat:floatchat@localhost:5433/floatchat"
    DATABASE_URL_DIRECT: str = "postgresql+psycopg2://floatchat:floatchat@localhost:5432/floatchat"
    READONLY_DATABASE_URL: str = "postgresql+psycopg2://floatchat_readonly:floatchat_readonly@localhost:5433/floatchat"
    READONLY_DB_PASSWORD: str = "floatchat_readonly"
    
    # =========================================================================
    # Connection Pool (SQLAlchemy)
    # =========================================================================
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE: int = 3600
    
    # =========================================================================
    # Redis / Celery
    # =========================================================================
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"
    
    # =========================================================================
    # Redis Cache (Feature 2)
    # =========================================================================
    REDIS_CACHE_TTL_SECONDS: int = 300  # 5-minute TTL for query result cache
    REDIS_CACHE_MAX_ROWS: int = 10000  # Do not cache results larger than this
    
    # =========================================================================
    # S3 / MinIO Object Storage
    # =========================================================================
    S3_ENDPOINT_URL: Optional[str] = None  # Set for MinIO, leave None for AWS S3
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET_NAME: str = "floatchat-raw-uploads"
    S3_REGION: str = "us-east-1"
    
    # =========================================================================
    # LLM (OpenAI)
    # =========================================================================
    OPENAI_API_KEY: Optional[str] = None  # Optional - uses fallback if not set
    LLM_MODEL: str = "gpt-4o"
    LLM_TIMEOUT_SECONDS: int = 30
    
    # =========================================================================
    # Ingestion Settings
    # =========================================================================
    MAX_UPLOAD_SIZE_BYTES: int = 2_147_483_648  # 2GB
    DB_INSERT_BATCH_SIZE: int = 1000
    
    # =========================================================================
    # Authentication (JWT)
    # =========================================================================
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    
    # =========================================================================
    # Monitoring
    # =========================================================================
    SENTRY_DSN: Optional[str] = None  # Optional - disabled if not set
    
    # =========================================================================
    # Metadata Search Engine (Feature 3)
    # =========================================================================
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = 1536
    EMBEDDING_BATCH_SIZE: int = 100
    SEARCH_SIMILARITY_THRESHOLD: float = 0.3
    SEARCH_DEFAULT_LIMIT: int = 10
    SEARCH_MAX_LIMIT: int = 50
    RECENCY_BOOST_DAYS: int = 90
    RECENCY_BOOST_VALUE: float = 0.05
    REGION_MATCH_BOOST_VALUE: float = 0.10
    FUZZY_MATCH_THRESHOLD: float = 0.4
    
    # =========================================================================
    # Application
    # =========================================================================
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.
    
    Uses lru_cache to ensure settings are only loaded once.
    """
    return Settings()


# Export singleton instance for convenience
settings = get_settings()
