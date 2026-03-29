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

import time

from celery import Celery
from celery.schedules import crontab
from celery.signals import task_postrun, task_prerun

from app.config import settings
from app.monitoring.metrics import observe_celery_task_duration

# Create Celery app
celery = Celery(
    "floatchat",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.ingestion.tasks",
        "app.search.tasks",
        "app.export.tasks",
        "app.anomaly.tasks",
        "app.admin.tasks",
        "app.gdac.tasks",
        "app.monitoring.digest",
    ],  # Auto-discover tasks modules
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
        "app.search.tasks.index_dataset_task": {"queue": "default"},
        "app.export.tasks.generate_export_task": {"queue": "default"},
        "app.anomaly.tasks.run_anomaly_scan": {"queue": "default"},
        "app.admin.tasks.hard_delete_dataset_task": {"queue": "default"},
        "app.admin.tasks.regenerate_summary_task": {"queue": "default"},
        "app.gdac.tasks.run_gdac_sync_task": {"queue": "default"},
        "app.monitoring.digest.send_ingestion_digest_task": {"queue": "default"},
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
        # Nightly GDAC sync run (Feature GDAC)
        "run-gdac-sync-nightly": {
            "task": "app.gdac.tasks.run_gdac_sync_task",
            "schedule": crontab(hour=1, minute=0),
        },
        # Nightly anomaly detection scan (Feature 15)
        "run-anomaly-scan-nightly": {
            "task": "app.anomaly.tasks.run_anomaly_scan",
            "schedule": crontab(hour=2, minute=0),
        },
        # Daily ingestion digest for previous UTC day (Feature 12)
        "send-ingestion-digest-daily": {
            "task": "app.monitoring.digest.send_ingestion_digest_task",
            "schedule": crontab(hour=7, minute=0),
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


_task_started_at: dict[str, float] = {}


@task_prerun.connect
def _record_task_start(task_id=None, task=None, **_kwargs):
    if task_id is None:
        return
    _task_started_at[task_id] = time.perf_counter()


@task_postrun.connect
def _record_task_duration(task_id=None, task=None, **_kwargs):
    if task_id is None:
        return
    started = _task_started_at.pop(task_id, None)
    if started is None:
        return
    task_name = getattr(task, "name", "unknown") if task is not None else "unknown"
    observe_celery_task_duration(max(time.perf_counter() - started, 0.0), task_name)
