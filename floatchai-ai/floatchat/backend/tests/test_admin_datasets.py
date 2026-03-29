"""Feature 10 admin dataset API tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.db.models import Dataset


@pytest.fixture(autouse=True)
def _sqlite_geo_functions(db_session):
    raw = db_session.connection().connection
    raw.create_function("AsBinary", 1, lambda x: x)
    raw.create_function("ST_AsGeoJSON", 1, lambda x: x)


def _create_dataset(
    db_session,
    *,
    name: str,
    source_filename: str,
    is_public: bool = True,
    deleted_at: datetime | None = None,
) -> Dataset:
    ds = Dataset(
        name=name,
        source_filename=source_filename,
        is_active=True,
        is_public=is_public,
        tags=["argo"],
        profile_count=10,
        float_count=2,
        deleted_at=deleted_at,
        dataset_version=1,
    )
    db_session.add(ds)
    db_session.commit()
    return ds


def test_admin_datasets_requires_auth(client):
    response = client.get("/api/v1/admin/datasets")
    assert response.status_code == 401


def test_admin_datasets_requires_admin_role(client, researcher_headers):
    response = client.get("/api/v1/admin/datasets", headers=researcher_headers)
    assert response.status_code == 403


def test_list_admin_datasets_hides_soft_deleted_by_default(client, db_session, admin_headers):
    _create_dataset(db_session, name="Active Dataset", source_filename="active.nc")
    _create_dataset(
        db_session,
        name="Deleted Dataset",
        source_filename="deleted.nc",
        deleted_at=datetime.now(UTC),
    )

    response = client.get("/api/v1/admin/datasets", headers=admin_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["datasets"][0]["name"] == "Active Dataset"


def test_list_admin_datasets_include_deleted_returns_all(client, db_session, admin_headers):
    _create_dataset(db_session, name="Active Dataset", source_filename="active.nc")
    _create_dataset(
        db_session,
        name="Deleted Dataset",
        source_filename="deleted.nc",
        deleted_at=datetime.now(UTC),
    )

    response = client.get(
        "/api/v1/admin/datasets?include_deleted=true",
        headers=admin_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2


def test_patch_admin_dataset_metadata_updates_name_and_visibility(client, db_session, admin_headers):
    dataset = _create_dataset(
        db_session,
        name="Old Name",
        source_filename="meta.nc",
        is_public=True,
    )

    response = client.patch(
        f"/api/v1/admin/datasets/{dataset.dataset_id}/metadata",
        json={"name": "New Name", "is_public": False, "tags": ["updated"]},
        headers=admin_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "New Name"
    assert body["is_public"] is False


def test_regenerate_summary_queues_task(client, db_session, admin_headers, monkeypatch):
    dataset = _create_dataset(db_session, name="Summary DS", source_filename="summary.nc")

    from app.api.v1 import admin as admin_api

    delay_mock = MagicMock(return_value=SimpleNamespace(id="task-regenerate-1"))
    monkeypatch.setattr(admin_api.regenerate_summary_task, "delay", delay_mock)

    response = client.post(
        f"/api/v1/admin/datasets/{dataset.dataset_id}/regenerate-summary",
        headers=admin_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["task_id"] == "task-regenerate-1"
    delay_mock.assert_called_once_with(dataset_id=dataset.dataset_id)


def test_soft_delete_and_restore_dataset(client, db_session, admin_headers):
    dataset = _create_dataset(db_session, name="Lifecycle DS", source_filename="lifecycle.nc")

    soft_delete = client.post(
        f"/api/v1/admin/datasets/{dataset.dataset_id}/soft-delete",
        headers=admin_headers,
    )
    assert soft_delete.status_code == 200
    deleted_payload = soft_delete.json()
    assert deleted_payload["deleted_at"] is not None
    assert deleted_payload["deleted_by"] is not None

    restore = client.post(
        f"/api/v1/admin/datasets/{dataset.dataset_id}/restore",
        headers=admin_headers,
    )
    assert restore.status_code == 200
    restored_payload = restore.json()
    assert restored_payload["deleted_at"] is None
    assert restored_payload["deleted_by"] is None


def test_hard_delete_queues_task_with_name_confirmation(client, db_session, admin_headers, monkeypatch):
    dataset = _create_dataset(db_session, name="Hard Delete DS", source_filename="hard-delete.nc")

    from app.api.v1 import admin as admin_api

    delay_mock = MagicMock(return_value=SimpleNamespace(id="task-hard-delete-1"))
    monkeypatch.setattr(admin_api.hard_delete_dataset_task, "delay", delay_mock)

    response = client.post(
        f"/api/v1/admin/datasets/{dataset.dataset_id}/hard-delete",
        json={"confirm": True, "confirm_dataset_name": "hard delete ds"},
        headers=admin_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["task_id"] == "task-hard-delete-1"

    called_kwargs = delay_mock.call_args.kwargs
    assert called_kwargs["dataset_id"] == dataset.dataset_id
    assert called_kwargs["expected_dataset_name"] == "Hard Delete DS"


# ---------------------------------------------------------------------------
# Soft-delete enforcement regression tests (Phase 5 verification)
# ---------------------------------------------------------------------------

def test_search_summaries_exclude_soft_deleted_datasets(client, db_session):
    active = _create_dataset(db_session, name="Visible", source_filename="visible.nc")
    _create_dataset(
        db_session,
        name="Hidden",
        source_filename="hidden.nc",
        deleted_at=datetime.now(UTC),
    )

    response = client.get("/api/v1/search/datasets/summaries")

    assert response.status_code == 200
    payload = response.json()
    ids = [row["dataset_id"] for row in payload["results"]]
    assert active.dataset_id in ids
    assert len(ids) == 1


def test_search_single_summary_returns_404_for_soft_deleted_dataset(client, db_session):
    soft_deleted = _create_dataset(
        db_session,
        name="Hidden",
        source_filename="hidden-single.nc",
        deleted_at=datetime.now(UTC),
    )

    response = client.get(f"/api/v1/search/datasets/{soft_deleted.dataset_id}/summary")

    assert response.status_code == 404
