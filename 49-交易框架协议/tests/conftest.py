"""M0-02 / M0-05 tests path setup."""

from __future__ import annotations

import sys
from pathlib import Path

CONTRACT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CONTRACT_ROOT.parent
for path in (
    CONTRACT_ROOT / "scripts",
    REPO_ROOT / "23-四层闭环自进化交易架构",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
