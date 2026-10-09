"""参数中心聚合 Runner — 定时调用 6 算法适配器 + StatAggregator 产出动态 SL/TP

职责：
  1. 调用 get_all_adapters() 获取 6 个算法的 observations
  2. StatAggregator.aggregate() BMA+KL散度加权聚合
  3. 将聚合结果写入 ParamRepository 聚合缓存层
  4. repository.get() 优先返回聚合值，失败回退静态3D表

CLI:
  python runner.py --symbol BTC --regime chop
  python runner.py --symbol BTC,NVDA,ETH --regime chop
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

# 路径设置
_THIS = Path(__file__).resolve()
_SCRIPTS_16 = _THIS.parent.parent
_PROJECT_ROOT = _SCRIPTS_16.parent.parent
_YIJING_SCRIPTS = _PROJECT_ROOT / "11-易经推理系统" / "scripts"
for _p in [_YIJING_SCRIPTS, _SCRIPTS_16]:
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

from memory_l4.bcrm2.sl_tp_config import SLTPParams
from param_center.adapters import get_all_adapters
from param_center.aggregator import ParamProposal, StatAggregator
from param_center.repository import get_repository

logger = logging.getLogger(__name__)

# K 线数据目录
_KLINES_DIR = _YIJING_SCRIPTS / "data" / "klines"


def load_market_data(symbol: str, timeframe: str = "1H") -> Optional[dict]:
    """从本地 CSV 加载 K 线数据，构建 market_data dict。

    返回的 dict 包含:
      - closes: 收盘价列表 (float[])
      - regime_name: 简单 regime 判断结果 (供 Bagua 适配器使用)

    加载失败时返回 None，适配器自动跳过。
    """
    import csv

    sym_up = symbol.upper().strip()
    csv_path = _KLINES_DIR / f"{sym_up}_{timeframe}.csv"
    if not csv_path.exists():
        # 尝试无 timeframe 后缀
        csv_path = _KLINES_DIR / f"{sym_up}.csv"
        if not csv_path.exists():
            logger.debug("load_market_data: %s 无 K线文件", sym_up)
            return None

    try:
        closes: list[float] = []
        with open(csv_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                c = float(row.get("close", 0))
                closes.append(c)

        if len(closes) < 120:
            logger.debug("load_market_data: %s K线不足120根 (%d)", sym_up, len(closes))
            return None

        # 简单 regime 判断：最近 50 根的斜率和波动率
        recent = closes[-200:]
        ma_short = sum(recent[-20:]) / 20.0
        ma_long = sum(recent[-50:]) / 50.0
        price = closes[-1]

        # 波动率（最近 50 根的收益率标准差）
        rets = [(recent[i] - recent[i - 1]) / recent[i - 1] for i in range(-49, 0)]
        vol = (sum(r * r for r in rets) / len(rets)) ** 0.5

        # 简单 regime 判断逻辑
        if ma_short > ma_long * 1.02:
            if vol > 0.03:
                regime_name = "FOMO_RALLY"
            else:
                regime_name = "TREND_UP_MILD"
        elif ma_short < ma_long * 0.98:
            if vol > 0.03:
                regime_name = "VOLATILE_DROP"
            else:
                regime_name = "REVERSAL"
        elif vol < 0.01:
            regime_name = "CONSOLIDATION"
        else:
            regime_name = "RANGE_BOUND"

        return {
            "closes": closes,
            "regime_name": regime_name,
            # PMapper 的 L/T/C 输入（用简化指标）
            "L": 0.0,  # 链上流动性指标，暂无数据源
            "T": 0.0,  # 情绪指标，暂无数据源
            "C": 0.0,  # 相关性指标，暂无数据源
        }
    except Exception as exc:
        logger.warning("load_market_data: %s 加载失败: %s", sym_up, exc)
        return None


def build_market_data_map(symbols: List[str]) -> Dict[str, dict]:
    """批量构建 {symbol: market_data}。"""
    md_map: Dict[str, dict] = {}
    for sym in symbols:
        md = load_market_data(sym)
        if md is not None:
            md_map[sym] = md
            logger.debug(
                "build_market_data_map: %s OK closes=%d regime=%s",
                sym, len(md["closes"]), md["regime_name"],
            )
    return md_map


def run_aggregation(
    symbol: str,
    market_regime: str = "chop",
    market_data: Optional[dict] = None,
) -> Optional[ParamProposal]:
    """运行单次聚合：6 算法适配器 → StatAggregator → 写入 repository 缓存。

    Args:
        symbol: 交易对（如 "BTC"）
        market_regime: 市场形态 bull/chop/bear
        market_data: 市场数据 dict（含 closes 等字段），None 时适配器可能返回 None

    Returns:
        ParamProposal 或 None（全部适配器失败时）
    """
    symbol_up = symbol.upper().strip()
    adapters = get_all_adapters()

    observations = []
    for adapter in adapters:
        obs = adapter.observe(symbol_up, market_data)
        if obs is not None:
            observations.append(obs)
            logger.debug(
                "Adapter[%s] observe OK symbol=%s params=%s conf=%.2f",
                adapter.name, symbol_up, obs.params, obs.confidence,
            )

    if not observations:
        logger.warning(
            "run_aggregation: 全部适配器返回 None symbol=%s, 回退静态表",
            symbol_up,
        )
        return None

    aggregator = StatAggregator()
    proposal = aggregator.aggregate(observations)

    # 获取静态 3D 表基准值（资产特定），用作聚合结果的锚点
    from memory_l4.bcrm2.asset_classifier import classify_asset
    from memory_l4.bcrm2.sl_tp_config import get_sltp_params as _get_static
    try:
        ac, mc = classify_asset(symbol_up)
        static = _get_static(ac, mc, market_regime)
    except Exception:
        static = None

    params_dict = proposal.params
    agg_sl = float(params_dict.get("sl_floor", 0.03))
    agg_tp = float(params_dict.get("tp_floor", 0.12))
    atr_mult = float(params_dict.get("atr_mult", 4.5))

    if static is not None:
        # 向静态基准靠拢：聚合值与静态值按 40:60 混合
        # 适配器不区分资产类别，直接用聚合值会导致美股 SL=4.2% (应≈3%)
        final_sl = static.sl_floor * 0.6 + agg_sl * 0.4
        final_tp = static.tp_floor * 0.6 + agg_tp * 0.4
        # ATR 倍数也向静态基准靠拢
        static_atr_mid = (static.atr_mult_range[0] + static.atr_mult_range[1]) / 2.0
        final_atr = static_atr_mid * 0.6 + atr_mult * 0.4
        logger.debug(
            "asset_clamp %s: static SL=%.3f%% TP=%.3f%% ATR=%.2f "
            "→ blend SL=%.3f%% TP=%.3f%% ATR=%.2f",
            symbol_up,
            static.sl_floor * 100, static.tp_floor * 100, static_atr_mid,
            final_sl * 100, final_tp * 100, final_atr,
        )
    else:
        final_sl = agg_sl
        final_tp = agg_tp
        final_atr = atr_mult

    sltp = SLTPParams(
        sl_floor=final_sl,
        tp_floor=final_tp,
        atr_mult_range=(max(2.0, final_atr - 1.0), final_atr + 1.0),
        rr_ratio_target=max(2.0, final_tp / max(final_sl, 1e-6)),
    )

    repo = get_repository()
    repo.set_aggregated(symbol_up, market_regime, sltp, confidence=proposal.confidence)

    logger.info(
        "run_aggregation symbol=%s regime=%s | sl=%.4f tp=%.4f atr=%.2f "
        "conf=%.2f adapters=%d weights=%s",
        symbol_up, market_regime,
        sltp.sl_floor, sltp.tp_floor, final_atr,
        proposal.confidence, len(observations),
        json.dumps(proposal.weights, ensure_ascii=False),
    )
    return proposal


def run_aggregation_for_symbols(
    symbols: List[str],
    market_regime: str = "chop",
    market_data_map: Optional[Dict[str, dict]] = None,
) -> Dict[str, Optional[ParamProposal]]:
    """批量聚合多个币种。

    Args:
        symbols: 币种列表
        market_regime: 市场形态
        market_data_map: {symbol: market_data}，None 时全部传 None

    Returns:
        {symbol: ParamProposal or None}
    """
    results = {}
    for sym in symbols:
        md = market_data_map.get(sym) if market_data_map else None
        results[sym] = run_aggregation(sym, market_regime, md)
    return results


def main():
    parser = argparse.ArgumentParser(description="参数中心聚合 Runner")
    parser.add_argument("--symbol", type=str, required=True, help="币种，逗号分隔")
    parser.add_argument("--regime", type=str, default="chop", choices=["bull", "chop", "bear"])
    parser.add_argument("--verbose", action="store_true", help="详细日志")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    symbols = [s.strip().upper() for s in args.symbol.split(",") if s.strip()]

    # 加载 K 线数据构建 market_data_map
    logger.info("开始加载 K 线数据 for %d symbols", len(symbols))
    md_map = build_market_data_map(symbols)
    logger.info(
        "K 线数据加载完成: %d/%d symbols 有数据",
        len(md_map), len(symbols),
    )

    results = run_aggregation_for_symbols(symbols, args.regime, md_map)

    print("\n=== 聚合结果 ===")
    for sym, proposal in results.items():
        if proposal is None:
            print(f"{sym}: 聚合失败（回退静态表）")
        else:
            p = proposal.params
            print(
                f"{sym}: sl={p['sl_floor']*100:.1f}% tp={p['tp_floor']*100:.1f}% "
                f"atr={p['atr_mult']:.2f} conf={proposal.confidence:.2f}"
            )
    print("================")


if __name__ == "__main__":
    main()
