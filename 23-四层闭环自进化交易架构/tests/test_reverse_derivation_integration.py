"""RED 测试：ReverseDerivationIntegration — 数据源集成层。

将 PrimaryContradictionIdentifier 的 paths 和 cross_attention 的 last_attn_weights
转换为 ReverseDeriver 所需的 dimension_predictions 和 attention_weights。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "dreambuddy_evolution" / "engines"))
sys.path.insert(0, str(Path(__file__).parent.parent / "dreambuddy_evolution"))

from reverse_derivation_integration import (
    extract_dimension_predictions,
    extract_attention_weights,
)


def test_extract_dimension_predictions_from_paths():
    """RED: 从 identify() 输入 paths 提取每维度方向。"""
    paths = [
        {"source": "bdsm", "direction": "long"},
        {"source": "bcrm", "direction": "short"},
        {"source": "strategic", "direction": "long"},
    ]
    result = extract_dimension_predictions(paths)
    assert result == {"C1": "long", "C3": "short", "C4": "long"}


def test_extract_dimension_predictions_handles_grid_trading():
    """RED: grid_trading 映射到 C2（与 trend_following 同维度）。"""
    paths = [
        {"source": "trend_following", "direction": "short"},
        {"source": "grid_trading", "direction": "long"},
    ]
    result = extract_dimension_predictions(paths)
    # 同一维度多个路径时，取最后一个（或可配置策略）
    assert result["C2"] in ("short", "long")


def test_extract_dimension_predictions_skips_unknown_source():
    """RED: 未知 source 跳过，不抛异常。"""
    paths = [
        {"source": "bdsm", "direction": "long"},
        {"source": "unknown_source", "direction": "short"},
    ]
    result = extract_dimension_predictions(paths)
    assert result == {"C1": "long"}


def test_extract_dimension_predictions_fail_open_on_invalid():
    """RED: 无效输入 FAIL-OPEN 返回空 dict。"""
    assert extract_dimension_predictions(None) == {}
    assert extract_dimension_predictions([]) == {}
    assert extract_dimension_predictions("not_a_list") == {}


def test_extract_attention_weights_from_tensor():
    """RED: 从 cross_attention last_attn_weights 提取维度权重列表。"""
    import torch
    # last_attn_weights shape: (B=1, n_heads=2, 1, N=3)
    weights = torch.tensor([[[[0.2, 0.5, 0.3]], [[0.1, 0.6, 0.3]]]])
    result = extract_attention_weights(weights)
    assert isinstance(result, list)
    assert len(result) == 3
    # 跨 head 平均后
    assert result[0] == 0.15  # (0.2+0.1)/2
    assert result[1] == 0.55  # (0.5+0.6)/2


def test_extract_attention_weights_fail_open():
    """RED: None 或非 tensor 输入返回空列表。"""
    assert extract_attention_weights(None) == []
    assert extract_attention_weights([0.1, 0.2]) == [0.1, 0.2]
