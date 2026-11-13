"""T-G2a：capital_control / capital_allocator 迁移后的导入契约。

- 新路径：13-通用风控模块/risk_capital 下可独立导入（不依赖 16）
- 旧路径：16-调控系统/core 下的 shim 等价重定向到新实现
- shim 必须支持子模块旧路径（component / types / capital_rules）

用子进程隔离验证，避免 `core` 顶层包在 pytest 单进程内互相污染。
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RISK_DIR = REPO / "13-通用风控模块"
RISK_CAPITAL = RISK_DIR / "risk_capital"
LEGACY_16_CORE = REPO / "16-调控系统" / "core"


def _run(code: str, cwd: Path = REPO) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_new_path_imports_both_components():
    code = (
        "import sys\n"
        f"sys.path.insert(0, r'{RISK_DIR}')\n"
        "from risk_capital.capital_control.component import CapitalControlComponent\n"
        "from risk_capital.capital_allocator.component import CapitalAllocatorComponent\n"
        "print(CapitalControlComponent.__module__, CapitalAllocatorComponent.__module__)\n"
    )
    p = _run(code)
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip() == (
        "risk_capital.capital_control.component risk_capital.capital_allocator.component"
    )


def test_legacy_shim_redirects_to_new_implementation():
    code = (
        "import inspect, sys\n"
        f"sys.path.insert(0, r'{LEGACY_16_CORE}')\n"
        "from capital_control.component import CapitalControlComponent\n"
        "from capital_control.types import CapitalMode\n"
        "from capital_allocator.component import CapitalAllocatorComponent\n"
        "from capital_allocator.types import AllocatorMode\n"
        "print(inspect.getsourcefile(CapitalControlComponent))\n"
        "print(inspect.getsourcefile(CapitalAllocatorComponent))\n"
    )
    p = _run(code)
    assert p.returncode == 0, p.stderr
    assert "13-通用风控模块/risk_capital/capital_control/component.py" in p.stdout
    assert "13-通用风控模块/risk_capital/capital_allocator/component.py" in p.stdout


def test_legacy_shim_resolves_capital_rules_submodule():
    code = (
        "import sys\n"
        f"sys.path.insert(0, r'{LEGACY_16_CORE}')\n"
        "from capital_control.capital_rules import okx_live_rule\n"
        "print(okx_live_rule.__name__)\n"
    )
    p = _run(code)
    assert p.returncode == 0, p.stderr
    assert "okx_live_rule" in p.stdout


def test_no_reverse_import_to_11_in_risk_capital():
    """13/risk_capital 不得 import 11 的任何模块（依赖方向 11→22→13）。"""
    offenders = []
    for path in RISK_CAPITAL.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "11-易经推理系统" in text and "all_trades.jsonl" not in text:
            offenders.append(str(path.relative_to(REPO)))
    assert offenders == []
