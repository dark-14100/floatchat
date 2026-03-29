def test_docs_public_access(client):
    resp = client.get("/docs")
    assert resp.status_code == 200


def test_openapi_has_api_key_security_scheme(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()

    security_schemes = schema.get("components", {}).get("securitySchemes", {})
    assert "ApiKeyAuth" in security_schemes
    assert security_schemes["ApiKeyAuth"]["type"] == "apiKey"
    assert security_schemes["ApiKeyAuth"]["name"] == "X-API-Key"

    assert "BearerAuth" in security_schemes
    assert security_schemes["BearerAuth"]["type"] == "http"
