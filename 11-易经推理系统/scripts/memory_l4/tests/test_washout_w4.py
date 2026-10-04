"""W4 RED 测试 — WashoutClassifier (KNN/CBR + 贝叶斯) + 案例库 + 贝叶斯更新器.

Spec: docs/superpowers/specs/2026-09-21-washout-detector-design.md §9.4

W4 新增 3 文件 (纯新增, 零回归):
  - 1-ARCHITECTURE/dreamos/evolution/washout_case_library.py     — WashoutCase + KNN 检索
  - 1-ARCHITECTURE/dreamos/evolution/washout_bayesian_updater.py — 贝叶斯先验/后验更新
  - 1-ARCHITECTURE/dreamos/evolution/washout_classifier.py      — KNN/CBR + 贝叶斯主类

W4 修改 1 文件 (classifier=None 时字节等价, 零回归):
  - 11-易经推理系统/scripts/memory_l4/bcrm2/washout_detector.py
      run() 注入 classifier 后走 KNN/Bayesian 路径

设计原则 (硬约束):
  - HC-2: KNN/CBR + 贝叶斯闭环（禁用 LLM）
  - 案例库 >= 30 才走 KNN，否则降级规则（§5.4）
  - reward = tanh(pnl_pct / 0.02) 归一化 [-1, 1]（自进化硬约束）
  - 复用 EvolutionEngine._sandbox_validate 沙箱验证（§5.4 evolve）
  - FAIL-OPEN 铁律：异常 → unknown()，不阻塞

TDD 测试清单 (§9.4 共 14 项):
  T1  / test_washout_case_library_add_and_retrieve           — 案例入库 + 检索
  T2  / test_washout_case_library_knn_search_returns_k_neighbors — KNN 返回 k 个最近邻
  T3  / test_washout_case_library_knn_search_distance_euclidean — 欧氏距离正确
  T4  / test_washout_classifier_insufficient_cases_fallback_rule — 案例 < 30 → 降级规则
  T5  / test_washout_classifier_predict_washout_high_confidence — 高置信度洗盘判定
  T6  / test_washout_classifier_predict_weakness_high_confidence — 高置信度真弱势判定
  T7  / test_washout_classifier_predict_unknown_middle_confidence — 中等置信度 → unknown
  T8  / test_washout_classifier_bayesian_update_prior_posterior — 贝叶斯先验/后验更新正确
  T9  / test_washout_classifier_record_case_updates_library   — 闭环后案例入库
  T10 / test_washout_classifier_evolve_sandbox_validate       — 复用 _sandbox_validate 通过
  T11 / test_washout_classifier_reward_tanh_normalization     — reward = tanh(pnl/0.02) 归一化
  T12 / test_washout_classifier_no_llm_dependency             — grep 确认无 LLM 调用
  T13 / test_washout_classifier_evolution_engine_integration  — 与 EvolutionEngine 集成
  T14 / test_washout_detector_with_classifier_predict         — WashoutDetector 注入 classifier 走 KNN/Bayesian
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Dict, List, Optional

import pytest

# ============================================================
# sys.path 设置: 同时支持 bcrm2 (11-易经推理系统/) 和 dreamos (1-ARCHITECTURE/)
# ============================================================
_THIS_DIR = Path(__file__).resolve().parent
# _THIS_DIR = .../11-易经推理系统/scripts/memory_l4/tests
# .parent.parent = .../11-易经推理系统/scripts  (sys.path 加这个, cwd 的 '' 让 scripts package 可 import)
_BCRM2_SCRIPTS_ROOT = _THIS_DIR.parent.parent
# .parent.parent.parent = .../dreambuddy-v2  (1-ARCHITECTURE 的父目录)
_PROJECT_ROOT = _BCRM2_SCRIPTS_ROOT.parent.parent
_ARCH_ROOT = _PROJECT_ROOT / "1-ARCHITECTURE"  # dreambuddy-v2/1-ARCHITECTURE

for _p in (_BCRM2_SCRIPTS_ROOT, _ARCH_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ============================================================
# 导入（RED 阶段：模块不存在时 ImportError）
# ============================================================
from scripts.memory_l4.bcrm2.washout_detector import (  # noqa: E402
    WashoutDetector,
    WashoutLabel,
    WashoutVerdict,
)

from dreamos.evolution.washout_case_library import (  # noqa: E402
    WashoutCase,
    WashoutCaseLibrary,
)
from dreamos.evolution.washout_bayesian_updater import (  # noqa: E402
    BayesianUpdater,
)
from dreamos.evolution.washout_classifier import (  # noqa: E402
    WashoutClassifier,
)


# ============================================================
# 辅助：构造 WashoutCase
# ============================================================
def _make_case(
    case_id: str,
    features: Dict[str, float],
    label: str,
    pnl_pct: float = 0.0,
    coin: str = "BTC",
) -> WashoutCase:
    """构造测试用 WashoutCase.

    Args:
        case_id: 案例唯一 ID
        features: 特征快照
        label: "washout" / "weakness"
        pnl_pct: 闭环盈亏百分比
    """
    import math as _m
    reward = _m.tanh(pnl_pct / 0.02)
    return WashoutCase(
        case_id=case_id,
        coin=coin,
        entry_time="2026-01-01T00:00:00",
        exit_time="2026-01-02T00:00:00",
        features_snapshot=dict(features),
        actual_label=label,
        pnl_pct=pnl_pct,
        reward=reward,
        timestamp="2026-01-02T00:00:00",
    )


# 洗盘特征模板（缩量 + 支撑守住 + 振幅收窄 + 低位 + 反弹强）
_WASHOUT_FEATURES: Dict[str, float] = {
    "volume_ratio_20d": 0.5,      # 缩量
    "support_holds_count": 3.0,   # 3 次守住支撑
    "atr_compress_ratio": 0.7,    # 振幅收窄
    "cycle_position_365d": 0.2,   # 低位
    "rebound_ratio_5d": 0.7,      # 反弹强
}

# 真弱势特征模板（放量 + 破位 + 振幅扩大 + 高位 + 反弹弱）
_WEAKNESS_FEATURES: Dict[str, float] = {
    "volume_ratio_20d": 2.0,      # 放量
    "support_holds_count": 0.0,   # 无守住
    "atr_compress_ratio": 1.5,    # 振幅扩大
    "cycle_position_365d": 0.8,   # 高位
    "rebound_ratio_5d": 0.2,      # 反弹弱
}

# 中间特征（query 在两类中间）
_MIDDLE_FEATURES: Dict[str, float] = {
    "volume_ratio_20d": 1.25,
    "support_holds_count": 1.5,
    "atr_compress_ratio": 1.1,
    "cycle_position_365d": 0.5,
    "rebound_ratio_5d": 0.45,
}


def _build_washout_library(n_washout: int = 30, n_weakness: int = 5) -> WashoutCaseLibrary:
    """构造测试用案例库 (默认 35 个 case: 30 washout + 5 weakness)."""
    lib = WashoutCaseLibrary()
    for i in range(n_washout):
        lib.add(_make_case(f"w{i}", _WASHOUT_FEATURES, "washout", pnl_pct=0.05))
    for i in range(n_weakness):
        lib.add(_make_case(f"s{i}", _WEAKNESS_FEATURES, "weakness", pnl_pct=-0.05))
    return lib


# ============================================================
# T1: WashoutCaseLibrary 案例入库 + 检索
# ============================================================
class TestCaseLibraryAddRetrieve:
    """T1: 案例入库 + 通过 case_id 检索."""

    def test_washout_case_library_add_and_retrieve(self):
        lib = WashoutCaseLibrary()
        assert len(lib) == 0

        case = _make_case("c1", {"x": 1.0}, "washout", pnl_pct=0.03)
        lib.add(case)
        assert len(lib) == 1

        got = lib.get("c1")
        assert got is not None
        assert got.case_id == "c1"
        assert got.actual_label == "washout"
        assert got.features_snapshot == {"x": 1.0}

        # 不存在的 case_id → None
        assert lib.get("nonexistent") is None


# ============================================================
# T2: KNN 返回 k 个最近邻 + 升序排列
# ============================================================
class TestCaseLibraryKnnReturnK:
    """T2: KNN 返回 k 个最近邻, 按距离升序."""

    def test_washout_case_library_knn_search_returns_k_neighbors(self):
        lib = WashoutCaseLibrary()
        # 10 个 case, 特征值 [0.0, 0.1, 0.2, ..., 0.9]
        for i in range(10):
            lib.add(_make_case(f"c{i}", {"x": float(i) * 0.1}, "washout"))

        query = {"x": 0.55}  # 离 0.5 和 0.6 最近
        results = lib.knn_search(query, k=5)
        assert len(results) == 5
        # 距离升序
        distances = [d for d, _ in results]
        assert distances == sorted(distances)
        # 最近的应该是 0.5, 0.6, 0.4, 0.7, 0.3 (浮点精度容差)
        nearest_features = [c.features_snapshot["x"] for _, c in results]
        assert any(abs(f - 0.5) < 0.01 for f in nearest_features)
        assert any(abs(f - 0.6) < 0.01 for f in nearest_features)


# ============================================================
# T3: KNN 欧氏距离正确
# ============================================================
class TestCaseLibraryKnnEuclidean:
    """T3: KNN 距离为欧氏距离."""

    def test_washout_case_library_knn_search_distance_euclidean(self):
        lib = WashoutCaseLibrary()
        # 3 个 case, 2 维特征
        lib.add(_make_case("a", {"x": 0.0, "y": 0.0}, "washout"))
        lib.add(_make_case("b", {"x": 3.0, "y": 4.0}, "weakness"))
        lib.add(_make_case("c", {"x": 1.0, "y": 1.0}, "washout"))

        query = {"x": 0.0, "y": 0.0}
        results = lib.knn_search(query, k=3)
        assert len(results) == 3

        # 距离: a=0, c=sqrt(2), b=sqrt(9+16)=5
        assert results[0][0] == pytest.approx(0.0)
        assert results[0][1].case_id == "a"
        assert results[1][0] == pytest.approx(math.sqrt(2.0))
        assert results[1][1].case_id == "c"
        assert results[2][0] == pytest.approx(5.0)
        assert results[2][1].case_id == "b"


# ============================================================
# T4: 案例 < 30 → 降级规则
# ============================================================
class TestClassifierInsufficientCases:
    """T4: 案例库 < 30 → predict 降级规则化判定."""

    def test_washout_classifier_insufficient_cases_fallback_rule(self):
        lib = WashoutCaseLibrary()
        # 29 个 case (< 30)
        for i in range(29):
            lib.add(_make_case(f"c{i}", _WASHOUT_FEATURES, "washout"))

        clf = WashoutClassifier(case_library=lib, min_cases=30)
        verdict = clf.predict(_WASHOUT_FEATURES)

        # 降级 → UNKNOWN + reason 含 "fallback" 或 "insufficient"
        assert verdict.label == WashoutLabel.UNKNOWN
        reason_lower = verdict.reason.lower()
        assert "fallback" in reason_lower or "insufficient" in reason_lower, (
            f"reason 应含 fallback/insufficient, got '{verdict.reason}'"
        )


# ============================================================
# T5: 高置信度洗盘判定
# ============================================================
class TestClassifierPredictWashout:
    """T5: 30+ washout 案例 → predict 高置信度 WASHOUT."""

    def test_washout_classifier_predict_washout_high_confidence(self):
        lib = _build_washout_library(n_washout=30, n_weakness=5)
        clf = WashoutClassifier(case_library=lib, k_neighbors=5, min_cases=30)
        verdict = clf.predict(_WASHOUT_FEATURES)

        # 5 邻居全是 washout → posterior = (1+5)/(1+1+5) = 6/7 ≈ 0.857 > 0.65
        assert verdict.label == WashoutLabel.WASHOUT, (
            f"应为 WASHOUT, got {verdict.label} conf={verdict.confidence}"
        )
        assert verdict.confidence > 0.65
        assert verdict.trigger_activated is True
        assert "knn" in verdict.reason.lower() or "bayesian" in verdict.reason.lower()


# ============================================================
# T6: 高置信度真弱势判定
# ============================================================
class TestClassifierPredictWeakness:
    """T6: 5 washout + 30 weakness → predict 高置信度 WEAKNESS."""

    def test_washout_classifier_predict_weakness_high_confidence(self):
        lib = _build_washout_library(n_washout=5, n_weakness=30)
        clf = WashoutClassifier(case_library=lib, k_neighbors=5, min_cases=30)
        verdict = clf.predict(_WEAKNESS_FEATURES)

        # 5 邻居全是 weakness → posterior = (1+0)/(1+1+5) = 1/7 ≈ 0.143 < 0.35
        assert verdict.label == WashoutLabel.WEAKNESS, (
            f"应为 WEAKNESS, got {verdict.label} conf={verdict.confidence}"
        )
        assert verdict.confidence > 0.65  # confidence = 1 - posterior = 6/7


# ============================================================
# T7: 中等置信度 → unknown
# ============================================================
class TestClassifierPredictUnknownMiddle:
    """T7: washout/weakness 各半 → 中等置信度 → UNKNOWN."""

    def test_washout_classifier_predict_unknown_middle_confidence(self):
        # 构造交替入库的案例库: washout 和 weakness 距离 query 相等
        # 交替入库确保 KNN 取 k 个时返回 k/2 washout + k/2 weakness
        lib = WashoutCaseLibrary()
        # washout 特征 [0.4, 0.4], weakness 特征 [0.6, 0.6], query [0.5, 0.5]
        # 距离都是 sqrt(0.02) ≈ 0.141, 交替入库保证 KNN 取混合
        for i in range(15):
            lib.add(_make_case(f"wn{i}", {"x": 0.4, "y": 0.4}, "washout", pnl_pct=0.05))
            lib.add(_make_case(f"sn{i}", {"x": 0.6, "y": 0.6}, "weakness", pnl_pct=-0.05))
        # 远离的案例 (距离 sqrt(0.5) ≈ 0.707, 不进入 k=6 邻居)
        for i in range(15):
            lib.add(_make_case(f"wf{i}", {"x": 0.0, "y": 0.0}, "washout", pnl_pct=0.05))
            lib.add(_make_case(f"sf{i}", {"x": 1.0, "y": 1.0}, "weakness", pnl_pct=-0.05))

        clf = WashoutClassifier(case_library=lib, k_neighbors=6, min_cases=30)
        query = {"x": 0.5, "y": 0.5}
        verdict = clf.predict(query)

        # KNN k=6 交替取 3 washout + 3 weakness
        # posterior = (1+3)/(1+1+6) = 4/8 = 0.5 ∈ [0.35, 0.65] → UNKNOWN
        assert verdict.label == WashoutLabel.UNKNOWN, (
            f"中等置信度应为 UNKNOWN, got {verdict.label} conf={verdict.confidence} "
            f"reason={verdict.reason}"
        )


# ============================================================
# T8: 贝叶斯先验/后验更新正确
# ============================================================
class TestClassifierBayesianUpdate:
    """T8: 贝叶斯先验/后验更新正确 (Beta-Bernoulli)."""

    def test_washout_classifier_bayesian_update_prior_posterior(self):
        updater = BayesianUpdater(prior_alpha=1.0, prior_beta=1.0)

        # 先验 P(washout) = alpha / (alpha + beta) = 0.5
        prior = updater.prior_mean()
        assert prior == pytest.approx(0.5)

        # 4 washout + 1 weakness → posterior = (1+4)/(1+1+5) = 5/7 ≈ 0.714 > prior
        posterior_1 = updater.update(washout_count=4, weakness_count=1)
        assert posterior_1 > prior
        assert posterior_1 == pytest.approx(5.0 / 7.0, abs=0.01)

        # 1 washout + 4 weakness → posterior = (1+1)/(1+1+5) = 2/7 ≈ 0.286 < prior
        posterior_2 = updater.update(washout_count=1, weakness_count=4)
        assert posterior_2 < prior
        assert posterior_2 == pytest.approx(2.0 / 7.0, abs=0.01)

        # 0 washout + 0 weakness → posterior = prior (无更新)
        posterior_0 = updater.update(washout_count=0, weakness_count=0)
        assert posterior_0 == pytest.approx(prior)


# ============================================================
# T9: 闭环后案例入库
# ============================================================
class TestClassifierRecordCase:
    """T9: record_case 后案例库长度增加."""

    def test_washout_classifier_record_case_updates_library(self):
        lib = WashoutCaseLibrary()
        clf = WashoutClassifier(case_library=lib)
        assert len(lib) == 0

        case = _make_case("r1", _WASHOUT_FEATURES, "washout", pnl_pct=0.05)
        clf.record_case(case)
        assert len(lib) == 1
        assert lib.get("r1") is not None


# ============================================================
# T10: 复用 _sandbox_validate 沙箱验证
# ============================================================
class TestClassifierEvolveSandboxValidate:
    """T10: WashoutClassifier.evolve() 复用 _sandbox_validate."""

    def test_washout_classifier_evolve_sandbox_validate(self):
        # mock sandbox_validate_fn 返回 True
        def mock_validate(proposal: Dict) -> bool:
            return True

        lib = _build_washout_library(n_washout=5, n_weakness=5)
        clf = WashoutClassifier(
            case_library=lib,
            sandbox_validate_fn=mock_validate,
        )
        proposal = {
            "scenario_id": "washout_test",
            "new_pattern": "knn_bayesian_v2",
            "nodes": ["C1", "C2", "C3"],
            "score": 0.85,
        }
        result = clf.evolve(proposal=proposal)
        assert isinstance(result, dict)
        assert result.get("accepted") is True

    def test_washout_classifier_evolve_sandbox_reject(self):
        """sandbox_validate 返回 False → accepted=False."""
        def mock_validate(proposal: Dict) -> bool:
            return False

        lib = _build_washout_library(n_washout=5, n_weakness=5)
        clf = WashoutClassifier(
            case_library=lib,
            sandbox_validate_fn=mock_validate,
        )
        result = clf.evolve(proposal={"score": 0.3})
        assert result.get("accepted") is False


# ============================================================
# T11: reward = tanh(pnl/0.02) 归一化
# ============================================================
class TestClassifierRewardTanh:
    """T11: reward = tanh(pnl_pct / 0.02) 归一化到 [-1, 1]."""

    def test_washout_classifier_reward_tanh_normalization(self):
        # pnl=0.02 → tanh(1) ≈ 0.7616
        r1 = BayesianUpdater.compute_reward(0.02)
        assert r1 == pytest.approx(math.tanh(1.0), abs=0.01)
        assert 0.7 < r1 < 0.8

        # pnl=-0.02 → tanh(-1) ≈ -0.7616
        r2 = BayesianUpdater.compute_reward(-0.02)
        assert r2 == pytest.approx(-math.tanh(1.0), abs=0.01)
        assert -0.8 < r2 < -0.7

        # pnl=0 → reward=0
        r0 = BayesianUpdater.compute_reward(0.0)
        assert r0 == pytest.approx(0.0, abs=0.001)

        # 大盈利 pnl=0.10 → tanh(5) ≈ 0.9999 (饱和)
        r_big = BayesianUpdater.compute_reward(0.10)
        assert r_big > 0.99

        # 大亏损 pnl=-0.10 → tanh(-5) ≈ -0.9999
        r_big_neg = BayesianUpdater.compute_reward(-0.10)
        assert r_big_neg < -0.99

        # 范围验证: reward ∈ [-1, 1]
        for pnl in [-0.20, -0.10, -0.05, -0.02, 0.0, 0.02, 0.05, 0.10, 0.20]:
            r = BayesianUpdater.compute_reward(pnl)
            assert -1.0 <= r <= 1.0, f"reward 越界 pnl={pnl} r={r}"


# ============================================================
# T12: 无 LLM 依赖 (grep 验证)
# ============================================================
class TestClassifierNoLLM:
    """T12: WashoutClassifier 全程禁用 LLM (HC-2)."""

    def test_washout_classifier_no_llm_dependency(self):
        # 检查 3 个源文件 + WashoutDetector (W4 修改) 无 LLM import/调用
        files_to_check = [
            "1-ARCHITECTURE/dreamos/evolution/washout_classifier.py",
            "1-ARCHITECTURE/dreamos/evolution/washout_case_library.py",
            "1-ARCHITECTURE/dreamos/evolution/washout_bayesian_updater.py",
        ]
        project_root = _PROJECT_ROOT
        # LLM 关键字模式 (import / from / 显式调用)
        llm_patterns = [
            "import openai",
            "from openai",
            "import anthropic",
            "from anthropic",
            "ChatCompletion",
            "chat.completions",
            "messages.create",
            "llm_client",
            "LLMClient",
            "call_llm",
            "invoke_llm",
            "claude_client",
            "gemini_client",
            "qwen_client",
        ]
        for rel_path in files_to_check:
            full_path = project_root / rel_path
            assert full_path.exists(), f"文件不存在: {rel_path}"
            content = full_path.read_text(encoding="utf-8")
            for pattern in llm_patterns:
                assert pattern not in content, (
                    f"{rel_path} 含禁用的 LLM 调用模式: '{pattern}'"
                )


# ============================================================
# T13: 与 EvolutionEngine 集成
# ============================================================
class TestClassifierEvolutionEngineIntegration:
    """T13: WashoutClassifier 与 EvolutionEngine 集成 (复用 _sandbox_validate)."""

    def test_washout_classifier_evolution_engine_integration(self):
        from dreamos.evolution.engine import EvolutionEngine

        engine = EvolutionEngine()
        lib = _build_washout_library(n_washout=5, n_weakness=5)

        # 注入 engine._sandbox_validate 作为沙箱验证函数
        clf = WashoutClassifier(
            case_library=lib,
            sandbox_validate_fn=engine._sandbox_validate,
        )
        # 验证集成点: sandbox_validate_fn 是 engine._sandbox_validate 的同一个函数
        # (bound method 每次访问创建新对象, 用 __func__ 比较底层函数)
        assert callable(clf.sandbox_validate_fn)
        assert clf.sandbox_validate_fn.__func__ is engine._sandbox_validate.__func__
        assert clf.sandbox_validate_fn.__self__ is engine

        # 调用 evolve (proposal 不完整或 backtester 无数据 → accepted=False, 但集成点已验证)
        result = clf.evolve(proposal={
            "scenario_id": "washout_integration_test",
            "new_pattern": "c_g_chain",
            "nodes": ["C1", "C2", "C3"],
            "score": 0.5,
        })
        assert isinstance(result, dict)
        assert "accepted" in result
        # 集成点验证: evolve 成功调用了 engine._sandbox_validate (未抛异常)
        # 结果可能是 True 或 False (取决于 backtester 数据), 关键是不抛异常


# ============================================================
# T14: WashoutDetector 注入 classifier 后走 KNN/Bayesian
# ============================================================
class TestWashoutDetectorWithClassifier:
    """T14: WashoutDetector 注入 classifier 后走 KNN/Bayesian 路径."""

    def test_washout_detector_with_classifier_predict(self):
        # 构造一个触发门通过的 df (30d 涨幅 20% + 回撤 8%)
        # 使用 require_above_ma200=False 避免需要 200+ 数据点
        import pandas as pd
        import numpy as np
        from scripts.memory_l4.bcrm2.washout_trigger_gate import WashoutTriggerGate

        # 触发门逻辑: start_price=close[-31], peak=max(high[-30:]), runup=peak/start-1
        # 设计: 前 30 天 close=100, 后 30 天从 100 涨到 120 再跌到 110.4
        n = 60
        dates = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
        # 前 30 天平 100, 后 5 天涨到 120, 再 25 天跌到 110.4
        closes = [100.0] * 30 + list(np.linspace(100, 120, 5)) + list(np.linspace(120, 110.4, 25))
        df = pd.DataFrame({
            "open": closes,
            "high": [c * 1.005 for c in closes],
            "low": [c * 0.995 for c in closes],
            "close": closes,
            "volume": [1000.0] * n,
        }, index=dates)

        # 构造 classifier (30 washout 案例)
        lib = _build_washout_library(n_washout=30, n_weakness=2)
        clf = WashoutClassifier(case_library=lib, k_neighbors=5, min_cases=30)

        # mock feature_extractor 返回 washout 特征
        class _MockExtractor:
            def extract_all(self, df, macro_data):
                return dict(_WASHOUT_FEATURES)

        # 注入 require_above_ma200=False 的触发门 (避免需要 200+ 数据点)
        gate = WashoutTriggerGate(require_above_ma200=False)
        detector = WashoutDetector(
            enable=True,
            trigger_gate=gate,
            classifier=clf,
            feature_extractor=_MockExtractor(),
        )
        verdict = detector.run("BTC", df, {"oi_series": [100, 110]})

        # classifier 注入后, run() 应走 KNN/Bayesian 路径, 不是 w1_trigger_passed_classifier_pending
        assert verdict.label == WashoutLabel.WASHOUT, (
            f"注入 classifier 后应走 KNN/Bayesian 返回 WASHOUT, got {verdict.label} "
            f"reason={verdict.reason}"
        )
        assert verdict.confidence > 0.65
        # reason 不应是 w1_trigger_passed_classifier_pending
        assert "w1_trigger_passed" not in verdict.reason, (
            f"classifier 已注入, 不应返回 w1_trigger_passed, got '{verdict.reason}'"
        )
        # feature_snapshot 应含 washout 特征 (来自 mock extractor)
        assert "volume_ratio_20d" in verdict.feature_snapshot

    def test_washout_detector_without_classifier_still_w1_path(self):
        """零回归验证: classifier=None 时仍走 W1 路径 (字节等价)."""
        import pandas as pd
        import numpy as np
        from scripts.memory_l4.bcrm2.washout_trigger_gate import WashoutTriggerGate

        n = 60
        dates = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
        closes = [100.0] * 30 + list(np.linspace(100, 120, 5)) + list(np.linspace(120, 110.4, 25))
        df = pd.DataFrame({
            "open": closes,
            "high": [c * 1.005 for c in closes],
            "low": [c * 0.995 for c in closes],
            "close": closes,
            "volume": [1000.0] * n,
        }, index=dates)

        # require_above_ma200=False 让触发门通过
        gate = WashoutTriggerGate(require_above_ma200=False)
        detector = WashoutDetector(enable=True, trigger_gate=gate, classifier=None)
        verdict = detector.run("BTC", df, {})
        # 零回归: classifier=None → W1 路径不变
        assert verdict.label == WashoutLabel.UNKNOWN
        assert verdict.reason == "w1_trigger_passed_classifier_pending"


# ============================================================
# FAIL-OPEN 验证 (额外, 非 spec 必需但遵循铁律)
# ============================================================
class TestClassifierFailOpen:
    """FAIL-OPEN: 异常 → unknown() 不阻塞."""

    def test_classifier_predict_on_empty_features_fail_open(self):
        """features 为空 dict → 异常或降级 → 不抛错."""
        lib = _build_washout_library(n_washout=30, n_weakness=5)
        clf = WashoutClassifier(case_library=lib, k_neighbors=5, min_cases=30)
        # 空 features: KNN 距离全 0, 贝叶斯仍可计算, 应返回 verdict 不抛错
        verdict = clf.predict({})
        assert isinstance(verdict, WashoutVerdict)

    def test_classifier_predict_on_exception_fail_open(self):
        """case_library 异常 → unknown() 不抛错."""
        class _BrokenLib:
            def __len__(self):
                return 50  # >= min_cases
            def knn_search(self, *a, **kw):
                raise RuntimeError("broken library")

        clf = WashoutClassifier(case_library=_BrokenLib(), min_cases=30)
        verdict = clf.predict({"x": 1.0})
        assert verdict.label == WashoutLabel.UNKNOWN
        assert verdict.confidence == 0.0
