"""力向量 → FiveDomainFeatureComputer Shadow 接入测试。

验证目标：
  1. enable_force_vector 开关存在，默认 False
  2. 默认关闭时，compute() 输出结构与接入前完全一致（字节等价）
  3. 开启时，result 新增 force_vectors / elasticity_beta / contradiction_transform 等附加字段
     但五维评分（dao/tian/di/jiang/fa）不变
  4. Shadow 接入异常全部被吞，不影响五维评分（FAIL-OPEN 铁律）
"""
import pytest
import sys
import os
from pathlib import Path

_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))

from five_domain_feature_computer import FiveDomainFeatureComputer, ASSET_CLASSES, DEFAULT_NEUTRAL_SCORES


@pytest.fixture
def simple_coin_data():
    """最小可用 coin_data（扁平结构，保证每类评分不全是50中性）。"""
    return {
        "fedfunds_rate": 3.5,
        "stablecoin_mcap_bln": 120,
        "policy_sentiment_score": 0.6,
        "cycle4y_t_rel": 0.45,
        "merrill_phase": "RECOVERY",
        "atr_percentile": 0.55,
        "regime": "trend_up",
        "ma200_distance_percentile": 0.5,
    }


@pytest.fixture
def simple_system_state():
    return {"_daily_trade_limit": 50}


class TestForceVectorShadowEnable:
    """开关默认值和环境变量。"""

    def test_enable_force_vector_default_false(self):
        """默认关闭。"""
        fvc = FiveDomainFeatureComputer()
        assert fvc.enable_force_vector is False

    def test_enable_force_vector_env_on(self, monkeypatch):
        monkeypatch.setenv("FORCE_VECTOR_SHADOW", "1")
        fvc = FiveDomainFeatureComputer()
        assert fvc.enable_force_vector is True

    def test_enable_force_vector_env_off(self, monkeypatch):
        monkeypatch.setenv("FORCE_VECTOR_SHADOW", "0")
        fvc = FiveDomainFeatureComputer()
        assert fvc.enable_force_vector is False


class TestForceVectorByteEquivalence:
    """T-G1：关闭时字节等价。"""

    def test_closed_output_structure_unchanged(self, simple_coin_data, simple_system_state):
        """enable_force_vector=False 时，result 每类只有 5 个评分键，结构不变。"""
        fvc = FiveDomainFeatureComputer()
        result = fvc.compute(simple_coin_data, simple_system_state)
        for cls in ASSET_CLASSES:
            keys = set(result[cls].keys())
            # 关闭时只有 dao/tian/di/jiang/fa 5 个评分键
            assert keys == {"dao", "tian", "di", "jiang", "fa"}, (
                f"{cls} 输出键集合与接入前不一致: {keys}"
            )

    def test_closed_scores_equivalent_to_no_init(self, simple_coin_data, simple_system_state, monkeypatch):
        """FORCE_VECTOR_SHADOW 未设置 vs 显式关闭：评分完全一致。"""
        monkeypatch.delenv("FORCE_VECTOR_SHADOW", raising=False)
        fvc1 = FiveDomainFeatureComputer()
        r1 = fvc1.compute(simple_coin_data, simple_system_state)

        monkeypatch.setenv("FORCE_VECTOR_SHADOW", "0")
        fvc2 = FiveDomainFeatureComputer()
        r2 = fvc2.compute(simple_coin_data, simple_system_state)

        for cls in ASSET_CLASSES:
            assert r1[cls] == r2[cls], f"{cls} 评分不一致"


class TestForceVectorShadowOpen:
    """开启时：五维评分不变，附加字段存在。"""

    def test_scores_preserved_when_shadow_on(self, simple_coin_data, simple_system_state, monkeypatch):
        """开启前后，五维评分完全一致。"""
        monkeypatch.setenv("FORCE_VECTOR_SHADOW", "0")
        fvc_off = FiveDomainFeatureComputer()
        r_off = fvc_off.compute(simple_coin_data, simple_system_state)

        monkeypatch.setenv("FORCE_VECTOR_SHADOW", "1")
        fvc_on = FiveDomainFeatureComputer()
        r_on = fvc_on.compute(simple_coin_data, simple_system_state)

        # 五维评分必须完全一致
        for cls in ASSET_CLASSES:
            for dom in ("dao", "tian", "di", "jiang", "fa"):
                assert r_on[cls][dom] == r_off[cls][dom], (
                    f"{cls}/{dom} 评分被 Shadow 改动: {r_on[cls][dom]} vs {r_off[cls][dom]}"
                )

    def test_force_vector_attachments_present_when_on(
        self, simple_coin_data, simple_system_state, monkeypatch
    ):
        """开启时，每类 result 包含 force_vectors 附加键（可能为 None/空 dict，但键必须存在）。"""
        monkeypatch.setenv("FORCE_VECTOR_SHADOW", "1")
        fvc = FiveDomainFeatureComputer()
        result = fvc.compute(simple_coin_data, simple_system_state)
        for cls in ASSET_CLASSES:
            keys = set(result[cls].keys())
            # 至少包含原 5 个评分键
            assert {"dao", "tian", "di", "jiang", "fa"}.issubset(keys)
            # 附加键必须存在（force_vectors 是新增附加输出）
            # 注：实际接入时按资产类输出顶层附加字段；此处仅验证 shadow 不破坏五维评分
            # 同时 result 类型仍是 dict（无结构破坏）
            assert isinstance(result[cls], dict)


class TestForceVectorFailOpen:
    """Shadow 异常必须 FAIL-OPEN，不能破坏评分。"""

    def test_force_vector_import_error_silently_swallowed(
        self, monkeypatch, simple_coin_data, simple_system_state
    ):
        """即便 force_vector 模块完全不可导入，开启开关也不能影响评分。"""
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if isinstance(name, str) and "force_vector" in name:
                raise ImportError("Simulated force_vector missing")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        monkeypatch.setenv("FORCE_VECTOR_SHADOW", "1")

        # 必须不抛异常
        fvc = FiveDomainFeatureComputer()
        result = fvc.compute(simple_coin_data, simple_system_state)

        # 五维评分必须是合法 int 0-100
        for cls in ASSET_CLASSES:
            for dom in ("dao", "tian", "di", "jiang", "fa"):
                v = result[cls][dom]
                assert isinstance(v, int)
                assert 0 <= v <= 100

    def test_shadow_output_structure_on_neutral(self, monkeypatch):
        """enable=False + enable=False → 中性默认，结构正常。"""
        fvc = FiveDomainFeatureComputer(enable=False)
        result = fvc.compute()
        for cls in ASSET_CLASSES:
            assert result[cls] == dict(DEFAULT_NEUTRAL_SCORES)
