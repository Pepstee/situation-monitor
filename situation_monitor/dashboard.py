"""Web dashboard for situation_monitor."""

from __future__ import annotations

from typing import Callable, Optional

from flask import Flask, Response, abort, jsonify, render_template_string, request

from situation_monitor.urls import safe_url

_TEMPLATE = """\
{% autoescape true %}
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="60">
  <title>Situation Monitor</title>
  <style>
    body { font-family: sans-serif; padding: 1rem; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; }
    th { background: #f0f0f0; }
    tr:nth-child(even) { background: #fafafa; }
    a { color: #1a6fa8; }
    .dual-cols { display: flex; gap: 1rem; margin-top: 0.5rem; }
    .col { flex: 1; padding: 0.5rem; border: 1px solid #ddd; border-radius: 4px; }
    .col-left { background: #f0f4ff; }
    .col-right { background: #fff4f0; }
    .spin-badge { display: inline-block; background: #444; color: #fff;
                  border-radius: 3px; padding: 0 0.3rem; font-size: 0.75rem;
                  margin-right: 0.4rem; }
    .event-card { margin-bottom: 1.5rem; border: 1px solid #ccc;
                  border-radius: 4px; padding: 0.75rem; }
    .spin-delta { font-size: 0.85rem; color: #555; margin: 0.25rem 0 0.75rem; }
    .article-card { margin-bottom: 0.5rem; font-size: 0.9rem; }
    h2 { margin-top: 1.5rem; }
  </style>
</head>
<body>
  <h1>Situation Monitor</h1>
  <form method="get" style="margin-bottom: 0.75rem;">
    <label for="domain-select">Domain:</label>
    <select id="domain-select" name="domain" onchange="this.form.submit()">
      <option value="">All</option>
      <option value="world" {% if request.args.get('domain','').lower() == 'world' %}selected{% endif %}>World</option>
      <option value="markets" {% if request.args.get('domain','').lower() == 'markets' %}selected{% endif %}>Markets</option>
      <option value="ai" {% if request.args.get('domain','').lower() == 'ai' %}selected{% endif %}>AI</option>
    </select>
  </form>
  <p>{{ stories | length }} stories — auto-refreshes every 60 s</p>
  {% if events %}
  <h2>Dual-Lens Events</h2>
  {% for event in events %}
  <div class="event-card">
    <h3>{{ event.event_title }}</h3>
    <p class="spin-delta">spin_delta: {{ '%.1f' | format(event.spin_delta) }}</p>
    <div class="dual-cols">
      <div class="col col-left">
        <h4>LEFT</h4>
        {% for aa in event.left_articles %}
        <div class="article-card">
          <span class="spin-badge">spin_pct: {{ '%.1f' | format(aa.spin.spin_pct) }}%</span>
          <a href="{{ aa.article.url | safe_url }}">{{ aa.article.title }}</a><br>
          <small>{{ aa.article.source }}</small>
        </div>
        {% endfor %}
        {% if not event.left_articles %}<em>No left-framing articles</em>{% endif %}
      </div>
      <div class="col col-right">
        <h4>RIGHT</h4>
        {% for aa in event.right_articles %}
        <div class="article-card">
          <span class="spin-badge">spin_pct: {{ '%.1f' | format(aa.spin.spin_pct) }}%</span>
          <a href="{{ aa.article.url | safe_url }}">{{ aa.article.title }}</a><br>
          <small>{{ aa.article.source }}</small>
        </div>
        {% endfor %}
        {% if not event.right_articles %}<em>No right-framing articles</em>{% endif %}
      </div>
    </div>
  </div>
  {% endfor %}
  {% endif %}
  <h2>All Stories</h2>
  <table>
    <thead>
      <tr>
        <th>Title</th>
        <th>Source</th>
        <th>Lean</th>
        <th>Reliability</th>
        <th>Relevance</th>
        <th>Cluster</th>
        <th>Propaganda Flags</th>
        <th>Polymarket Odds</th>
      </tr>
    </thead>
    <tbody>
      {% for s in stories %}
      <tr>
        <td><a href="{{ s.url | safe_url }}">{{ s.title }}</a></td>
        <td>{{ s.source }}</td>
        <td>{{ s.source_lean or '' }}</td>
        <td>{{ s.source_reliability_label or s.reliability.value }}</td>
        <td>{% if s.relevance_score is not none %}{{ '%.2f' | format(s.relevance_score) }}{% endif %}</td>
        <td>{{ s.cluster_id or '' }}</td>
        <td>{{ s.propaganda_flags | join(', ') }}</td>
        <td>{% if s.polymarket_odds is not none %}{{ '%.2f' | format(s.polymarket_odds) }}{% endif %}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</body>
</html>
{% endautoescape %}
"""


def _event_to_dict(event) -> dict:
    def _aa_dict(aa) -> dict:
        art = aa.article
        return {
            "url": art.url,
            "title": art.title,
            "source": art.source,
            "source_lean": art.source_lean,
            "cluster_id": art.cluster_id,
            "relevance_score": art.relevance_score,
            "spin_pct": aa.spin.spin_pct,
            "spin_lens": aa.spin.lens,
            "spin_receipts": aa.spin.receipts,
        }

    return {
        "event_title": event.event_title,
        "spin_delta": event.spin_delta,
        "left_articles": [_aa_dict(aa) for aa in event.left_articles],
        "right_articles": [_aa_dict(aa) for aa in event.right_articles],
        "center_articles": [_aa_dict(aa) for aa in event.center_articles],
    }


def _practical_to_dict(pm) -> dict:
    return {
        "asset": pm.asset,
        "change_pct": pm.change_pct,
        "direction": pm.direction,
        "who_it_affects": pm.who_it_affects,
        "what_to_watch": pm.what_to_watch,
        "source_url": pm.source_url,
    }


def make_app(
    get_stories: Callable[[], list],
    get_events: Optional[Callable[[], list]] = None,
    get_practical: Optional[Callable[[], list]] = None,
) -> Flask:
    """Create the Flask dashboard app.

    Args:
        get_stories: zero-argument callable returning the current list of Article objects.
        get_events: optional callable returning the current list of DualLensEvent objects.
        get_practical: optional callable returning the current list of PracticalMover objects.
    """
    app = Flask(__name__)
    app.jinja_env.filters["safe_url"] = safe_url

    def _domain_filter(domain_param: Optional[str]):
        """Return a normalised domain name string or None if no filter requested."""
        return domain_param.upper() if domain_param else None

    def _filter_stories(stories: list, domain: Optional[str]) -> list:
        if domain is None:
            return stories
        return [s for s in stories if s.domain is not None and s.domain.name == domain]

    def _filter_events(events: list, domain: Optional[str]) -> list:
        if domain is None:
            return events
        result = []
        for event in events:
            all_articles = event.left_articles + event.right_articles + event.center_articles
            if any(aa.article.domain is not None and aa.article.domain.name == domain for aa in all_articles):
                result.append(event)
        return result

    @app.route("/")
    def index() -> str:
        domain = _domain_filter(request.args.get("domain"))
        stories = _filter_stories(get_stories(), domain)
        events = _filter_events(get_events() if get_events is not None else [], domain)
        return render_template_string(_TEMPLATE, stories=stories, events=events)

    @app.route("/api/events")
    def api_events() -> Response:
        domain = _domain_filter(request.args.get("domain"))
        events = _filter_events(get_events() if get_events is not None else [], domain)
        return jsonify([_event_to_dict(e) for e in events])

    @app.route("/api/events/<cluster_id>/rationale")
    def api_event_rationale(cluster_id: str) -> Response:
        events = get_events() if get_events is not None else []
        try:
            idx = int(cluster_id)
        except ValueError:
            abort(404)
        if idx < 0 or idx >= len(events):
            abort(404)
        event = events[idx]
        all_articles = event.left_articles + event.right_articles + event.center_articles
        receipts = [
            {
                "title": aa.article.title,
                "source": aa.article.source,
                "receipts": aa.spin.receipts,
            }
            for aa in all_articles
        ]
        return jsonify({"event_title": event.event_title, "receipts": receipts})

    @app.route("/api/practical")
    def api_practical() -> Response:
        practical = get_practical() if get_practical is not None else []
        return jsonify([_practical_to_dict(p) for p in practical])

    return app
