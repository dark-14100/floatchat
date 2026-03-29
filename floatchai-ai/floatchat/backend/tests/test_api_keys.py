import uuid


def test_create_list_revoke_api_key(client, auth_headers):
    create_resp = client.post(
        "/api/v1/auth/api-keys",
        headers=auth_headers,
        json={"name": "notebook"},
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["key"].startswith("fck_")
    assert "warning" in created

    list_resp = client.get("/api/v1/auth/api-keys", headers=auth_headers)
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) >= 1
    assert "key_hash" not in items[0]

    revoke_resp = client.delete(f"/api/v1/auth/api-keys/{created['key_id']}", headers=auth_headers)
    assert revoke_resp.status_code == 200

    revoke_again_resp = client.delete(f"/api/v1/auth/api-keys/{created['key_id']}", headers=auth_headers)
    assert revoke_again_resp.status_code == 409


def test_api_key_auth_on_public_endpoint(client, auth_headers):
    create_resp = client.post(
        "/api/v1/auth/api-keys",
        headers=auth_headers,
        json={"name": "script"},
    )
    assert create_resp.status_code == 201
    api_key = create_resp.json()["key"]

    resp = client.post(
        "/api/v1/query/benchmark",
        headers={"X-API-Key": api_key},
        json={"query": "show me recent datasets"},
    )
    assert resp.status_code != 401


def test_api_key_rejected_on_auth_management_endpoints(client, auth_headers):
    create_resp = client.post(
        "/api/v1/auth/api-keys",
        headers=auth_headers,
        json={"name": "restricted"},
    )
    assert create_resp.status_code == 201
    api_key = create_resp.json()["key"]

    management_resp = client.get("/api/v1/auth/api-keys", headers={"X-API-Key": api_key})
    assert management_resp.status_code == 401


def test_api_key_rejected_on_admin_endpoints(client, auth_headers):
    create_resp = client.post(
        "/api/v1/auth/api-keys",
        headers=auth_headers,
        json={"name": "admin-check"},
    )
    assert create_resp.status_code == 201
    api_key = create_resp.json()["key"]

    resp = client.get("/api/v1/admin/datasets", headers={"X-API-Key": api_key})
    assert resp.status_code in (401, 403)
