"""Threshold-based alerting for high-relevance articles."""

from __future__ import annotations

import sys
from typing import IO, Optional, Union

from situation_monitor.models import Article


def check_and_emit_alerts(
    articles: list[Article],
    threshold: float,
    output_file: Optional[Union[str, IO[str]]] = None,
) -> list[Article]:
    """Emit alerts for articles whose relevance_score meets or exceeds *threshold*.

    Alerts are printed to stdout unless *output_file* is set, in which case
    they are appended to that file.  Returns the list of alerted articles.
    """
    # Root-cause fix: original code used strict `>`, failing test_alert_fires_when_score_at_threshold
    # and test_mixed_score_batch_returns_correct_subset which require score >= threshold.
    alerted: list[Article] = [
        a for a in articles
        if a.relevance_score is not None and a.relevance_score >= threshold
    ]

    lines = [
        f"ALERT: title={a.title!r} score={a.relevance_score:.4f} cluster={a.cluster_id!r}"
        for a in alerted
    ]

    if not lines:
        return alerted

    if output_file is not None:
        # Root-cause fix: original code called open(output_file,'a') unconditionally, raising
        # TypeError when given a file-like object (StringIO) — test_stringio_accepted_as_output_file.
        if hasattr(output_file, "write"):
            output_file.write("\n".join(lines) + "\n")
        else:
            with open(output_file, "a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
    else:
        for line in lines:
            print(line, file=sys.stdout)

    return alerted
