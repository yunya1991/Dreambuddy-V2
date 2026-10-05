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
                from dreambuddy_dal import get_market_macro_repo
                self._repo = get_market_macro_repo(backend="sqlite_unified")
            except Exception as exc:
                logger.warning("[ExogenousBridge] 无法获取 DAL repo: %s", exc)
                self._repo = None
        return self._repo

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

# 候选因子清单 (sub_category, metric_name, factor_name)
# 来自 19-DAL mm_metrics 中 ≥50 数据点的宏观/链上/衍生品指标
CROSS_ATTENTION_FACTOR_METRICS: list[tuple[str, str, str]] = [
    # --- 宏观 (Macro) ---
    ("cpi", "actual", "cpi_actual"),
    ("cpi", "forecast", "cpi_forecast"),
    ("fedwatch", "hike_prob", "rate_hike_prob"),
    ("fomc_decision", "rate_change", "fomc_rate_change"),
    ("DX-Y.NYB", "close", "dxy"),
    # --- 链上 (On-chain) ---
    ("btc_basics", "market_cap_usd", "btc_market_cap"),
    ("btc_basics", "tx_count_24h", "btc_tx_count"),
    ("btc_onchain", "active_addresses", "active_addresses"),
    ("exchanges_whales", "ex_bal_BTC_chg30d_pct", "exchange_balance_chg"),
    # --- 衍生品/资金流 (Derivatives/Flows) ---
    ("funding_rate", "funding_rate", "funding_rate"),
    ("etf_flow", "total_flow", "etf_net_flow"),
    ("stablecoin_tvl", "total_tvl_usd", "stablecoin_tvl"),
]


def build_exogenous_factors_for_cross_attention(
    timestamps: list,
    bridge: Optional["ExogenousDataBridge"] = None,
    factor_names: Optional[list[str]] = None,
) -> tuple[np.ndarray, list[str]]:
    """构建 Cross-Attention 外生因子时序矩阵.

    从 19-DAL 加载候选因子的历史时序, 按给定时间戳前向填充对齐,
    返回 (N, F) 因子矩阵 + 因子名列表. 缺失因子用 0.0 填充 (FAIL-OPEN).

    Args:
        timestamps: list[datetime], 价格序列时间戳 (对齐目标)
        bridge: 可选 ExogenousDataBridge, None 则尝试自建
        factor_names: 可选指定因子子集 (来自 CROSS_ATTENTION_FACTOR_METRICS 的 factor_name),
                      None 则使用全部候选因子

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
        for sub, metric, name in CROSS_ATTENTION_FACTOR_METRICS
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

    from datetime import timedelta as _td

    t_min = min(timestamps) - _td(days=180)
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
    return factors.astype(np.float64), factor_names_result


def build_cross_attention_factors_from_closes(
    closes: np.ndarray,
    timestamps: Optional[list] = None,
    bridge: Optional["ExogenousDataBridge"] = None,
    factor_names: Optional[list[str]] = None,
) -> tuple[np.ndarray, list[str]]:
    """便捷接口: 从 closes 价格序列构建 Cross-Attention 因子矩阵.

    若 timestamps 为 None, 则用最近 365 天逐日时间戳近似.
    若 bridge 不可用, 返回全 0 矩阵 (FAIL-OPEN, 不影响价格路径预测).

    Args:
        closes: (N,) close 价格序列
        timestamps: 可选 list[datetime], 与 closes 对齐; None 则生成近似时间戳
        bridge: 可选 ExogenousDataBridge
        factor_names: 可选指定因子子集

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
    )
