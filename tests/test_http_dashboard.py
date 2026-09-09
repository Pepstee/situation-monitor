"""Actual HTTP checks for the restored dashboard boundary."""
import http.client
import json
import socket
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from monitor.dashboard import DashboardServer


def snapshot():
    return {
        "schema": "situation-monitor.dashboard.v1",
        "articles": {"items": [
            {"title": '<img src=x onerror="alert(1)">', "url": "javascript:alert(1)", "source": "<script>bad</script>", "score": '<svg onload="alert(1)">', "confidence_low": "<script>x</script>", "confidence_high": 90},
            {"title": "Public article", "url": 'https://example.org/?a=1&b="two"', "source": "hackernews", "score": 70},
        ]},
        "sources": {"items": [{"name": "hackernews"}]},
        "reliability": [{"source": "model:local", "run_count": 2, "success_count": 1, "mean_latency_ms": 24.5}],
    }


def test_dashboard_serves_snapshot_and_legacy_endpoints():
    state = snapshot()
    server = DashboardServer(lambda: state, port=0).start()
    try:
        assert server.start() is server
        for path, expected in [("/data", state), ("/api/items", state["articles"]["items"]), ("/api/reliability", state["reliability"])]:
            with urlopen(server.url + path, timeout=3) as response:
                assert response.status == 200
                assert json.load(response) == expected
                assert response.headers["Cache-Control"] == "no-store"
                assert response.headers["X-Content-Type-Options"] == "nosniff"
        # Each request fetches new data; no stale process-wide snapshot cache.
        state["articles"]["items"] = []
        with urlopen(server.url + "/api/items", timeout=3) as response:
            assert json.load(response) == []
    finally:
        server.stop()


def test_dashboard_escapes_all_source_fields_and_unsafe_links():
    server = DashboardServer(snapshot, port=0).start()
    try:
        with urlopen(server.url, timeout=3) as response:
            page = response.read().decode()
            assert "default-src 'none'" in response.headers["Content-Security-Policy"]
            assert "script-src 'unsafe-inline'" not in response.headers["Content-Security-Policy"]
        assert '<meta http-equiv="refresh" content="30">' in page
        assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in page
        assert "<script>" not in page and "<svg" not in page and "<img" not in page
        assert "javascript:" not in page
        assert 'href="https://example.org/?a=1&amp;b=&quot;two&quot;"' in page
        assert "model:local" in page and "24.5" in page
        assert 'scope="col"' in page and 'overflow-x:auto' in page
    finally:
        server.stop()


def test_snapshot_failure_is_visible_and_not_an_empty_success():
    def failing():
        raise RuntimeError("sensitive-local-path")
    server = DashboardServer(failing, port=0).start()
    try:
        for path in ["/", "/data", "/api/items", "/api/reliability"]:
            with pytest.raises(HTTPError) as error:
                urlopen(server.url + path, timeout=3)
            assert error.value.code == 503
            body = error.value.read()
            assert b"Dashboard unavailable" in body
            assert b"sensitive-local-path" not in body
        with pytest.raises(HTTPError) as error:
            urlopen(server.url + "/unknown", timeout=3)
        assert error.value.code == 404
    finally:
        server.stop()


def test_dashboard_local_only_and_closes_socket():
    with pytest.raises(ValueError, match="authentication"):
        DashboardServer(snapshot, host="0.0.0.0", port=0)
    server = DashboardServer(snapshot, host="localhost", port=0).start()
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=3)
    try:
        connection.request("GET", "/data", headers={"Host": "attacker.example"})
        response = connection.getresponse()
        assert response.status == 403
        response.read()
    finally:
        connection.close()
        server.stop()
    server.stop()
    assert server._thread is not None and not server._thread.is_alive()
    with socket.socket() as probe:
        probe.settimeout(1)
        assert probe.connect_ex(("127.0.0.1", server.port)) != 0
    with pytest.raises(RuntimeError, match="closed"):
        server.start()
    # stop before start must not deadlock in HTTPServer.shutdown().
    unused = DashboardServer(snapshot, port=0)
    unused.stop()
