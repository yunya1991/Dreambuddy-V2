# -*- coding: utf-8 -*-
"""延续性统计分析模块（T0）公共常量与异常。"""

CAVEAT = "历史统计，不代表未来"
KIND = "persistence"

# Hurst 可信门槛：R/S 在 3 年左右日频上不稳定，低于此值只作参考
HURST_CONFIDENT_N = 2000
# Hurst 分块上限：固定后可保证不同样本长度的 H 跨期可比（评审 B3）
HURST_MAX_CHUNK = 256
# 统计类最小样本
MIN_N = 250
# 浮点保护
EPS = 1e-12
# p 值下限：正态近似下溢时不用 0（0 会被读成"确定性"）
P_FLOOR = 1e-12


class PersistenceError(ValueError):
    """样本/参数不足或非法。"""
