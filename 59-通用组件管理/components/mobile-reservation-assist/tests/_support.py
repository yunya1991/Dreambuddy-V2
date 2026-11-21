"""测试支撑：把组件脚本加入 sys.path，提供临时 store 与样例作业。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
COMPONENT = TESTS_DIR.parent
SCRIPTS = COMPONENT / "skill" / "scripts"
FIXTURES = TESTS_DIR / "fixtures"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def temp_store():
    import store as store_mod

    tmp = tempfile.TemporaryDirectory()
    db = store_mod.Store(Path(tmp.name) / "state.db")
    return db, tmp


def sample_hit(adapter: str = "railway", task_id: str = "t1", fingerprint: str = "fp-abc") -> dict:
    return {
        "adapter": adapter,
        "task_id": task_id,
        "fingerprint": fingerprint,
        "at": 1_700_000_000_000,
        "target": {"target_id": "G1", "session": "2026-12-01", "price_tier": "二等座"},
        "max_price": 600,
    }
