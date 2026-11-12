"""E-4 静态检查：非 gate 模块不得手写 verdict 字面量（SPEC §7.6.4）。

唯一允许产出因子 verdict 的模块是 registry/factor_gate.py。
本测试扫描 48-涌现架构 下所有 .py，出现 `"verdict":` 字面量即视为绕过。

LEGACY_ALLOWLIST 是**存量豁免**（E1-E5 / 实验级 verdict，非因子 verdict），
目的是避免一次性全红；每迁移一个模块到 assert_gate() 就从名单删除一项。
新增文件不在名单内 → 直接 fail。
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE_FILE = "registry/factor_gate.py"
PATTERN = re.compile(r'"verdict"\s*:')

LEGACY_ALLOWLIST = {
    "asil/cognitive_writeback.py",
    "asil/orchestrator.py",
    "asil/verdict_router.py",
    "asil/oracle_validator.py",
    "asil/oracle_rea_independent.py",
    "metrics/emergence_metrics.py",
    "metrics/verdict_dashboard.py",
    "experiments/d2a_holdout/evaluate.py",
    "experiments/d2a_holdout/run_d2a.py",
    "experiments/d2a_holdout/leak_audit.py",
    "experiments/d2b_engineering/evaluate.py",
    "experiments/d3a_intent/evaluate.py",
    "experiments/d3a_intent/run_d3a.py",
    "experiments/d3b_intent_combo/evaluate.py",
    "experiments/e3_coupling/coupling_counterfactual.py",
    "experiments/e3_coupling/rolling_retest.py",
    "experiments/xa_transfer/evaluate.py",
    "experiments/xa_transfer/real_ab.py",
    "experiments/xa_transfer/run_xa.py",
}


def _iter_py_files():
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if "__pycache__" in rel or "/tests/" in f"/{rel}" or "/__tests__/" in f"/{rel}":
            continue
        if rel == GATE_FILE:
            continue
        yield rel, path


def test_no_direct_verdict_write():
    violations = []
    for rel, path in _iter_py_files():
        if rel in LEGACY_ALLOWLIST:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if PATTERN.search(line):
                violations.append(f"{rel}:{lineno}: {line.strip()}")
    assert not violations, "存在绕过 factor_gate 的手写 verdict：\n" + "\n".join(violations)


def test_allowlist_entries_still_exist():
    """防止豁免名单腐烂：迁移后应删除条目，而不是留下幽灵路径。"""
    missing = [rel for rel in sorted(LEGACY_ALLOWLIST) if not (ROOT / rel).is_file()]
    assert not missing, f"豁免名单中的文件已不存在，请清理：{missing}"
