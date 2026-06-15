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
   reads the ambient environment via ``Config.from_file``.  Because we also
   normalise ``os.environ`` here, those children inherit the hermetic value too
   unless they override it on purpose.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_ORCH_ROOT = Path(__file__).parent.parent.parent.parent
if str(_ORCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_ORCH_ROOT))

# Backends that reach the network or a local binary — exactly the ones that make
# the suite non-deterministic and the test gate oscillate (project memory:
# "Live-claude flaky test gate").  ``setdefault`` alone is not enough: when the
# gate runs the suite inside the daemon's environment, a leaked
# ``SM_LLM_BACKEND=claude`` (the orchestrator's own default) is *already set*, so
# setdefault respects it and every pipeline subprocess that inherits the ambient
# env shells out to the live ``claude`` binary — flaky, slow, network-bound.  No
# in-process test needs a live backend (they mock ``get_llm_client``, pin
# offline, or only string-check), so force a hermetic backend whenever the
# ambient one would hit the network/binary.  An explicit *hermetic* choice
# (offline/stub/deterministic) is still respected.
_NETWORKED_BACKENDS = {"claude", "ollama"}
if os.environ.get("SM_LLM_BACKEND", "").strip().lower() in _NETWORKED_BACKENDS:
    os.environ["SM_LLM_BACKEND"] = "offline"
else:
    os.environ.setdefault("SM_LLM_BACKEND", "offline")
