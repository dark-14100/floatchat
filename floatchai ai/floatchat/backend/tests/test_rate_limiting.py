def test_query_benchmark_rate_limit_enforced(client, auth_headers):
    from app.config import settings

    original_limit = settings.JWT_RATE_LIMIT_PER_MINUTE
    settings.JWT_RATE_LIMIT_PER_MINUTE = 2
    try:
        r1 = client.post(
            "/api/v1/query/benchmark",
            headers=auth_headers,
            json={"query": "query one"},
        )
        r2 = client.post(
            "/api/v1/query/benchmark",
            headers=auth_headers,
            json={"query": "query two"},
        )
        r3 = client.post(
            "/api/v1/query/benchmark",
            headers=auth_headers,
            json={"query": "query three"},
        )

        assert r1.status_code in (200, 400)
        assert r2.status_code in (200, 400)
        assert r3.status_code == 429
        body = r3.json()
        assert body.get("detail") == "Rate limit exceeded"
        assert "retry_after" in body
        assert "Retry-After" in r3.headers
    finally:
        settings.JWT_RATE_LIMIT_PER_MINUTE = original_limit
