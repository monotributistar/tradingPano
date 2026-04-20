"""
tests/api/test_system_metrics.py
==================================

Integration tests for the system monitoring API endpoints.

GET /api/system/metrics
GET /api/system/uptime

Both endpoints require authentication.
``psutil`` is expected to be present in the dev environment; if it isn't
the metrics endpoint returns 503 and the tests skip gracefully.
"""

import pytest


# ── Helpers ────────────────────────────────────────────────────────────────────

def _psutil_available(client, auth_headers) -> bool:
    """Return True when psutil is installed and the endpoint returns 200."""
    resp = client.get("/api/system/metrics", headers=auth_headers)
    return resp.status_code == 200


# ── /api/system/metrics ────────────────────────────────────────────────────────

@pytest.mark.api
class TestSystemMetrics:
    def test_metrics_no_auth_blocked(self, client):
        assert client.get("/api/system/metrics").status_code == 403

    def test_metrics_wrong_key_blocked(self, client):
        assert client.get("/api/system/metrics", headers={"X-API-Key": "bad"}).status_code == 403

    def test_metrics_returns_200_or_503(self, client, auth_headers):
        """The endpoint is valid; 503 only when psutil is missing."""
        resp = client.get("/api/system/metrics", headers=auth_headers)
        assert resp.status_code in (200, 503)

    def test_metrics_503_message_when_psutil_missing(self, client, auth_headers):
        """When psutil is absent the body explains why."""
        resp = client.get("/api/system/metrics", headers=auth_headers)
        if resp.status_code == 503:
            assert "psutil" in resp.json().get("detail", "").lower()

    def test_metrics_has_cpu_field(self, client, auth_headers):
        resp = client.get("/api/system/metrics", headers=auth_headers)
        if resp.status_code != 200:
            pytest.skip("psutil not available")
        assert "cpu_pct" in resp.json()

    def test_metrics_has_ram_fields(self, client, auth_headers):
        resp = client.get("/api/system/metrics", headers=auth_headers)
        if resp.status_code != 200:
            pytest.skip("psutil not available")
        data = resp.json()
        assert "ram_pct"     in data
        assert "ram_used_mb" in data
        assert "ram_total_mb" in data

    def test_metrics_has_disk_object(self, client, auth_headers):
        resp = client.get("/api/system/metrics", headers=auth_headers)
        if resp.status_code != 200:
            pytest.skip("psutil not available")
        disk = resp.json().get("disk")
        assert isinstance(disk, dict)
        assert "used_gb"  in disk
        assert "total_gb" in disk
        assert "pct"      in disk

    def test_metrics_has_process_fields(self, client, auth_headers):
        resp = client.get("/api/system/metrics", headers=auth_headers)
        if resp.status_code != 200:
            pytest.skip("psutil not available")
        data = resp.json()
        assert "process_rss_mb"   in data
        assert "process_cpu_pct"  in data
        assert "process_uptime_s" in data
        assert "process_threads"  in data

    def test_metrics_cpu_pct_is_numeric(self, client, auth_headers):
        resp = client.get("/api/system/metrics", headers=auth_headers)
        if resp.status_code != 200:
            pytest.skip("psutil not available")
        cpu = resp.json()["cpu_pct"]
        assert isinstance(cpu, (int, float))
        assert 0.0 <= cpu <= 100.0

    def test_metrics_ram_pct_is_numeric(self, client, auth_headers):
        resp = client.get("/api/system/metrics", headers=auth_headers)
        if resp.status_code != 200:
            pytest.skip("psutil not available")
        pct = resp.json()["ram_pct"]
        assert isinstance(pct, (int, float))
        assert 0.0 <= pct <= 100.0

    def test_metrics_process_uptime_is_positive(self, client, auth_headers):
        resp = client.get("/api/system/metrics", headers=auth_headers)
        if resp.status_code != 200:
            pytest.skip("psutil not available")
        uptime = resp.json()["process_uptime_s"]
        assert uptime >= 0.0

    def test_metrics_process_threads_is_positive_int(self, client, auth_headers):
        resp = client.get("/api/system/metrics", headers=auth_headers)
        if resp.status_code != 200:
            pytest.skip("psutil not available")
        threads = resp.json()["process_threads"]
        assert isinstance(threads, int)
        assert threads >= 1

    def test_metrics_disk_pct_in_range(self, client, auth_headers):
        resp = client.get("/api/system/metrics", headers=auth_headers)
        if resp.status_code != 200:
            pytest.skip("psutil not available")
        pct = resp.json()["disk"]["pct"]
        assert 0.0 <= pct <= 100.0


# ── /api/system/uptime ─────────────────────────────────────────────────────────

@pytest.mark.api
class TestSystemUptime:
    def test_uptime_no_auth_blocked(self, client):
        assert client.get("/api/system/uptime").status_code == 403

    def test_uptime_returns_200(self, client, auth_headers):
        resp = client.get("/api/system/uptime", headers=auth_headers)
        assert resp.status_code == 200

    def test_uptime_has_process_uptime(self, client, auth_headers):
        data = client.get("/api/system/uptime", headers=auth_headers).json()
        assert "process_uptime_s" in data

    def test_uptime_process_uptime_is_non_negative(self, client, auth_headers):
        uptime = client.get("/api/system/uptime", headers=auth_headers).json()["process_uptime_s"]
        assert isinstance(uptime, (int, float))
        assert uptime >= 0.0

    def test_uptime_os_uptime_field_present(self, client, auth_headers):
        """os_uptime_s is optional but the key should be present (null or float)."""
        data = client.get("/api/system/uptime", headers=auth_headers).json()
        assert "os_uptime_s" in data

    def test_uptime_os_uptime_is_positive_when_set(self, client, auth_headers):
        os_up = client.get("/api/system/uptime", headers=auth_headers).json().get("os_uptime_s")
        if os_up is not None:
            assert os_up > 0.0
