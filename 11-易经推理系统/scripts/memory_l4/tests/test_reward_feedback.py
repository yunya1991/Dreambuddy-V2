"""阶段2 RED 测试 — reward 回流闭环 + 阈值退火.

Spec: .trae/documents/strengthen-evolution-exploration.md 阶段2

核心改动:
  - BayesianUpdater 新增 update_with_reward(washout_count, weakness_count, avg_reward)
  - WashoutClassifier.predict() 传入邻居 avg_reward
  - ExplorationPolicy 新增 get_washout_threshold / get_weakness_threshold
  - 阈值退火: 冷启动时 UNKNOWN 区间收窄, 鼓励做出判定 → 触发 probe 仓 → 积累案例

设计原则 (硬约束):
  - 代码驱动, 纯数学计算, 无 LLM 依赖 (HC-2)
  - FAIL-OPEN: 异常 → 返回先验均值 / 硬编码阈值, 不抛错
  - 模块化开关: ENABLE_EVOLUTION_EXPLORATION 默认 False, 关断时字节等价
  - reward = tanh(pnl_pct/0.02) 归一化 [-1,1] (硬约束, 不改公式)

reward 加权公式:
  effective_k = k * (1 + avg_reward) / 2    — 正 reward 放大 washout 证据
  effective_m = m * (1 - avg_reward) / 2  — 负 reward 放大 weakness 证据
  posterior = (alpha + effective_k) / (alpha + beta + effective_k + effective_m)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ============================================================
# sys.path 设置: 复用 test_washout_w4.py 模式
# ============================================================
_THIS_DIR = Path(__file__).resolve().parent
_BCRM2_SCRIPTS_ROOT = _THIS_DIR.parent.parent
_PROJECT_ROOT = _BCRM2_SCRIPTS_ROOT.parent.parent
_ARCH_ROOT = _PROJECT_ROOT / "1-ARCHITECTURE"

for _p in (_BCRM2_SCRIPTS_ROOT, _ARCH_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from dreamos.evolution.washout_bayesian_updater import BayesianUpdater
from dreamos.evolution.washout_case_library import WashoutCase, WashoutCaseLibrary
from dreamos.evolution.washout_classifier import WashoutClassifier
from dreamos.evolution.exploration_policy import ExplorationPolicy


# ============================================================
# BayesianUpdater.update_with_reward 测试
# ============================================================
class TestBayesianUpdateWithReward:
    """BayesianUpdater.update_with_reward 方法测试.

    公式:
      effective_k = k * (1 + avg_reward) / 2
      effective_m = m * (1 - avg_reward) / 2
      posterior = (alpha + effective_k) / (alpha + beta + effective_k + effective_m)
    """

    @pytest.fixture(autouse=True)
    def _enable_exploration(self, monkeypatch):
        monkeypatch.setenv("ENABLE_EVOLUTION_EXPLORATION", "1")

    def test_method_exists(self):
        """update_with_reward 方法存在."""
        updater = BayesianUpdater()
        assert hasattr(updater, "update_with_reward")
        assert callable(updater.update_with_reward)

    def test_positive_reward_increases_posterior(self):
        """正 reward → effective_k 增大, posterior 高于无 reward."""
        updater = BayesianUpdater(prior_alpha=1.0, prior_beta=1.0)
        # k=3, m=2, reward=0.8
        # effective_k = 3 * (1+0.8)/2 = 2.7
        # effective_m = 2 * (1-0.8)/2 = 0.2
        # posterior = (1+2.7)/(2+2.7+0.2) = 3.7/4.9 ≈ 0.7551
        posterior = updater.update_with_reward(
            washout_count=3, weakness_count=2, avg_reward=0.8
        )
        no_reward = updater.update(washout_count=3, weakness_count=2)  # 0.6667
        assert posterior > no_reward
        assert abs(posterior - 3.7 / 4.9) < 0.001

    def test_negative_reward_decreases_posterior(self):
        """负 reward → effective_m 增大, posterior 低于无 reward."""
        updater = BayesianUpdater(prior_alpha=1.0, prior_beta=1.0)
        # k=3, m=2, reward=-0.8
        # effective_k = 3 * (1-0.8)/2 = 0.3
        # effective_m = 2 * (1+0.8)/2 = 1.8
        # posterior = (1+0.3)/(2+0.3+1.8) = 1.3/4.1 ≈ 0.3171
        posterior = updater.update_with_reward(
            washout_count=3, weakness_count=2, avg_reward=-0.8
        )
        no_reward = updater.update(washout_count=3, weakness_count=2)  # 0.6667
        assert posterior < no_reward
        assert abs(posterior - 1.3 / 4.1) < 0.001

    def test_zero_reward_shrinks_evidence(self):
        """reward=0 → effective_k=k/2, effective_m=m/2, posterior 介于先验和无reward之间."""
        updater = BayesianUpdater(prior_alpha=1.0, prior_beta=1.0)
        # k=3, m=2, reward=0.0
        # effective_k = 3 * 0.5 = 1.5
        # effective_m = 2 * 0.5 = 1.0
        # posterior = (1+1.5)/(2+1.5+1.0) = 2.5/4.5 ≈ 0.5556
        posterior = updater.update_with_reward(
            washout_count=3, weakness_count=2, avg_reward=0.0
        )
        prior = updater.prior_mean()       # 0.5
        no_reward = updater.update(3, 2)  # 0.6667
        assert prior < posterior < no_reward
        assert abs(posterior - 2.5 / 4.5) < 0.001

    def test_full_positive_reward_ignores_weakness(self):
        """reward=1.0 → effective_m=0, posterior 最大化 (受先验约束)."""
        updater = BayesianUpdater(prior_alpha=1.0, prior_beta=1.0)
        # k=3, m=2, reward=1.0
        # effective_k = 3, effective_m = 0
        # posterior = (1+3)/(1+1+3+0) = 4/5 = 0.8
        posterior = updater.update_with_reward(
            washout_count=3, weakness_count=2, avg_reward=1.0
        )
        assert abs(posterior - 4.0 / 5.0) < 0.001

    def test_full_negative_reward_ignores_washout(self):
        """reward=-1.0 → effective_k=0, posterior 最小化 (受先验约束)."""
        updater = BayesianUpdater(prior_alpha=1.0, prior_beta=1.0)
        # k=3, m=2, reward=-1.0
        # effective_k = 0, effective_m = 2
        # posterior = (1+0)/(1+1+0+2) = 1/4 = 0.25
        posterior = updater.update_with_reward(
            washout_count=3, weakness_count=2, avg_reward=-1.0
        )
        assert abs(posterior - 1.0 / 4.0) < 0.001

    def test_fail_open_on_invalid_reward(self):
        """avg_reward 非 float → 返回先验均值 (FAIL-OPEN)."""
        updater = BayesianUpdater(prior_alpha=1.0, prior_beta=1.0)
        prior = updater.prior_mean()
        result = updater.update_with_reward(
            washout_count=3,
            weakness_count=2,
            avg_reward="not_a_number",  # type: ignore[arg-type]
        )
        assert abs(result - prior) < 0.001

    def test_fail_open_on_none_reward(self):
        """avg_reward=None → 返回先验均值 (FAIL-OPEN)."""
        updater = BayesianUpdater(prior_alpha=2.0, prior_beta=3.0)
        prior = updater.prior_mean()  # 2/5 = 0.4
        result = updater.update_with_reward(
            washout_count=3,
            weakness_count=2,
            avg_reward=None,  # type: ignore[arg-type]
        )
        assert abs(result - prior) < 0.001


# ============================================================
# WashoutClassifier 集成 reward 加权测试
# ============================================================
class TestKnnRewardWeighting:
    """WashoutClassifier.predict 传入邻居 reward 信号测试."""

    @staticmethod
    def _build_library(n_washout: int, n_weakness: int, reward: float) -> WashoutCaseLibrary:
        """构造案例库, 所有案例特征相同 (距离=0), 按入库顺序排列."""
        lib = WashoutCaseLibrary()
        features = {"F1": 1.0, "F2": 2.0, "F3": 3.0}
        for i in range(n_washout):
            lib.add(WashoutCase(
                case_id=f"w_{i}",
                coin="BTC",
                entry_time="2026-01-01T00:00:00Z",
                exit_time="2026-01-01T01:00:00Z",
                features_snapshot=features,
                actual_label="washout",
                pnl_pct=0.05 * (1 if reward > 0 else -1),
                reward=reward,
                timestamp="2026-01-01T00:00:00Z",
            ))
        for i in range(n_weakness):
            lib.add(WashoutCase(
                case_id=f"s_{i}",
                coin="BTC",
                entry_time="2026-01-01T00:00:00Z",
                exit_time="2026-01-01T01:00:00Z",
                features_snapshot=features,
                actual_label="weakness",
                pnl_pct=0.05 * (1 if reward > 0 else -1),
                reward=reward,
                timestamp="2026-01-01T00:00:00Z",
            ))
        return lib

    def test_reward_weighting_activated_when_enabled(self, monkeypatch):
        """开关开启 + 邻居 reward=1.0 → effective_m=0, posterior 高于无reward → WASHOUT."""
        monkeypatch.setenv("ENABLE_EVOLUTION_EXPLORATION", "1")
        # 35 案例: 3 washout + 32 weakness, KNN k=5 返回前5个 (3w+2s)
        # 所有 reward=1.0 → avg_reward=1.0
        # effective_k=3*1=3, effective_m=2*0=0 → posterior=(1+3)/(2+3)=4/5=0.8
        lib = self._build_library(n_washout=3, n_weakness=32, reward=1.0)
        clf = WashoutClassifier(
            case_library=lib,
            k_neighbors=5,
            min_cases=30,
        )
        verdict = clf.predict(features={"F1": 1.0, "F2": 2.0, "F3": 3.0})
        # posterior=0.8 > 0.62 (成熟期 washout 阈值) → WASHOUT
        # 开关关断时 posterior=4/7≈0.571 → UNKNOWN, 所以 WASHOUT 证明 reward 加权生效
        assert verdict.label.value == "washout"
        assert verdict.confidence > 0.75

    def test_no_reward_weighting_when_disabled(self, monkeypatch):
        """开关关断 → 走原始 update(), 不做 reward 加权."""
        monkeypatch.delenv("ENABLE_EVOLUTION_EXPLORATION", raising=False)
        # 同样的案例库, 但开关关断 → posterior=4/7≈0.571
        # 0.571 在 [0.35, 0.65] → UNKNOWN
        lib = self._build_library(n_washout=3, n_weakness=32, reward=1.0)
        clf = WashoutClassifier(
            case_library=lib,
            k_neighbors=5,
            min_cases=30,
        )
        verdict = clf.predict(features={"F1": 1.0, "F2": 2.0, "F3": 3.0})
        # 开关关断: posterior=4/7≈0.571 → UNKNOWN (在 [0.35, 0.65] 区间)
        assert verdict.label.value == "unknown"

    def test_negative_reward_flips_to_weakness(self, monkeypatch):
        """开关开启 + 邻居 reward=-1.0 → effective_k=0, posterior 趋向 0 → WEAKNESS."""
        monkeypatch.setenv("ENABLE_EVOLUTION_EXPLORATION", "1")
        # 35 案例: 3 washout + 32 weakness, KNN k=5 返回前5个 (3w+2s)
        # 所有 reward=-1.0 → avg_reward=-1.0
        # effective_k=0, effective_m=2 → posterior=1/3≈0.333
        lib = self._build_library(n_washout=3, n_weakness=32, reward=-1.0)
        clf = WashoutClassifier(
            case_library=lib,
            k_neighbors=5,
            min_cases=30,
        )
        verdict = clf.predict(features={"F1": 1.0, "F2": 2.0, "F3": 3.0})
        # posterior ≈ 0.333 < 0.35 (或退火后阈值) → WEAKNESS
        assert verdict.label.value == "weakness"


# ============================================================
# ExplorationPolicy 阈值退火测试
# ============================================================
class TestThresholdAnnealing:
    """阈值随案例数动态调整测试.

    冷启动时 UNKNOWN 区间收窄, 鼓励做出判定 → 触发 probe 仓 → 积累案例.
    """

    @pytest.fixture(autouse=True)
    def _enable_exploration(self, monkeypatch):
        monkeypatch.setenv("ENABLE_EVOLUTION_EXPLORATION", "1")

    def test_get_washout_threshold_method_exists(self):
        """get_washout_threshold 方法存在."""
        policy = ExplorationPolicy()
        assert hasattr(policy, "get_washout_threshold")
        assert callable(policy.get_washout_threshold)

    def test_get_weakness_threshold_method_exists(self):
        """get_weakness_threshold 方法存在."""
        policy = ExplorationPolicy()
        assert hasattr(policy, "get_weakness_threshold")
        assert callable(policy.get_weakness_threshold)

    def test_cold_start_washout_threshold_lower(self):
        """冷启动 (<10): washout_threshold=0.55 (比稳定 0.65 更宽松)."""
        policy = ExplorationPolicy()
        threshold = policy.get_washout_threshold(case_count=5)
        assert threshold == 0.55
        assert threshold < 0.65  # 比稳定期更宽松

    def test_cold_start_weakness_threshold_higher(self):
        """冷启动 (<10): weakness_threshold=0.45 (比稳定 0.35 更宽松)."""
        policy = ExplorationPolicy()
        threshold = policy.get_weakness_threshold(case_count=5)
        assert threshold == 0.45
        assert threshold > 0.35  # 比稳定期更宽松

    def test_stable_washout_threshold_default(self):
        """稳定 (≥100): washout_threshold=0.65 (硬约束值)."""
        policy = ExplorationPolicy()
        assert policy.get_washout_threshold(case_count=150) == 0.65

    def test_stable_weakness_threshold_default(self):
        """稳定 (≥100): weakness_threshold=0.35 (硬约束值)."""
        policy = ExplorationPolicy()
        assert policy.get_weakness_threshold(case_count=150) == 0.35

    def test_cold_start_unknown_zone_narrower(self):
        """冷启动 UNKNOWN 区间 [0.45, 0.55] 宽度=0.10 < 稳定 [0.35, 0.65] 宽度=0.30."""
        policy = ExplorationPolicy()
        cold_w = policy.get_washout_threshold(case_count=5)
        cold_s = policy.get_weakness_threshold(case_count=5)
        cold_zone = cold_w - cold_s  # 0.10

        stable_w = policy.get_washout_threshold(case_count=150)
        stable_s = policy.get_weakness_threshold(case_count=150)
        stable_zone = stable_w - stable_s  # 0.30

        assert cold_zone < stable_zone


# ============================================================
# 开关关断字节等价测试
# ============================================================
class TestSwitchOffByteEquivalence:
    """开关关断时 update_with_reward 行为等同 update (字节等价)."""

    def test_update_with_reward_equals_update_when_disabled(self, monkeypatch):
        """开关关断 → update_with_reward(reward=X) == update() (忽略 reward)."""
        monkeypatch.delenv("ENABLE_EVOLUTION_EXPLORATION", raising=False)
        updater = BayesianUpdater(prior_alpha=1.0, prior_beta=1.0)
        # 开关关断: update_with_reward 应等同 update
        result_with_reward = updater.update_with_reward(
            washout_count=3, weakness_count=2, avg_reward=0.9
        )
        result_no_reward = updater.update(washout_count=3, weakness_count=2)
        assert abs(result_with_reward - result_no_reward) < 1e-9

    def test_threshold_returns_hardcoded_when_disabled(self, monkeypatch):
        """开关关断 → washout/weakness 阈值返回硬编码 0.65/0.35."""
        monkeypatch.delenv("ENABLE_EVOLUTION_EXPLORATION", raising=False)
        policy = ExplorationPolicy()
        assert policy.get_washout_threshold(case_count=5) == 0.65
        assert policy.get_weakness_threshold(case_count=5) == 0.35

    def test_predict_uses_original_update_when_disabled(self, monkeypatch):
        """开关关断 → predict 走原始 update() 路径, 不调用 update_with_reward."""
        monkeypatch.delenv("ENABLE_EVOLUTION_EXPLORATION", raising=False)
        # 35 案例: 3 washout + 32 weakness, reward=1.0
        # 开关关断 → posterior=4/7≈0.571 → UNKNOWN
        lib = TestKnnRewardWeighting._build_library(
            n_washout=3, n_weakness=32, reward=1.0
        )
        clf = WashoutClassifier(
            case_library=lib,
            k_neighbors=5,
            min_cases=30,
        )
        verdict = clf.predict(features={"F1": 1.0, "F2": 2.0, "F3": 3.0})
        # 原始 update: posterior=4/7≈0.571 → UNKNOWN
        assert verdict.label.value == "unknown"
