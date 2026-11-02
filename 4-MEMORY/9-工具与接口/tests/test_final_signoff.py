"""最终签收脚本单测（V1-V15 全量验收，设计节 6.2 + 7.9）。"""
import sys
import types
from pathlib import Path
from unittest.mock import patch

_MODULE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MODULE_DIR))

# 本目录 scripts/ 与仓库根 scripts/ 都是无 __init__.py 的命名空间包，而
# 11-易经推理系统/scripts 是常规包（含 __init__.py）。按 PEP 420，常规包优先于
# 命名空间包，仓库根 conftest 注入该目录后，pytest 内 `import scripts` 会命中
# 常规包，导致本目录 scripts.final_signoff 不可见（ModuleNotFoundError）。
# 这里预先注册命名空间包，按 sys.path 顺序收集所有 scripts 目录，
# 复现无遮蔽时的命名空间解析语义。
_pkg = sys.modules.get("scripts")
if _pkg is None or not hasattr(_pkg, "__path__"):
    _pkg = types.ModuleType("scripts")
    _pkg.__path__ = []
    sys.modules["scripts"] = _pkg
_local_scripts = str(_MODULE_DIR / "scripts")
if _local_scripts not in _pkg.__path__:
    _pkg.__path__.insert(0, _local_scripts)
for _entry in sys.path:
    _cand = str(Path(_entry) / "scripts")
    if _cand != _local_scripts and Path(_cand).is_dir() and _cand not in _pkg.__path__:
        _pkg.__path__.append(_cand)

from scripts.final_signoff import (  # noqa: E402  命名空间包注册必须先于 import
    AcceptanceItem,
    run_all_acceptance,
)


def test_acceptance_returns_15_items():
    """V1-V15 共 15 项验收。"""
    with patch("scripts.final_signoff._run_acceptance_check") as mock_check:
        mock_check.return_value = True
        results = run_all_acceptance()
    assert len(results) == 15
    ids = [r.vid for r in results]
    assert ids == [f"V{i}" for i in range(1, 16)]


def test_all_acceptance_items_have_fields():
    """每个验收项含 vid/name/method/criteria/passed 字段。"""
    with patch("scripts.final_signoff._run_acceptance_check") as mock_check:
        mock_check.return_value = True
        results = run_all_acceptance()
    for r in results:
        assert isinstance(r, AcceptanceItem)
        assert r.vid != ""
        assert r.name != ""
        assert r.method != ""
        assert r.criteria != ""
        assert r.passed in (True, False)


def test_v14_quarantine_filter_check():
    """V14：quarantined 的 Solution Path recall 不召回。"""
    from scripts.final_signoff import _check_v14
    with patch("scripts.final_signoff._run_cli") as mock_cli:
        # recall 返回不含 quarantined 的 applied
        mock_cli.return_value = {
            "processes": {
                "applied": [
                    {"applied_id": "APP-1", "quality_level": "B"},
                    {"applied_id": "APP-2", "quality_level": "A"},
                ]
            }
        }
        result = _check_v14()
    assert result.passed is True
    assert "quarantined" not in result.actual or "0" in result.actual
