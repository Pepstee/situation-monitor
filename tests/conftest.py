"""Session-wide pytest configuration for the Situation Monitor test suite.

Two responsibilities:

1. Make ``situation_monitor`` importable from every test module by putting the
   project root on ``sys.path`` (mirrors ``tests/situation_monitor/conftest.py``
   for the top-level test files).

2. Pin the LLM backend to ``offline`` for the entire test session **unless the
   caller has explicitly chosen one**.  The default backend is ``"claude"``,
   which shells out to the live ``claude`` binary (see
   ``situation_monitor/llm.py``).  If any test reaches that code path the suite
   becomes non-deterministic — it depends on a binary, the network, and real
   model output — which is exactly what made the test gate oscillate.  Forcing
   ``offline`` at collection time guarantees the suite is hermetic: the spin
   estimator and bias rubric still run for real, but no subprocess or network
   call is ever made.

   Subprocess-based tests that spawn a fresh interpreter set ``SM_LLM_BACKEND``
   in the child's environment themselves; this only governs in-process code that
   reads the ambient environment via ``Config.from_file``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Set at import (collection) time so any Config built during collection is
# already hermetic.  Respect an explicit choice if the operator set one.
os.environ.setdefault("SM_LLM_BACKEND", "offline")
