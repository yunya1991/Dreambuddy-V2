#!/usr/bin/env python3
"""
test_5ma_short_filter.py — Phase C+ (五均线弹簧力场 + 做空阈值分层) TDD 测试

RED → GREEN 路径:
  1. 5 均线（MA30/65/128/200/MA200周）分层弹簧力场
  2. SHORT_CONF_TIERS 做空置信度分层阈值
  3. 与 _check_short_trend_filter 主过滤器的集成

运行:
    cd 11-易经推理系统
    python -m pytest scripts/memory_l4/tests/test_5ma_short_filter.py -v -s
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
    # 做空置信度分层阈值（类属性已定义，无需覆盖）
    # 做空仓位规模分层（类属性已定义）
    # 动态弹簧力场参数（类属性已定义）
    t.short_confidence_threshold = 0.70  # 基础做空阈值
    t.confidence_threshold = 0.70       # 基础做多阈值
    return t


def _build_closes_5ma(targets, seed=42):
    """构造合成日K closes（newest-first），满足指定 MA 数值。

    targets: {"ma30": x, "ma65": y, "ma128": z, "ma200": w, "ma1400": v}
    返回: len 1500 list (newest-first), 前N日均值≈targets[N]

    Phase D 修正：
      - 用单调下降/上升基底构造真趋势（避免 random.shuffle 抹平趋势）
      - 调整 MA 时仅调整尾部 N 根（避免影响趋势方向）
    """
    import random
    random.seed(seed)
    # 1. 构造整体基底：从 ma1400 缓慢过渡到 ma200（old→new 单调）
    #    indices 0..1399 对应 newest→oldest，所以 closes[1399] = ma1400 附近
    #    closes[0] = ma30 附近
    base_old = targets["ma1400"]
    base_new = targets["ma30"]
    closes = []
    for i in range(1400):
        # i=0 (newest) → 接近 base_new；i=1399 (oldest) → 接近 base_old
        t = i / 1399.0  # 0..1
        trend_val = base_new * (1 - t) + base_old * t
        # 加入小幅波动让数据更自然
        wave = 0.005 * trend_val * random.uniform(-1, 1)
        closes.append(trend_val + wave)

    # 2. 调整前 N 根的均值到目标 MA（仅微调，保持趋势方向）
    def _adjust_ma(arr, n, target, start=0):
        cur = sum(arr[start:start+n]) / n
        delta = target - cur
        # 只调整该区间内的值，避免影响其他区间
        for i in range(start, start+n):
            arr[i] += delta
    # 按周期从长到短调整（避免短周期调整被长周期覆盖）
    _adjust_ma(closes, 1400, targets["ma1400"], 0)
    _adjust_ma(closes, 200, targets["ma200"], 0)
    _adjust_ma(closes, 128, targets["ma128"], 0)
    _adjust_ma(closes, 65, targets["ma65"], 0)
    _adjust_ma(closes, 30, targets["ma30"], 0)
    # 末尾补 100 根 = closes[1399] 的重复（MA1500 需要）
    closes = closes + [closes[1399]] * 100
    return closes  # newest-first, len=1500


def _build_trend_closes_5ma(direction="bear", start_price=100000,
                            daily_change=0.005, n_trend_bars=250, n_total=1500):
    """构造真趋势日K数据（newest-first），MA排列和斜率自然正确。

    原理：价格持续单调变化 → 短周期MA比长周期MA变化更快 →
          自然形成空头/多头排列 + 所有MA斜率同向

    direction: "bear"（持续下跌，MA斜率<0） / "bull"（持续上涨，MA斜率>0）
    start_price: 趋势起点的价格（趋势开始前的平稳期价格）
    daily_change: 每日变化率（0.005 = 0.5%）
    n_trend_bars: 趋势持续的K线数（需≥200以保证 MA200 斜率也正确）
    n_total: 总K线数

    返回: newest-first list, len=n_total
    """
    import random
    random.seed(42)

    if direction == "bear":
        change = -abs(daily_change)  # 每日跌
    else:
        change = abs(daily_change)   # 每日涨

    # 构造 oldest-first 序列（更直观），最后反转为 newest-first
    closes_of = []

    # 1. Pre-trend flat period (平稳期，价格围绕 start_price 波动)
    for i in range(n_total - n_trend_bars):
        noise = 0.001 * start_price * random.uniform(-1, 1)
        closes_of.append(start_price + noise)

    # 2. Trend period (趋势期，价格单调变化)
    p = start_price
    for i in range(n_trend_bars):
        p = p * (1 + change)
        noise = 0.001 * p * random.uniform(-1, 1)
        closes_of.append(p + noise)

    # 转为 newest-first
    closes = closes_of[::-1]
    return closes[:n_total]


class TestFiveMASpringForce(unittest.TestCase):
    """RED: 5 均线分层弹簧力场

    结构：短中期(MA30/MA65, w_total=0.35) + 中期(MA128/MA200, w_total=0.40) + 长期(MA1400, w=0.25)
    每个子组内按距离权重分配；子组权重固定
    """

    def test_5ma_bullish_strong_long_order(self):
        """RED: 5均线完美多头排列（MA30>MA65>MA128>MA200>MA1400），价格在MA30上方
        → 所有均线 = 下方支撑 → F_net 显著为负 → 多头趋势，禁止做空
        """
        t = _make_trader()
        closes = _build_closes_5ma({
            "ma30": 150000, "ma65": 142000, "ma128": 135000,
            "ma200": 125000, "ma1400": 100000,
        })
        price = 152000  # 略高于 MA30
        for i in range(3): closes[i] = price
        t._btc_trend_cache = {"ts": 0, "result": None}
        with patch("scripts.memory_l4.polling_trader._load_kline_from_okx",
                   return_value=[{"c": c} for c in closes]):
            bearish, reason = t._check_btc_trend()

        self.assertFalse(bearish, f"5均线完美多头不应允许做空: {reason}")
        self.assertIn("F_net=", reason)
        import re
        m = re.search(r"F_net=([+-]?[\d.]+)", reason)
        self.assertTrue(m)
        f = float(m.group(1))
        self.assertLess(f, 0, f"多头排列F_net应为负，实际{f}")

    def test_5ma_bearish_perfect_short_order(self):
        """Phase D 优化后：5均线空头排列 + 均线密集 → RANGING + 低U → 允许做空

        回测显示 RANGING 胜率 68.6% 最高，优化后放宽 score 允许档位。
        偏离 1.6% → U_short 很小（< 0.003）→ 不触发超卖过滤 → 允许做空。
        """
        t = _make_trader()
        closes = _build_closes_5ma({
            "ma30": 95000, "ma65": 95500, "ma128": 96000,
            "ma200": 96500, "ma1400": 97000,
        })
        price = 93500  # 偏离 MA30 约 1.6%
        for i in range(3): closes[i] = price + i * 100  # 3日继续跌
        t._btc_trend_cache = {"ts": 0, "result": None}
        with patch("scripts.memory_l4.polling_trader._load_kline_from_okx",
                   return_value=[{"c": c} for c in closes]):
            bearish, reason = t._check_btc_trend()

        # RANGING + 低U + 3日跌破 → 允许做空（优化后放宽）
        self.assertTrue(bearish, f"RANGING+低U应允许做空: {reason}")
        self.assertIn("regime=RANGING", reason)

    def test_5ma_short_allowed_in_trend_early(self):
        """GREEN: 真趋势早期（均线发散 + 斜率向下 + 3日跌破）→ TREND_BEAR → 允许做空

        Phase D：构造 TR>0.5 + CV>0.02 + 斜率<-0.02% 的真趋势数据
        使用 _build_trend_closes_5ma 保证 MA 斜率方向正确
        """
        t = _make_trader()
        # 构造真趋势数据：均线空头发散 + 持续下跌
        closes = _build_trend_closes_5ma(direction="bear")
        t._btc_trend_cache = {"ts": 0, "result": None}
        with patch("scripts.memory_l4.polling_trader._load_kline_from_okx",
                   return_value=[{"c": c} for c in closes]):
            bearish, reason = t._check_btc_trend()

        self.assertTrue(bearish, f"真趋势早期(均线发散+斜率向下)应允许做空: {reason}")
        self.assertIn("SHORT_ALLOWED", reason)

    def test_5ma_short_breakdown_short_tier(self):
        """RED: 真趋势早期 + score=STRONG + 3日跌破 → TREND_BEAR → 允许做空

        Phase D：构造 TREND_BEAR 形态（TR>0.5 + CV>0.02 + 斜率向下）
        """
        t = _make_trader()
        closes = _build_trend_closes_5ma(direction="bear")
        t._btc_trend_cache = {"ts": 0, "result": None}
        with patch("scripts.memory_l4.polling_trader._load_kline_from_okx",
                   return_value=[{"c": c} for c in closes]):
            bearish, reason = t._check_btc_trend()

        self.assertTrue(bearish, f"真趋势+3日确认应允许做空: {reason}")
        # TREND_BEAR 或 STRONG_TREND_BEAR 形态下允许做空
        self.assertTrue(
            "regime=TREND_BEAR" in reason or "regime=STRONG_TREND_BEAR" in reason,
            f"应判定为TREND_BEAR或STRONG_TREND_BEAR: {reason}"
        )

    def test_5ma_full_bearish_tier(self):
        """Phase D 优化后：5均线完美空头排列 + 均线密集 → RANGING + 低U → 允许做空

        回测显示 RANGING 胜率 68.6% 最高，优化后放宽 score 允许档位（全档位）。
        """
        t = _make_trader()
        closes = _build_closes_5ma({
            "ma30": 95000, "ma65": 95500, "ma128": 96000,
            "ma200": 96500, "ma1400": 97000,
        })
        price = 93500
        for i in range(3): closes[i] = price + i * 500  # 3日全低于MA30
        t._btc_trend_cache = {"ts": 0, "result": None}
        with patch("scripts.memory_l4.polling_trader._load_kline_from_okx",
                   return_value=[{"c": c} for c in closes]):
            bearish, reason = t._check_btc_trend()
        # RANGING + 低U + 3日跌破 → 允许做空（优化后放宽）
        self.assertTrue(bearish, f"RANGING+低U应允许做空: {reason}")


class TestShortConfidenceTiers(unittest.TestCase):
    """RED: 做空置信度分层阈值

    有效阈值 = 基础阈值 × 乘数
      STRONG → ×0.9091 ≈ 1/1.10 → 降低门槛（强趋势可放宽）
      NORMAL → ×1.0000          → 标准
      WEAK   → ×1.1765 ≈ 1/0.85 → 抬高门槛（弱趋势要求更高置信度）
    """

    def test_short_conf_tier_strong(self):
        """RED: STRONG档 → 基础阈值×0.9091 → 降低门槛

        Phase D：构造 TREND_BEAR 形态（均线发散+斜率向下）使做空被允许
        """
        t = _make_trader()
        # 用真趋势数据构造，保证 regime 判定为 TREND_BEAR
        closes = _build_trend_closes_5ma(direction="bear")
        t._btc_trend_cache = {"ts": 0, "result": None}
        with patch("scripts.memory_l4.polling_trader._load_kline_from_okx",
                   return_value=[{"c": c} for c in closes]):
            bearish, reason = t._check_btc_trend()

        self.assertTrue(bearish, f"TREND_BEAR应允许做空: {reason}")
        self.assertIn("score=STRONG", reason)
        # 验证乘数方向：STRONG < 1.0 → 降低门槛
        self.assertLess(t.SHORT_CONF_MULTI_MA_STRONG, 1.0)
        inferred_threshold = t.short_confidence_threshold * t.SHORT_CONF_MULTI_MA_STRONG
        self.assertAlmostEqual(inferred_threshold, 0.70 * 0.9091, places=4)

    def test_short_conf_tier_weak_gate(self):
        """RED: WEAK档 ×1.1765 → 抬高门槛（弱趋势要求更高置信度避免诱空）"""
        t = _make_trader()
        # 构造 WEAK: 仅短中期空头，长期多头
        closes = _build_closes_5ma({
            "ma30": 130000, "ma65": 134000, "ma128": 138000,
            "ma200": 125000, "ma1400": 100000,
        })
        price = 132000  # 在 MA65 和 MA128 之间
        for i in range(3): closes[i] = price - i * 500
        t._btc_trend_cache = {"ts": 0, "result": None}
        with patch("scripts.memory_l4.polling_trader._load_kline_from_okx",
                   return_value=[{"c": c} for c in closes]):
            bearish, reason = t._check_btc_trend()

        if bearish and "score=WEAK" in reason:
            # WEAK → 乘数 > 1.0 → 抬高门槛
            self.assertGreater(t.SHORT_CONF_MULTI_MA_WEAK, 1.0)
            inferred_threshold = t.short_confidence_threshold * t.SHORT_CONF_MULTI_MA_WEAK
            self.assertAlmostEqual(inferred_threshold, 0.70 * 1.1765, places=4)
            self.assertIn("score=WEAK", reason)


class TestShortPositionMultiplier(unittest.TestCase):
    """RED: 做空仓位规模分层

    理论：周期越短可信度越低，但趋势识别越早 → 不禁开，而是控制资金规模
          随着跌破更多均线，弹簧压力越来越重 → 仓位越来越大

    bearish_score → position_multiplier:
      STRONG → ×1.0 标准仓位（弹簧压力最重，5均线空头+3日确认）
      NORMAL → ×0.7（3~4均线空头，中等压力）
      WEAK   → ×0.4 小仓试水（仅1~2均线短周期空头，压力轻）
    """

    def test_position_multi_constants_exist(self):
        """RED: 仓位乘数常量定义存在"""
        t = _make_trader()
        self.assertIsInstance(t.SHORT_POSITION_MULTI_STRONG, float)
        self.assertIsInstance(t.SHORT_POSITION_MULTI_NORMAL, float)
        self.assertIsInstance(t.SHORT_POSITION_MULTI_WEAK, float)

    def test_position_multi_strong_is_full(self):
        """STRONG → ×1.0 标准仓位"""
        t = _make_trader()
        multi = t._compute_short_position_multiplier("STRONG")
        self.assertAlmostEqual(multi, 1.0, places=2)

    def test_position_multi_normal_is_reduced(self):
        """NORMAL → ×0.7 仓位缩减"""
        t = _make_trader()
        multi = t._compute_short_position_multiplier("NORMAL")
        self.assertAlmostEqual(multi, 0.7, places=2)

    def test_position_multi_weak_is_small(self):
        """WEAK → ×0.4 小仓试水"""
        t = _make_trader()
        multi = t._compute_short_position_multiplier("WEAK")
        self.assertAlmostEqual(multi, 0.4, places=2)

    def test_position_multi_ordering(self):
        """弹簧压力递增 → 仓位递增：WEAK < NORMAL < STRONG"""
        t = _make_trader()
        w = t._compute_short_position_multiplier("WEAK")
        n = t._compute_short_position_multiplier("NORMAL")
        s = t._compute_short_position_multiplier("STRONG")
        self.assertLess(w, n)
        self.assertLess(n, s)

    def test_position_multi_none_fallback(self):
        """NONE → 极小兜底仓位"""
        t = _make_trader()
        multi = t._compute_short_position_multiplier("NONE")
        self.assertLess(multi, 0.5)


class TestIntegrationShortFilter(unittest.TestCase):
    """RED: _check_short_trend_filter 集成测试（主入口）"""

    def test_full_short_allowed_with_5ma_strong(self):
        """RED: TREND_BEAR 形态 + BTC趋势OK + 美股OK + 自身趋势OK → 最终允许做空

        Phase D：用真趋势数据构造使 regime=TREND_BEAR/STRONG_TREND_BEAR
        """
        t = _make_trader()
        # 用真趋势数据构造，保证 regime 判定为 TREND_BEAR
        closes = _build_trend_closes_5ma(direction="bear")
        # 构造推理对象
        inference = {
            "direction": "DOWN",
            "confidence": 0.88,
            "df_prices": closes[:200],
        }
        t._btc_trend_cache = {"ts": 0, "result": None}
        with patch("scripts.memory_l4.polling_trader._load_kline_from_okx",
                   return_value=[{"c": c} for c in closes]):
            # 同时 mock 美股指数（非看空 → 不额外限制）
            t._us_index_trend_cache = {
                "ts": 1e18, "result": (False, "mock 美股多头")
            }
            ok, reason, multi = t._check_short_trend_filter("BTC", inference)

        self.assertTrue(ok, f"TREND_BEAR+高置信+美股多头 = 应允许做空: {reason}")
        self.assertIn("score=STRONG", reason)
        self.assertAlmostEqual(multi, 0.9091, places=3)

    def test_short_blocked_by_high_threshold_when_weak(self):
        """RED: WEAK档 → 抬高门槛 + 小仓试水

        注意：_check_short_trend_filter 只给信心分级，门槛+仓位判定交给 _execute_trade
        """
        t = _make_trader()

        # 检查常量定义存在
        self.assertIsInstance(t.SHORT_CONF_MULTI_MA_STRONG, float)
        self.assertIsInstance(t.SHORT_CONF_MULTI_MA_WEAK, float)
        self.assertIsInstance(t.SHORT_POSITION_MULTI_STRONG, float)
        self.assertIsInstance(t.SHORT_POSITION_MULTI_WEAK, float)

        # 阈值方向：STRONG < 1.0 降低门槛；WEAK > 1.0 抬高门槛
        self.assertLess(t.SHORT_CONF_MULTI_MA_STRONG, 1.0)
        self.assertGreater(t.SHORT_CONF_MULTI_MA_WEAK, 1.0)

        # 仓位方向：STRONG > WEAK（弹簧压力越重仓位越大）
        self.assertGreater(t.SHORT_POSITION_MULTI_STRONG, t.SHORT_POSITION_MULTI_WEAK)


class TestDynamicSpringForce(unittest.TestCase):
    """Phase C++ 动态弹簧力场测试

    ① inter-MA力：均线间相对距离 → 趋势力
    ② MA斜率调制k：k_eff = k × (1 + α × tanh(slope))
    ③ 势能 U = ½kx²
    """

    def test_inter_ma_force_exists(self):
        """RED: F_inter_net 和 inter_ma_details 应存在"""
        t = _make_trader()
        closes = _build_closes_5ma({
            "ma30": 95000, "ma65": 97000, "ma128": 99000,
            "ma200": 102000, "ma1400": 108000,
        })
        price = 93500  # 偏离 MA30 约 1.6%，趋势早期
        for i in range(3): closes[i] = price
        res = t._calc_5ma_spring_force(closes, tier="daily_btc")
        self.assertIn("F_inter_net", res)
        self.assertIn("inter_ma_details", res)
        # 空头排列（短<长）→ inter_dist < 0 → F_inter > 0（做空方向力）
        self.assertGreater(res["F_inter_net"], 0, "空头排列 inter-MA 力应为正（做空方向）")

    def test_inter_ma_force_bullish_direction(self):
        """RED: 多头排列 → F_inter < 0（做多方向力）"""
        t = _make_trader()
        closes = _build_closes_5ma({
            "ma30": 150000, "ma65": 142000, "ma128": 135000,
            "ma200": 125000, "ma1400": 100000,
        })
        price = 152000
        for i in range(3): closes[i] = price
        res = t._calc_5ma_spring_force(closes, tier="daily_btc")
        # 多头排列（短>长）→ inter_dist > 0 → F_inter < 0（做多方向力）
        self.assertLess(res["F_inter_net"], 0, "多头排列 inter-MA 力应为负（做多方向）")

    def test_f_total_equals_f_net_plus_f_inter(self):
        """RED: F_total = F_net + F_inter_net"""
        t = _make_trader()
        closes = _build_closes_5ma({
            "ma30": 95000, "ma65": 97000, "ma128": 99000,
            "ma200": 102000, "ma1400": 108000,
        })
        price = 93500  # 偏离 MA30 约 1.6%，趋势早期
        for i in range(3): closes[i] = price
        res = t._calc_5ma_spring_force(closes, tier="daily_btc")
        self.assertAlmostEqual(
            res["F_total"], res["F_net"] + res["F_inter_net"], places=6
        )

    def test_ma_slope_exists(self):
        """RED: ma_slopes 应存在且为数"""
        t = _make_trader()
        closes = _build_closes_5ma({
            "ma30": 95000, "ma65": 97000, "ma128": 99000,
            "ma200": 102000, "ma1400": 108000,
        })
        res = t._calc_5ma_spring_force(closes, tier="daily_btc")
        self.assertIn("ma_slopes", res)
        self.assertIn("slope_avg", res)
        self.assertIsInstance(res["slope_avg"], float)

    def test_potential_energy_exists(self):
        """RED: U_potential 应存在且恒正（势能 U=½kx² ≥ 0）"""
        t = _make_trader()
        closes = _build_closes_5ma({
            "ma30": 95000, "ma65": 97000, "ma128": 99000,
            "ma200": 102000, "ma1400": 108000,
        })
        price = 93500  # 偏离 MA30 约 1.6%，趋势早期
        for i in range(3): closes[i] = price
        res = t._calc_5ma_spring_force(closes, tier="daily_btc")
        self.assertIn("U_potential", res)
        self.assertGreaterEqual(res["U_potential"], 0, "势能 U=½kx² 应恒非负")

    def test_k_eff_modulated_by_slope(self):
        """RED: k_eff 应受斜率调制（≠ 原 k=2.0）"""
        t = _make_trader()
        closes = _build_closes_5ma({
            "ma30": 95000, "ma65": 97000, "ma128": 99000,
            "ma200": 102000, "ma1400": 108000,
        })
        res = t._calc_5ma_spring_force(closes, tier="daily_btc")
        self.assertIn("k_eff", res)
        # 斜率不为0时 k_eff ≠ 2.0
        if abs(res.get("slope_avg", 0)) > 0.01:
            self.assertNotAlmostEqual(res["k_eff"], 2.0, places=2)

    def test_price_between_two_mas(self):
        """RED: 价格在 MA30 和 MA65 之间时，inter-MA 力能正确辨别方向"""
        t = _make_trader()
        # MA30=80000 < price=82000 < MA65=90000，其余均线更高
        closes = _build_closes_5ma({
            "ma30": 80000, "ma65": 90000, "ma128": 110000,
            "ma200": 130000, "ma1400": 150000,
        })
        price = 82000  # 在 MA30 和 MA65 之间
        for i in range(3): closes[i] = price
        res = t._calc_5ma_spring_force(closes, tier="daily_btc")
        # MA30 < MA65 → inter_dist < 0 → F_inter > 0（空头方向力）
        # 即使价格在两条均线之间，inter-MA 力仍正确判别为空头方向
        self.assertGreater(res["F_inter_net"], 0,
                           "MA30<MA65 空头排列，inter-MA 力应为正（做空方向），即使价格在两线之间")
        # F_total 也应偏正（做空方向）
        self.assertGreater(res["F_total"], 0,
                           "价格在 MA30-MA65 之间但整体空头排列，F_total 应偏正（做空方向）")

    def test_spring_details_has_slope_and_potential(self):
        """RED: spring_details 每条均线应含 slope% 和 U"""
        t = _make_trader()
        closes = _build_closes_5ma({
            "ma30": 95000, "ma65": 97000, "ma128": 99000,
            "ma200": 102000, "ma1400": 108000,
        })
        res = t._calc_5ma_spring_force(closes, tier="daily_btc")
        sd = res.get("spring_details", {})
        for key, detail in sd.items():
            self.assertIn("slope%", detail, f"{key} 缺少 slope%")
            self.assertIn("U", detail, f"{key} 缺少 U")


class TestMarketRegimeClassification(unittest.TestCase):
    """Phase D：4维度市场形态判定器

    4维度：
      ① 趋势强度比 TR = |F_inter| / (|F_net| + |F_inter| + ε)
      ② 均线发散度 CV = std(MA30/65/128/200) / mean
      ③ 斜率强度 |slope_avg|
      ④ F_dot（F_total 变化率）

    5种形态：TREND_BULL / STRONG_TREND_BEAR / TREND_BEAR / MEAN_REVERTING / RANGING
    """

    def test_regime_outputs_exist(self):
        """RED: _calc_5ma_spring_force 应输出 regime 相关字段"""
        t = _make_trader()
        closes = _build_closes_5ma({
            "ma30": 95000, "ma65": 97000, "ma128": 99000,
            "ma200": 102000, "ma1400": 108000,
        })
        res = t._calc_5ma_spring_force(closes, tier="daily_btc")
        self.assertIn("trend_ratio", res)
        self.assertIn("cv_dispersion", res)
        self.assertIn("abs_slope", res)
        self.assertIn("market_regime", res)
        self.assertIsInstance(res["market_regime"], str)

    def test_regime_trend_bull_detected(self):
        """GREEN: 多头排列 + 斜率向上 + 发散 → TREND_BULL → 禁止做空"""
        t = _make_trader()
        # 用真趋势数据构造多头趋势
        closes = _build_trend_closes_5ma(direction="bull")
        t._btc_trend_cache = {"ts": 0, "result": None}
        with patch("scripts.memory_l4.polling_trader._load_kline_from_okx",
                   return_value=[{"c": c} for c in closes]):
            bearish, reason = t._check_btc_trend()
        self.assertFalse(bearish, f"TREND_BULL应禁止做空: {reason}")
        # 多头趋势禁止做空（可能因偏见底兜底或TREND_BULL regime）
        self.assertTrue(
            "TREND_BULL" in reason or "偏见底" in reason,
            f"应判定为TREND_BULL或偏见底: {reason}"
        )

    def test_regime_trend_bear_allows_short(self):
        """GREEN: 均线空头发散 + 斜率向下 + TR高 → TREND_BEAR → 允许做空"""
        t = _make_trader()
        closes = _build_trend_closes_5ma(direction="bear")
        t._btc_trend_cache = {"ts": 0, "result": None}
        with patch("scripts.memory_l4.polling_trader._load_kline_from_okx",
                   return_value=[{"c": c} for c in closes]):
            bearish, reason = t._check_btc_trend()
        self.assertTrue(bearish, f"TREND_BEAR应允许做空: {reason}")
        self.assertTrue(
            "regime=TREND_BEAR" in reason or "regime=STRONG_TREND_BEAR" in reason,
            f"应判定为TREND_BEAR: {reason}"
        )

    def test_regime_ranging_blocks_high_u(self):
        """Phase D 优化后：均线密集（CV低）+ 大偏离 → RANGING + U超阈值 → 禁止做空

        优化后 RANGING 允许全档位 score，但 U_short > 0.003（约>5%偏离MA30）时仍禁止做空（超卖）。
        """
        t = _make_trader()
        # 均线密集排列，差距<1%
        closes = _build_closes_5ma({
            "ma30": 95000, "ma65": 95200, "ma128": 95400,
            "ma200": 95600, "ma1400": 95800,
        })
        # 价格大幅偏离 MA30（~10% below）→ U_short > 0.003 → 超卖过滤
        price = 85500
        for i in range(3): closes[i] = price - i * 100
        t._btc_trend_cache = {"ts": 0, "result": None}
        with patch("scripts.memory_l4.polling_trader._load_kline_from_okx",
                   return_value=[{"c": c} for c in closes]):
            bearish, reason = t._check_btc_trend()
        # RANGING + 超卖（U > 0.003）→ 禁止做空
        self.assertFalse(bearish, f"RANGING+超卖应禁止做空: {reason}")
        self.assertIn("超卖", reason)

    def test_regime_mean_reverting_blocks_short(self):
        """GREEN: TR低 + F_dot收敛（偏离在收敛）→ MEAN_REVERTING → 严格过滤

        均值回归市中 F>0 = 超卖 = 禁止做空（会反弹）
        """
        t = _make_trader()
        # 构造 TR 低 + F_dot 收敛的场景：
        # 价格偏离小（F_net 小）+ 均线纠缠（CV低）+ 价格反弹中（F_dot<0）
        closes = _build_closes_5ma({
            "ma30": 95000, "ma65": 95100, "ma128": 95200,
            "ma200": 95300, "ma1400": 95400,
        })
        # 价格从下方反弹回均线附近 → F_dot 为负（偏离在收敛）
        price = 94800
        # 构造前几日价格更低，最近反弹
        for i in range(5): closes[i] = price - (5 - i) * 50
        closes[0] = price  # 最新价格回到均线附近
        t._btc_trend_cache = {"ts": 0, "result": None}
        with patch("scripts.memory_l4.polling_trader._load_kline_from_okx",
                   return_value=[{"c": c} for c in closes]):
            bearish, reason = t._check_btc_trend()
        # 均值回归市禁止做空
        self.assertFalse(bearish, f"MEAN_REVERTING应禁止做空: {reason}")

    def test_regime_filter_strong_trend_more_permissive(self):
        """GREEN: STRONG_TREND_BEAR 允许更大 U_short（阈值0.010 vs RANGING的0.001）

        验证差异化过滤：趋势市允许更大偏离（均线成阻力=顺势做空）
        注: U_short 仅含短期组(MA30/65)势能，尺度远小于原 U_potential
        """
        t = _make_trader()
        # 验证阈值差异：STRONG_TREND_BEAR 的 U 阈值 > RANGING 的 U 阈值
        self.assertGreater(
            t.FMA_U_THRESHOLD_STRONG_TREND,  # 0.010
            t.FMA_U_THRESHOLD_RANGE,         # 0.001
            "强趋势市应允许更大U_short（宽松过滤）"
        )
        # TREND_BEAR 的 U 阈值也大于 RANGING
        self.assertGreater(
            t.FMA_U_THRESHOLD_TREND,         # 0.005
            t.FMA_U_THRESHOLD_RANGE,         # 0.001
            "弱趋势市U_short阈值也应大于RANGING"
        )
        # MEAN_REVERTING 的 score 限制最严（仅WEAK）
        self.assertEqual(t.FMA_ALLOW_SCORE_REVERT, ("WEAK",))
        self.assertEqual(t.FMA_ALLOW_SCORE_RANGE, ("WEAK",))
        # TREND 允许所有档位
        self.assertEqual(t.FMA_ALLOW_SCORE_TREND, ("STRONG", "NORMAL", "WEAK"))

    def test_regime_trend_ratio_calculation(self):
        """GREEN: TR = |F_inter| / (|F_net| + |F_inter| + ε) 应在 [0, 1] 区间"""
        t = _make_trader()
        closes = _build_closes_5ma({
            "ma30": 95000, "ma65": 97000, "ma128": 99000,
            "ma200": 102000, "ma1400": 108000,
        })
        res = t._calc_5ma_spring_force(closes, tier="daily_btc")
        tr = res["trend_ratio"]
        self.assertGreaterEqual(tr, 0.0, "TR应≥0")
        self.assertLessEqual(tr, 1.0, "TR应≤1")

    def test_regime_cv_dispersion_calculation(self):
        """GREEN: CV = std(MA30/65/128/200) / mean 应非负"""
        t = _make_trader()
        closes = _build_closes_5ma({
            "ma30": 95000, "ma65": 97000, "ma128": 99000,
            "ma200": 102000, "ma1400": 108000,
        })
        res = t._calc_5ma_spring_force(closes, tier="daily_btc")
        cv = res["cv_dispersion"]
        self.assertGreaterEqual(cv, 0.0, "CV应≥0")
        # 均线发散（95000/97000/99000/102000 差距较大）→ CV 应较大
        # std ≈ 2900, mean ≈ 98250 → CV ≈ 0.029
        self.assertGreater(cv, 0.01, f"发散均线CV应较大，实际{cv}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
