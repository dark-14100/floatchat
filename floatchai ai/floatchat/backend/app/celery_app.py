"""
FloatChat Celery Application Configuration

Configures Celery for async task processing with Redis as broker.
Used for background data ingestion jobs.

Usage:
    # Start worker
    celery -A app.celery_app.celery worker --loglevel=info
    
    # Start beat (for scheduled tasks)
    celery -A app.celery_app.celery beat --loglevel=info
"""

from celery import Celery

from app.config import settings

# Create Celery app
celery = Celery(
    "floatchat",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.ingestion.tasks"],  # Auto-discover tasks module
)

# Celery configuration
celery.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    
    # Timezone
    timezone="UTC",
    enable_utc=True,
    
    # Task execution
    task_acks_late=True,  # Acknowledge after task completes (for reliability)
    task_reject_on_worker_lost=True,  # Requeue tasks if worker crashes
    task_track_started=True,  # Track when task begins execution
    
    # Result backend settings
    result_expires=86400,  # Results expire after 24 hours
    result_extended=True,  # Store additional task metadata
    
    # Worker settings
    worker_prefetch_multiplier=1,  # Conservative prefetch for long-running tasks
    worker_concurrency=4,  # Number of concurrent workers
    
    # Task routing
    task_routes={
        "app.ingestion.tasks.ingest_file_task": {"queue": "ingestion"},
        "app.ingestion.tasks.ingest_zip_task": {"queue": "ingestion"},
        "app.ingestion.tasks.retry_stale_jobs": {"queue": "default"},
    },
    
    # Task default queue
    task_default_queue="default",
    
    # Task time limits (in seconds)
    task_soft_time_limit=600,  # 10 minutes soft limit
    task_time_limit=900,  # 15 minutes hard limit
    
    # Retry settings
    task_default_retry_delay=60,  # 1 minute between retries
    task_max_retries=3,  # Max 3 retry attempts
    
    # Beat schedule (periodic tasks)
    beat_schedule={
        # Retry failed jobs every 15 minutes
        "retry-failed-jobs": {
            "task": "app.ingestion.tasks.retry_stale_jobs",
            "schedule": 900.0,  # 15 minutes
        },
    },
)


# Optional: Configure Celery logging with structlog
def configure_celery_logging():
    """Configure Celery to use structlog for consistent logging."""
    import logging
    
    import structlog
    
    # Silence noisy loggers
    logging.getLogger("celery").setLevel(logging.WARNING)
    
    # Add structlog processors
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


# Apply logging config when module loads
configure_celery_logging()
