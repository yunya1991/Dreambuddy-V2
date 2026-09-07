"""
PathLibrary — 传统/加密成熟最优路径知识库

设计哲学:
  传统金融和加密社区已有大量被验证的盈利路径（如资金轮动、动量突破、均值回归等）。
  这些路径作为"参考模板"提供给系统，但**不直接执行**。
  系统必须通过自身数据计算验证路径是否在当前市场有效，
  并通过实际盈亏对路径评分——盈亏是唯一的成功标准。

路径生命周期:
  1. 参考路径库（人工/社区经验） → 系统参考
  2. 数据验证（当前市场数据计算路径信号强度）
  3. 小仓实践（按置信度下单，低置信也可开仓但仓位小）
  4. 盈亏评分（实际 P&L 更新路径 score）
  5. 自进化（高分路径权重提升，低分路径衰减）
  6. 探索（系统可生成新路径，经实践验证后入库）
"""
from __future__ import annotations

import json
import math
import logging
from pathlib import Path
from typing import Any

try:
    from .ftc_schema import FTC, FTCStep, KnowledgeAlignment, gen_ftc_id, gen_step_id
    from .ftc_similarity import align_to_anchors, get_track_by_similarity
    _FTC_AVAILABLE = True
except ImportError:
    _FTC_AVAILABLE = False

logger = logging.getLogger(__name__)


# 预设参考路径库 — 来自传统金融 + 加密社区的成熟经验
# 每条路径定义了触发条件、数据需求、计算逻辑、评分方法
REFERENCE_PATHS: dict[str, dict[str, Any]] = {
    "capital_rotation": {
        "name": "资金轮动",
        "origin": "加密社区 · 板块轮动理论",
        "description": "竞品组内资金从弱势币流向强势币，跟随强势方",
        "trigger": {
            "capital_rotation_abs": 0.15,   # |轮动信号| > 0.15
            "regime_in": ("trend_up", "trend_down"),  # 趋势市有效
        },
        "data_required": ["close", "vol_5", "vol_20", "competitor_scores"],
        "logic": "token_score - group_avg_score > 0.15 → 跟多；< -0.15 → 跟空",
        "direction": "follow_strong",
        "initial_score": 0.5,
        "tags": ["capital_flow", "sector_rotation", "momentum"],
    },
    "momentum_breakout": {
        "name": "动量突破",
        "origin": "传统金融 · 趋势跟随 (Jegadeesh & Titman 1993)",
        "description": "价格突破近期高点且放量，趋势延续概率高",
        "trigger": {
            "price_above_ma20": True,
            "vol_ratio_min": 1.3,       # 放量确认
            "adx_min": 20,              # 趋势强度
        },
        "data_required": ["close", "high", "vol_5", "vol_20", "adx"],
        "logic": "close > MA20 且 vol_5/vol_20 > 1.3 且 ADX > 20 → 做多",
        "direction": "long",
        "initial_score": 0.5,
        "tags": ["momentum", "breakout", "trend"],
    },
    "mean_reversion": {
        "name": "均值回归",
        "origin": "传统金融 · 统计套利 (Ornstein-Uhlenbeck)",
        "description": "价格偏离均值过远时回归，震荡市有效",
        "trigger": {
            "regime_eq": "ranging",       # 仅震荡市
            "z_score_abs": 2.0,          # 偏离均值2个标准差
        },
        "data_required": ["close", "ma20", "std20"],
        "logic": "z_score > 2 → 做空；z_score < -2 → 做多（回归方向）",
        "direction": "contrarian",
        "initial_score": 0.5,
        "tags": ["mean_reversion", "stat_arb", "ranging"],
    },
    "oi_divergence": {
        "name": "OI 背离",
        "origin": "加密社区 · 衍生品分析",
        "description": "价格下跌但 OI 上升 → 空头建仓，可能继续下跌；反之亦然",
        "trigger": {
            "oi_change_pct_abs": 0.05,    # OI 变化 > 5%
            "price_direction": "opposite",  # 价格与 OI 反向
        },
        "data_required": ["close", "oi_change_pct"],
        "logic": "OI↑+price↓ → 做空；OI↓+price↑ → 做多（跟 OI 方向）",
        "direction": "follow_oi",
        "initial_score": 0.5,
        "tags": ["open_interest", "derivatives", "divergence"],
    },
    "funding_rate_arb": {
        "name": "资金费率套利",
        "origin": "加密社区 · 永续合约机制",
        "description": "资金费率极端时反向下单（高费率做空，低费率做多）",
        "trigger": {
            "funding_rate_abs": 0.001,    # |费率| > 0.1%
        },
        "data_required": ["funding_rate"],
        "logic": "funding > 0.1% → 做空赚费率；< -0.1% → 做多赚费率",
        "direction": "contrarian",
        "initial_score": 0.4,
        "tags": ["funding_rate", "arb", "perpetual"],
    },
    "volume_surge": {
        "name": "放量异动",
        "origin": "传统金融 · 量价分析",
        "description": "成交量突然放大（5倍以上）预示重大行情启动",
        "trigger": {
            "vol_ratio_min": 3.0,         # 量比 > 3
        },
        "data_required": ["vol_5", "vol_20"],
        "logic": "vol_5/vol_20 > 3 → 跟随价格方向（突破前兆）",
        "direction": "follow_price",
        "initial_score": 0.5,
        "tags": ["volume", "breakout", "anomaly"],
    },
    "regime_adaptive": {
        "name": "状态自适应",
        "origin": "传统金融 · Markov Regime Switching",
        "description": "根据市场状态选择策略：趋势市动量，震荡市均值回归",
        "trigger": {
            "always": True,  # 始终运行，根据 regime 切换
        },
        "data_required": ["regime", "close", "ma20", "vol_ratio"],
        "logic": "trend_up → 动量做多；trend_down → 动量做空；ranging → 均值回归",
        "direction": "regime_dependent",
        "initial_score": 0.6,
        "tags": ["regime", "adaptive", "meta"],
    },
    # =====================================================================
    # 深度多步因果路径（参考 UNI 案例：链上手续费→资金流入→代币→轮动→对手出逃）
    # 每条路径都有清晰的因果链，需要多维度数据交叉验证
    # =====================================================================
    "protocol_revenue": {
        "name": "协议收入传导",
        "origin": "UNI案例抽象 · 协议代币价值捕获",
        "description": "协议手续费/收入增长 → 代币回购或销毁 → 代币价值提升。因果链: 收入↑→价值捕获↑→代币↑",
        "causal_chain": [
            "Step1: 协议收入（手续费）持续增长",
            "Step2: 收入用于回购/销毁代币或分红",
            "Step3: 代币价值捕获增强 → 价格上涨",
        ],
        "trigger": {
            "vol_ratio_min": 1.3,
            "price_above_ma20": True,
        },
        "data_required": ["close", "vol_5", "vol_20", "capital_rotation"],
        "logic": "价量齐升+资金轮动流入 → 做多（协议收入增长信号）",
        "direction": "long",
        "initial_score": 0.55,
        "tags": ["fundamental", "revenue", "value_capture", "deep_causal"],
    },
    "exchange_token_cycle": {
        "name": "交易所币周期",
        "origin": "加密社区 · BNB/OKB 周期性",
        "description": "交易所交易量暴增 → 手续费收入↑ → 交易所代币（BNB/OKB）回购销毁↑ → 代币上涨。因果链: 交易量↑→收入↑→回购↑→价格↑",
        "causal_chain": [
            "Step1: 交易所现货/合约交易量激增",
            "Step2: 手续费收入增长",
            "Step3: 定期回购销毁（BNB季度销毁/OKB回购）",
            "Step4: 供给收缩 → 价格上涨",
        ],
        "trigger": {
            "vol_ratio_min": 1.5,
            "symbol_in": ("BNB", "OKB", "HT", "GT"),
        },
        "data_required": ["close", "vol_5", "vol_20", "symbol"],
        "logic": "交易所币+放量 → 做多（交易量驱动的收入预期）",
        "direction": "long",
        "initial_score": 0.5,
        "tags": ["exchange_token", "buyback", "volume_driven", "deep_causal"],
    },
    "stablecoin_inflow": {
        "name": "稳定币流入传导",
        "origin": "加密社区 · 资金面分析",
        "description": "稳定币总供给扩张 → 新资金入场 → 市场整体上涨。因果链: USDT/USDC供给↑→购买力↑→资产价格↑",
        "causal_chain": [
            "Step1: 稳定币（USDT/USDC）链上增发",
            "Step2: 法币资金通过稳定币入场",
            "Step3: 购买力增强 → 加密资产普涨",
        ],
        "trigger": {
            "vol_ratio_min": 1.2,
            "regime_in": ("trend_up",),
        },
        "data_required": ["close", "vol_5", "vol_20", "regime", "capital_flow"],
        "logic": "趋势市+放量+资金流入 → 做多（稳定币入场驱动）",
        "direction": "long",
        "initial_score": 0.5,
        "tags": ["stablecoin", "capital_inflow", "macro", "deep_causal"],
    },
    "lsd_staking_flow": {
        "name": "LSD质押流向",
        "origin": "加密社区 · ETH LSD 生态",
        "description": "ETH质押量增长 → LSD（stETH/rETH）需求↑ → LSD代币（LDO/RPL）受益。因果链: 质押↑→LSD需求↑→LSD协议收入↑→代币↑",
        "causal_chain": [
            "Step1: ETH 质押量持续增长",
            "Step2: LSD 代币（stETH/rETH）铸造需求上升",
            "Step3: LSD 协议（Lido/Rocket Pool）收入增长",
            "Step4: 协议代币（LDO/RPL）价值提升",
        ],
        "trigger": {
            "vol_ratio_min": 1.3,
            "symbol_in": ("LDO", "RPL", "FXS", "ETH"),
        },
        "data_required": ["close", "vol_5", "vol_20", "symbol"],
        "logic": "LSD生态币+放量 → 做多（质押增长驱动）",
        "direction": "long",
        "initial_score": 0.5,
        "tags": ["lsd", "staking", "eth_ecosystem", "deep_causal"],
    },
    "funding_squeeze": {
        "name": "费率挤压反转",
        "origin": "加密社区 · 永续合约博弈",
        "description": "资金费率极端（>0.1%或<-0.1%）→ 一方仓位过重 → 清算触发 → 强制平仓 → 反向行情。因果链: 费率极端→拥挤交易→清算→反转",
        "causal_chain": [
            "Step1: 资金费率极端（多头/空头拥挤）",
            "Step2: 反向波动触发大规模清算",
            "Step3: 清算加剧波动 → 形成挤仓",
            "Step4: 价格向拥挤方的反方向剧烈运动",
        ],
        "trigger": {
            "funding_rate_abs": 0.001,
        },
        "data_required": ["funding_rate", "close", "vol_ratio"],
        "logic": "funding>0.1% → 做空（多头拥挤，清算风险）；<-0.1% → 做多",
        "direction": "contrarian",
        "initial_score": 0.55,
        "tags": ["funding_rate", "liquidation", "squeeze", "deep_causal"],
    },
    "cross_chain_flow": {
        "name": "跨链资金流向",
        "origin": "加密社区 · 跨链生态轮动",
        "description": "资金从一条链流向另一条链 → 目标链原生代币需求↑ → 价格上涨。因果链: 桥接TVL变化→链上活跃度→原生代币需求",
        "causal_chain": [
            "Step1: 跨链桥接资金量变化（某条链净流入）",
            "Step2: 目标链上 DeFi/Gas 活跃度提升",
            "Step3: 原生代币（ETH/SOL/ARB/OP）需求增长",
            "Step4: 原生代币价格上涨",
        ],
        "trigger": {
            "vol_ratio_min": 1.3,
            "symbol_in": ("ETH", "SOL", "ARB", "OP", "AVAX", "SUI", "APT"),
        },
        "data_required": ["close", "vol_5", "vol_20", "symbol", "capital_rotation"],
        "logic": "L1/L2代币+放量+轮动流入 → 做多（跨链资金流入驱动）",
        "direction": "long",
        "initial_score": 0.5,
        "tags": ["cross_chain", "layer1", "layer2", "capital_flow", "deep_causal"],
    },
    "meme_season_rotation": {
        "name": "Meme季节轮动",
        "origin": "PUMP案例抽象 · Meme板块周期",
        "description": "Meme币爆发 → Meme发行平台（PUMP）受益 → 资金从其他板块流入Meme → 非Meme币承压。因果链: Meme热度↑→PUMP收入↑→PUMP代币↑→其他板块资金流出",
        "causal_chain": [
            "Step1: Meme币批量爆发（金狗出现）",
            "Step2: Meme发行平台（PUMP）交易量和收入激增",
            "Step3: 资金从 DeFi/L1 等板块流入 Meme",
            "Step4: PUMP代币上涨，其他板块代币承压",
        ],
        "trigger": {
            "vol_ratio_min": 2.0,
            "symbol_in": ("PUMP",),
        },
        "data_required": ["close", "vol_5", "vol_20", "symbol", "capital_rotation"],
        "logic": "PUMP放量 → 做多PUMP（Meme季节受益）；其他板块做空（资金流出）",
        "direction": "sector_rotation",
        "initial_score": 0.55,
        "tags": ["meme", "sector_rotation", "pump", "deep_causal"],
    },
    "etf_flow_amplification": {
        "name": "ETF资金传导",
        "origin": "传统金融 · ETF资金流传导",
        "description": "现货ETF持续净流入 → 底层资产需求↑ → 相关基础设施（交易所/矿企）受益。因果链: ETF净流入↑→BTC/ETH需求↑→相关概念股↑",
        "causal_chain": [
            "Step1: 现货ETF（BTC/ETH）持续净流入",
            "Step2: 底层资产买盘支撑，价格上涨",
            "Step3: 交易所（COIN/MSTR）和矿企（MARA/RIOT）收入预期提升",
            "Step4: 相关概念股上涨",
        ],
        "trigger": {
            "vol_ratio_min": 1.3,
            "symbol_in": ("BTC", "ETH", "COIN", "MSTR", "MARA", "RIOT"),
        },
        "data_required": ["close", "vol_5", "vol_20", "symbol", "capital_flow"],
        "logic": "ETF相关资产+放量+资金流入 → 做多（ETF资金传导）",
        "direction": "long",
        "initial_score": 0.5,
        "tags": ["etf", "institutional", "capital_flow", "deep_causal"],
    },
    "gas_fee_economics": {
        "name": "Gas费经济传导",
        "origin": "加密社区 · 链上经济",
        "description": "链上活跃度提升 → Gas费上涨 → 验证者/质押者收入↑ → 原生代币价值↑。因果链: 活跃度↑→Gas↑→质押收入↑→代币↑",
        "causal_chain": [
            "Step1: 链上交易活跃度提升（新协议/空投/叙事）",
            "Step2: Gas费上涨，网络拥堵",
            "Step3: 验证者/质押者收入增长",
            "Step4: 原生代币（ETH/SOL）价值捕获增强",
        ],
        "trigger": {
            "vol_ratio_min": 1.3,
            "symbol_in": ("ETH", "SOL", "AVAX", "SUI", "APT"),
        },
        "data_required": ["close", "vol_5", "vol_20", "symbol"],
        "logic": "L1代币+放量 → 做多（Gas经济驱动）",
        "direction": "long",
        "initial_score": 0.5,
        "tags": ["gas", "validator", "staking", "layer1", "deep_causal"],
    },
    "attention_capital_breakout": {
        "name": "注意力+资金+突破三共振",
        "origin": "核心最优路径 · 三因素确认",
        "description": "市场注意力上升（放量+情绪热度） + 资金持续流入（轮动+资金流） + 技术突破确认（站上MA20+放量+ADX）。三者共振时置信度最高。因果链: 注意力↑→资金流入↑→突破确认↑→趋势启动",
        "causal_chain": [
            "Step1: 市场注意力上升 — 成交量放大(vol_ratio>1.3) + 情绪/叙事热度为正",
            "Step2: 资金持续流入 — 竞品轮动信号为正(capital_rotation>0) + 资金流为正(capital_flow>0)",
            "Step3: 技术突破确认 — 价格站上MA20 + 放量(vol_ratio>1.3) + 趋势强度(ADX>20)",
            "Step4: 三因素共振 → 高置信做多（最小阻力路径）",
        ],
        "trigger": {
            "vol_ratio_min": 1.3,
            "capital_rotation_min": 0.1,
            "capital_flow_min": 0.0,
            "adx_min": 20,
            "price_above_ma20": True,
        },
        "data_required": ["close", "vol_ratio", "capital_rotation", "capital_flow", "adx", "sentiment", "narrative"],
        "logic": "注意力(量比+情绪) ∩ 资金流入(轮动+资金流) ∩ 突破(MA20+ADX) → 高置信做多",
        "direction": "long",
        "initial_score": 0.7,  # 三因素共振，初始评分最高
        "tags": ["attention", "capital_flow", "breakout", "triple_confirm", "core", "deep_causal"],
    },
}


class PathLibrary:
    """
    最优路径库 — 参考模板 + 盈亏评分 + 自进化

    使用方式:
      1. get_paths() → 获取所有参考路径
      2. evaluate_path(path_name, kline_data) → 计算路径在当前数据下的信号
      3. record_trade(path_name, pnl_pct) → 用盈亏更新路径评分
      4. get_top_paths(n) → 获取评分最高的 n 条路径
    """

    def __init__(self, persist_path: str | None = None):
        self._paths: dict[str, dict[str, Any]] = {}
        for name, template in REFERENCE_PATHS.items():
            self._paths[name] = {
                **template,
                "score": template["initial_score"],
                "n_trades": 0,
                "win_rate": 0.0,
                "avg_pnl": 0.0,
                "total_pnl": 0.0,
                "last_updated": None,
            }
        self._persist_path = persist_path
        if persist_path:
            self._load()

    # ------------------------------------------------------------------
    # 路径查询
    # ------------------------------------------------------------------

    def get_paths(self) -> dict[str, dict[str, Any]]:
        """获取所有路径及其当前评分"""
        return {
            name: {k: v for k, v in p.items() if k != "trigger"}
            for name, p in self._paths.items()
        }

    def get_path(self, name: str) -> dict[str, Any] | None:
        return self._paths.get(name)

    def get_top_paths(self, n: int = 3) -> list[tuple[str, float]]:
        """获取评分最高的 n 条路径"""
        ranked = sorted(
            self._paths.items(),
            key=lambda x: x[1]["score"],
            reverse=True,
        )
        return [(name, p["score"]) for name, p in ranked[:n]]

    # ------------------------------------------------------------------
    # 路径评估（数据验证）
    # ------------------------------------------------------------------

    def evaluate_path(self, path_name: str, kline_data: dict[str, Any]) -> dict[str, Any]:
        """
        用当前市场数据评估路径是否触发。

        Returns:
            {
                "triggered": bool,       # 路径是否触发
                "direction": str,        # long/short/neutral
                "confidence": float,     # [0, 1] 置信度
                "reason": str,           # 触发/未触发原因
            }
        """
        path = self._paths.get(path_name)
        if path is None:
            return {"triggered": False, "direction": "neutral",
                    "confidence": 0.0, "reason": "path_not_found"}

        try:
            trigger = path["trigger"]
            direction = "neutral"
            confidence = 0.0
            reason = ""

            if path_name == "capital_rotation":
                rotation = kline_data.get("capital_rotation", 0.0)
                regime = kline_data.get("regime", "ranging")
                if abs(rotation) >= trigger["capital_rotation_abs"] and regime in trigger["regime_in"]:
                    direction = "long" if rotation > 0 else "short"
                    confidence = min(1.0, abs(rotation))
                    reason = f"rotation={rotation:+.3f} regime={regime}"
                else:
                    reason = f"rotation={rotation:+.3f} regime={regime} (未达阈值)"

            elif path_name == "momentum_breakout":
                close = kline_data.get("close", [])
                vol_ratio = kline_data.get("vol_ratio", 1.0)
                adx = kline_data.get("adx", 0)
                if close and len(close) >= 20:
                    ma20 = sum(close[-20:]) / 20
                    price_above = close[-1] > ma20
                    if price_above and vol_ratio >= trigger["vol_ratio_min"] and adx >= trigger["adx_min"]:
                        direction = "long"
                        confidence = min(1.0, (vol_ratio - 1.0) * 0.5 + (adx - 20) / 100)
                        reason = f"price>MA20 vol_ratio={vol_ratio:.2f} adx={adx:.1f}"
                    else:
                        reason = f"price_above={price_above} vol={vol_ratio:.2f} adx={adx:.1f}"
                else:
                    reason = "insufficient_data"

            elif path_name == "mean_reversion":
                regime = kline_data.get("regime", "ranging")
                close = kline_data.get("close", [])
                if regime == trigger["regime_eq"] and close and len(close) >= 20:
                    ma20 = sum(close[-20:]) / 20
                    std20 = self._std(close[-20:])
                    if std20 > 0:
                        z = (close[-1] - ma20) / std20
                        if abs(z) >= trigger["z_score_abs"]:
                            direction = "short" if z > 0 else "long"
                            confidence = min(1.0, abs(z) / 4.0)
                            reason = f"z_score={z:.2f} regime={regime}"
                        else:
                            reason = f"z_score={z:.2f} < 2.0"
                    else:
                        reason = "zero_volatility"
                else:
                    reason = f"regime={regime} (need ranging)"

            elif path_name == "oi_divergence":
                oi_change = kline_data.get("oi_change_pct", 0.0)
                close = kline_data.get("close", [])
                if abs(oi_change) >= trigger["oi_change_pct_abs"] and close and len(close) >= 2:
                    price_up = close[-1] > close[-2]
                    oi_up = oi_change > 0
                    if price_up != oi_up:  # 背离
                        direction = "short" if oi_up else "long"
                        confidence = min(1.0, abs(oi_change) * 10)
                        reason = f"oi={oi_change:+.3f} price_up={price_up} (divergence)"
                    else:
                        reason = "no_divergence"
                else:
                    reason = f"oi_change={oi_change:+.3f} (below threshold)"

            elif path_name == "funding_rate_arb":
                funding = kline_data.get("funding_rate", 0.0)
                if abs(funding) >= trigger["funding_rate_abs"]:
                    direction = "short" if funding > 0 else "long"
                    confidence = min(1.0, abs(funding) / 0.005)
                    reason = f"funding_rate={funding:+.5f}"
                else:
                    reason = f"funding_rate={funding:+.5f} (below threshold)"

            elif path_name == "volume_surge":
                vol_ratio = kline_data.get("vol_ratio", 1.0)
                if vol_ratio >= trigger["vol_ratio_min"]:
                    close = kline_data.get("close", [])
                    direction = "long" if (close and len(close) >= 2 and close[-1] > close[-2]) else "short"
                    confidence = min(1.0, vol_ratio / 5.0)
                    reason = f"vol_ratio={vol_ratio:.2f} (surge)"
                else:
                    reason = f"vol_ratio={vol_ratio:.2f} < 3.0"

            elif path_name == "regime_adaptive":
                regime = kline_data.get("regime", "ranging")
                close = kline_data.get("close", [])
                if close and len(close) >= 20:
                    ma20 = sum(close[-20:]) / 20
                    if regime == "trend_up":
                        direction = "long"
                        confidence = 0.6
                        reason = f"regime=trend_up follow momentum"
                    elif regime == "trend_down":
                        direction = "short"
                        confidence = 0.6
                        reason = f"regime=trend_down follow momentum"
                    else:
                        z = (close[-1] - ma20) / max(self._std(close[-20:]), 1e-9)
                        direction = "short" if z > 0 else "long"
                        confidence = min(0.5, abs(z) / 4.0)
                        reason = f"regime=ranging mean_revert z={z:.2f}"
                else:
                    reason = "insufficient_data"

            # ==================== 深度多步因果路径 ====================
            elif path_name == "protocol_revenue":
                # 因果链: 协议收入↑ → 价值捕获↑ → 代币↑
                vol_ratio = kline_data.get("vol_ratio", 1.0)
                close = kline_data.get("close", [])
                rotation = kline_data.get("capital_rotation", 0.0)
                if close and len(close) >= 20:
                    ma20 = sum(close[-20:]) / 20
                    price_above = close[-1] > ma20
                    if vol_ratio >= trigger["vol_ratio_min"] and price_above and rotation > 0:
                        direction = "long"
                        confidence = min(1.0, (vol_ratio - 1.0) * 0.4 + rotation * 0.5)
                        reason = f"vol={vol_ratio:.2f} price>MA20 rot={rotation:+.3f}"
                    else:
                        reason = f"vol={vol_ratio:.2f} above_ma={price_above} rot={rotation:+.3f}"
                else:
                    reason = "insufficient_data"

            elif path_name == "exchange_token_cycle":
                # 因果链: 交易量↑ → 收入↑ → 回购销毁↑ → 价格↑
                symbol = kline_data.get("symbol", "")
                vol_ratio = kline_data.get("vol_ratio", 1.0)
                if symbol in trigger["symbol_in"] and vol_ratio >= trigger["vol_ratio_min"]:
                    direction = "long"
                    confidence = min(1.0, (vol_ratio - 1.0) * 0.4)
                    reason = f"{symbol} exchange_token vol={vol_ratio:.2f}"
                else:
                    reason = f"symbol={symbol} vol={vol_ratio:.2f} (not exchange_token or low vol)"

            elif path_name == "stablecoin_inflow":
                # 因果链: 稳定币供给↑ → 购买力↑ → 资产价格↑
                regime = kline_data.get("regime", "ranging")
                vol_ratio = kline_data.get("vol_ratio", 1.0)
                cap_flow = kline_data.get("capital_flow", 0.0)
                rotation = kline_data.get("capital_rotation", 0.0)
                inflow = cap_flow > 0 or rotation > 0
                if regime == "trend_up" and vol_ratio >= trigger["vol_ratio_min"] and inflow:
                    direction = "long"
                    confidence = min(1.0, (vol_ratio - 1.0) * 0.3 + abs(cap_flow) * 0.3 + rotation * 0.3)
                    reason = f"regime={regime} vol={vol_ratio:.2f} flow_inflow={inflow}"
                else:
                    reason = f"regime={regime} vol={vol_ratio:.2f} inflow={inflow}"

            elif path_name == "lsd_staking_flow":
                # 因果链: ETH质押↑ → LSD需求↑ → 协议收入↑ → 代币↑
                symbol = kline_data.get("symbol", "")
                vol_ratio = kline_data.get("vol_ratio", 1.0)
                if symbol in trigger["symbol_in"] and vol_ratio >= trigger["vol_ratio_min"]:
                    direction = "long"
                    confidence = min(1.0, (vol_ratio - 1.0) * 0.4)
                    reason = f"{symbol} LSD_eco vol={vol_ratio:.2f}"
                else:
                    reason = f"symbol={symbol} vol={vol_ratio:.2f}"

            elif path_name == "funding_squeeze":
                # 因果链: 费率极端 → 拥挤交易 → 清算 → 反转
                funding = kline_data.get("funding_rate", 0.0)
                vol_ratio = kline_data.get("vol_ratio", 1.0)
                if abs(funding) >= trigger["funding_rate_abs"]:
                    direction = "short" if funding > 0 else "long"
                    confidence = min(1.0, abs(funding) / 0.005 + vol_ratio * 0.1)
                    reason = f"funding={funding:+.5f} (squeeze risk) vol={vol_ratio:.2f}"
                else:
                    reason = f"funding={funding:+.5f} (normal)"

            elif path_name == "cross_chain_flow":
                # 因果链: 桥接净流入 → 链上活跃 → 原生代币需求↑ → 价格↑
                symbol = kline_data.get("symbol", "")
                vol_ratio = kline_data.get("vol_ratio", 1.0)
                rotation = kline_data.get("capital_rotation", 0.0)
                if symbol in trigger["symbol_in"] and vol_ratio >= trigger["vol_ratio_min"] and rotation > 0:
                    direction = "long"
                    confidence = min(1.0, (vol_ratio - 1.0) * 0.4 + rotation * 0.4)
                    reason = f"{symbol} L1/L2 vol={vol_ratio:.2f} rot_in={rotation:+.3f}"
                else:
                    reason = f"symbol={symbol} vol={vol_ratio:.2f} rot={rotation:+.3f}"

            elif path_name == "meme_season_rotation":
                # 因果链: Meme爆发 → PUMP收入↑ → PUMP↑ → 其他板块资金流出
                symbol = kline_data.get("symbol", "")
                vol_ratio = kline_data.get("vol_ratio", 1.0)
                rotation = kline_data.get("capital_rotation", 0.0)
                if symbol in trigger["symbol_in"]:
                    if vol_ratio >= trigger["vol_ratio_min"]:
                        direction = "long"
                        confidence = min(1.0, (vol_ratio - 1.0) * 0.3 + max(0, rotation) * 0.3)
                        reason = f"{symbol} meme_season vol={vol_ratio:.2f}"
                    else:
                        reason = f"{symbol} vol={vol_ratio:.2f} (below 2.0)"
                elif rotation < -0.1:
                    # 非PUMP币 + 资金流出（被Meme吸血）
                    direction = "short"
                    confidence = min(1.0, abs(rotation) * 0.5)
                    reason = f"meme_season capital_outflow rot={rotation:+.3f}"
                else:
                    reason = f"symbol={symbol} rot={rotation:+.3f} (no meme impact)"

            elif path_name == "etf_flow_amplification":
                # 因果链: ETF净流入 → BTC/ETH需求↑ → 交易所/矿企收入↑ → 概念股↑
                symbol = kline_data.get("symbol", "")
                vol_ratio = kline_data.get("vol_ratio", 1.0)
                cap_flow = kline_data.get("capital_flow", 0.0)
                if symbol in trigger["symbol_in"] and vol_ratio >= trigger["vol_ratio_min"] and cap_flow > 0:
                    direction = "long"
                    confidence = min(1.0, (vol_ratio - 1.0) * 0.4 + cap_flow * 0.3)
                    reason = f"{symbol} ETF_related vol={vol_ratio:.2f} flow={cap_flow:+.3f}"
                else:
                    reason = f"symbol={symbol} vol={vol_ratio:.2f} flow={cap_flow:+.3f}"

            elif path_name == "gas_fee_economics":
                # 因果链: 链上活跃↑ → Gas↑ → 质押收入↑ → 原生代币↑
                symbol = kline_data.get("symbol", "")
                vol_ratio = kline_data.get("vol_ratio", 1.0)
                if symbol in trigger["symbol_in"] and vol_ratio >= trigger["vol_ratio_min"]:
                    direction = "long"
                    confidence = min(1.0, (vol_ratio - 1.0) * 0.4)
                    reason = f"{symbol} L1_gas_econ vol={vol_ratio:.2f}"
                else:
                    reason = f"symbol={symbol} vol={vol_ratio:.2f}"

            elif path_name == "attention_capital_breakout":
                # 三因素共振: 注意力 + 资金流入 + 突破确认
                vol_ratio = kline_data.get("vol_ratio", 1.0)
                rotation = kline_data.get("capital_rotation", 0.0)
                cap_flow = kline_data.get("capital_flow", 0.0)
                adx = kline_data.get("adx", 0)
                close = kline_data.get("close", [])
                sentiment = kline_data.get("sentiment") or kline_data.get("news_sentiment_score") or 0.0
                narrative = kline_data.get("narrative") or 0.0

                # 因素1: 市场注意力（放量 + 情绪/叙事热度）
                attention_vol = vol_ratio >= trigger["vol_ratio_min"]
                attention_sent = sentiment > 0 or narrative > 0
                attention_ok = attention_vol and attention_sent
                attention_score = min(1.0, (vol_ratio - 1.0) * 0.4 + max(sentiment, narrative) * 0.3)

                # 因素2: 资金持续流入（轮动 + 资金流）
                capital_ok = rotation >= trigger["capital_rotation_min"] and cap_flow >= trigger["capital_flow_min"]
                capital_score = min(1.0, rotation * 0.5 + cap_flow * 0.3)

                # 因素3: 技术突破确认（MA20 + 放量 + ADX）
                price_above = False
                if close and len(close) >= 20:
                    ma20 = sum(close[-20:]) / 20
                    price_above = close[-1] > ma20
                breakout_ok = price_above and vol_ratio >= trigger["vol_ratio_min"] and adx >= trigger["adx_min"]
                breakout_score = min(1.0, (1 if price_above else 0) * 0.3 + (vol_ratio - 1.0) * 0.3 + (adx - 20) / 100)

                if attention_ok and capital_ok and breakout_ok:
                    # 三因素全部满足 → 高置信做多
                    direction = "long"
                    # 置信度 = 三因素得分加权平均（三因素共振，置信度上限更高）
                    confidence = min(0.95, (attention_score * 0.3 + capital_score * 0.35 + breakout_score * 0.35))
                    reason = (f"TRIPLE_OK attn={attention_score:.2f}(vol={vol_ratio:.2f},sent={sentiment:.2f}) "
                              f"cap={capital_score:.2f}(rot={rotation:+.3f},flow={cap_flow:+.3f}) "
                              f"brk={breakout_score:.2f}(ma20={price_above},adx={adx:.1f})")
                elif attention_ok and capital_ok and not breakout_ok:
                    # 注意力+资金到位但未突破 → 低置信等待
                    direction = "long"
                    confidence = min(0.3, (attention_score + capital_score) / 2 * 0.3)
                    reason = f"attn+cap OK, breakout pending (ma20={price_above} adx={adx:.1f})"
                else:
                    reason = (f"attn_ok={attention_ok} cap_ok={capital_ok} brk_ok={breakout_ok} | "
                              f"vol={vol_ratio:.2f} rot={rotation:+.3f} flow={cap_flow:+.3f} adx={adx:.1f} ma20={price_above}")

            else:
                reason = "unknown_path"

            return {
                "triggered": direction != "neutral",
                "direction": direction,
                "confidence": round(confidence, 4),
                "reason": reason,
            }
        except Exception as e:
            logger.debug("[FO] evaluate_path %s: %s", path_name, e)
            return {"triggered": False, "direction": "neutral",
                    "confidence": 0.0, "reason": f"error: {e}"}

    def evaluate_all(self, kline_data: dict[str, Any]) -> list[dict[str, Any]]:
        """评估所有路径，返回触发的路径列表（按置信度排序）"""
        results = []
        for name in self._paths:
            r = self.evaluate_path(name, kline_data)
            if r["triggered"]:
                results.append({"path": name, **r})
        results.sort(key=lambda x: x["confidence"], reverse=True)
        return results

    # ------------------------------------------------------------------
    # 盈亏评分（闭环学习）
    # ------------------------------------------------------------------

    def record_trade(self, path_name: str, pnl_pct: float) -> None:
        """
        用实际盈亏更新路径评分。

        评分规则 (贝叶斯式更新):
          - 盈利: score += 0.02 × min(1, |pnl|/0.05)  (最多+0.02)
          - 亏损: score -= 0.05 × min(1, |pnl|/0.05)  (最多-0.05)
          - score 钳制在 [0.1, 0.9]
          - 胜率和平均盈亏同步更新
        """
        path = self._paths.get(path_name)
        if path is None:
            return

        magnitude = min(1.0, abs(pnl_pct) / 0.05)  # 5% 盈亏为满刻度
        if pnl_pct > 0:
            delta = 0.02 * magnitude
        else:
            delta = -0.05 * magnitude

        old_score = path["score"]
        path["score"] = max(0.1, min(0.9, old_score + delta))

        # 更新统计
        path["n_trades"] += 1
        path["total_pnl"] += pnl_pct
        path["avg_pnl"] = path["total_pnl"] / path["n_trades"]
        wins = path.get("_wins", 0)
        if pnl_pct > 0:
            wins += 1
        path["_wins"] = wins
        path["win_rate"] = wins / path["n_trades"]

        from datetime import datetime
        path["last_updated"] = datetime.now().isoformat()

        logger.debug(
            "[PathLibrary] %s score %.3f→%.3f (pnl=%+.2f%% n=%d win=%.0f%%)",
            path_name, old_score, path["score"], pnl_pct * 100,
            path["n_trades"], path["win_rate"] * 100,
        )

        if self._persist_path:
            self._save()

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _save(self) -> None:
        try:
            data = {}
            for name, p in self._paths.items():
                data[name] = {
                    "score": p["score"],
                    "n_trades": p["n_trades"],
                    "win_rate": p["win_rate"],
                    "avg_pnl": p["avg_pnl"],
                    "total_pnl": p["total_pnl"],
                    "last_updated": p["last_updated"],
                }
            Path(self._persist_path).parent.mkdir(parents=True, exist_ok=True)
            Path(self._persist_path).write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("[FO] PathLibrary save: %s", e)

    def _load(self) -> None:
        try:
            if not Path(self._persist_path).exists():
                return
            data = json.loads(Path(self._persist_path).read_text(encoding="utf-8"))
            for name, stats in data.items():
                if name in self._paths:
                    self._paths[name].update(stats)
        except Exception as e:
            logger.warning("[FO] PathLibrary load: %s", e)

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    @staticmethod
    def _std(data: list[float]) -> float:
        if len(data) < 2:
            return 0.0
        mean = sum(data) / len(data)
        var = sum((x - mean) ** 2 for x in data) / len(data)
        return math.sqrt(var)

    # ─── FTC 拆解 ──────────────────────────────────────────────

    def decompose_to_ftc(self, path_name: str | None = None) -> list[FTC]:
        """
        将经验路径拆解为金融思维链 (FTC) 种子。

        拆解规则:
          - trigger 条件 → condition 步骤（可观测条件）
          - causal_chain 描述 → inference 步骤（因果推理，不执行）
          - direction/logic → action 步骤（交易动作）

        如果 path_name 为 None，拆解全部 17 条路径。
        """
        if not _FTC_AVAILABLE:
            logger.warning("FTC modules not available, skip decompose_to_ftc")
            return []

        path_names = [path_name] if path_name else list(self._paths.keys())
        ftcs: list[FTC] = []

        for name in path_names:
            path = self._paths.get(name)
            if not path:
                continue
            ftc = self._decompose_single_path(name, path)
            if ftc:
                ftcs.append(ftc)

        return ftcs

    def _decompose_single_path(self, name: str, path: dict) -> FTC | None:
        """将单条路径拆解为 FTC"""
        steps: list[FTCStep] = []

        trigger = path.get("trigger", {})
        causal_chain = path.get("causal_chain", [])
        data_required = path.get("data_required", [])
        direction = path.get("direction", "long")
        logic = path.get("logic", "")

        prev_step_id = None

        # Step 1+: 从 trigger 提取 condition 步骤
        condition_step_ids = []
        for trig_key, trig_val in trigger.items():
            if trig_key == "always":
                # regime_adaptive 等 always 路径: 创建一个 regime condition 占位
                cond_step = FTCStep(
                    step_id=gen_step_id(),
                    type="condition",
                    description="市场状态判断（趋势/震荡）",
                    gene_ref="CD-REGIME-DETECT",
                    data_required=["regime"],
                    depends_on=[],
                )
                steps.append(cond_step)
                condition_step_ids.append(cond_step.step_id)
                prev_step_id = cond_step.step_id
                continue
            cond_step = FTCStep(
                step_id=gen_step_id(),
                type="condition",
                description=f"{trig_key} = {trig_val}",
                gene_ref=self._map_trigger_to_gene(trig_key),
                data_required=[d for d in data_required if d in self._trigger_data_map.get(trig_key, [])],
                threshold=trig_val if isinstance(trig_val, (int, float)) else None,
                depends_on=[prev_step_id] if prev_step_id else [],
            )
            steps.append(cond_step)
            condition_step_ids.append(cond_step.step_id)
            prev_step_id = cond_step.step_id

        # 中间插入 inference 步骤（从 causal_chain 提取因果节点）
        if causal_chain:
            for chain_step in causal_chain:
                # 跳过纯 condition 描述的 step（已在上面处理）
                if any(kw in chain_step for kw in ("成交量", "vol", "放量", "价格", "站上", "突破", "资金", "轮动", "流入")):
                    # 这是条件描述，作为 inference 的因果解释
                    pass
                inf_step = FTCStep(
                    step_id=gen_step_id(),
                    type="inference",
                    description=chain_step,
                    logic=chain_step,
                    knowledge_ref=self._infer_knowledge_ref(name, chain_step),
                    depends_on=[prev_step_id] if prev_step_id else [],
                )
                steps.append(inf_step)
                prev_step_id = inf_step.step_id

        # 最后一步: action
        action_gene = self._map_direction_to_action(direction)
        action_step = FTCStep(
            step_id=gen_step_id(),
            type="action",
            description=f"{direction}: {logic}",
            gene_ref=action_gene,
            depends_on=[prev_step_id] if prev_step_id else [],
        )
        steps.append(action_step)

        # 构建 FTC
        ftc = FTC(
            ftc_id=f"FTC-{name.upper()}",
            name=path.get("name", name),
            steps=steps,
            source="experience_seed",
        )

        # 对齐知识锚点
        ftc.knowledge_alignment = align_to_anchors(ftc, top_k=3)
        ftc.track = get_track_by_similarity(ftc.max_similarity)

        return ftc

    def _map_trigger_to_gene(self, trigger_key: str) -> str:
        """将 trigger key 映射到 condition 基因 ID"""
        mapping = {
            "vol_ratio_min": "CD-VOL-SURGE",
            "price_above_ma20": "CD-PRICE-BREAKOUT",
            "adx_min": "CD-ADX-STRONG",
            "capital_rotation_abs": "CD-CAPITAL-ROTATION",
            "capital_rotation_min": "CD-CAPITAL-ROTATION",
            "capital_flow_min": "CD-CAPITAL-INFLOW",
            "oi_change_pct_abs": "CD-OI-DIVERGENCE",
            "funding_rate_abs": "CD-FUNDING-EXTREME",
            "z_score_abs": "CD-ZSCORE-EXTREME",
            "regime_eq": "CD-REGIME-RANGING",
            "regime_in": "CD-REGIME-TREND",
            "symbol_in": "CD-SYMBOL-MATCH",
        }
        return mapping.get(trigger_key, f"CD-{trigger_key.upper()}")

    def _map_direction_to_action(self, direction: str) -> str:
        """将 direction 映射到 action 基因 ID"""
        mapping = {
            "long": "AC-LONG",
            "short": "AC-SHORT",
            "follow_strong": "AC-FOLLOW-STRONG",
            "follow_oi": "AC-FOLLOW-OI",
            "follow_price": "AC-FOLLOW-PRICE",
            "contrarian": "AC-CONTRARIAN",
            "sector_rotation": "AC-SECTOR-ROTATION",
            "regime_dependent": "AC-REGIME-DEPENDENT",
        }
        return mapping.get(direction, "AC-LONG")

    def _infer_knowledge_ref(self, path_name: str, chain_step: str) -> str | None:
        """从路径名和因果步骤推断关联的金融理论"""
        # 路径名 → 理论映射
        path_theory_map = {
            "capital_rotation": "资金轮动",
            "momentum_breakout": "动量突破",
            "mean_reversion": "均值回归",
            "oi_divergence": "反身性",
            "funding_rate_arb": "费率套利",
            "funding_squeeze": "反身性",
            "volume_surge": "动量突破",
            "protocol_revenue": "价值捕获",
            "exchange_token_cycle": "价值捕获",
            "stablecoin_inflow": "资金轮动",
            "lsd_staking_flow": "价值捕获",
            "cross_chain_flow": "资金轮动",
            "meme_season_rotation": "资金轮动",
            "etf_flow_amplification": "价值捕获",
            "gas_fee_economics": "价值捕获",
            "attention_capital_breakout": "动量突破",
            "regime_adaptive": "均值回归",
        }
        return path_theory_map.get(path_name)

    # trigger key → 关联数据字段映射（用于拆解时填充 data_required）
    _trigger_data_map = {
        "vol_ratio_min": ["vol_5", "vol_20", "vol_ratio"],
        "price_above_ma20": ["close"],
        "adx_min": ["adx"],
        "capital_rotation_abs": ["capital_rotation"],
        "capital_rotation_min": ["capital_rotation"],
        "capital_flow_min": ["capital_flow"],
        "oi_change_pct_abs": ["oi_change_pct"],
        "funding_rate_abs": ["funding_rate"],
        "z_score_abs": ["close", "ma20", "std20"],
        "regime_eq": ["regime"],
        "regime_in": ["regime"],
        "symbol_in": ["symbol"],
    }
