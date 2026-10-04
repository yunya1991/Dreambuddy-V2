# -*- coding: utf-8 -*-
"""u_open 与 cbr_sim 耦合约束 TDD 测试 — experiment() 部分（Spec 缺陷E+F，P2）

问题背景（RIVER 案例，2026-09-28 Spec 缺陷E+F）：
  RIVER u_open=1.0（高开仓意愿）vs cbr_sim=0.3738（低相似度）矛盾。
  高 u_open + 低 cbr_sim 表示"基因组强烈想开但历史相似度不足"，
  缺少耦合约束导致低质量开仓。

修复目标：
  1. experiment() 对齐检查后增加耦合约束（为未来 u_open>0.5 预留）：
     u_open > 0.5 且 cbr_sim < 0.4 → u_open = 0.1, action = "WAIT"
  2. FAIL-OPEN：检查异常不阻断

注：_evolution_build_position 的 u_open/cbr_sim 耦合测试位于
    11-易经推理系统/scripts/memory_l4/tests/test_evolution_u_open_cbr_coupling.py
    （polling_trader 导入需要 --import-mode=importlib 环境）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# dreambuddy_evolution 路径
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


# ============================================================================
# 缺陷E+F.2: TightCouplingOrchestrator.experiment 耦合约束（未来扩展预留）
# ============================================================================

class TestExperimentUOpenCbrCoupling:
    """experiment() u_open/cbr_sim 耦合约束测试（为未来 u_open>0.5 预留）.

    当前 experiment() 的 u_open 只会是 0.1 或 0.0，不会 > 0.5。
    耦合约束 `u_open > 0.5 and cbr_sim < 0.4` 在当前不会触发，
    但为未来扩展（u_open 可能 > 0.5）预留防线。
    """

    @pytest.fixture
    def orchestrator(self):
        """构造 TightCouplingOrchestrator 实例."""
        from dreambuddy_evolution.engines.tight_coupling_orchestrator import TightCouplingOrchestrator
        return TightCouplingOrchestrator(mode="Phase2")

    def test_aligned_low_cbr_still_open_small(self, orchestrator):
        """aligned=True + cbr_sim=0.37 + 当前 u_open=0.1 → 不触发耦合约束，正常开仓.

        场景: 当前 u_open 只会是 0.1（< 0.5），耦合约束不触发
        """
        # R_up=0.1 最低（< R_smooth*R_refl=0.25）→ d_star="long"，ess_dir="long" → aligned=True
        r_vector = {"R_up": 0.1, "R_down": 0.7, "R_smooth": 0.5,
                    "R_flow": 0.5, "R_reflexivity": 0.5}
        hyp = {"inference_formed": True, "ess_dir": "long"}
        result = orchestrator.experiment(
            r_vector=r_vector, hyp=hyp, symbol="BTC",
            ess_id="test", cbr_sim=0.37, cluster_id="c1",
        )
        # u_open=0.1 < 0.5，耦合约束不触发，正常开仓
        assert result["action"] == "long"
        assert result["u_open"] == 0.1

    def test_aligned_high_cbr_normal_open(self, orchestrator):
        """aligned=True + cbr_sim=0.6 → 正常开仓 u_open=0.1."""
        r_vector = {"R_up": 0.1, "R_down": 0.7, "R_smooth": 0.5,
                    "R_flow": 0.5, "R_reflexivity": 0.5}
        hyp = {"inference_formed": True, "ess_dir": "long"}
        result = orchestrator.experiment(
            r_vector=r_vector, hyp=hyp, symbol="BTC",
            ess_id="test", cbr_sim=0.6, cluster_id="c1",
        )
        assert result["action"] == "long"
        assert result["u_open"] == 0.1

    def test_not_aligned_does_not_open(self, orchestrator):
        """aligned=False → u_open=0.0, action=WAIT（与 cbr_sim 无关）."""
        # R_up=0.1 最低 → d_star="long"，但 ess_dir="short" → aligned=False
        r_vector = {"R_up": 0.1, "R_down": 0.7, "R_smooth": 0.5,
                    "R_flow": 0.5, "R_reflexivity": 0.5}
        hyp = {"inference_formed": True, "ess_dir": "short"}  # 方向不一致
        result = orchestrator.experiment(
            r_vector=r_vector, hyp=hyp, symbol="BTC",
            ess_id="test", cbr_sim=0.6, cluster_id="c1",
        )
        assert result["action"] == "WAIT"
        assert result["u_open"] == 0.0
