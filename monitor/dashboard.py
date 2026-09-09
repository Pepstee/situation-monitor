"""Read-only HTTP presentation of the canonical dashboard snapshot.

The CLI owns snapshot queries. This module owns only HTTP/rendering/lifecycle,
replacing the archived v1/v2 web servers without a second database owner.
/data returns the full snapshot; /api/items returns articles.items;
/api/reliability returns reliability (including model run statistics).
"""
from __future__ import annotations

import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import threading
from typing import Any, Callable
from urllib.parse import urlsplit

_LOG = logging.getLogger(__name__)
_CSS = """
body{font-family:system-ui,sans-serif;margin:0;background:#f5f5f5;color:#333}
main{max-width:72rem;margin:auto;padding:2rem}
h1{font-size:1.75rem}h2{font-size:1.25rem;margin-top:2rem}
h1,h2{text-wrap:balance}p{max-width:72ch;line-height:1.5}
a{color:#0066cc;text-underline-offset:.15em}a:hover{color:#004a94}
a:focus-visible{outline:2px solid #0066cc;outline-offset:3px}
nav{display:flex;flex-wrap:wrap;gap:1rem}.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;background:#fff;text-align:left}
caption{text-align:left;padding:.6rem 0;color:#555}
th,td{padding:.7rem .8rem;border-bottom:1px solid #ddd;vertical-align:top}
th{font-weight:600;background:#eee}td:first-child{min-width:15rem}
td{overflow-wrap:anywhere}.score{font-variant-numeric:tabular-nums;white-space:nowrap}
small{display:block;color:#555;margin-top:.3rem}.empty{padding:1rem;background:#fff}
@media(max-width:40rem){main{padding:1rem}th,td{padding:.6rem}}
"""


def _text(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _link(title: Any, url: Any) -> str:
    label = _text(title or "Untitled")
    if not isinstance(url, str) or any(ord(char) < 32 for char in url) or "\\" in url:
        return label
    try:
        parsed = urlsplit(url)
        safe = parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password
    except ValueError:
        safe = False
    return f'<a href="{_text(url)}" rel="noreferrer">{label}</a>' if safe else label


def _reliability(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return snapshot.get("reliability", snapshot["sources"]["items"])


def render_dashboard(snapshot: dict[str, Any]) -> str:
    """Render escaped source data, with no script or external asset requests."""
    article_rows = []
    for item in snapshot["articles"]["items"]:
        score = "Unscored" if item.get("score") is None else _text(item["score"])
        if item.get("confidence_low") is not None and item.get("confidence_high") is not None:
            score += f'<small>Range {_text(item["confidence_low"])}–{_text(item["confidence_high"])}</small>'
        article_rows.append(
            f'<tr><td>{_link(item.get("title"), item.get("url"))}</td>'
            f'<td>{_text(item.get("source", ""))}</td><td class="score">{score}</td></tr>'
        )
    articles = (
        '<div class="table-wrap"><table><caption>Most recent articles</caption>'
        '<thead><tr><th scope="col">Article</th><th scope="col">Source</th>'
        '<th scope="col">Score / 100</th></tr></thead><tbody>'
        + "".join(article_rows) + '</tbody></table></div>'
        if article_rows else '<p class="empty">No articles in this time window. Run a source check to collect articles.</p>'
    )
    source_rows = []
    for item in _reliability(snapshot):
        latency = "Not measured" if item.get("mean_latency_ms") is None else _text(item["mean_latency_ms"])
        source_rows.append(
            f'<tr><td>{_text(item.get("source", item.get("name", "")))}</td>'
            f'<td>{_text(item.get("success_count", 0))} / {_text(item.get("run_count", 0))}</td>'
            f'<td>{latency}</td></tr>'
        )
    sources = (
        '<div class="table-wrap"><table><caption>Recorded source and scoring runs</caption>'
        '<thead><tr><th scope="col">Source</th><th scope="col">Successful / total</th>'
        '<th scope="col">Mean latency (ms)</th></tr></thead><tbody>'
        + "".join(source_rows) + '</tbody></table></div>'
        if source_rows else '<p class="empty">No source runs recorded yet.</p>'
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="refresh" content="30"><title>Situation Monitor</title>'
        f'<style>{_CSS}</style></head><body><main><h1>Situation Monitor</h1>'
        '<p>Read-only local dashboard. Refreshes every 30 seconds.</p>'
        '<nav aria-label="Dashboard data"><a href="/">Refresh now</a>'
        '<a href="/data">Full snapshot (JSON)</a></nav>'
        f'<h2>Articles</h2>{articles}<h2>Source reliability</h2>{sources}'
        '</main></body></html>'
    )


class DashboardServer:
    """Loopback-only dashboard with explicit, restart-safe owner lifecycle.

    start() is non-blocking and idempotent while running. stop() closes the
    socket, including before start. Create a new instance after stop().
    """

    def __init__(self, snapshot_fn: Callable[[], dict[str, Any]], host: str = "127.0.0.1", port: int = 8080) -> None:
        if host not in {"127.0.0.1", "localhost"}:
            raise ValueError("Dashboard host must be 127.0.0.1 or localhost; remote access has no authentication")
        self._snapshot_fn = snapshot_fn
        self._thread: threading.Thread | None = None
        self._closed = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def _send(self, status: int, body: bytes, content_type: str) -> None:
                self.send_response_only(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                # Reject alternate Host names so a public site cannot use DNS
                # rebinding to read the local unauthenticated dashboard.
                allowed = {f"127.0.0.1:{owner.port}", f"localhost:{owner.port}"}
                if self.headers.get("Host") not in allowed:
                    self._send(403, b"Local dashboard host required.\n", "text/plain; charset=utf-8")
                    return
                route = self.path.partition("?")[0]
                if route not in {"/", "/data", "/api/items", "/api/reliability"}:
                    self._send(404, b"Not found.\n", "text/plain; charset=utf-8")
                    return
                try:
                    snapshot = owner._snapshot_fn()
                    if route == "/":
                        payload = render_dashboard(snapshot).encode("utf-8")
                        content_type = "text/html; charset=utf-8"
                    else:
                        data = snapshot if route == "/data" else snapshot["articles"]["items"] if route == "/api/items" else _reliability(snapshot)
                        payload = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
                        content_type = "application/json; charset=utf-8"
                except Exception:
                    _LOG.exception("Dashboard snapshot failed")
                    self._send(503, b"Dashboard unavailable. Check the monitor's local error log and try again.\n", "text/plain; charset=utf-8")
                    return
                self._send(200, payload, content_type)

        self._http = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.port = self._http.server_port

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> DashboardServer:
        if self._closed:
            raise RuntimeError("Dashboard is closed; create a new server")
        if self._thread is None:
            self._thread = threading.Thread(target=self._http.serve_forever, kwargs={"poll_interval": 0.1}, name="situation-dashboard", daemon=True)
            self._thread.start()
        return self

    def serve_forever(self) -> None:
        self.start()
        try:
            assert self._thread is not None
            self._thread.join()
        finally:
            self.stop()

    def stop(self) -> None:
        if self._closed:
            return
        if self._thread is not None:
            self._http.shutdown()
            self._thread.join()
        self._http.server_close()
        self._closed = True
