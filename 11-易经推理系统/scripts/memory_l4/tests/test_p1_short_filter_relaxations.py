#!/usr/bin/env python3
"""
test_p1_short_filter_relaxations.py — 三类做空过滤优化的 TDD 测试（RED → GREEN）

测试项 A. BTC Step2 弱共振分级（2026-08-23 阈值放宽 3%→5%）：
  A1 严格空头 SMA20<50<200 → allow=True, 升级score
  A2 多头排列但 MA20-MA50 < 5% 且 conf>0.85 → allow=True, WEAK级, position_mult×0.4
  A3 多头排列但 MA20-MA50 ≥ 5% → allow=False 拦截
  A4 多头排列收窄<5% 但 conf≤0.85 → allow=False 拦截
  A5 边界：MA20-MA50 恰好 4.99%+ 置信0.85(阈值边界，需严格>) → 拦截
  A6 BTC真实收敛区间 3%-5%（如 4.5%） + 高置信 → 弱共振放行（小仓）

测试项 B. 美股代币条件B放宽：
  B1 F_avg<-0.02 + 两指数score都是WEAK(无valid_bd) → allow=True, WEAK级
  B2 F_avg<-0.02 + 一个WEAK一个NONE → allow=False 拦截
  B3 F_avg≥-0.02 + 两score都是WEAK → allow=False 拦截（F不够强）
  B4 原有 strict 逻辑不破坏（STRONG+valid_bd直接放行）

测试项 C. 加密美股分类路由：
  C1 COIN/MSTR/CRCL → 路由到 _check_btc_trend（跟随BTC）
  C2 AAPL/AMZN/NVDA → 路由到 _check_us_index_trend（跟随美股大盘）
  C3 BTC/SOL → 路由到 _check_btc_trend（加密组）
  C4 XAU/黄金非加密非美股 → 路由到 _check_self_trend（自身趋势）
  C5 做多方向长过滤器路由对称（一致性验证）

运行:
    cd 11-易经推理系统
    python -m pytest scripts/memory_l4/tests/test_p1_short_filter_relaxations.py -v -s
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts.memory_l4.polling_trader import PollingTrader  # noqa: E402


def _make_trader():
    with patch.object(PollingTrader, "__init__", lambda self, *a, **kw: None):
        t = PollingTrader.__new__(PollingTrader)
    t._log = MagicMock()
    t._btc_trend_cache = {"ts": 0, "result": None}
    t._us_index_trend_cache = {"ts": 0, "result": None}
    t.short_confidence_threshold = 0.70
    t.confidence_threshold = 0.70
    t.FMA_REGIME_FILTER_ENABLED = False  # 默认值：无趋势过滤(回测最优)
    return t


def _build_kline_data(closes_newest_first):
    """构造 inference["kline_data"] 格式（list[dict]，newest-first，每个含"c"）"""
    return [{"c": str(c)} for c in closes_newest_first]


def _build_sma_closes(sma20_target, sma50_target, sma200_target, n=200):
    """构造 closes（newest-first），使前 20/50/200 的均值精确≈目标值。

    原理：
      - 令 closes[200..n-1] = sma200_target（保证 MA200 不受短端调整影响）
      - 令 closes[50..199] = x（MA50 = (sum_0_49 + 150*x) / 200，这里更简单做法：
        closes[0:20] 围绕 sma20_target，closes[20:50] 围绕 sma50_target，closes[50:200] 围绕 sma200_target
      - 迭代修正
    """
    closes = [sma200_target] * n
    # Step 1：设 closes[50:200] = sma200_target → MA200 会受 0-49 影响，所以迭代收敛
    for _ in range(20):
        # 修正 closes[0:20] 使 sum(0:20)/20 = sma20_target
        cur20 = sum(closes[:20]) / 20
        d20 = sma20_target - cur20
        for i in range(20):
            closes[i] += d20
        # 修正 closes[20:50] 使 sum(0:50)/50 = sma50_target
        cur50 = sum(closes[:50]) / 50
        d50 = sma50_target - cur50
        # 只调整 20:50 避免破坏 0:20
        s20_50 = sum(closes[20:50])
        target_s20_50 = sma50_target * 50 - sum(closes[:20])
        factor = target_s20_50 / s20_50 if s20_50 else 1.0
        for i in range(20, 50):
            closes[i] *= factor
        # 修正 closes[50:200] 使 sum(0:200)/200 = sma200_target
        cur200 = sum(closes[:200]) / 200
        d200 = sma200_target - cur200
        s50_200 = sum(closes[50:200])
        target_s50_200 = sma200_target * 200 - sum(closes[:50])
        factor = target_s50_200 / s50_200 if s50_200 else 1.0
        for i in range(50, 200):
            closes[i] *= factor
    return closes


# =============================================================
# 测试项 A：BTC Step2 弱共振分级
# =============================================================

class TestWeakResonanceGrading(unittest.TestCase):
    """RED → GREEN: Step2 短周期共振支持"弱共振"（多头排列反转前夜）"""

    def _run_short_filter(self, coin, closes_sma, step1_result, confidence=None):
        """构造最小化场景：跳过真实 Step1（mock返回），直接测 Step2 逻辑"""
        t = _make_trader()
        # 准备 inference：带上 kline_data（SMA 需要200根）
        inference = {
            "coin": coin,
            "inst_id": f"{coin}-USDT-SWAP",
            "direction": "DOWN",
            "confidence": confidence if confidence is not None else 0.80,
            "kline_data": _build_kline_data(closes_sma),
            "hexagram": "水天需",
        }
        # Mock Step1 大盘趋势确认：返回 (True, step1_reason) 让 Step1 放行
        # Step1 reason 需含 score=... 供 _parse_bearish_score_from_reason 解析
        if coin in t.CRYPTO_COINS or coin in t.US_STOCK_COINS:
            # 根据路由mock不同函数
            if coin in t.CRYPTO_COINS:
                mock_fn = "scripts.memory_l4.polling_trader.PollingTrader._check_btc_trend"
            else:
                mock_fn = "scripts.memory_l4.polling_trader.PollingTrader._check_us_index_trend"
        else:
            mock_fn = "scripts.memory_l4.polling_trader.PollingTrader._check_self_trend"

        with patch(mock_fn, return_value=step1_result):
            result = t._check_short_trend_filter(coin, inference)
        return t, result

    # ---- A1: 严格空头排列 → 标准放行（score升级）----
    def test_A1_strict_bear_order_upgrades_score(self):
        # SMA20=97 < SMA50=98 < SMA200=100: 标准空头排列
        closes = _build_sma_closes(97.0, 98.0, 100.0, 200)
        step1_ok = (True, "[SHORT_ALLOWED] BTC做空允许 ... score=WEAK valid_breakdown ...")
        _, res = self._run_short_filter("BTC", closes, step1_ok, confidence=0.80)
        allow, reason, mult = res[0], res[1], res[2] if len(res) >= 3 else 0.0
        self.assertTrue(allow, f"严格空头排列应放行，但被拦截: {reason}")
        self.assertIn("共振", reason, "reason应提及共振成功")
        # Step1=WEAK + 共振 → 升级为 NORMAL，所以 conf_multiplier 应该是 SHORT_CONF_MULTI_MA_NORMAL=1.0
        # 但 mult 包含 regime，所以 reason 里应含 score=NORMAL
        self.assertIn("score=NORMAL", reason, f"WEAK+共振应升级为NORMAL，实际: {reason}")

    # ---- A2: 多头排列但20-50收窄<5%+高conf → 弱共振放行 ----
    def test_A2_bull_order_narrowing_high_conf_weak_allow(self):
        # 多头排列：SMA20=77500, SMA50=76000, SMA200=66000
        # 20 vs 50 差值 = (77500-76000)/76000 = 1.97% < 5%，符合收窄条件
        closes = _build_sma_closes(77500.0, 76000.0, 66000.0, 200)
        step1_ok = (True, "[SHORT_ALLOWED] BTC做空允许 ... score=WEAK valid_breakdown ...")
        _, res = self._run_short_filter("BTC", closes, step1_ok, confidence=0.88)
        allow, reason, mult = res[0], res[1], res[2] if len(res) >= 3 else 0.0
        self.assertTrue(allow, f"多头反转前夜(差值1.97%<5%)+高置信0.88应弱共振放行，但被拦截: {reason}")
        self.assertIn("弱共振", reason, "reason应提及弱共振放行")
        self.assertIn("score=WEAK", reason, "弱共振不应升级评分，保持WEAK级")

    # ---- A3: 多头排列20-50差值≥5% → 拦截 ----
    def test_A3_bull_order_wide_gap_still_blocked(self):
        # SMA20=80000, SMA50=76000: 差值=(80000-76000)/76000=5.26% > 5%
        closes = _build_sma_closes(80000.0, 76000.0, 66000.0, 200)
        step1_ok = (True, "[SHORT_ALLOWED] BTC做空允许 ... score=WEAK valid_breakdown ...")
        _, res = self._run_short_filter("BTC", closes, step1_ok, confidence=0.90)
        allow, reason, _ = res[0], res[1], res[2] if len(res) >= 3 else 0.0
        self.assertFalse(allow, f"MA20-MA50差值5.26%>5%应拦截，但被放行: {reason}")
        self.assertIn("共振失败", reason)

    # ---- A4: 收窄<5% 但 conf≤0.85 → 拦截 ----
    def test_A4_bull_narrowing_but_low_conf_blocked(self):
        closes = _build_sma_closes(77500.0, 76000.0, 66000.0, 200)  # 差值1.97%<5%
        step1_ok = (True, "[SHORT_ALLOWED] BTC做空允许 ... score=WEAK valid_breakdown ...")
        _, res = self._run_short_filter("BTC", closes, step1_ok, confidence=0.80)  # ≤0.85
        allow, reason, _ = res[0], res[1], res[2] if len(res) >= 3 else 0.0
        self.assertFalse(allow, f"收窄<5%但置信0.80≤0.85应拦截，但放行: {reason}")
        self.assertIn("弱共振不满足", reason, "reason应说明弱共振条件不足(低置信)")

    # ---- A5: 边界case：20-50恰好4.99%收窄 + 边界置信0.85（严格>0.85才放行，0.85仍拦截） ----
    def test_A5_boundary_narrowing_4p99_conf_0p85(self):
        # (20 - 50) / 50 = 4.99% 刚好 < 5%
        sma50 = 76000.0
        sma20 = sma50 * 1.0499  # 4.99% 差值
        closes = _build_sma_closes(sma20, sma50, 66000.0, 200)
        step1_ok = (True, "[SHORT_ALLOWED] BTC做空允许 ... score=WEAK valid_breakdown ...")
        _, res = self._run_short_filter("BTC", closes, step1_ok, confidence=0.85)
        allow, reason, _ = res[0], res[1], res[2] if len(res) >= 3 else 0.0
        # 设计：conf > 0.85（严格大于），所以0.85拦截
        self.assertFalse(allow, f"边界置信度0.85=阈值应拦截（需严格>0.85）: {reason}")

    # ---- A6: BTC真实收敛区间(3%-5%) + 高置信 → 弱共振放行小仓（用户放宽阈值的核心场景） ----
    def test_A6_btc_real_gap_4p5_high_conf_allow_weak(self):
        # 真实BTC第1轮: 差值≈4.44%，最新轮≈3.69%，均在3%-5%区间内
        # 取 4.5% 典型值 + 置信0.90(>0.85)
        sma50 = 76000.0
        sma20 = sma50 * 1.045  # 4.5% 差值
        closes = _build_sma_closes(sma20, sma50, 66000.0, 200)
        step1_ok = (True, "[SHORT_ALLOWED] BTC做空允许 ... score=STRONG regime=TREND_BEAR")
        _, res = self._run_short_filter("BTC", closes, step1_ok, confidence=0.90)
        allow, reason, mult = res[0], res[1], res[2] if len(res) >= 3 else 0.0
        self.assertTrue(allow, f"BTC真实差值4.5%<5%+高置信0.90应通过弱共振放行(WEAK级小仓)，但拦截: {reason}")
        self.assertIn("弱共振", reason)
        self.assertIn("score=WEAK", reason, "弱共振放行不升级评分，保持WEAK")
        self.assertIn("差值4.50%<5%", reason, "reason应标注新阈值5%")


# =============================================================
# 测试项 B：美股代币条件B放宽
# =============================================================

class TestUSIndexRelaxedConditionB(unittest.TestCase):
    """RED → GREEN: 美股大盘条件B增加 F_avg<-0.02 + 两指数WEAK评分 放行路径"""

    def _run_us_index(self, ixic_res_dict: dict, gspc_res_dict: dict):
        """通用执行：mock yfinance.download + PollingTrader._calc_5ma_spring_force"""
        t = _make_trader()
        results_iter = iter([ixic_res_dict, gspc_res_dict])

        # yf 在函数内局部 import：需要 patch yfinance.download 模块级
        import pandas as pd
        fake_df = pd.DataFrame({"Close": [100.0 + i * 0.1 for i in range(300)]})

        def fake_calc(self_or_closes, *args, **kwargs):
            # patch.object(instance/class 会不同调用方式，统一兼容
            return next(results_iter)

        with patch("yfinance.download", return_value=fake_df):
            with patch.object(PollingTrader, "_calc_5ma_spring_force", fake_calc):
                allow, reason = t._check_us_index_trend()
        return allow, reason

    def test_B1_Favg_below_minus02_both_WEAK_allows(self):
        """条件B放宽：F_avg=-0.064 < -0.02，两指数score==WEAK(无3日确认)→ allow=True WEAK级"""
        ixic_r = {"bearish_score": "WEAK", "F_net": -0.059, "valid_breakdown": False,
                  "in_long_term_window": False}
        gspc_r = {"bearish_score": "WEAK", "F_net": -0.069, "valid_breakdown": False,
                  "in_long_term_window": False}
        allow, reason = self._run_us_index(ixic_r, gspc_r)
        self.assertTrue(allow, f"F_avg<-0.02 + 两指数WEAK评分应放行，但拦截: {reason}")
        self.assertIn("SHORT_ALLOWED", reason)
        self.assertIn("score=WEAK", reason or "", "放宽路径输出WEAK级评分")

    def test_B2_Favg_below_minus02_one_WEAK_one_NONE_blocks(self):
        """条件B放宽必要条件：两指数都需至少WEAK，一个NONE一个WEAK仍拦截"""
        ixic_r = {"bearish_score": "NONE", "F_net": -0.059, "valid_breakdown": False,
                  "in_long_term_window": False}
        gspc_r = {"bearish_score": "WEAK", "F_net": -0.069, "valid_breakdown": False,
                  "in_long_term_window": False}
        allow, reason = self._run_us_index(ixic_r, gspc_r)
        self.assertFalse(allow, f"F_avg<-0.02 但IXIC=NONE不满足双WEAK，应拦截: {reason}")
        self.assertIn("无看空确认", reason)

    def test_B3_Favg_ge_minus02_both_WEAK_still_blocks(self):
        """F_avg≥-0.02（力度不足）即便两WEAK也不放行"""
        # F_avg = (-0.010 + -0.015)/2 = -0.0125 ≥ -0.02
        ixic_r = {"bearish_score": "WEAK", "F_net": -0.010, "valid_breakdown": False,
                  "in_long_term_window": False}
        gspc_r = {"bearish_score": "WEAK", "F_net": -0.015, "valid_breakdown": False,
                  "in_long_term_window": False}
        allow, reason = self._run_us_index(ixic_r, gspc_r)
        self.assertFalse(allow, f"F_avg=-0.0125≥-0.02力度不足，即便双WEAK也应拦截: {reason}")

    def test_B4_original_STRONG_path_unaffected(self):
        """原有 any_strict 逻辑（STRONG+valid_bd）必须仍然工作（非回归）"""
        ixic_r = {"bearish_score": "STRONG", "F_net": -0.030, "valid_breakdown": True,
                  "in_long_term_window": False}
        gspc_r = {"bearish_score": "NONE", "F_net": +0.010, "valid_breakdown": False,
                  "in_long_term_window": False}
        allow, reason = self._run_us_index(ixic_r, gspc_r)
        self.assertTrue(allow, f"原路径(IXIC STRONG+valid_bd)必须仍然放行: {reason}")
        self.assertIn("SHORT_ALLOWED", reason)


# =============================================================
# 测试项 C：加密美股分类路由
# =============================================================

class TestCryptoUSStockRouting(unittest.TestCase):
    """RED → GREEN: COIN/MSTR/CRCL 路由到 BTC 趋势确认而非美股大盘"""

    def _detect_route(self, coin: str, direction_filter: str = "short") -> str:
        """
        通过mock三个检查函数的返回值中带唯一标识，来判断哪个函数被实际调用。
        路由目标：
          - _check_btc_trend      → "btc_route"
          - _check_us_index_trend → "us_index_route"
          - _check_self_trend     → "self_route"
        """
        t = _make_trader()
        # 构造足够长的kline_data避免SMA阶段触发无共振数据降级
        closes = _build_sma_closes(97.0, 98.0, 100.0, 200)
        inference = {"kline_data": _build_kline_data(closes), "confidence": 0.90}

        markers = {
            "btc": "[SHORT_ALLOWED] BTC_MARKER score=WEAK",
            "us":  "[SHORT_ALLOWED] USIDX_MARKER score=WEAK",
            "slf": "[SHORT_ALLOWED] SELF_MARKER score=WEAK",
        }

        with patch.object(PollingTrader, "_check_btc_trend",
                          return_value=(True, markers["btc"])) as mock_btc, \
             patch.object(PollingTrader, "_check_us_index_trend",
                          return_value=(True, markers["us"])) as mock_us, \
             patch.object(PollingTrader, "_check_self_trend",
                          return_value=(True, markers["slf"])):
            if direction_filter == "short":
                allow, reason, *_ = t._check_short_trend_filter(coin, inference)
            else:
                allow, reason, *_ = t._check_long_trend_filter(coin, inference, {})

        if markers["btc"] in reason or mock_btc.called:
            return "btc_route"
        elif markers["us"] in reason or mock_us.called:
            return "us_index_route"
        elif markers["slf"] in reason or mock_slf.called:
            return "self_route"
        return "unknown"

    def test_C1_COIN_MSTR_CRCL_follow_BTC_route(self):
        """C1: COIN/MSTR/CRCL → 加密美股，跟随BTC趋势"""
        for coin in ("COIN", "MSTR", "CRCL"):
            route = self._detect_route(coin)
            self.assertEqual(route, "btc_route",
                             f"{coin} 应路由到 BTC 趋势确认(跟随加密)，实际: {route}")

    def test_C2_AAPL_AMZN_NVDA_follow_US_index(self):
        """C2: 纯美股科技股 → 跟随美股大盘"""
        for coin in ("AAPL", "AMZN", "NVDA", "TSLA", "META", "NFLX", "GOOGL", "MSFT",
                     "MU", "SKHYNIX", "SNDK", "SPCX", "BABA", "PLTR", "BMNR"):
            route = self._detect_route(coin)
            self.assertEqual(route, "us_index_route",
                             f"{coin} 应路由到美股大盘趋势，实际: {route}")

    def test_C3_BTC_SOL_crypto_btc_route(self):
        """C3: 纯加密币种 → BTC路由"""
        for coin in ("BTC", "SOL", "UNI", "OKB", "HYPE", "PUMP"):
            route = self._detect_route(coin)
            self.assertEqual(route, "btc_route",
                             f"{coin} 加密组应路由BTC趋势，实际: {route}")

    def test_C4_XAU_gold_self_route(self):
        """C4: 黄金/XAU 非加密非美股 → 自身趋势（self_route）"""
        route = self._detect_route("XAU")
        self.assertEqual(route, "self_route",
                         f"XAU 非加密非美股，应路由 self 趋势检查，实际: {route}")

    def test_C5_long_filter_routing_symmetry(self):
        """C5: 做多方向（长过滤）路由对称：加密美股跟随BTC，纯美股跟随大盘"""
        # COIN → BTC route（对称）
        route_coin = self._detect_route("COIN", direction_filter="long")
        self.assertEqual(route_coin, "btc_route",
                         f"做多方向COIN也应跟随BTC路由，实际: {route_coin}")
        # AAPL → US index（对称）
        route_aapl = self._detect_route("AAPL", direction_filter="long")
        self.assertEqual(route_aapl, "us_index_route",
                         f"做多方向AAPL也应跟随美股大盘路由，实际: {route_aapl}")


if __name__ == "__main__":
    unittest.main()
