from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import uuid

from app.db.models import Float, GDACSyncRun, IngestionJob, Profile
from app.monitoring.digest import build_digest_data


def test_build_digest_data_aggregates_previous_day(db_session):
    target_day = date(2026, 3, 26)
    start = datetime(2026, 3, 26, 0, 0, tzinfo=UTC)

    float_row = Float(
        platform_number="5900001",
        wmo_id="5900001",
        created_at=start + timedelta(hours=1),
        updated_at=start + timedelta(hours=1),
    )
    db_session.add(float_row)
    db_session.flush()

    profile_row = Profile(
        profile_id=1,
        float_id=float_row.float_id,
        platform_number="5900001",
        cycle_number=1,
        created_at=start + timedelta(hours=2),
        updated_at=start + timedelta(hours=2),
    )
    db_session.add(profile_row)

    success_job = IngestionJob(
        job_id=uuid.uuid4(),
        status="succeeded",
        profiles_ingested=120,
        source="manual_upload",
        original_filename="ok.nc",
        created_at=start + timedelta(hours=3),
    )
    failed_job = IngestionJob(
        job_id=uuid.uuid4(),
        status="failed",
        profiles_ingested=0,
        source="gdac_sync",
        original_filename=None,
        created_at=start + timedelta(hours=4),
    )
    db_session.add(success_job)
    db_session.add(failed_job)

    gdac_run = GDACSyncRun(
        run_id=uuid.uuid4(),
        started_at=start + timedelta(hours=5),
        completed_at=start + timedelta(hours=5, minutes=20),
        status="completed",
        gdac_mirror="https://example.gdac",
        lookback_days=1,
        triggered_by="scheduled",
    )
    db_session.add(gdac_run)

    db_session.commit()

    payload = build_digest_data(db_session, target_day)

    assert payload["target_date"] == "2026-03-26"
    assert payload["total_profiles_ingested"] == 120
    assert payload["new_floats_discovered"] == 1
    assert payload["failed_jobs_count"] == 1
    assert payload["failed_job_names"] == ["unknown_file"]
    assert payload["gdac_sync_status"] == "completed"
