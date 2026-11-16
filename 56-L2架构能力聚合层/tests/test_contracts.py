# -*- coding: utf-8 -*-
"""契约可判定性门禁：validate_contracts.py --self-test 必须 1 正 5 负全绿。"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_contracts_self_test():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_contracts.py"), "--self-test"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "SELF-TEST PASSED" in proc.stdout
