"""RED 测试 — WashoutReversalCaseLibrary (洗盘反转做多案例库).

Spec: docs/superpowers/specs/2026-09-22-washout-reversal-genome-design.md §3.2

阶段1 新增文件 (纯新增):
  - 1-ARCHITECTURE/dreamos/evolution/washout_reversal_case_library.py
      — 复用 WashoutCase 结构 + 独立案例库 + KNN 检索

设计原则 (硬约束):
  - HC-G4: 案例库 <30 时走规则化 EndingDetector
  - actual_label: reversal_long_success / reversal_long_fail
  - reward: tanh(pnl_pct/0.02) 归一化 [-1,1]
  - KNN: 欧氏距离 + key 并集缺失填 0.0 + 稳定排序
  - FAIL-OPEN: knn_search 异常 → 返回空列表

TDD 测试清单:
  T1  / test_add_and_retrieve                    — 案例入库 + 检索
  T2  / test_knn_search_returns_k_neighbors       — KNN 返回 k 个最近邻
  T3  / test_knn_search_distance_euclidean        — 欧氏距离正确
  T4  / test_knn_search_empty_library            — 空库返回空列表
  T5  / test_knn_search_k_greater_than_size       — k > 库大小返回全部
  T6  / test_actual_label_reversal_long_success   — 标签 reversal_long_success
  T7  / test_actual_label_reversal_long_fail      — 标签 reversal_long_fail
  T8  / test_reward_tanh_normalization            — reward = tanh(pnl/0.02)
  T9  / test_reward_clip_range                    — reward 裁剪到 [-1, 1]
  T10 / test_case_id_duplicate_overwrite          — case_id 重复覆盖
  T11 / test_knn_search_fail_open_exception        — 异常 → 空列表
  T12 / test_min_cases_threshold                  — len() < 30 → 降级标识
  T13 / test_no_llm_dependency                    — grep 确认无 LLM 调用
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

# ============================================================
# sys.path 设置
# ============================================================
_THIS_DIR = Path(__file__).resolve().parent
_BCRM2_SCRIPTS_ROOT = _THIS_DIR.parent.parent
_PROJECT_ROOT = _BCRM2_SCRIPTS_ROOT.parent.parent
_ARCH_ROOT = _PROJECT_ROOT / "1-ARCHITECTURE"

for _p in (_BCRM2_SCRIPTS_ROOT, _ARCH_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ============================================================
# 导入（RED 阶段：模块不存在时 ImportError）
# ============================================================
from dreamos.evolution.washout_reversal_case_library import (  # noqa: E402
    WashoutReversalCaseLibrary,
)
from dreamos.evolution.washout_case_library import WashoutCase  # noqa: E402


# ============================================================
# 辅助函数: 构造测试案例
# ============================================================
def _make_case(
    case_id: str = "case-001",
    coin: str = "BTC",
    actual_label: str = "reversal_long_success",
    pnl_pct: float = 0.05,
    features: dict = None,
) -> WashoutCase:
    """构造测试用 WashoutCase."""
    if features is None:
        features = {"F1": 1.0, "F2": 2.0, "F3": 3.0}
    return WashoutCase(
        case_id=case_id,
        coin=coin,
        entry_time="2026-09-22T00:00:00+00:00",
        exit_time="2026-09-22T12:00:00+00:00",
        features_snapshot=features,
        actual_label=actual_label,
        pnl_pct=pnl_pct,
        reward=WashoutCase.compute_reward(pnl_pct),
        timestamp="2026-09-22T12:00:00+00:00",
    )


# ============================================================
# T1-T5: 案例库基本操作 + KNN 检索
# ============================================================
class TestCaseLibraryBasic:
    def test_add_and_retrieve(self):
        """T1: 案例入库 + 通过 case_id 检索."""
        lib = WashoutReversalCaseLibrary()
        case = _make_case()
        lib.add(case)
        assert len(lib) == 1
        retrieved = lib.get("case-001")
        assert retrieved is not None
        assert retrieved.case_id == "case-001"

    def test_knn_search_returns_k_neighbors(self):
        """T2: KNN 返回 k 个最近邻."""
        lib = WashoutReversalCaseLibrary()
        for i in range(5):
            lib.add(_make_case(case_id=f"case-{i}", features={"F1": float(i)}))
        results = lib.knn_search({"F1": 2.0}, k=3)
        assert len(results) == 3
        # 按距离升序
        for i in range(len(results) - 1):
            assert results[i][0] <= results[i + 1][0]

    def test_knn_search_distance_euclidean(self):
        """T3: 欧氏距离正确."""
        lib = WashoutReversalCaseLibrary()
        lib.add(_make_case(case_id="a", features={"F1": 0.0, "F2": 0.0}))
        lib.add(_make_case(case_id="b", features={"F1": 3.0, "F2": 4.0}))
        results = lib.knn_search({"F1": 0.0, "F2": 0.0}, k=2)
        # case-a 距离=0, case-b 距离=5.0
        assert results[0][1].case_id == "a"
        assert results[0][0] == pytest.approx(0.0)
        assert results[1][1].case_id == "b"
        assert results[1][0] == pytest.approx(5.0)

    def test_knn_search_empty_library(self):
        """T4: 空库返回空列表."""
        lib = WashoutReversalCaseLibrary()
        results = lib.knn_search({"F1": 1.0}, k=5)
        assert results == []

    def test_knn_search_k_greater_than_size(self):
        """T5: k > 库大小 → 返回全部."""
        lib = WashoutReversalCaseLibrary()
        for i in range(3):
            lib.add(_make_case(case_id=f"c-{i}", features={"F1": float(i)}))
        results = lib.knn_search({"F1": 0.0}, k=10)
        assert len(results) == 3


# ============================================================
# T6-T7: 标签语义
# ============================================================
class TestCaseLabelSemantics:
    def test_actual_label_reversal_long_success(self):
        """T6: actual_label=reversal_long_success 入库."""
        lib = WashoutReversalCaseLibrary()
        case = _make_case(actual_label="reversal_long_success", pnl_pct=0.08)
        lib.add(case)
        assert lib.get(case.case_id).actual_label == "reversal_long_success"

    def test_actual_label_reversal_long_fail(self):
        """T7: actual_label=reversal_long_fail 入库."""
        lib = WashoutReversalCaseLibrary()
        case = _make_case(actual_label="reversal_long_fail", pnl_pct=-0.05)
        lib.add(case)
        assert lib.get(case.case_id).actual_label == "reversal_long_fail"


# ============================================================
# T8-T9: reward 计算
# ============================================================
class TestRewardComputation:
    def test_reward_tanh_normalization(self):
        """T8: reward = tanh(pnl_pct/0.02) 归一化."""
        # pnl=0.02 → tanh(1) ≈ 0.7616
        r = WashoutCase.compute_reward(0.02)
        assert r == pytest.approx(math.tanh(1.0), abs=1e-6)
        # pnl=-0.02 → tanh(-1) ≈ -0.7616
        r_neg = WashoutCase.compute_reward(-0.02)
        assert r_neg == pytest.approx(math.tanh(-1.0), abs=1e-6)

    def test_reward_clip_range(self):
        """T9: reward 裁剪到 [-1, 1]."""
        case = _make_case(pnl_pct=1.0, actual_label="reversal_long_success")
        assert case.reward <= 1.0
        case_neg = _make_case(pnl_pct=-1.0, actual_label="reversal_long_fail")
        assert case_neg.reward >= -1.0


# ============================================================
# T10-T12: 边界 + FAIL-OPEN
# ============================================================
class TestEdgeCases:
    def test_case_id_duplicate_overwrite(self):
        """T10: case_id 重复时覆盖旧案例."""
        lib = WashoutReversalCaseLibrary()
        lib.add(_make_case(case_id="dup", features={"F1": 1.0}))
        lib.add(_make_case(case_id="dup", features={"F1": 99.0}))
        assert len(lib) == 1
        assert lib.get("dup").features_snapshot["F1"] == 99.0

    def test_knn_search_fail_open_exception(self):
        """T11: knn_search 异常 → 返回空列表."""
        lib = WashoutReversalCaseLibrary()
        lib.add(_make_case())
        # 传入非法 query 触发异常
        results = lib.knn_search(None, k=5)  # type: ignore
        assert results == []

    def test_min_cases_threshold(self):
        """T12: len() < 30 → 可用于降级判定."""
        lib = WashoutReversalCaseLibrary()
        for i in range(10):
            lib.add(_make_case(case_id=f"c-{i}"))
        assert len(lib) == 10
        assert len(lib) < 30  # 低于 min_cases 阈值


# ============================================================
# T13: 无 LLM 依赖
# ============================================================
class TestNoLLMDependency:
    def test_no_llm_dependency(self):
        """T13: 源码中无 LLM/openai/anthropic 调用."""
        source_path = (
            _ARCH_ROOT / "dreamos" / "evolution"
            / "washout_reversal_case_library.py"
        )
        if source_path.exists():
            source = source_path.read_text()
            for kw in ("import openai", "from openai", "import anthropic", "from anthropic",
                        "chat.completions.create", "messages.create"):
                assert kw not in source.lower(), f"发现 LLM 依赖: {kw}"
