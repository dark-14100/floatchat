"""
FloatChat Celery Worker Entry Point

Start the worker:
    celery -A celery_worker.celery worker --loglevel=info -Q ingestion,default

Start the beat scheduler:
    celery -A celery_worker.celery beat --loglevel=info

Start both (dev only):
    celery -A celery_worker.celery worker --beat --loglevel=info -Q ingestion,default
"""

# Import the Celery app instance
from app.celery_app import celery  # noqa: F401

# Import tasks so Celery can discover them
import app.ingestion.tasks  # noqa: F401
