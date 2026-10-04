"""
25-用户策略生成系统 - 策略模板

基于 10-经典指标系统/Bot2StrategyTrend 的成熟结构，
提供标准化的 Freqtrade 策略骨架，供 LLM 填充具体逻辑。
"""
from __future__ import annotations

# ── 策略骨架模板 ──────────────────────────────────────────────────────────
# LLM 需填充: INDICATORS_BLOCK / ENTRY_CONDITIONS / EXIT_CONDITIONS / PARAMS_BLOCK
STRATEGY_TEMPLATE = '''# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
# flake8: noqa: F401
# isort: skip_file
# --- Do not remove these imports ---
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from pandas import DataFrame
from typing import Optional

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, merge_informative_pair
from freqtrade.persistence import Trade

import talib.abstract as ta
from technical import qtpylib


class {class_name}(IStrategy):
    """
    {strategy_name}
    {description}
    """
    INTERFACE_VERSION = 3

    timeframe = "{timeframe}"
    can_short: bool = False

    minimal_roi = {{
        "0": 0.10,
        "60": 0.05,
        "120": 0.02,
        "240": 0.00,
    }}

    stoploss = {stoploss}
    trailing_stop = {trailing_stop}

    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    startup_candle_count: int = 200

    order_types = {{
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }}

    order_time_in_force = {{
        "entry": "GTC",
        "exit": "GTC",
    }}

    # ── Hyperopt 参数 ──────────────────────────────────────────────
{params_block}

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """计算策略所需的技术指标。"""
{indicators_block}
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """定义入场信号。"""
        conditions = []
{entry_conditions}

        if conditions:
            dataframe.loc[
                functools.reduce(lambda x, y: x & y, conditions),
                'enter_long',
            ] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """定义出场信号。"""
        conditions = []
{exit_conditions}

        if conditions:
            dataframe.loc[
                functools.reduce(lambda x, y: x | y, conditions),
                'exit_long',
            ] = 1

        return dataframe
'''

# 注意：模板中使用 functools.reduce，需在文件顶部 import
# 但为简化，生成器会在最终代码中添加 import functools
#
# 关键设计（LLM 必须遵守）：
# - populate_entry_trend：使用 functools.reduce(lambda x, y: x & y, conditions)
#   入场条件必须全部满足（AND 逻辑）—— 确保信号质量
# - populate_exit_trend：使用 functools.reduce(lambda x, y: x | y, conditions)
#   出场条件任一满足即出场（OR 逻辑）—— 确保及时止损/止盈
# 这是 Freqtrade 成熟策略的通用模式（参考 freqtrade-strategies 仓库）。


def get_template_fields() -> dict:
    """返回模板需要 LLM 填充的字段说明。"""
    return {
        "class_name": "策略类名（PascalCase，如 TrendFollowingStrategy）",
        "strategy_name": "策略中文名/简称",
        "description": "策略描述（1-2 句话）",
        "timeframe": "K线周期，如 5m / 15m / 1h",
        "stoploss": "止损比例，如 -0.05",
        "trailing_stop": "是否移动止损，True/False",
        "params_block": "Hyperopt 参数定义（IntParameter/DecimalParameter）",
        "indicators_block": "指标计算代码（RSI/EMA/MACD 等）",
        "entry_conditions": "入场条件列表（append 到 conditions）",
        "exit_conditions": "出场条件列表（append 到 conditions）",
    }
