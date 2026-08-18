#!/usr/bin/env python3
"""
test_short_filter_scenarios.py — P1 做空过滤器多场景模拟测试

目的：验证 _check_btc_trend / _check_short_trend_filter 在不同市场环境下的实际输出，
      而非理论分析。

测试矩阵：
  1. 构造 4 类市场排列 × 5 类价格位置 = 20 个合成场景
  2. 用实盘日志中的真实做空信号币种（NVDA/HYPE）运行 _check_self_trend
  3. 用 BTC 真实历史K线在 5 个关键时点回放 _check_btc_trend

运行：
    cd 11-易经推理系统
    python scripts/memory_l4/tests/test_short_filter_scenarios.py
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts.memory_l4.polling_trader import PollingTrader  # noqa: E402


def _make_trader():
    """轻量构造 PollingTrader，跳过 __init__"""
    with patch.object(PollingTrader, "__init__", lambda self, *a, **kw: None):
        t = PollingTrader.__new__(PollingTrader)
    t._log = MagicMock()
    t._btc_trend_cache = {"ts": 0, "result": None}
    t._us_index_trend_cache = {"ts": 0, "result": None}
    return t


def _calc(t, price, ma128, ma200, closes_recent_3):
    """直接计算 _check_btc_trend 的决策（绕过 OKX 拉取，用合成 closes）

    关键：closes 必须让前128根的均值=ma128，前1400根的均值=ma200
    每次清空 _btc_trend_cache 避免缓存命中
    """
    import random
    random.seed(42)
    base = ma200
    closes = []
    for i in range(1400):
        trend = (i / 1400) * (ma128 - ma200) * 0.3
        wave = 0.02 * base * random.uniform(-1, 1)
        closes.append(base + trend + wave)
    random.shuffle(closes)
    current_mean_128 = sum(closes[:128]) / 128
    delta_128 = ma128 - current_mean_128
    for i in range(128):
        closes[i] += delta_128
    current_mean_1400 = sum(closes[:1400]) / 1400
    delta_1400 = ma200 - current_mean_1400
    for i in range(1400):
        closes[i] += delta_1400
    current_mean_128 = sum(closes[:128]) / 128
    delta_128 = ma128 - current_mean_128
    for i in range(128):
        closes[i] += delta_128
    for i, v in enumerate(closes_recent_3):
        closes[2 - i] = v
    closes[0] = price
    # 清缓存避免命中上次结果
    t._btc_trend_cache = {"ts": 0, "result": None}
    with patch("scripts.memory_l4.polling_trader._load_kline_from_okx",
               return_value=[{"c": c} for c in closes]):
        return t._check_btc_trend()


class TestSyntheticScenarios(unittest.TestCase):
    """场景1：合成 K 线，覆盖 4×5 矩阵"""

    def test_matrix_20_scenarios(self):
        """4 排列 × 5 价格位置 = 20 场景全跑"""
        t = _make_trader()
        # 基础数值
        MA128_BULL = 138000       # 牛市 MA128
        MA200_BULL = 120000       # 牛市 MA200周 < MA128
        MA128_BEAR = 95000        # 熊市 MA128
        MA200_BEAR = 130000       # 熊市 MA200周 > MA128

        scenarios = [
            # ── 牛市排列 (MA128 > MA200) ──
            ("牛市·远高于两MA +20%", MA128_BULL*1.20, MA128_BULL, MA200_BULL,
             [MA128_BULL*1.20, MA128_BULL*1.18, MA128_BULL*1.17]),
            ("牛市·略高于MA128 +3%", MA128_BULL*1.03, MA128_BULL, MA200_BULL,
             [MA128_BULL*1.03, MA128_BULL*1.02, MA128_BULL*1.01]),
            ("牛市·刚跌破MA128 -1%", MA128_BULL*0.99, MA128_BULL, MA200_BULL,
             [MA128_BULL*0.99, MA128_BULL*0.985, MA128_BULL*0.98]),
            ("牛市·深跌破 -8%在MA200上方", MA128_BULL*0.92, MA128_BULL, MA200_BULL*1.05,
             [MA128_BULL*0.92, MA128_BULL*0.93, MA128_BULL*0.94]),
            ("牛市·MA200+1%兜底", MA200_BULL*1.005, MA128_BULL*0.95, MA200_BULL,
             [MA200_BULL*1.005, MA200_BULL*1.00, MA200_BULL*0.995]),
            # ── 熊市排列 (MA128 < MA200) ──
            ("熊市·远低于两MA -15%", MA128_BEAR*0.85, MA128_BEAR, MA200_BEAR,
             [MA128_BEAR*0.85, MA128_BEAR*0.87, MA128_BEAR*0.88]),
            ("熊市·略低于MA128 -3%", MA128_BEAR*0.97, MA128_BEAR, MA200_BEAR,
             [MA128_BEAR*0.97, MA128_BEAR*0.96, MA128_BEAR*0.95]),
            ("熊市·刚跌破MA128 -1%", MA128_BEAR*0.99, MA128_BEAR, MA200_BEAR,
             [MA128_BEAR*0.99, MA128_BEAR*0.985, MA128_BEAR*0.98]),
            ("熊市·价格在两MA之间", (MA128_BEAR+MA200_BEAR)/2, MA128_BEAR, MA200_BEAR,
             [(MA128_BEAR+MA200_BEAR)/2]*3),
            ("熊市·MA200+1%兜底（不可能场景）", MA200_BEAR*1.005, MA128_BEAR, MA200_BEAR,
             [MA200_BEAR*1.005]*3),
        ]

        print("\n" + "="*100)
        print(f"{'场景':40s} | {'允许做空':8s} | {'F_net':>9s} | {'角色日/周':12s} | {'3日跌破':6s} | {'原因'}")
        print("="*100)
        for name, price, ma128, ma200, recent_3 in scenarios:
            bearish, reason = _calc(t, price, ma128, ma200, recent_3)
            # 从 reason 解析关键信息
            f_net_str = ""
            import re
            m = re.search(r"F_net=([+-]?[\d.]+)", reason)
            if m:
                f_net_str = m.group(1)
            ma_match = re.search(r"日距=([+-]?[\d.]+)%\(([0-9.]+)\)\s*周距=([+-]?[\d.]+)%\(([0-9.]+)\)", reason)
            role_d = "支撑" if price > ma128 else "阻力"
            role_w = "支撑" if price > ma200 else "阻力"
            breakdown = "是" if all(c <= ma128 for c in recent_3) else "否"
            allowed = "✅允许" if bearish else "禁止"
            print(f"{name:40s} | {allowed:8s} | {f_net_str:>9s} | {role_d}/{role_w:6s} | {breakdown:6s} | {reason[:60]}")
        print("="*100)


class TestRealBtcHistorical(unittest.TestCase):
    """场景2：用真实 BTC K 线在关键历史时点回放"""

    def test_btc_historical_moments(self):
        """构造 5 个 BTC 历史关键时点（不依赖 OKX 实时）"""
        t = _make_trader()

        # 用经验值构造各历史时点的 MA（基于公开历史价格估算）
        moments = [
            # (时点描述, price, MA128估计, MA200周估计, 3日收盘价估计)
            ("2024-12 BTC见顶回落 10.5万→9.5万", 95000, 98000, 65000,
             [95000, 96000, 95500]),  # 跌破MA128 但远在MA200上方
            ("2025-03 牛市深调 8.4万（MA200上方）", 84000, 95000, 78000,
             [84000, 85000, 86000]),  # 深跌破MA128 但在MA200上方
            ("2024-08 牛市回踩MA200 5.5万", 55000, 62000, 54000,
             [55000, 56000, 57000]),  # 接近MA200兜底
            ("2022-11 FTX崩盘 1.6万（熊市深熊）", 16000, 22000, 35000,
             [16000, 17000, 18000]),  # 熊市排列，深跌
            ("2023-10 熊转牛初期 2.8万", 28000, 26000, 32000,
             [28000, 27500, 27000]),  # MA128<MA200熊市排列，价在两MA之间
        ]

        print("\n" + "="*100)
        print("BTC 历史关键时点回放")
        print(f"{'时点':50s} | {'允许做空':8s} | {'F_net':>9s} | {'均线排列':10s} | {'实际后市'}")
        print("="*100)

        actual_outcomes = [
            "后续2月跌至8万后反弹",   # 2024-12: 见顶后继续跌到8万 → 做空合理
            "后续1月反弹至9.5万",     # 2025-03: 深调后反弹 → 做空会被套
            "后续3月涨至10万",        # 2024-08: 牛市继续 → 不做空正确
            "后续3月反弹至2.3万",     # 2022-11: 熊市底部反弹 → 做空会被套
            "后续3月涨至4万",         # 2023-10: 牛市起点 → 不做空正确
        ]

        for (desc, price, ma128, ma200, recent_3), actual in zip(moments, actual_outcomes):
            bearish, reason = _calc(t, price, ma128, ma200, recent_3)
            import re
            m = re.search(r"F_net=([+-]?[\d.]+)", reason)
            f_net_str = m.group(1) if m else "?"
            align = "牛市(M128>M200)" if ma128 > ma200 else "熊市(M128<M200)"
            allowed = "✅允许" if bearish else "禁止"
            print(f"{desc:50s} | {allowed:8s} | {f_net_str:>9s} | {align:10s} | 后市: {actual}")

        print("="*100)


class TestRealCoinsFromLog(unittest.TestCase):
    """场景3：用实盘日志中的做空信号币种(NVDA/HYPE)运行 _check_self_trend"""

    def test_real_coins_short_signals(self):
        """用实盘日志中最近出现做空信号的币种验证"""
        t = _make_trader()

        # 从日志提取真实做空信号 (NVDA/HYPE 出现 DOWN 推理)
        print("\n" + "="*100)
        print("实盘日志做空信号币种 _check_self_trend 模拟")
        print(f"{'币种':10s} | {'允许做空':8s} | {'F_net':>9s} | {'角色日/周':10s} | {'reason'}")
        print("="*100)

        # 构造 NVDA/HYPE 的合成日K数据
        # NVDA 当前价 223 (从日志读取), 假设 MA50=220, MA200=180 (美股长牛)
        # HYPE 假设当前 25, MA50=23, MA200=15 (加密牛市)
        cases = [
            ("NVDA", 223.0, 220.0, 180.0, [223, 222, 221]),  # 略高于MA50，远高于MA200
            ("NVDA", 215.0, 220.0, 180.0, [215, 217, 219]),  # 刚跌破MA50，仍在MA200上方
            ("NVDA", 175.0, 200.0, 180.0, [175, 176, 177]),  # 跌破MA50和MA200
            ("HYPE", 25.0, 23.0, 15.0, [25, 24.5, 24]),       # 牛市略高于MA50
            ("HYPE", 22.0, 23.0, 15.0, [22, 22.5, 23]),       # 刚跌破MA50
            ("HYPE", 14.0, 20.0, 15.0, [14, 14.5, 15]),       # 跌破MA200
        ]

        for coin, price, ma50, ma200, recent in cases:
            # 构造 closes (newest-first), 250 根
            closes = list(recent) + [ma50]*47 + [ma200]*200
            closes[0] = price
            with patch("scripts.memory_l4.polling_trader._load_kline_from_okx",
                       return_value=[{"c": c} for c in closes]):
                bearish, reason = t._check_self_trend(coin)

            import re
            m = re.search(r"F_net=([+-]?[\d.]+)", reason)
            f_net_str = m.group(1) if m else "?"
            role_d = "支撑" if price > ma50 else "阻力"
            role_w = "支撑" if price > ma200 else "阻力"
            allowed = "✅允许" if bearish else "禁止"
            print(f"{coin:10s} | {allowed:8s} | {f_net_str:>9s} | {role_d}/{role_w:6s} | {reason[:70]}")

        print("="*100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
