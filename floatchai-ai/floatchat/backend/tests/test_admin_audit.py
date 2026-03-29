"""Feature 10 admin audit log API tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.db.models import AdminAuditLog, User


def _create_admin_user(db_session, email: str = "audit-admin@example.com") -> User:
    user = User(
        user_id=uuid.uuid4(),
        email=email,
        hashed_password="hash",
        name="Audit Admin",
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _create_audit_log(
    db_session,
    *,
    admin_user_id,
    action: str,
    entity_type: str = "dataset",
    entity_id: str = "1",
    created_at: datetime | None = None,
):
    row = AdminAuditLog(
        admin_user_id=admin_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details={"k": "v"},
        created_at=created_at or datetime.now(UTC),
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_audit_log_requires_auth(client):
    response = client.get("/api/v1/admin/audit-log")
    assert response.status_code == 401


def test_audit_log_requires_admin_role(client, researcher_headers):
    response = client.get("/api/v1/admin/audit-log", headers=researcher_headers)
    assert response.status_code == 403


def test_list_audit_log_returns_entries_with_admin_email(client, db_session, admin_headers):
    admin = _create_admin_user(db_session)
    row = _create_audit_log(
        db_session,
        admin_user_id=admin.user_id,
        action="dataset_metadata_updated",
        entity_type="dataset",
        entity_id="42",
    )

    response = client.get("/api/v1/admin/audit-log", headers=admin_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1

    first = payload["logs"][0]
    assert first["log_id"] == str(row.log_id)
    assert first["admin_user_email"] == admin.email
    assert first["action"] == "dataset_metadata_updated"


def test_list_audit_log_filters_by_action(client, db_session, admin_headers):
    admin = _create_admin_user(db_session, email="audit-filter@example.com")
    _create_audit_log(
        db_session,
        admin_user_id=admin.user_id,
        action="dataset_metadata_updated",
        entity_id="100",
    )
    _create_audit_log(
        db_session,
        admin_user_id=admin.user_id,
        action="ingestion_job_retried",
        entity_type="ingestion_job",
        entity_id="job-1",
    )

    response = client.get(
        "/api/v1/admin/audit-log?action=ingestion_job_retried",
        headers=admin_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["logs"][0]["action"] == "ingestion_job_retried"


def test_list_audit_log_invalid_admin_user_id_returns_400(client, admin_headers):
    response = client.get(
        "/api/v1/admin/audit-log?admin_user_id=not-a-uuid",
        headers=admin_headers,
    )
    assert response.status_code == 400
