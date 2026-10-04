"""backtrader 适配器 — FAIL-OPEN 设计测试

验证 backtrader_adapter.enhance_signals 的 FAIL-OPEN 行为：
1. backtrader 未安装/不可用时返回 None（不影响 C3 主流程）
2. 异常输入时返回 None（保持稳定）

设计原则：
- enhance_signals 返回 Optional[Dict]，None 表示"未增强，使用原简化结果"
- 返回 dict 时包含字段：win_rate/sharpe/max_dd/total_trades/source="backtrader"
- 任何异常都不得冒泡到 C3 节点
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest


def test_adapter_fail_open_when_unavailable():
    """无 klines 输入时 enhance_signals 返回 None

    场景：C3 节点未提供 backtest_klines（典型情况），适配器应返回 None，
    C3 节点继续使用简化模拟结果，不影响主流程。
    """
    from dreamos.capabilities.trading.backtest.backtrader_adapter import (
        enhance_signals,
    )

    # 无 klines
    result = enhance_signals(signals=[], klines=None)
    assert result is None

    # klines 为空 list
    result = enhance_signals(signals=[], klines=[])
    assert result is None

    # klines 为空 dict
    result = enhance_signals(signals=[], klines={})
    assert result is None


def test_adapter_fail_open_on_exception():
    """异常输入时 enhance_signals 返回 None，不得抛出异常

    场景：klines 格式非法（None 嵌套、字段缺失、类型错误），
    适配器应捕获所有异常并返回 None，保持 FAIL-OPEN。
    """
    from dreamos.capabilities.trading.backtest.backtrader_adapter import (
        enhance_signals,
    )

    # 非法 klines：嵌套 None
    result = enhance_signals(
        signals=[{"symbol": "BTC", "confidence": 0.8}],
        klines=None,
    )
    assert result is None

    # 非法 klines：字段缺失
    result = enhance_signals(
        signals=[{"symbol": "BTC", "confidence": 0.8}],
        klines=[{"open": 100}],  # 缺失 close/high/low
    )
    assert result is None

    # 非法 signals：非 list
    result = enhance_signals(signals=None, klines=[{"close": 100}])
    assert result is None

    # 非法 signals：元素非 dict
    result = enhance_signals(
        signals=["not_a_dict"],
        klines=[{"close": 100}],
    )
    assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
