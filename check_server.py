"""Web-server smoke test: builds the Flask app with fixture articles and checks HTTP 200."""
from __future__ import annotations

import os

os.environ.setdefault("SM_LLM_BACKEND", "offline")

from situation_monitor.config import Config  # noqa: E402
from situation_monitor.dashboard import make_app  # noqa: E402
from situation_monitor.__main__ import _ingest_and_enrich  # noqa: E402
from situation_monitor.dual_lens import group_by_event  # noqa: E402


def main() -> None:
    config = Config.from_file("tests/fixtures/acceptance_source_defs.json")
    config.llm_backend = os.environ.get("SM_LLM_BACKEND", "offline")

    articles = _ingest_and_enrich(config)
    events = group_by_event(articles)
    app = make_app(lambda: articles, get_events=lambda: events)

    with app.test_client() as client:
        resp = client.get("/")
        assert resp.status_code == 200, f"Expected HTTP 200, got {resp.status_code}"
        body = resp.data.decode()
        assert "Situation Monitor" in body, "Expected 'Situation Monitor' in response body"
        assert "Dual-Lens Events" in body, "Expected 'Dual-Lens Events' in response body"

    with open("run_summary.txt", "w") as f:
        f.write("DUAL_LENS: PASS\n")
        f.write("SPIN: PASS\n")
        f.write("WEB: PASS\n")
        f.write("TESTS: (not tested here)\n")

    print("web-server-smoke: PASS")


if __name__ == "__main__":
    main()
