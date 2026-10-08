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

    # 转换为 SLTPParams 并写入 repository 聚合缓存
    params_dict = proposal.params
    atr_mult = float(params_dict.get("atr_mult", 4.5))
    sltp = SLTPParams(
        sl_floor=float(params_dict.get("sl_floor", 0.03)),
        tp_floor=float(params_dict.get("tp_floor", 0.12)),
        atr_mult_range=(max(2.0, atr_mult - 1.0), atr_mult + 1.0),
        rr_ratio_target=max(2.0, params_dict.get("tp_floor", 0.12) / max(params_dict.get("sl_floor", 0.03), 1e-6)),
    )

    repo = get_repository()
    repo.set_aggregated(symbol_up, market_regime, sltp, confidence=proposal.confidence)

    logger.info(
        "run_aggregation symbol=%s regime=%s | sl=%.4f tp=%.4f atr=%.2f "
        "conf=%.2f adapters=%d weights=%s",
        symbol_up, market_regime,
        sltp.sl_floor, sltp.tp_floor, atr_mult,
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
    results = run_aggregation_for_symbols(symbols, args.regime)

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
