"""
exogenous_data_bridge.py — 23 自进化系统的外生数据桥。

从 19-数据访问层 MarketMacroRepository.mm_metrics 读取真实基本面/宏观/链上指标，
映射为 ExogenousStrengthEvaluator.evaluate(data) 期望的字段，
使 Phase 1/3 外生力量评估器获得真实数据而非空值。

字段映射（19-DAL sub_category.metric_name → 评估器字段）：
  etf_flow.total_flow            → etf_net_flow
  cpi.actual / cpi.forecast      → cpi_actual / cpi_expected
  fedwatch.hike_prob             → rate_hike_prob
  fomc_decision.rate_change      → monetary_cycle（降息/加息/持平）
  exchanges_whales.ex_bal_BTC_chg30d_pct → exchange_net_flow（派生）
  btc_basics.market_cap_usd + tx_count_24h → nvt_ratio（派生）
  funding_rate                   → funding_rate
  DX-Y.NYB                       → dxy（最新值）

缺失字段留空，评估器内部按可用字段降级计算（fail-open）。

P1 集成 (PLAN-exogenous-integration.md §三):
  build_exogenous_series(closes, bridge=None, evaluator=None) → np.ndarray (N, 9)
    构建逐点对齐的外生力量时序, 用于 NeuralSDE drift_net 输入扩展.
    bridge 可用时 → fetch() 最新快照 + 前向填充 (宏观低频, 技术面逐点算)
    bridge 不可用 → 仅从 closes 衍生技术面 (ma_200, monthly_trend_slope),
                    其余维度保持中性值 0.5 (FAIL-OPEN)
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import torch

logger = logging.getLogger(__name__)


def build_exogenous_series(
    closes: np.ndarray,
    bridge: Optional["ExogenousDataBridge"] = None,
    evaluator: Optional[Any] = None,
    per_point_data: Optional[list[dict[str, Any]]] = None,
) -> np.ndarray:
    """构建外生力量时序 (shape=(N, 9), [0,1] 标准化).

    9 维 = 3 维度 (technical/fundamental/macro) × 3 周期 (short/medium/long).
    返回数组每行:
      [tech_s, tech_m, tech_l, fund_s, fund_m, fund_l, macro_s, macro_m, macro_l]

    时序对齐策略:
      - 技术面 (ma_200, monthly_trend_slope): 从 closes 截断到 i 点逐点计算
      - 基本面/宏观 (etf_flow, cpi, rate_prob...):
        * 若提供 per_point_data: 每点用 per_point_data[i] (真实时序对齐)
        * 否则 bridge.fetch() 返回最新快照, 前向填充到所有点 (低频宏观前向填充)

    Args:
        closes: (N,) close 价格序列
        bridge: 可选 ExogenousDataBridge, None 则仅用 closes 衍生技术面
        evaluator: 可选 ExogenousStrengthEvaluator, None 则新建实例
        per_point_data: 可选长度 N 的 list[dict], 每点的外生数据 dict
                       (覆盖 bridge 快照, 用于真实时序对齐的 PoC)

    Returns:
        (N, 9) numpy 数组, 值域 [0, 1], 0.5 = 中性
    """
    closes = np.asarray(closes, dtype=np.float64).ravel()
    n = closes.size
    if n == 0:
        return np.zeros((0, 9), dtype=np.float64)

    # 从 bridge 获取最新宏观/基本面快照 (forward-fill 到所有点, 仅当无 per_point_data)
    snapshot: dict[str, Any] = {}
    if per_point_data is None and bridge is not None:
        try:
            snapshot = bridge.fetch()
        except Exception as exc:
            logger.warning(
                "[build_exogenous_series] bridge.fetch 失败, 仅技术面: %s", exc,
            )
            snapshot = {}

    series = np.full((n, 9), 0.5, dtype=np.float64)  # 默认中性值

    for i in range(n):
        # 每行新建评估器: 快照被前向填充为常量, 若复用同一评估器,
        # _normalize 的历史缓冲在 10 个相同值后 std=0 → 恒返回 0.5 (中性).
        # 新建实例确保 fund/macro 维度用线性映射保留真实信号.
        try:
            from dreambuddy_evolution.core.exogenous_strength_evaluator import (
                ExogenousStrengthEvaluator,
            )
            ev = ExogenousStrengthEvaluator()
        except Exception as exc:
            logger.warning(
                "[build_exogenous_series] 评估器不可用, 返回全 0.5: %s", exc,
            )
            return np.full((n, 9), 0.5, dtype=np.float64)

        # 复制快照 (或逐点数据), 加入逐点计算的技术面
        if per_point_data is not None and i < len(per_point_data):
            data: dict[str, Any] = dict(per_point_data[i])
        else:
            data = dict(snapshot)
        data["close"] = closes[: i + 1]

        # ma_200: 当前点往前 200 周期均值
        if i >= 199:
            data["ma_200"] = float(np.mean(closes[i - 199: i + 1]))
        elif i >= 0:
            # 数据不足 200 时用现有长度均值 (避免 None)
            data["ma_200"] = float(np.mean(closes[: i + 1])) if i > 0 else float(closes[0])

        # monthly_trend_slope: 线性回归斜率 (最近 ~30 点近似月线)
        if i >= 30:
            x = np.arange(31, dtype=float)
            y_arr = closes[i - 30: i + 1]
            try:
                slope = float(np.polyfit(x, y_arr, 1)[0])
                data["monthly_trend_slope"] = slope
            except Exception:
                pass

        # 评估 9 维
        try:
            evals = ev.evaluate(data)
            row = np.array(
                [
                    evals["technical"]["short"],
                    evals["technical"]["medium"],
                    evals["technical"]["long"],
                    evals["fundamental"]["short"],
                    evals["fundamental"]["medium"],
                    evals["fundamental"]["long"],
                    evals["macro"]["short"],
                    evals["macro"]["medium"],
                    evals["macro"]["long"],
                ],
                dtype=np.float64,
            )
            # NaN/Inf → 中性 0.5
            row = np.where(np.isfinite(row), row, 0.5)
            series[i] = row
        except Exception as exc:
            logger.debug(
                "[build_exogenous_series] i=%d 评估失败, 用 0.5: %s", i, exc,
            )
            # 保留默认 0.5

    return series


class ExogenousDataBridge:
    """从 19-DAL 读取外生数据并映射为评估器字段。"""

    def __init__(self, repo: Optional[Any] = None) -> None:
        self._repo = repo

    def get_repo(self) -> Optional[Any]:
        if self._repo is None:
            try:
                import os
                # 确保 DAL_DB_PATH 指向 19-数据访问层 的统一数据库
                if "DAL_DB_PATH" not in os.environ:
                    # exogenous_data_bridge.py 位于 <repo>/23-四层闭环自进化交易架构/dreambuddy_evolution/core/
                    # repo root = 向上 3 级
                    _repo_root = os.path.abspath(
                        os.path.join(os.path.dirname(__file__), "..", "..", "..")
                    )
                    _db_path = os.path.join(_repo_root, "19-数据访问层", "data", "dreambuddy_core.db")
                    if os.path.exists(_db_path):
                        os.environ["DAL_DB_PATH"] = _db_path
                from dreambuddy_dal import get_market_macro_repo
                self._repo = get_market_macro_repo(backend="sqlite_unified")
            except Exception as exc:
                logger.warning("[ExogenousBridge] 无法获取 DAL repo: %s", exc)
                self._repo = None
        return self._repo

    def get_fomc_calendar(self) -> list[datetime]:
        """从 19-DAL 查询 FOMC 会议日历（所有决议日）.

        数据来源: 18-数据获取中心 FedEventCollector(type=fomc_calendar)
                  → 20-dal_sink → 19-DAL mm_metrics
                  sub_category=fomc_calendar, metric_name=timestamp,
                  metric_value=决议日 19:00 UTC 的 Unix 时间戳

        Returns:
            FOMC 决议日列表 (datetime, UTC)，按时间排序.
            DAL 不可用或无数据时返回空列表 (FAIL-OPEN).
        """
        from datetime import datetime, timedelta, timezone
        repo = self.get_repo()
        if repo is None:
            return []
        try:
            # 查询 2020-2030 全部 FOMC 日历
            start = datetime(2020, 1, 1, tzinfo=timezone.utc)
            end = datetime(2030, 12, 31, tzinfo=timezone.utc)
            rows = repo.query_metric_by_time("fomc_calendar", "timestamp", start, end)
            meetings: list[datetime] = []
            for r in rows:
                # query_metric_by_time 返回 (sub_category, metric_name, value, ts)
                # value = metric_value (决议日 timestamp float), ts = 记录时间戳
                val = r[2] if len(r) > 2 else None
                if val is None:
                    continue
                try:
                    dt = datetime.fromtimestamp(float(val), tz=timezone.utc)
                    meetings.append(dt)
                except (ValueError, OSError):
                    continue
            meetings.sort()
            return meetings
        except Exception as e:
            logger.debug("[ExogenousBridge] FOMC 日历查询失败: %s", e)
            return []

    def get_next_fomc(self, now: Optional[datetime] = None) -> Optional[datetime]:
        """获取下一次 FOMC 决议时间 (从 19-DAL)."""
        from datetime import timezone
        if now is None:
            from datetime import datetime as _dt
            now = _dt.now(timezone.utc)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        future = [d for d in self.get_fomc_calendar() if d > now]
        return min(future) if future else None

    def get_last_fomc(self, now: Optional[datetime] = None) -> Optional[datetime]:
        """获取最近一次已发生的 FOMC 决议时间 (从 19-DAL)."""
        from datetime import timezone
        if now is None:
            from datetime import datetime as _dt
            now = _dt.now(timezone.utc)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        past = [d for d in self.get_fomc_calendar() if d <= now]
        return max(past) if past else None

    def _latest(self, sub_category: str, metric_name: str) -> Optional[float]:
        repo = self.get_repo()
        if repo is None:
            return None
        try:
            row = repo.query_latest_metric(sub_category, metric_name)
            return float(row[1]) if row is not None else None
        except Exception:
            return None

    def _historical_nvt_median(self, days: int = 30) -> Optional[float]:
        """从 19-DAL 历史数据计算 NVT 中位数，用于评估器的 NVT 偏离度计算。"""
        repo = self.get_repo()
        if repo is None:
            return None
        try:
            from datetime import datetime, timedelta, timezone
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=days)
            mcap_rows = repo.query_metric_by_time("btc_basics", "market_cap_usd", start, end)
            vol_rows = repo.query_metric_by_time("btc_basics", "output_volume_btc", start, end)
            tx_rows = repo.query_metric_by_time("btc_basics", "tx_count_24h", start, end)
            btc_price = self._latest("bitcoin", "current_price_usd") or 0.0

            # 按 timestamp 对齐
            vol_map = {r[3]: float(r[2]) for r in vol_rows if r[2]}
            tx_map = {r[3]: float(r[2]) for r in tx_rows if r[2]}

            nvts = []
            for r in mcap_rows:
                mcap = float(r[2])
                ts = r[3]
                if not mcap or mcap <= 0:
                    continue
                vol = vol_map.get(ts, 0)
                if vol > 0 and btc_price > 0:
                    daily_vol_usd = vol * btc_price
                elif ts in tx_map and tx_map[ts] > 0:
                    daily_vol_usd = tx_map[ts] * 100000.0  # 回退假设
                else:
                    continue
                if daily_vol_usd > 0:
                    nvts.append(mcap / daily_vol_usd)

            if len(nvts) >= 5:
                nvts.sort()
                return nvts[len(nvts) // 2]
            # 历史样本不足 5 个时，使用 BTC 长期 NVT 中位数作为回退（历史区间 ~10-100，中位 ~25）
            return 25.0
        except Exception:
            return 25.0

    def fetch(self) -> dict[str, Any]:
        """返回外生数据 dict（仅含有值字段）。"""
        data: dict[str, Any] = {}

        # --- 资金流 ---
        etf_flow = self._latest("etf_flow", "total_flow")
        if etf_flow is not None:
            data["etf_net_flow"] = etf_flow

        funding = self._latest("funding_rate", "funding_rate")
        if funding is not None:
            data["funding_rate"] = funding

        # --- 宏观 ---
        cpi_actual = self._latest("cpi", "actual")
        cpi_forecast = self._latest("cpi", "forecast")
        if cpi_actual is not None:
            data["cpi_actual"] = cpi_actual
        if cpi_forecast is not None:
            data["cpi_expected"] = cpi_forecast

        hike_prob = self._latest("fedwatch", "hike_prob")
        if hike_prob is not None:
            data["rate_hike_prob"] = hike_prob

        rate_change = self._latest("fomc_decision", "rate_change")
        if rate_change is not None:
            if rate_change < 0:
                data["monetary_cycle"] = "easing"
            elif rate_change > 0:
                data["monetary_cycle"] = "tightening"
            else:
                data["monetary_cycle"] = "neutral"

        # --- 链上 ---
        ex_bal_chg = self._latest("exchanges_whales", "ex_bal_BTC_chg30d_pct")
        if ex_bal_chg is not None:
            # 余额下降 → 流出（看涨）；上升 → 流入（看跌）
            data["exchange_net_flow"] = -ex_bal_chg * 10.0

        market_cap = self._latest("btc_basics", "market_cap_usd")
        tx_count = self._latest("btc_basics", "tx_count_24h")
        output_volume_btc = self._latest("btc_basics", "output_volume_btc")
        btc_price = self._latest("bitcoin", "current_price_usd")

        if market_cap is not None and market_cap > 0:
            # NVT = Market Cap / 每日链上交易量(USD)
            # 优先用 output_volume_btc × btc_price；回退到 tx_count × 平均交易额假设
            if output_volume_btc and output_volume_btc > 0 and btc_price and btc_price > 0:
                daily_volume_usd = output_volume_btc * btc_price
            elif tx_count and tx_count > 0:
                avg_tx_usd = 100000.0  # 保守假设均值
                daily_volume_usd = tx_count * avg_tx_usd
            else:
                daily_volume_usd = 0
            if daily_volume_usd > 0:
                data["nvt_ratio"] = market_cap / daily_volume_usd

        active_addr = self._latest("btc_basics", "active_addresses")
        if active_addr is not None and active_addr > 0:
            data["active_addresses"] = active_addr

        # NVT 历史中位数（用于评估器计算 NVT 偏离度）
        nvt_median = self._historical_nvt_median()
        if nvt_median is not None and nvt_median > 0:
            data["nvt_historical_median"] = nvt_median

        # --- 跨市场 ---
        dxy = self._latest("DX-Y.NYB", "value")
        if dxy is not None:
            data["dxy"] = dxy

        # 标注数据来源，便于调试
        if data:
            data["_exogenous_source"] = "19-DAL"

        return data

    def fetch_historical_aligned(self, timestamps: list) -> list[dict[str, Any]]:
        """时序对齐的历史外生数据 (P1 A1).

        从 19-DAL 查询所有相关指标的历史时序, 按给定时间戳前向填充
        (低频宏观/链上数据天然适合前向填充), 返回每点的 data dict.

        Args:
            timestamps: list[datetime], 需对齐的时间点 (通常是价格序列的时间戳)

        Returns:
            list[dict], 长度 = len(timestamps), 每点含该时点的外生数据
            (缺失字段不出现, 评估器按可用字段降级计算)
        """
        repo = self.get_repo()
        if repo is None or not timestamps:
            return [{} for _ in timestamps]

        from datetime import datetime as _dt, timedelta as _td

        t_min = min(timestamps) - _td(days=90)  # 缓冲 90 天, 确保首个点能前向填充
        t_max = max(timestamps)

        def _load(sub: str, metric: str) -> list[tuple[_dt, float]]:
            try:
                rows = repo.query_metric_by_time(sub, metric, t_min, t_max)
                return [(r[3], float(r[2])) for r in rows if r[2] is not None]
            except Exception:
                return []

        # 加载所有历史时序
        series = {
            "etf_net_flow": _load("etf_flow", "total_flow"),
            "funding_rate": _load("funding_rate", "funding_rate"),
            "cpi_actual": _load("cpi", "actual"),
            "cpi_expected": _load("cpi", "forecast"),
            "rate_hike_prob": _load("fedwatch", "hike_prob"),
            "rate_change": _load("fomc_decision", "rate_change"),
            "active_addresses": _load("btc_onchain", "active_addresses"),
            "market_cap": _load("btc_basics", "market_cap_usd"),
            "tx_count": _load("btc_basics", "tx_count_24h"),
            "dxy": _load("DX-Y.NYB", "close"),
            "ex_bal_chg": _load("exchanges_whales", "ex_bal_BTC_chg30d_pct"),
        }

        # 排序 (query_metric_by_time 已按时序, 保险起见再排)
        for k in series:
            series[k].sort(key=lambda x: x[0])

        def _ffill(ts_list: list[tuple[_dt, float]], t: _dt) -> Optional[float]:
            """前向填充: 返回 <= t 的最近一个值."""
            if not ts_list:
                return None
            lo, hi = 0, len(ts_list)
            while lo < hi:
                mid = (lo + hi) // 2
                if ts_list[mid][0] <= t:
                    lo = mid + 1
                else:
                    hi = mid
            return ts_list[lo - 1][1] if lo > 0 else None

        # NVT 历史中位数 (用全量市场历史计算, 作为偏离度基准)
        nvt_median = self._historical_nvt_median(days=365 * 5) or 25.0

        result: list[dict[str, Any]] = []
        for t in timestamps:
            d: dict[str, Any] = {}

            etf = _ffill(series["etf_net_flow"], t)
            if etf is not None:
                d["etf_net_flow"] = etf

            fr = _ffill(series["funding_rate"], t)
            if fr is not None:
                d["funding_rate"] = fr

            cpi_a = _ffill(series["cpi_actual"], t)
            if cpi_a is not None:
                d["cpi_actual"] = cpi_a
            cpi_e = _ffill(series["cpi_expected"], t)
            if cpi_e is not None:
                d["cpi_expected"] = cpi_e

            rp = _ffill(series["rate_hike_prob"], t)
            if rp is not None:
                d["rate_hike_prob"] = rp

            rc = _ffill(series["rate_change"], t)
            if rc is not None:
                if rc < 0:
                    d["monetary_cycle"] = "easing"
                elif rc > 0:
                    d["monetary_cycle"] = "tightening"
                else:
                    d["monetary_cycle"] = "neutral"

            aa = _ffill(series["active_addresses"], t)
            if aa is not None and aa > 0:
                d["active_addresses"] = aa

            mcap = _ffill(series["market_cap"], t)
            tx = _ffill(series["tx_count"], t)
            if mcap is not None and mcap > 0:
                if tx and tx > 0:
                    daily_vol_usd = tx * 100000.0
                    d["nvt_ratio"] = mcap / daily_vol_usd
                d["nvt_historical_median"] = nvt_median

            exb = _ffill(series["ex_bal_chg"], t)
            if exb is not None:
                d["exchange_net_flow"] = -exb * 10.0

            dxy = _ffill(series["dxy"], t)
            if dxy is not None:
                d["dxy"] = dxy

            result.append(d)

        return result


# ----------------------------------------------------------------------
# P1+ Cross-Attention 因子桥接
# ----------------------------------------------------------------------

# 候选因子清单 (sub_category, metric_name, factor_name, dimension)
# 来自 19-DAL mm_metrics 中 ≥50 数据点的宏观/链上/衍生品指标
# 按 C1-C8 矛盾维度分组，覆盖全部 10 个基本面模块
# 共 36 个因子；dimension 字段用于 build_factor_head_mask 构建维度对齐 mask
CROSS_ATTENTION_FACTOR_METRICS: list[tuple[str, str, str, str]] = [
    # --- C1 资金面 / flow 模块 (7) ---
    ("etf_flow", "total_flow", "etf_total_flow", "C1"),
    ("funding_rate", "funding_rate_pct", "funding_rate", "C1"),
    ("long_short_ratio", "long_short_ratio", "long_short_ratio", "C1"),
    ("derivatives_spot", "fut_open_interest_usd", "open_interest", "C1"),
    ("exchanges_whales", "ex_summary_inflowUsd24h", "exchange_inflow_24h", "C1"),
    ("derivatives_spot", "fut_liq_long_24h_usd", "liq_long_24h", "C1"),
    ("derivatives_spot", "fut_liq_short_24h_usd", "liq_short_24h", "C1"),
    # --- C2 情绪面 / sentiment+narrative 模块 (5) ---
    ("crypto_fear_greed", "value", "fear_greed", "C2"),
    ("fear_greed_enhanced", "momentum", "fg_momentum", "C2"),
    ("fear_greed_enhanced", "volatility", "fg_volatility", "C2"),
    ("fear_greed_enhanced", "capital_flow", "fg_capital_flow", "C2"),
    ("fear_greed_enhanced", "funding", "fg_funding", "C2"),
    # --- C3 技术面 / onchain 模块 (6) ---
    ("btc_basics", "active_addresses", "active_addresses", "C3"),
    ("btc_basics", "tx_count_24h", "tx_count_24h", "C3"),
    ("exchanges_whales", "ex_bal_BTC_chg30d_pct", "exchange_balance_chg", "C3"),
    ("utxo_age_distribution", "profit_supply_pct", "profit_supply_pct", "C3"),
    ("btc_basics", "hashrate", "hashrate", "C3"),
    ("utxo_age_distribution", "short_term_holder_supply_pct", "sth_supply_pct", "C3"),
    # --- C4 宏观面 / macro+calendar 模块 (6) ---
    ("cpi", "surprise", "cpi_surprise", "C4"),
    ("ppi", "surprise", "ppi_surprise", "C4"),
    ("nfp", "surprise", "nfp_surprise", "C4"),
    ("fedwatch", "cut_prob", "cut_prob", "C4"),
    ("FEDFUNDS", "value", "fed_funds", "C4"),
    ("fomc_decision", "rate_change", "fomc_rate_change", "C4"),
    # --- C6 估值 / valuation 模块 (4) ---
    ("cycle_signals", "bottom_mvrv_value", "mvrv", "C6"),
    ("cycle_signals", "bottom_nupl_value", "nupl", "C6"),
    ("cycle_signals", "bottom_puell-multiple_value", "puell_multiple", "C6"),
    ("cycle_signals", "bottom_reserve-risk_value", "reserve_risk", "C6"),
    # --- C7 广度 / breadth 模块 (3) ---
    ("overview_market", "btc_dominance_pct", "btc_dominance", "C7"),
    ("stablecoins_top_10", "total_circulating_usd_bln", "stablecoin_total", "C7"),
    ("overview_market", "global_change24_pct", "global_change_24h", "C7"),
    # --- C8 跨市场 / intermarket 模块 (3) ---
    ("DX-Y.NYB", "close", "dxy", "C8"),
    ("^VIX", "value", "vix", "C8"),
    ("SPY", "value", "spx", "C8"),
    # --- news 模块 (2) ---
    ("social_volume", "news_count_24h", "news_count_24h", "news"),
    ("social_volume", "total_news_records", "total_news_records", "news"),
]


def build_factor_head_mask(
    metrics: Optional[list[tuple]] = None,
    mask_value: float = float("-inf"),
) -> torch.Tensor:
    """根据 CROSS_ATTENTION_FACTOR_METRICS 的维度元数据构建 factor_head_mask.

    每个矛盾维度对应一个 attention head，该 head 只关注所属维度的因子，
    其余因子被 mask 屏蔽。维度顺序按因子列表中首次出现的顺序排列。

    Args:
        metrics: 因子列表，每项为 (sub_category, metric_name, factor_name, dimension)，
                 None 则使用 CROSS_ATTENTION_FACTOR_METRICS
        mask_value: 屏蔽值，默认 -inf（硬 mask）；传入大负值如 -1e9 则为软 mask

    Returns:
        mask: torch.Tensor shape (n_dimensions, n_factors)
              0.0 = 允许该 head 关注该因子
              mask_value = 屏蔽该因子
    """
    if metrics is None:
        metrics = CROSS_ATTENTION_FACTOR_METRICS

    n_factors = len(metrics)
    # 按首次出现顺序收集唯一维度
    dims: list[str] = []
    for entry in metrics:
        d = entry[3] if len(entry) > 3 else None
        if d and d not in dims:
            dims.append(d)
    n_dims = len(dims)

    mask = torch.full((n_dims, n_factors), mask_value, dtype=torch.float32)
    for f_idx, entry in enumerate(metrics):
        d = entry[3] if len(entry) > 3 else None
        if d is None:
            continue
        head_idx = dims.index(d)
        mask[head_idx, f_idx] = 0.0

    return mask


def get_factor_dimensions() -> list[str]:
    """返回 CROSS_ATTENTION_FACTOR_METRICS 中按首次出现顺序的唯一维度列表。"""
    dims: list[str] = []
    for entry in CROSS_ATTENTION_FACTOR_METRICS:
        d = entry[3] if len(entry) > 3 else None
        if d and d not in dims:
            dims.append(d)
    return dims


def build_exogenous_factors_for_cross_attention(
    timestamps: list,
    bridge: Optional["ExogenousDataBridge"] = None,
    factor_names: Optional[list[str]] = None,
    impact_multipliers: Optional[np.ndarray] = None,
) -> tuple[np.ndarray, list[str]]:
    """构建 Cross-Attention 外生因子时序矩阵.

    从 19-DAL 加载候选因子的历史时序, 按给定时间戳前向填充对齐,
    返回 (N, F) 因子矩阵 + 因子名列表. 缺失因子用 0.0 填充 (FAIL-OPEN).

    Phase 2: 若提供 impact_multipliers (shape (F,)), 在返回前应用时间衰减:
        factor_effective = factor_raw × impact_multiplier(cycle_phase, dimension)
        (ImpactMultiplier.get_multipliers() 计算衰减向量)

    Args:
        timestamps: list[datetime], 价格序列时间戳 (对齐目标)
        bridge: 可选 ExogenousDataBridge, None 则尝试自建
        factor_names: 可选指定因子子集 (来自 CROSS_ATTENTION_FACTOR_METRICS 的 factor_name),
                      None 则使用全部候选因子
        impact_multipliers: 可选 (F,) 衰减系数向量, None 则不衰减 (FAIL-OPEN)

    Returns:
        (factors: np.ndarray shape (N, F), names: list[str] length F)
        N = len(timestamps), F = 因子数
        缺失因子列全 0 (FAIL-OPEN)
    """
    if not timestamps:
        return np.zeros((0, 0), dtype=np.float64), []

    if bridge is None:
        bridge = ExogenousDataBridge()

    # 确定要加载的因子
    metric_list = [
        (sub, metric, name)
        for sub, metric, name, _ in CROSS_ATTENTION_FACTOR_METRICS
        if factor_names is None or name in factor_names
    ]
    if not metric_list:
        return np.zeros((len(timestamps), 0), dtype=np.float64), []

    repo = bridge.get_repo()
    n = len(timestamps)
    factor_data: dict[str, np.ndarray] = {}
    factor_names_result: list[str] = []

    if repo is None:
        # DAL 不可用 → 全 0 (FAIL-OPEN)
        names = [name for _, _, name in metric_list]
        return np.zeros((n, len(names)), dtype=np.float64), names

    from datetime import timedelta as _td, datetime as _dt, timezone as _tz

    # 使用较早起始时间，确保能捕获所有历史数据用于 forward-fill
    # 部分因子（如 DX-Y.NYB）数据可能停更于较早时间，需要从更早起点查询
    t_min = _dt(2010, 1, 1, tzinfo=_tz.utc)
    t_max = max(timestamps)

    for sub, metric, name in metric_list:
        try:
            rows = repo.query_metric_by_time(sub, metric, t_min, t_max)
            ts_vals = [(r[3], float(r[2])) for r in rows if r[2] is not None]
            ts_vals.sort(key=lambda x: x[0])
        except Exception:
            ts_vals = []

        if not ts_vals:
            # 无数据 → 全 0 列 (FAIL-OPEN)
            factor_data[name] = np.zeros(n, dtype=np.float64)
            factor_names_result.append(name)
            continue

        # 前向填充对齐
        col = np.zeros(n, dtype=np.float64)
        last_val = 0.0
        idx = 0
        for i, t in enumerate(timestamps):
            while idx < len(ts_vals) and ts_vals[idx][0] <= t:
                last_val = ts_vals[idx][1]
                idx += 1
            col[i] = last_val
        factor_data[name] = col
        factor_names_result.append(name)

    if not factor_names_result:
        return np.zeros((n, 0), dtype=np.float64), []

    factors = np.column_stack([factor_data[name] for name in factor_names_result])
    # NaN/Inf → 0
    factors = np.where(np.isfinite(factors), factors, 0.0)
    factors = factors.astype(np.float64)

    # Phase 2: 应用时间衰减系数 (若提供)
    factors = apply_impact_multiplier(factors, impact_multipliers)

    return factors, factor_names_result


def build_cross_attention_factors_from_closes(
    closes: np.ndarray,
    timestamps: Optional[list] = None,
    bridge: Optional["ExogenousDataBridge"] = None,
    factor_names: Optional[list[str]] = None,
    impact_multipliers: Optional[np.ndarray] = None,
) -> tuple[np.ndarray, list[str]]:
    """便捷接口: 从 closes 价格序列构建 Cross-Attention 因子矩阵.

    若 timestamps 为 None, 则用最近 365 天逐日时间戳近似.
    若 bridge 不可用, 返回全 0 矩阵 (FAIL-OPEN, 不影响价格路径预测).

    Args:
        closes: (N,) close 价格序列
        timestamps: 可选 list[datetime], 与 closes 对齐; None 则生成近似时间戳
        bridge: 可选 ExogenousDataBridge
        factor_names: 可选指定因子子集
        impact_multipliers: 可选 (F,) 衰减系数向量 (Phase 2), None 则不衰减

    Returns:
        (factors: (N, F), names: list[str])
    """
    closes = np.asarray(closes, dtype=np.float64).ravel()
    n = closes.size
    if n == 0:
        return np.zeros((0, 0), dtype=np.float64), []

    if timestamps is None:
        from datetime import datetime, timedelta, timezone
        end = datetime.now(timezone.utc)
        timestamps = [end - timedelta(days=n - 1 - i) for i in range(n)]

    return build_exogenous_factors_for_cross_attention(
        timestamps=timestamps,
        bridge=bridge,
        factor_names=factor_names,
        impact_multipliers=impact_multipliers,
    )


# ----------------------------------------------------------------------
# Phase 2: 因子影响力时间衰减 impact_multiplier(t) — SPEC §8
# ----------------------------------------------------------------------

class ImpactMultiplier:
    """因子影响力时间衰减器 (Phase 2, SPEC §8).

    factor_effective = factor_raw × impact_multiplier(cycle_phase, dimension)

    cycle_phase 来自 EventWindowTracker.get_context()["cycle_phase"]
    dimension 来自 CROSS_ATTENTION_FACTOR_METRICS 的第 4 元素 (C1/C2/.../news)

    Phase 2: 维度级 decay (硬编码先验表, 基于 §8.2 加息周期扩展到 8 维度)
    Phase 6: 数据驱动校准 (CausalEngine.estimate_ate 分桶替换硬编码)

    衰减逻辑:
      - neutral: 所有维度 = 1.0 (无衰减)
      - 预期构建期 (build→jump): 宏观面敏感度从 0.3 → 1.5 (逐步增强)
      - event: 资金面/情绪面/新闻主导 (1.5/1.4/1.5), 宏观面 1.2
      - repricing: 宏观面快速衰减 (0.3→0.2→0.1), 资金面/情绪面接管

    FAIL-OPEN:
      - cycle_phase=None/unknown → 1.0
      - dimension 未知 → 1.0
      - repricing 子阶段缺失 → 默认 relief
    """

    # 8 维度 × 7 阶段(含 3 repricing 子阶段) 衰减系数表
    # 基于 §8.2 加息敏感度+降息预期敏感度, 扩展到 8 维度
    # C1 资金面 / C2 情绪面 / C3 技术面 / C4 宏观面 /
    # C6 估值 / C7 广度 / C8 跨市场 / news 信息面
    MULTIPLIER_TABLE: dict[str, dict[str, float]] = {
        "neutral": {
            "C1": 1.0, "C2": 1.0, "C3": 1.0, "C4": 1.0,
            "C6": 1.0, "C7": 1.0, "C8": 1.0, "news": 1.0,
        },
        # 预期构建初期: 宏观面敏感度低 (远期事件 priced-in 慢)
        "expectation_build": {
            "C1": 0.6, "C2": 0.5, "C3": 0.8, "C4": 0.3,
            "C6": 0.7, "C7": 0.6, "C8": 0.4, "news": 0.3,
        },
        # 预期上升期: 各维度敏感度增强
        "expectation_rise": {
            "C1": 0.9, "C2": 0.8, "C3": 0.9, "C4": 0.8,
            "C6": 0.8, "C7": 0.7, "C8": 0.7, "news": 0.6,
        },
        # 预期跳跃期: 宏观面主导 (概率 >70%), 新闻敏感度激增
        "expectation_jump": {
            "C1": 1.3, "C2": 1.2, "C3": 1.1, "C4": 1.5,
            "C6": 1.0, "C7": 1.1, "C8": 1.2, "news": 1.3,
        },
        # 消化期: 概率稳定, 资金面/新闻仍敏感, 宏观面衰减
        "expectation_digest": {
            "C1": 1.1, "C2": 1.0, "C3": 1.0, "C4": 0.6,
            "C6": 0.9, "C7": 1.0, "C8": 1.0, "news": 1.2,
        },
        # 事件当天: 资金面/情绪面/新闻主导, 宏观面次之
        "event": {
            "C1": 1.5, "C2": 1.4, "C3": 1.0, "C4": 1.2,
            "C6": 0.9, "C7": 1.0, "C8": 1.1, "news": 1.5,
        },
        # repricing Phase A (relief, 0-5 天): 不确定性消除, 降息预期主导
        "repricing_relief": {
            "C1": 1.2, "C2": 1.3, "C3": 1.0, "C4": 0.3,
            "C6": 1.0, "C7": 1.1, "C8": 0.9, "news": 1.4,
        },
        # repricing Phase B (verification, 5-15 天): 基本面验证
        "repricing_verification": {
            "C1": 1.0, "C2": 1.1, "C3": 1.0, "C4": 0.2,
            "C6": 1.1, "C7": 1.0, "C8": 0.8, "news": 1.2,
        },
        # repricing Phase C (trend, 15+ 天): 债务周期位置主导
        "repricing_trend": {
            "C1": 0.9, "C2": 1.0, "C3": 1.0, "C4": 0.1,
            "C6": 1.0, "C7": 0.9, "C8": 0.7, "news": 1.0,
        },
    }

    # 维度集合 (与 factor_head_mask 的 head 顺序一致)
    DIMENSIONS = ["C1", "C2", "C3", "C4", "C6", "C7", "C8", "news"]

    def __init__(self) -> None:
        # 预构建 dimension → index 映射, 加速查找
        self._dim_index: dict[str, int] = {d: i for i, d in enumerate(self.DIMENSIONS)}
        # Phase 6: ATE 校准后的表 (初始为硬编码表的副本)
        self._calibrated_table: dict[str, dict[str, float]] = {
            phase: dict(dims) for phase, dims in self.MULTIPLIER_TABLE.items()
        }
        # 校准版本号，每次 update_from_ate 递增
        self._calibration_version: int = 0
        # 校准时间戳
        self._last_calibration: Optional[str] = None

    def update_from_ate(
        self,
        ate_results: dict[str, dict[str, dict[str, float]]],
        *,
        significant_shrink: float = 0.0,
        nonsignificant_shrink: float = 0.5,
    ) -> dict[str, int]:
        """Phase 6: 用 CausalEngine ATE 结果动态校准 MULTIPLIER_TABLE.

        映射规则 (ATE → multiplier 调整):
          - ATE 显著 (significant=True):
              multiplier = base * (1 + significant_shrink * sign(ATE))
              → 有因果效应，保留或按 ATE 方向微调
          - ATE 不显著 (significant=False):
              multiplier = base * nonsignificant_shrink
              → 无因果效应，衰减该维度影响力

        Args:
            ate_results: CausalEngine.calibrate_multipliers() 的输出
                {phase: {dimension: {"ate": float, "significant": bool, ...}}}
            significant_shrink: 显著时的微调系数 (0=保留原值, >0 按 ATE 方向微调)
            nonsignificant_shrink: 不显著时的衰减系数 (0.5=衰减一半)

        Returns:
            {"updated": 已校准的 (phase, dim) 数, "version": 新版本号}
        """
        if not ate_results:
            return {"updated": 0, "version": self._calibration_version}

        updated = 0
        for phase, dim_ates in ate_results.items():
            if phase not in self._calibrated_table:
                # 新 phase (如 repricing_relief 等)，初始化为 neutral 表
                self._calibrated_table[phase] = dict(self.MULTIPLIER_TABLE.get("neutral", {}))
            for dim, ate_info in dim_ates.items():
                if dim not in self._dim_index:
                    continue
                base = self._calibrated_table[phase].get(dim, 1.0)
                ate_val = float(ate_info.get("ate", 0.0))
                significant = bool(ate_info.get("significant", False))
                if significant:
                    # 显著：保留原值，按 ATE 方向微调
                    sign = 1.0 if ate_val >= 0 else -1.0
                    new_val = base * (1.0 + significant_shrink * sign)
                else:
                    # 不显著：衰减
                    new_val = base * nonsignificant_shrink
                # clamp 到合理范围 [0.05, 3.0]
                new_val = float(max(0.05, min(3.0, new_val)))
                self._calibrated_table[phase][dim] = new_val
                updated += 1

        self._calibration_version += 1
        from datetime import datetime, timezone
        self._last_calibration = datetime.now(timezone.utc).isoformat()
        logger.info(
            "[Phase6] ImpactMultiplier ATE 校准完成: updated=%d, version=%d",
            updated, self._calibration_version,
        )
        return {"updated": updated, "version": self._calibration_version}

    def get_multiplier(
        self,
        cycle_phase: str | None,
        dimension: str,
        repricing_sub_phase: str = "none",
    ) -> float:
        """查询单个 (cycle_phase, dimension) 的衰减系数.

        Args:
            cycle_phase: EventWindowTracker 输出, 见 event_window_tracker.py
                         (neutral/expectation_build/expectation_rise/
                          expectation_jump/expectation_digest/event/repricing)
            dimension: 矛盾维度 (C1/C2/C3/C4/C6/C7/C8/news)
            repricing_sub_phase: relief/verification/trend/none
                                仅当 cycle_phase="repricing" 时生效

        Returns:
            衰减系数 (1.0 = 无衰减, <1.0 = 衰减, >1.0 = 放大)
        """
        # FAIL-OPEN: 无阶段信息
        if not cycle_phase or cycle_phase == "neutral":
            return 1.0

        # FAIL-OPEN: 未知维度
        if dimension not in self._dim_index:
            return 1.0

        # repricing 阶段: 合并 cycle_phase + sub_phase 为查表 key
        if cycle_phase == "repricing":
            sub = repricing_sub_phase or "relief"
            if sub not in ("relief", "verification", "trend"):
                sub = "relief"
            table_key = f"repricing_{sub}"
        else:
            table_key = cycle_phase

        phase_table = self._calibrated_table.get(table_key) or self.MULTIPLIER_TABLE.get(table_key)
        if phase_table is None:
            # 未知阶段 (如 expectation_build 等已知但拼写不同) → FAIL-OPEN
            return 1.0

        return float(phase_table.get(dimension, 1.0))

    def get_multipliers(
        self,
        cycle_phase: str | None,
        factor_names: list[str],
        repricing_sub_phase: str = "none",
        metrics: Optional[list[tuple]] = None,
    ) -> np.ndarray:
        """构建与因子列表对齐的衰减系数向量.

        Args:
            cycle_phase: 周期阶段
            factor_names: 因子名列表 (与 CROSS_ATTENTION_FACTOR_METRICS 的 factor_name 对应)
            repricing_sub_phase: repricing 子阶段
            metrics: 可选因子元数据列表, None 则用 CROSS_ATTENTION_FACTOR_METRICS
                     用于查找每个 factor_name 所属的 dimension

        Returns:
            multipliers: np.ndarray shape (len(factor_names),)
        """
        if metrics is None:
            metrics = CROSS_ATTENTION_FACTOR_METRICS

        # 构建 factor_name → dimension 映射
        name_to_dim: dict[str, str] = {}
        for entry in metrics:
            if len(entry) >= 4:
                name_to_dim[entry[2]] = entry[3]

        multipliers = np.ones(len(factor_names), dtype=np.float64)
        for i, fname in enumerate(factor_names):
            dim = name_to_dim.get(fname)
            if dim is None:
                # 因子不在元数据中 → 不衰减 (FAIL-OPEN)
                continue
            multipliers[i] = self.get_multiplier(
                cycle_phase, dim, repricing_sub_phase
            )
        return multipliers


def apply_impact_multiplier(
    factors: np.ndarray,
    multipliers: Optional[np.ndarray],
) -> np.ndarray:
    """对因子矩阵应用时间衰减系数.

    factor_effective = factor_raw × impact_multiplier(cycle_phase, dimension)

    Args:
        factors: (N, F) 因子矩阵
        multipliers: (F,) 衰减系数向量, None → 原样返回 (FAIL-OPEN)

    Returns:
        (N, F) 衰减后的因子矩阵 (新数组, 不修改输入)
    """
    if multipliers is None:
        return factors
    factors = np.asarray(factors, dtype=np.float64)
    multipliers = np.asarray(multipliers, dtype=np.float64).ravel()
    if factors.size == 0 or multipliers.size == 0:
        return factors
    # 广播: (N, F) × (F,) → (N, F)
    if multipliers.shape[0] != factors.shape[1]:
        logger.warning(
            "[apply_impact_multiplier] 维度不匹配: factors=%s multipliers=%s, 跳过衰减",
            factors.shape, multipliers.shape,
        )
        return factors
    return factors * multipliers[None, :]
