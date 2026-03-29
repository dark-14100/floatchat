#!/usr/bin/env python3
"""CLI entrypoint for Feature 15 baseline computation."""

from __future__ import annotations

import structlog

from app.anomaly.baselines import compute_all_baselines
from app.db.session import SessionLocal

logger = structlog.get_logger("compute_baselines")


def main() -> None:
    """Compute anomaly baselines and persist them."""
    db = SessionLocal()
    try:
        logger.info("compute_baselines_started")
        summary = compute_all_baselines(db)
        db.commit()
        logger.info("compute_baselines_succeeded", **summary)
    except Exception as exc:
        db.rollback()
        logger.error("compute_baselines_failed", error=str(exc))
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
