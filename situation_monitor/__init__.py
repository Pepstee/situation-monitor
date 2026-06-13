"""Situation Monitor — periodic digest of monitored news sources."""

__version__ = "0.1.0"

from situation_monitor.dual_lens import AnnotatedArticle, DualLensEvent, group_by_event  # noqa: F401
from situation_monitor.practical import PracticalMover, fetch_practical_movers, fetch_regulatory_movers  # noqa: F401
