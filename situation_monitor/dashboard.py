"""Web dashboard for situation_monitor."""

from __future__ import annotations

from typing import Callable

from flask import Flask, render_template_string

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
  </style>
</head>
<body>
  <h1>Situation Monitor</h1>
  <p>{{ stories | length }} stories — auto-refreshes every 60 s</p>
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
        <td><a href="{{ s.url }}">{{ s.title }}</a></td>
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


def make_app(get_stories: Callable[[], list]) -> Flask:
    """Create the Flask dashboard app.

    Args:
        get_stories: zero-argument callable returning the current list of Article objects.
    """
    app = Flask(__name__)

    @app.route("/")
    def index() -> str:
        return render_template_string(_TEMPLATE, stories=get_stories())

    return app
