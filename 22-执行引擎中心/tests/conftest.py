"""pytest bootstrap shared by all TEE tests.

Adds 22-执行引擎中心 to sys.path so tests can `import tee_core`.
The path injection mirrors the hand-written pattern in each test to keep
them independently runnable; this conftest merely avoids duplication.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # 22-执行引擎中心/tests
MODULE_ROOT = HERE.parent                        # 22-执行引擎中心
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))
