"""test_gene_tiered_storage.py — 基因分级存储单元测试（D1: ds4 非对称量化借鉴）

SPEC: SPEC-ds4架构借鉴与系统增强.md §3.2 Dimension 1
硬约束: HC-DS4-02（分级失败→降级全量加载）、HC-DS4-10（L0 核心基因完整精度）

分级规则:
  L0 核心 (core):      ess >= 0.7 且 n_samples >= 100（充分验证）
  L1 候选 (candidate): ess >= 0.5 或 n_samples >= 30（部分验证）
  L2 淘汰 (retired):   ess < 0.5 且 n_samples < 30（验证不足）

覆盖:
  - classify 分级正确性
  - load_tiered 返回完整 library + tier_info
  - FAIL-OPEN: 分级失败降级全量
  - L0 核心基因完整精度（HC-DS4-10）
  - 对外接口兼容性（load_gene_library 结构不变）
"""
from __future__ import annotations

import pytest

from dreambuddy_evolution.core.gene_tiered_storage import GeneTieredStorage


# ==============================================================================
# 1. classify 分级正确性
# ==============================================================================
class TestGeneTieredClassify:
    """D1: 基因分级逻辑验证"""

    def test_l0_core_high_ess_high_samples(self):
        """ess >= 0.7 且 n_samples >= 100 → L0 核心"""
        combo = {"combo_id": "CB-001", "ess": 0.85, "n_samples": 200}
        assert GeneTieredStorage.classify(combo) == GeneTieredStorage.TIER_CORE

    def test_l1_candidate_medium_ess(self):
        """ess >= 0.5 但 n_samples < 30 → L1 候选"""
        combo = {"combo_id": "CB-002", "ess": 0.6, "n_samples": 10}
        assert GeneTieredStorage.classify(combo) == GeneTieredStorage.TIER_CANDIDATE

    def test_l1_candidate_high_samples(self):
        """n_samples >= 30 但 ess < 0.5 → L1 候选"""
        combo = {"combo_id": "CB-003", "ess": 0.4, "n_samples": 50}
        assert GeneTieredStorage.classify(combo) == GeneTieredStorage.TIER_CANDIDATE

    def test_l2_retired_low_ess_low_samples(self):
        """ess < 0.5 且 n_samples < 30 → L2 淘汰"""
        combo = {"combo_id": "CB-004", "ess": 0.3, "n_samples": 10}
        assert GeneTieredStorage.classify(combo) == GeneTieredStorage.TIER_RETIRED

    def test_l0_boundary_ess_07_samples_100(self):
        """边界: ess=0.7 且 n_samples=100 → L0"""
        combo = {"combo_id": "CB-005", "ess": 0.7, "n_samples": 100}
        assert GeneTieredStorage.classify(combo) == GeneTieredStorage.TIER_CORE

    def test_l1_boundary_ess_05(self):
        """边界: ess=0.5 → L1（候选）"""
        combo = {"combo_id": "CB-006", "ess": 0.5, "n_samples": 10}
        assert GeneTieredStorage.classify(combo) == GeneTieredStorage.TIER_CANDIDATE

    def test_missing_fields_default_l2(self):
        """缺少 ess/n_samples → L2（保守分级）"""
        combo = {"combo_id": "CB-007"}
        assert GeneTieredStorage.classify(combo) == GeneTieredStorage.TIER_RETIRED

    def test_ess_from_meta_fallback(self):
        """ess 不在顶层但在 meta 中 → 从 meta 读取"""
        combo = {"combo_id": "CB-008", "meta": {"H": 0.8, "S": 0.8, "N": 200}}
        tier = GeneTieredStorage.classify(combo)
        # H=0.8, S=0.8, N=200 → ess ≈ 0.4*0.8 + 0.4*0.8 + 0.2*sqrt(200/500) ≈ 0.64 + 0.126 = 0.766
        assert tier in (GeneTieredStorage.TIER_CORE, GeneTieredStorage.TIER_CANDIDATE)


# ==============================================================================
# 2. load_tiered 分级加载
# ==============================================================================
class TestGeneTieredLoad:
    """D1: 分级加载验证"""

    def test_load_tiered_returns_tier_info(self):
        """load_tiered 返回 tier_info 分级信息"""
        combos = [
            {"combo_id": "CB-001", "ess": 0.85, "n_samples": 200,
             "condition_ids": ["CD-1"], "action_ids": ["AC-1"]},
            {"combo_id": "CB-002", "ess": 0.3, "n_samples": 10,
             "condition_ids": ["CD-2"], "action_ids": ["AC-2"]},
        ]
        library = {"combinations": combos}
        result = GeneTieredStorage.load_tiered(library)

        assert "tier_info" in result
        tier_info = result["tier_info"]
        assert "core" in tier_info
        assert "candidate" in tier_info
        assert "retired" in tier_info
        assert "CB-001" in tier_info["core"]
        assert "CB-002" in tier_info["retired"]

    def test_load_tiered_preserves_complete_data(self):
        """分级加载后，所有组合的完整数据仍在 combinations 中（对外接口不变）"""
        combos = [
            {"combo_id": "CB-001", "ess": 0.85, "n_samples": 200,
             "condition_ids": ["CD-1"], "action_ids": ["AC-1"],
             "parameters": {"risk": 0.5}},
            {"combo_id": "CB-002", "ess": 0.3, "n_samples": 10,
             "condition_ids": ["CD-2"], "action_ids": ["AC-2"],
             "parameters": {"risk": 0.3}},
        ]
        library = {"combinations": combos}
        result = GeneTieredStorage.load_tiered(library)

        # 所有组合完整保留（对外接口不变）
        assert len(result["combinations"]) == 2
        assert result["combinations"][0]["combo_id"] == "CB-001"
        assert result["combinations"][0]["parameters"]["risk"] == 0.5

    def test_load_tiered_l0_full_precision(self):
        """HC-DS4-10: L0 核心基因保持完整精度，不得有损压缩"""
        combo = {
            "combo_id": "CB-001", "ess": 0.85123456789, "n_samples": 200,
            "parameters": {"risk_multiplier": 0.7, "timeframe": "1d"},
            "meta": {"strategy_type": "breakout", "H": 0.82, "S": 0.82},
        }
        library = {"combinations": [combo]}
        result = GeneTieredStorage.load_tiered(library)

        l0_combo = result["combinations"][0]
        # ess 精度完整保留
        assert l0_combo["ess"] == pytest.approx(0.85123456789)
        # parameters 完整保留
        assert l0_combo["parameters"]["risk_multiplier"] == 0.7
        assert l0_combo["parameters"]["timeframe"] == "1d"
        # meta 完整保留
        assert l0_combo["meta"]["strategy_type"] == "breakout"

    def test_load_tiered_fail_open_on_error(self, monkeypatch):
        """HC-DS4-02: 分级失败 → 降级为全量加载（返回原 library）"""
        # 模拟 classify 抛异常
        def broken_classify(combo):
            raise RuntimeError("simulated failure")

        monkeypatch.setattr(GeneTieredStorage, "classify", staticmethod(broken_classify))

        combos = [{"combo_id": "CB-001", "ess": 0.85, "n_samples": 200}]
        library = {"combinations": combos}
        result = GeneTieredStorage.load_tiered(library)

        # FAIL-OPEN: 返回原 library 结构
        assert "combinations" in result
        assert len(result["combinations"]) == 1
        assert result["combinations"][0]["combo_id"] == "CB-001"


# ==============================================================================
# 3. 内存优化验证
# ==============================================================================
class TestGeneTieredMemoryOptimization:
    """D1: 分级存储的内存优化效果"""

    def test_l1_candidate_stripped_metadata(self):
        """L1 候选基因在 tier_info 中只存元数据（不存完整 parameters）"""
        combo = {
            "combo_id": "CB-002", "ess": 0.6, "n_samples": 10,
            "condition_ids": ["CD-2"], "action_ids": ["AC-2"],
            "parameters": {"risk_multiplier": 1.3, "timeframe": "1h"},
        }
        library = {"combinations": [combo]}
        result = GeneTieredStorage.load_tiered(library)

        tier_info = result["tier_info"]
        candidate = tier_info["candidate"]["CB-002"]
        # L1 只存元数据：combo_id, ess, n_samples, action_ids
        assert candidate["combo_id"] == "CB-002"
        assert "ess" in candidate
        assert "n_samples" in candidate
        assert "parameters" not in candidate  # L1 不存完整 parameters

    def test_l2_retired_only_id_and_score(self):
        """L2 淘汰基因只存 gene_id + 最终评分"""
        combo = {"combo_id": "CB-003", "ess": 0.3, "n_samples": 10}
        library = {"combinations": [combo]}
        result = GeneTieredStorage.load_tiered(library)

        tier_info = result["tier_info"]
        retired = tier_info["retired"]["CB-003"]
        assert retired["combo_id"] == "CB-003"
        assert "ess" in retired
        # L2 不存 condition_ids/action_ids/parameters
        assert "condition_ids" not in retired
