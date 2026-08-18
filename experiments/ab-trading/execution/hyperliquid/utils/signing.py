"""
Hyperliquid signing utilities (local fallback)
当 hyperliquid>=1.0.0 不可用时使用此模块
"""
from decimal import Decimal


def float_to_wire(x: float) -> str:
    """
    将浮点数转换为 Hyperliquid 协议要求的字符串格式

    Args:
        x: 输入浮点数

    Returns:
        标准化后的字符串表示

    示例:
        >>> float_to_wire(72.342)
        '72.342'
        >>> float_to_wire(0.00001234)
        '0.00001234'
    """
    rounded = f"{x:.8f}"
    return f"{Decimal(rounded).normalize():f}"
