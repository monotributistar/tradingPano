"""
tests/api/test_health.py
=========================

Smoke tests for public endpoints (no auth required).
These verify the app wires up correctly and basic routing works.
"""

import pytest


@pytest.mark.api
def test_health_returns_200(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200


@pytest.mark.api
def test_health_returns_ok_status(client):
    data = client.get("/api/health").json()
    assert data["status"] == "ok"


@pytest.mark.api
def test_health_includes_version(client):
    data = client.get("/api/health").json()
    assert "version" in data
    assert data["version"].startswith("3.")


@pytest.mark.api
def test_protected_endpoint_without_key_returns_403(client):
    resp = client.get("/api/bot/status")
    assert resp.status_code == 403


@pytest.mark.api
def test_protected_endpoint_with_wrong_key_returns_403(client):
    resp = client.get("/api/bot/status", headers={"X-API-Key": "wrong"})
    assert resp.status_code == 403


@pytest.mark.api
def test_protected_endpoint_with_correct_key_returns_200(client, auth_headers):
    resp = client.get("/api/bot/status", headers=auth_headers)
    assert resp.status_code == 200


@pytest.mark.api
def test_openapi_schema_accessible(client, auth_headers):
    """Swagger JSON schema should be reachable (used by /docs)."""
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    assert "paths" in schema
    assert "components" in schema
