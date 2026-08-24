"""T13 · FR 提拔等价性测试（★T-G5 铁门槛）。

验证：
  T13-1  shim.FeatureRegistry **is** feature_hub.FeatureRegistry（身份断言）
  T13-2  shim.ENABLED_SETS 逐 key 断言 dict 相等
  T13-3  shim.FeatureModuleSpec / _wdh_sub_key_splitter / _cycle_sub_key_splitter 身份一致
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_21_ROOT = _PROJECT_ROOT / "21-特征工程中心"
_11_ROOT = _PROJECT_ROOT / "11-易经推理系统"

# 确保两条路径都在 sys.path 中
for p in [str(_21_ROOT), str(_11_ROOT), str(_11_ROOT / "scripts" / "memory_l4")]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ============================================================
# T13-1  FeatureRegistry 身份断言
# ============================================================
def test_t13_1_feature_registry_identity():
    """shim.FeatureRegistry is feature_hub.hub.feature_registry.FeatureRegistry"""
    from feature_hub.hub.feature_registry import FeatureRegistry as HubFR
    from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry as ShimFR

    assert ShimFR is HubFR, (
        "shim.FeatureRegistry 与 feature_hub.FeatureRegistry 不是同一个对象！"
        f"shim={id(ShimFR)}, hub={id(HubFR)}"
    )


# ============================================================
# T13-2  ENABLED_SETS 逐 key 断言
# ============================================================
def test_t13_2_enabled_sets_equal():
    """shim.ENABLED_SETS == feature_hub.ENABLED_SETS（逐 key）"""
    from feature_hub.hub.feature_registry import ENABLED_SETS as HubSets
    from scripts.memory_l4.bcrm2.feature_registry import ENABLED_SETS as ShimSets

    assert set(HubSets.keys()) == set(ShimSets.keys()), (
        f"ENABLED_SETS key 不一致: "
        f"hub_only={set(HubSets) - set(ShimSets)}, "
        f"shim_only={set(ShimSets) - set(HubSets)}"
    )
    for key in HubSets:
        assert HubSets[key] == ShimSets[key], (
            f"ENABLED_SETS['{key}'] 不一致: hub={HubSets[key]}, shim={ShimSets[key]}"
        )


# ============================================================
# T13-3  其他导出符号身份一致
# ============================================================
def test_t13_3_other_symbols_identity():
    """FeatureModuleSpec / _wdh_sub_key_splitter / _cycle_sub_key_splitter 身份一致"""
    from feature_hub.hub.feature_registry import (
        FeatureModuleSpec as HubSpec,
    )
    from feature_hub.hub.feature_registry import (
        _cycle_sub_key_splitter as HubCycle,
    )
    from feature_hub.hub.feature_registry import (
        _wdh_sub_key_splitter as HubWdh,
    )
    from scripts.memory_l4.bcrm2.feature_registry import (
        FeatureModuleSpec as ShimSpec,
    )
    from scripts.memory_l4.bcrm2.feature_registry import (
        _cycle_sub_key_splitter as ShimCycle,
    )
    from scripts.memory_l4.bcrm2.feature_registry import (
        _wdh_sub_key_splitter as ShimWdh,
    )

    assert ShimSpec is HubSpec
    assert ShimWdh is HubWdh
    assert ShimCycle is HubCycle
