#!/usr/bin/env python3
"""
MarketPreprocessor — 行情数据预处理层 (P0 核心修复)

解决 ForceEngine 信号断层问题：
将原始行情字段（price_change_pct/RSI/FGI/funding_rate 等）
映射为 ForceEngine 期望的四维归一化评分
（supply_demand_score/technical_score/capital_flow_score/sentiment_score）

设计原则（借鉴 vnpy BarGenerator/ArrayManager）：
- 输入: 任意行情快照（宽松，字段缺失有合理默认值）
- 输出: ForceEngine/YijingEngine 可直接消费的标准化快照
- 无状态: 每次调用独立，无副作用
- 可解释: 每个评分都有明确的映射逻辑

映射规则（基于量化金融标准）:
  supply_demand_score  ← price_change_pct (动量代理供需)
  technical_score      ← RSI + EMA排列 + 趋势强度
  capital_flow_score   ← funding_rate (资金费率反转) + OI变化
  sentiment_score      ← FGI (恐惧贪婪指数)
  long_cycle_position  ← 综合宏观位置代理
  price_position       ← 相对高低位估算
  trend_strength       ← 动量绝对值
  volatility           ← ATR估算
"""
from typing import Dict, Any, Optional
import math


class MarketPreprocessor:
    """
    行情数据预处理器。

    用法:
        prep = MarketPreprocessor()
        normalized = prep.normalize(raw_snapshot)
        out = bcrm_engine.infer(market_snapshot=normalized)
    """

    def normalize(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """
        将原始行情快照转换为 ForceEngine 标准化格式。

        Args:
            snapshot: 原始行情，可包含任意字段组合

        Returns:
            标准化快照，保留原始字段并追加归一化评分
        """
        result = dict(snapshot)

        # ── 读取原始指标（宽松容错）─────────────────────────────────────
        pct   = float(snapshot.get("price_change_pct",
                      snapshot.get("ch24", 0)) or 0)
        pct4h = float(snapshot.get("ch4h", pct * 0.4) or 0)
        rsi   = float(snapshot.get("rsi", snapshot.get("rsi14", 50)) or 50)
        fgi   = float(snapshot.get("fgi", 50) or 50)
        funding = float(snapshot.get("funding_rate", 0) or 0)
        vol_ratio = float(snapshot.get("volume_ratio", 1.0) or 1.0)
        oi_change = float(snapshot.get("oi_change_pct", 0) or 0)
        ema20 = float(snapshot.get("ema20", 0) or 0)
        ema50 = float(snapshot.get("ema50", 0) or 0)
        price = float(snapshot.get("price", 0) or 0)

        # ── 已有标准化评分则直接保留（避免重复处理）──────────────────────
        if all(k in snapshot for k in ("supply_demand_score", "technical_score",
                                        "capital_flow_score", "sentiment_score")):
            return result

        # ── 1. 供需评分（supply_demand_score）─────────────────────────────
        # 主要动量 + 量比加成 + OI方向
        momentum_raw = (pct * 0.6 + pct4h * 0.4)           # 加权动量
        momentum_norm = self._tanh_norm(momentum_raw, scale=15.0)  # tanh平滑到[-1,1]
        vol_bonus = math.log(max(vol_ratio, 0.1)) * 0.08    # 量比对数加成
        oi_bonus  = self._tanh_norm(oi_change, scale=20.0) * 0.05
        sd_score  = self._to_01(momentum_norm + vol_bonus + oi_bonus)
        result["supply_demand_score"] = sd_score

        # ── 2. 技术评分（technical_score）─────────────────────────────────
        # RSI + EMA排列 + 趋势方向一致性
        rsi_norm = (rsi - 50) / 50.0                        # RSI → [-1, 1]
        ema_signal = 0.0
        if ema20 > 0 and ema50 > 0 and price > 0:
            ema_cross = (ema20 - ema50) / ema50             # EMA20/50 差距
            ema_signal = self._tanh_norm(ema_cross * 100, scale=5.0) * 0.3
        tech_score = self._to_01(rsi_norm * 0.6 + ema_signal
                                  + self._tanh_norm(pct, scale=10.0) * 0.1)
        result["technical_score"] = tech_score

        # ── 3. 资金流评分（capital_flow_score）────────────────────────────
        # 资金费率（正费率=多头拥挤→空方信号，取反）+ OI
        funding_signal = -self._tanh_norm(funding * 10000, scale=5.0)  # 反转
        oi_signal = self._tanh_norm(oi_change, scale=20.0) * 0.3
        cf_score = self._to_01(funding_signal * 0.6 + oi_signal)
        result["capital_flow_score"] = cf_score

        # ── 4. 情绪评分（sentiment_score）─────────────────────────────────
        # FGI: 0=极度恐惧(做多机会), 100=极度贪婪(做空信号)，取反
        # 注意：FGI高→市场贪婪→短期看多，FGI低→市场恐惧→底部反转机会
        # 这里用"顺势"逻辑（贪婪→多头情绪强）
        sent_score = fgi / 100.0
        result["sentiment_score"] = sent_score

        # ── 5. 周期位置（long_cycle_position）────────────────────────────
        # 综合多信号估算长周期位置
        # 价格相对高低位代理（用RSI+动量合成）
        long_cycle = self._to_01(
            rsi_norm * 0.5 + self._tanh_norm(pct, scale=20.0) * 0.3
            + (sent_score - 0.5) * 0.2
        )
        result["long_cycle_position"] = long_cycle

        # ── 6. 价格位置（price_position）──────────────────────────────────
        # RSI作为价格相对高低位代理（RSI高=高位，RSI低=低位）
        result["price_position"] = rsi / 100.0

        # ── 7. 趋势强度（trend_strength）──────────────────────────────────
        trend_str = min(abs(pct) / 20.0, 1.0)
        result["trend_strength"] = trend_str

        # ── 8. 波动率（volatility）────────────────────────────────────────
        # 用 |pct| 和量比估算波动率代理
        vol_proxy = min((abs(pct) / 30.0 + (vol_ratio - 1.0) * 0.1), 1.0)
        result["volatility"] = max(vol_proxy, 0.05)

        # ── 调试信息（可选）──────────────────────────────────────────────
        result["_preprocessed"] = True
        result["_scores"] = {
            "supply_demand": round(sd_score, 3),
            "technical":     round(tech_score, 3),
            "capital_flow":  round(cf_score, 3),
            "sentiment":     round(sent_score, 3),
        }

        return result

    # ── 辅助函数 ──────────────────────────────────────────────────────────

    @staticmethod
    def _tanh_norm(x: float, scale: float = 10.0) -> float:
        """tanh 平滑归一化到 [-1, 1]，比硬截断更自然。"""
        return math.tanh(x / scale)

    @staticmethod
    def _to_01(x: float) -> float:
        """将 [-1, 1] 线性映射到 [0, 1]，并截断越界值。"""
        return max(0.0, min(1.0, (x + 1.0) / 2.0))


# ── 便捷函数 ─────────────────────────────────────────────────────────────────

_default_preprocessor = MarketPreprocessor()


def normalize_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """全局便捷函数：预处理行情快照。"""
    return _default_preprocessor.normalize(snapshot)
