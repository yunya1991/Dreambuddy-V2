"""不确定性量化：综合多因子计算信号不确定性。"""

from typing import Any, Dict

from .types import MDRResult


def compute_uncertainty(
    triple_screen: Dict[str, Any],
    mrd: MDRResult,
    velocity: Dict[str, Any],
    total_cases: int,
) -> float:
    """计算综合不确定性。

    因子:
    1. 三屏对齐度: 1 - |alignment|
    2. MRD 置信度: 1 - mrd.confidence
    3. 数据量: max(0, 1 - n/20)
    4. 速度稳定性: 1 - velocity.confidence
    """
    factors: list[float] = []

    # 对齐度
    alignment = triple_screen.get("alignment", 0)
    factors.append(1.0 - abs(alignment))

    # MRD 置信度
    factors.append(1.0 - mrd.confidence)

    # 数据量（< 20 case → 高不确定）
    data_factor = max(0.0, 1.0 - total_cases / 20)
    factors.append(data_factor)

    # 速度稳定性
    v_conf = velocity.get("confidence", 0)
    factors.append(1.0 - v_conf)

    # 等权平均
    uncertainty = sum(factors) / len(factors)
    return round(max(0.0, min(1.0, uncertainty)), 4)
