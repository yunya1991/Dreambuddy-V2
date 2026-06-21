"""
信号生成引擎
基于多维度指标生成交易信号
"""

import math
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple


# 信号类型定义
SIGNAL_TYPES = {
    "strong_buy": {"strength": 0.8, "direction": 1, "horizon": "short"},
    "buy": {"strength": 0.6, "direction": 1, "horizon": "medium"},
    "hold": {"strength": 0.3, "direction": 0, "horizon": "medium"},
    "sell": {"strength": 0.6, "direction": -1, "horizon": "medium"},
    "strong_sell": {"strength": 0.8, "direction": -1, "horizon": "short"},
    "reduce": {"strength": 0.5, "direction": -1, "horizon": "short"},
    "risk_alert": {"strength": 0.5, "direction": 0, "horizon": "short"},
}


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class SignalEngine:
    """信号生成引擎"""

    def __init__(self):
        self.signal_counter = 0
        self.module_weights = {
            "flow": 1.5,
            "valuation": 1.4,
            "onchain": 1.3,
            "macro": 1.2,
            "news": 1.0,
            "sentiment": 1.0,
            "breadth": 1.0,
            "intermarket": 0.8,
            "narrative": 0.7,
            "calendar": 0.6,
        }

    # ---------- 公开 API ----------
    def generate_signals(
        self,
        resistance_3d: Dict[str, Any],
        metrics: Dict[str, Any],
        events: List[Dict[str, Any]] = None,
        stress: str = "normal",
    ) -> List[Dict[str, Any]]:
        """
        生成交易信号列表。

        Args:
            resistance_3d: 三维度计算结果
            metrics: 模块指标（支持平铺旧格式或 {core: {...}, breakdown: {...}} 新格式）
            events: 事件列表
            stress: 压力状态

        Returns:
            信号列表
        """
        signals: List[Dict[str, Any]] = []
        events = events or []

        core = self._normalize_metrics(metrics)
        module_name = self._detect_module(core)

        # 通用基础信号（趋势 + 情绪 + 背离 + 风险）
        signals.extend(self._base_signals(core, resistance_3d or {}, stress))

        # 模块专用信号
        signals.extend(self._module_specific_signals(module_name, core, resistance_3d or {}))

        # 事件驱动信号
        signals.extend(self._event_signals(events, core))

        # 信号去重（按 reason）
        seen_reasons = set()
        unique_signals: List[Dict[str, Any]] = []
        for sig in signals:
            reason = sig.get("reason", "")
            if reason and reason in seen_reasons:
                continue
            if reason:
                seen_reasons.add(reason)
            unique_signals.append(sig)
        return unique_signals

    def rank_signals(self, signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        对信号进行排序和筛选。

        Args:
            signals: 信号列表

        Returns:
            排序后的前 N 条信号
        """
        ranked = sorted(
            signals,
            key=lambda s: (
                _to_float(s.get("strength", 0)) * _to_float(s.get("confidence", 0))
                + _to_float(s.get("priority", 5)) / 10.0 * 0.3
            ),
            reverse=True,
        )
        return ranked[:5]

    # ---------- 新增：综合信号 ----------
    def generate_composite_signals(self, module_snapshots: Dict[str, Any]) -> Dict[str, Any]:
        """
        根据所有模块 snapshot 汇总生成综合信号。

        Args:
            module_snapshots: { module_name: snapshot_data }，每个 snapshot 含 resistance_3d

        Returns:
            综合信号对象
        """
        module_scores: Dict[str, Dict[str, Any]] = {}
        directions_map: Dict[str, str] = {}

        for module_name, snap in (module_snapshots or {}).items():
            snap = snap or {}
            r3d = snap.get("resistance_3d", {}) if isinstance(snap, dict) else {}
            snap_metrics = snap.get("metrics", {}) if isinstance(snap, dict) else {}
            score_entry = {
                "score": _to_float(r3d.get("direction_score", 0), 0.0),
                "confidence": _to_float(r3d.get("confidence", 0.5), 0.5),
                "velocity": _to_float(r3d.get("velocity", 0), 0.0),
                "metrics": self._normalize_metrics(snap_metrics),
            }
            module_scores[module_name] = score_entry
            directions_map[module_name] = self._module_vote(r3d)

        # 加权平均
        total_weight = 0.0
        weighted_score = 0.0
        weighted_confidence = 0.0
        for m, info in module_scores.items():
            w = _to_float(self.module_weights.get(m, 1.0), 1.0)
            total_weight += w
            weighted_score += w * info["score"]
            weighted_confidence += w * info["confidence"]
        if total_weight > 0:
            weighted_score /= total_weight
            weighted_confidence /= total_weight

        weighted_score = max(-1.0, min(1.0, weighted_score))
        weighted_confidence = max(0.0, min(1.0, weighted_confidence))

        strength_val = int(round(50 + weighted_score * 50))

        # 一致性评估
        directions = list(directions_map.values()) or ["neutral"]
        bullish_ratio = directions.count("bullish") / len(directions)
        bearish_ratio = directions.count("bearish") / len(directions)
        consistency = max(bullish_ratio, bearish_ratio) * 100

        # 推荐映射
        if weighted_score > 0.35 and consistency > 60:
            recommendation = "强烈买入"
        elif weighted_score > 0.15:
            recommendation = "买入"
        elif weighted_score > -0.15:
            recommendation = "观望"
        elif weighted_score > -0.35:
            recommendation = "减仓"
        else:
            recommendation = "强烈卖出"

        reasons = self._build_reasons(module_scores)
        risk_warnings = self._build_risk_warnings(module_scores)
        best_opportunities = self._build_best_opportunities(module_scores)

        # 汇总各模块信号
        top_signals: List[Dict[str, Any]] = []
        now = datetime.now(timezone.utc).isoformat()
        for module_name, info in module_scores.items():
            sig_type, reason, priority = self._top_signal_for_module(module_name, info)
            if sig_type:
                top_signals.append({
                    "id": f"sig_composite_{module_name}",
                    "type": sig_type,
                    "module": module_name,
                    "strength": round(abs(info["score"]), 2),
                    "confidence": round(info["confidence"], 2),
                    "reason": reason,
                    "horizon": "medium",
                    "factors": [module_name],
                    "created_at": now,
                    "priority": priority,
                })

        top_signals = self.rank_signals(top_signals)

        return {
            "score": round(weighted_score, 3),
            "confidence": round(weighted_confidence, 2),
            "strength": strength_val,
            "recommendation": recommendation,
            "reasons": reasons,
            "module_consensus": directions_map,
            "cross_module_validation": {
                "consistency_score": int(round(consistency)),
                "divergent_modules": [
                    m for m, d in directions_map.items()
                    if d != ("bullish" if bullish_ratio >= bearish_ratio else "bearish")
                    and d != "neutral"
                ],
            },
            "best_opportunities": best_opportunities,
            "risk_warnings": risk_warnings,
            "top_signals": top_signals,
        }

    # ---------- 新增：模块投票 ----------
    def _module_vote(self, resistance_3d: Dict[str, Any]) -> str:
        """把 resistance_3d 方向映射为 bullish / bearish / neutral。"""
        score = _to_float(resistance_3d.get("direction_score", 0), 0.0)
        if score > 0.15:
            return "bullish"
        if score < -0.15:
            return "bearish"
        return "neutral"

    # ---------- 新增：信号总结 ----------
    def generate_summary(self, signals: List[Dict[str, Any]], top_n: int = 3) -> str:
        """
        把 top N 信号整合为中文总结段落字符串。

        Args:
            signals: 信号列表
            top_n: 取前 N 个

        Returns:
            中文总结段落
        """
        if not signals:
            return "当前无明确交易信号，建议保持观望，关注基本面变化。"

        ranked = self.rank_signals(signals)[:top_n]

        type_cn = {
            "strong_buy": "强烈买入",
            "buy": "买入",
            "hold": "观望",
            "sell": "卖出",
            "strong_sell": "强烈卖出",
            "reduce": "减仓",
            "risk_alert": "风险提示",
        }

        parts = []
        for idx, sig in enumerate(ranked, 1):
            t = type_cn.get(sig.get("type"), "信号")
            reason = sig.get("reason", "")
            module = sig.get("module", "通用")
            parts.append(f"{idx}. 【{module}-{t}】{reason}")

        header = "综合信号总结：\n" + "\n".join(parts)
        return header

    # ---------- 内部辅助：指标标准化与模块识别 ----------
    def _normalize_metrics(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """兼容新旧两种 metrics 格式，统一返回平铺字典。"""
        if not metrics or not isinstance(metrics, dict):
            return {}
        if "core" in metrics and isinstance(metrics["core"], dict):
            core = dict(metrics["core"])
            if isinstance(metrics.get("breakdown"), dict):
                for k, v in metrics["breakdown"].items():
                    if k not in core:
                        core[k] = v
            return core
        return dict(metrics)

    def _detect_module(self, core: Dict[str, Any]) -> str:
        """根据 metrics 字段特征推断模块类型。"""
        if not core:
            return "generic"

        keys_lower = {k.lower() for k in core.keys()}

        def has(*names: str) -> bool:
            return any(n in keys_lower for n in names)

        if has("smart_money_direction", "smart_money", "etf_net_flow", "liquidation_pressure",
                "funding_rate", "stablecoin_supply_change", "whale_activity"):
            return "flow"
        if has("sentiment_index", "fear_greed_index", "narrative_heat", "consensus_level", "reversal_risk"):
            return "sentiment"
        if has("policy_score", "dxy_strength", "rate_impact", "crypto_friendly_score"):
            return "macro"
        if has("mvrv_z_score", "sopr", "ahr999", "pi_cycle_top", "mayer_multiple"):
            return "valuation"
        if has("whale_accumulation_score", "miner_position", "gas_price_gwei"):
            return "onchain"
        if has("news_sentiment", "news_volume", "news_count"):
            return "news"
        if has("breadth_index", "advancers", "decliners"):
            return "breadth"
        if has("spx_correlation", "gold_correlation"):
            return "intermarket"
        if has("calendar_events", "upcoming_events_count", "upcoming_events"):
            return "calendar"
        if has("narrative_score", "narrative_trend"):
            return "narrative"
        return "generic"

    # ---------- 基础/通用信号 ----------
    def _base_signals(
        self, core: Dict[str, Any], resistance_3d: Dict[str, Any], stress: str
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        direction = resistance_3d.get("direction", "neutral")
        velocity = _to_float(resistance_3d.get("velocity", 0), 0.0)
        sentiment = _to_float(core.get("sentiment", core.get("sentiment_index", 50)), 50.0)
        fear_greed = _to_float(core.get("fear_greed", core.get("fear_greed_index", 50)), 50.0)
        acceleration = _to_float(resistance_3d.get("acceleration", 0), 0.0)

        trend = self._trend_signal(direction, velocity, sentiment)
        if trend:
            out.append(trend)

        emotion = self._emotion_signal(fear_greed, sentiment)
        if emotion:
            out.append(emotion)

        divergence = self._divergence_signal(velocity, acceleration, sentiment)
        if divergence:
            out.append(divergence)

        risk = self._risk_signal(stress, sentiment, fear_greed)
        if risk:
            out.append(risk)
        return out

    def _event_signals(self, events: List[Dict[str, Any]], core: Dict[str, Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not events:
            return out
        for ev in events[:3]:
            if not isinstance(ev, dict):
                continue
            ev_type = str(ev.get("type", ev.get("kind", "event")))
            severity = ev.get("severity", "medium")
            weight = {"high": 0.8, "medium": 0.55, "low": 0.35}.get(severity, 0.4)
            impact = str(ev.get("impact", ev.get("direction", "warning"))).lower()
            sig_type_map = {"bullish": "buy", "bearish": "sell"}
            signal_type = sig_type_map.get(impact, "risk_alert")
            self.signal_counter += 1
            reason_value = ev.get("reason") or ev.get("title") or f"{ev_type} 事件发生"
            out.append({
                "id": f"sig_event_{self.signal_counter:04d}",
                "type": signal_type,
                "module": "event",
                "strength": weight,
                "confidence": 0.55,
                "reason": self._format_reason(ev_type, reason_value),
                "horizon": "short",
                "factors": [ev_type, severity],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "priority": 6,
            })
        return out

    # ---------- 原有信号生成器 ----------
    def _trend_signal(self, direction: str, velocity: float, sentiment: float) -> Optional[Dict]:
        self.signal_counter += 1
        sig_id = f"sig_trend_{self.signal_counter:04d}"
        ts = datetime.now(timezone.utc).isoformat()

        direction = str(direction or "").lower()
        velocity = float(velocity or 0)
        sentiment = float(sentiment or 50)

        if direction == "up" and velocity > 0.3 and sentiment > 55:
            return {
                "id": sig_id, "type": "strong_buy", "module": "trend",
                "strength": 0.8, "confidence": min(1.0, velocity + 0.3),
                "reason": "上升趋势强劲，多头信号确认", "horizon": "short",
                "factors": ["趋势向上", "速度较快", "情绪乐观"],
                "created_at": ts, "priority": 8,
            }
        if direction == "up" and sentiment > 52:
            return {
                "id": sig_id, "type": "buy", "module": "trend",
                "strength": 0.6, "confidence": min(1.0, sentiment / 100),
                "reason": "趋势向上，看涨信号", "horizon": "medium",
                "factors": ["趋势向上", "情绪偏好"],
                "created_at": ts, "priority": 6,
            }
        if direction == "down" and velocity < -0.3 and sentiment < 45:
            return {
                "id": sig_id, "type": "strong_sell", "module": "trend",
                "strength": 0.8, "confidence": min(1.0, abs(velocity) + 0.3),
                "reason": "下降趋势强劲，空头信号确认", "horizon": "short",
                "factors": ["趋势向下", "速度较快", "情绪悲观"],
                "created_at": ts, "priority": 8,
            }
        if direction == "down" and sentiment < 48:
            return {
                "id": sig_id, "type": "sell", "module": "trend",
                "strength": 0.6, "confidence": min(1.0, (100 - sentiment) / 100),
                "reason": "趋势向下，看跌信号", "horizon": "medium",
                "factors": ["趋势向下", "情绪偏弱"],
                "created_at": ts, "priority": 6,
            }
        return None

    def _emotion_signal(self, fear_greed: float, sentiment: float) -> Optional[Dict]:
        self.signal_counter += 1
        sig_id = f"sig_emotion_{self.signal_counter:04d}"
        ts = datetime.now(timezone.utc).isoformat()

        fear_greed = float(fear_greed or 50)
        sentiment = float(sentiment or 50)

        if fear_greed >= 85 or sentiment >= 80:
            return {
                "id": sig_id, "type": "sell", "module": "sentiment",
                "strength": 0.5, "confidence": 0.6,
                "reason": self._format_reason("fear_greed", fear_greed),
                "horizon": "short", "factors": ["情绪极端", "警惕回调"],
                "created_at": ts, "priority": 7,
            }
        if fear_greed <= 15 or sentiment <= 20:
            return {
                "id": sig_id, "type": "buy", "module": "sentiment",
                "strength": 0.5, "confidence": 0.6,
                "reason": self._format_reason("fear_greed_low", fear_greed),
                "horizon": "medium", "factors": ["情绪极端", "逆向机会"],
                "created_at": ts, "priority": 7,
            }
        return None

    def _divergence_signal(self, velocity: float, acceleration: float, sentiment: float) -> Optional[Dict]:
        self.signal_counter += 1
        sig_id = f"sig_div_{self.signal_counter:04d}"
        ts = datetime.now(timezone.utc).isoformat()

        velocity = float(velocity or 0)
        acceleration = float(acceleration or 0)
        sentiment = float(sentiment or 50)

        if velocity > 0.2 and acceleration < -0.2 and sentiment < 40:
            return {
                "id": sig_id, "type": "sell", "module": "divergence",
                "strength": 0.6, "confidence": 0.7,
                "reason": "价格与情绪背离，警惕反转", "horizon": "short",
                "factors": ["顶背离", "动量减弱"],
                "created_at": ts, "priority": 7,
            }
        if velocity < -0.2 and acceleration > 0.2 and sentiment > 60:
            return {
                "id": sig_id, "type": "buy", "module": "divergence",
                "strength": 0.6, "confidence": 0.7,
                "reason": "价格与情绪背离，可能反弹", "horizon": "short",
                "factors": ["底背离", "动量增强"],
                "created_at": ts, "priority": 7,
            }
        return None

    def _risk_signal(self, stress: str, sentiment: float, fear_greed: float) -> Optional[Dict]:
        self.signal_counter += 1
        sig_id = f"sig_risk_{self.signal_counter:04d}"
        ts = datetime.now(timezone.utc).isoformat()

        stress = str(stress or "").lower()
        sentiment = float(sentiment or 50)
        fear_greed = float(fear_greed or 50)

        if stress == "high" and (sentiment > 60 or fear_greed > 70):
            return {
                "id": sig_id, "type": "reduce", "module": "risk",
                "strength": 0.5, "confidence": 0.6,
                "reason": "市场压力较大，建议减仓", "horizon": "short",
                "factors": ["市场高压", "风险警惕"],
                "created_at": ts, "priority": 8,
            }
        return None

    # ---------- 模块专用信号 ----------
    def _module_specific_signals(
        self, module_name: str, metrics: Dict[str, Any], resistance_3d: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        now = datetime.now(timezone.utc).isoformat()

        def make_sig(sig_type: str, strength: float, confidence: float,
                     reason: str, module: str, factors: List[str],
                     priority: int = 5, horizon: str = "medium") -> Dict[str, Any]:
            self.signal_counter += 1
            return {
                "id": f"sig_{module}_{self.signal_counter:04d}",
                "type": sig_type, "module": module,
                "strength": strength, "confidence": confidence,
                "reason": reason, "horizon": horizon,
                "factors": factors, "created_at": now, "priority": priority,
            }

        if module_name == "flow":
            smart_money = _to_float(metrics.get("smart_money_direction", 0), 0.0)
            etf_flow = _to_float(metrics.get("etf_net_flow", 0), 0.0)
            liq = _to_float(metrics.get("liquidation_pressure", 0), 0.0)
            funding = _to_float(metrics.get("funding_rate", 0), 0.0)
            stable = _to_float(metrics.get("stablecoin_supply_change", 0), 0.0)
            whale = _to_float(metrics.get("whale_activity", 0), 0.0)
            ex_net = _to_float(metrics.get("exchange_net_flow", 0), 0.0)

            if smart_money > 0.3 or etf_flow > 100:
                out.append(make_sig(
                    "buy", min(0.7, 0.5 + smart_money / 2 + etf_flow / 400),
                    0.75, self._format_reason("smart_money_etf", (smart_money, etf_flow)),
                    "flow", ["聪明钱流入", "ETF 净流入"], priority=8))
            if liq > 70:
                out.append(make_sig(
                    "buy", min(0.65, 0.4 + liq / 200), 0.6,
                    self._format_reason("liquidation", liq),
                    "flow", ["高清算压力", "反向机会"], priority=7))
            if funding > 0.05:
                out.append(make_sig(
                    "reduce", 0.55, 0.6,
                    self._format_reason("funding_high", funding),
                    "flow", ["资金费率过高", "多头拥挤"], priority=7))
            if stable > 0:
                out.append(make_sig(
                    "buy", min(0.55, 0.35 + stable / 200), 0.55,
                    self._format_reason("stablecoin", stable),
                    "flow", ["稳定币供给增加", "潜在买入"], priority=6))
            if whale > 0.5 and ex_net < 0:
                out.append(make_sig(
                    "strong_buy", 0.75, 0.7,
                    self._format_reason("whale_exchange", (whale, ex_net)),
                    "flow", ["鲸鱼活跃", "交易所外流"], priority=8))

        elif module_name == "sentiment":
            sent_idx = _to_float(metrics.get("sentiment_index", 50), 50.0)
            fgi = _to_float(metrics.get("fear_greed_index", 50), 50.0)
            heat = _to_float(metrics.get("narrative_heat", 0.5), 0.5)
            consensus = _to_float(metrics.get("consensus_level", 50), 50.0)
            rev_risk = _to_float(metrics.get("reversal_risk", 0), 0.0)

            if sent_idx > 60:
                out.append(make_sig(
                    "buy", min(0.6, 0.35 + (sent_idx - 50) / 100), 0.6,
                    self._format_reason("sentiment_up", sent_idx),
                    "sentiment", ["情绪指数上升"], priority=6))
            elif sent_idx < 40:
                out.append(make_sig(
                    "sell", min(0.55, 0.35 + (50 - sent_idx) / 100), 0.6,
                    self._format_reason("sentiment_down", sent_idx),
                    "sentiment", ["情绪指数下降"], priority=6))
            if fgi >= 85:
                out.append(make_sig(
                    "sell", 0.6, 0.65, self._format_reason("fear_greed", fgi),
                    "sentiment", ["极度贪婪", "警惕回调"], priority=8))
            elif fgi <= 20:
                out.append(make_sig(
                    "buy", 0.6, 0.65, self._format_reason("fear_greed_low", fgi),
                    "sentiment", ["极度恐惧", "逆向机会"], priority=8))
            if heat > 0.8 and rev_risk > 0.5:
                out.append(make_sig(
                    "reduce", 0.55, 0.6, self._format_reason("fomo", heat),
                    "sentiment", ["FOMO 升温", "反转风险上升"], priority=7))
            if consensus < 20:
                out.append(make_sig(
                    "buy", 0.5, 0.55, self._format_reason("consensus_low", consensus),
                    "sentiment", ["共识极低", "反向操作"], priority=6))

        elif module_name == "macro":
            policy = _to_float(metrics.get("policy_score", 50), 50.0)
            dxy = _to_float(metrics.get("dxy_strength", 50), 50.0)
            rate = _to_float(metrics.get("rate_impact", 0), 0.0)
            friendly = _to_float(metrics.get("crypto_friendly_score", 50), 50.0)

            if policy > 60:
                out.append(make_sig(
                    "buy", min(0.6, 0.4 + (policy - 50) / 100), 0.65,
                    self._format_reason("policy_friendly", policy),
                    "macro", ["政策偏友好"], priority=7))
            elif policy < 40:
                out.append(make_sig(
                    "sell", min(0.6, 0.4 + (50 - policy) / 100), 0.65,
                    self._format_reason("policy_restrictive", policy),
                    "macro", ["政策偏紧缩"], priority=7))
            if dxy < 45:
                out.append(make_sig(
                    "buy", 0.55, 0.6, self._format_reason("dxy_weak", dxy),
                    "macro", ["美元走弱", "风险资产利好"], priority=7))
            elif dxy > 60:
                out.append(make_sig(
                    "sell", 0.55, 0.6, self._format_reason("dxy_strong", dxy),
                    "macro", ["美元走强", "风险资产承压"], priority=7))
            if rate < -0.3:
                out.append(make_sig(
                    "risk_alert", 0.6, 0.65, self._format_reason("rate_shock", rate),
                    "macro", ["利率冲击预警"], priority=8))
            if friendly > 70:
                out.append(make_sig(
                    "buy", 0.55, 0.55, self._format_reason("crypto_friendly", friendly),
                    "macro", ["宏观友好度高"], priority=6))

        elif module_name == "valuation":
            mvrv = _to_float(metrics.get("mvrv_z_score", 0), 0.0)
            sopr = _to_float(metrics.get("sopr", 1), 1.0)
            ahr = _to_float(metrics.get("ahr999", 0.5), 0.5)
            pi = _to_float(metrics.get("pi_cycle_top", 0), 0.0)
            mayer = _to_float(metrics.get("mayer_multiple", 1), 1.0)

            if mvrv < -1:
                out.append(make_sig(
                    "strong_buy", 0.8, 0.75, self._format_reason("mvrv_low", mvrv),
                    "valuation", ["MVRV 低估区"], priority=9))
            elif mvrv > 2:
                out.append(make_sig(
                    "strong_sell", 0.8, 0.75, self._format_reason("mvrv_high", mvrv),
                    "valuation", ["MVRV 过热区"], priority=9))
            if sopr < 0.95:
                out.append(make_sig(
                    "buy", 0.55, 0.6, self._format_reason("sopr_loss", sopr),
                    "valuation", ["SOPR 亏损区", "洗盘接近尾声"], priority=7))
            elif sopr > 1.05:
                out.append(make_sig(
                    "reduce", 0.55, 0.6, self._format_reason("sopr_profit", sopr),
                    "valuation", ["SOPR 盈利区", "警惕获利回吐"], priority=6))
            if ahr < 0.45:
                out.append(make_sig(
                    "buy", 0.6, 0.65, self._format_reason("ahr_dca", ahr),
                    "valuation", ["AHR999 定投区"], priority=7))
            if pi > 0.9:
                out.append(make_sig(
                    "strong_sell", 0.75, 0.7, self._format_reason("pi_top", pi),
                    "valuation", ["Pi Cycle 顶部预警"], priority=9))
            if mayer > 2.4:
                out.append(make_sig(
                    "sell", 0.6, 0.65, self._format_reason("mayer_high", mayer),
                    "valuation", ["Mayer Multiple 过热"], priority=7))
            elif mayer < 0.6:
                out.append(make_sig(
                    "buy", 0.6, 0.65, self._format_reason("mayer_low", mayer),
                    "valuation", ["Mayer Multiple 过冷"], priority=7))

        elif module_name == "onchain":
            whale_acc = _to_float(metrics.get("whale_accumulation_score", 50), 50.0)
            ex_net = _to_float(metrics.get("exchange_net_flow", 0), 0.0)
            miner = _to_float(metrics.get("miner_position", 50), 50.0)
            gas = _to_float(metrics.get("gas_price_gwei", 30), 30.0)

            if whale_acc > 60:
                out.append(make_sig(
                    "buy", min(0.7, 0.4 + (whale_acc - 50) / 100), 0.7,
                    self._format_reason("whale_accumulate", whale_acc),
                    "onchain", ["鲸鱼持续积累"], priority=8))
            if ex_net < 0:
                out.append(make_sig(
                    "buy", 0.6, 0.65, self._format_reason("exchange_outflow", ex_net),
                    "onchain", ["交易所净流出", "场外积累"], priority=7))
            if miner < 40:
                out.append(make_sig(
                    "buy", 0.55, 0.6, self._format_reason("miner_holding", miner),
                    "onchain", ["矿工囤币", "供给减少"], priority=6))
            elif miner > 70:
                out.append(make_sig(
                    "sell", 0.55, 0.6, self._format_reason("miner_selling", miner),
                    "onchain", ["矿工出货"], priority=6))
            if gas > 80:
                out.append(make_sig(
                    "buy", 0.5, 0.55, self._format_reason("gas_hot", gas),
                    "onchain", ["Gas 热潮", "链上活动活跃"], priority=5))

        elif module_name == "news":
            news_sent = _to_float(metrics.get("news_sentiment", 0), 0.0)
            news_vol = _to_float(metrics.get("news_volume", 0), 0.0)
            if news_sent > 0.5 and news_vol > 50:
                out.append(make_sig(
                    "buy", 0.55, 0.6, self._format_reason("news_positive", (news_sent, news_vol)),
                    "news", ["新闻偏多", "热度较高"], priority=7))
            elif news_sent < -0.3:
                out.append(make_sig(
                    "sell", 0.55, 0.6, self._format_reason("news_negative", (news_sent, news_vol)),
                    "news", ["新闻偏空"], priority=7))

        elif module_name == "breadth":
            adv = _to_float(metrics.get("advancers", 50), 50.0)
            dec = _to_float(metrics.get("decliners", 50), 50.0)
            if adv > dec * 1.5:
                out.append(make_sig(
                    "buy", 0.55, 0.6, self._format_reason("breadth_strong", (adv, dec)),
                    "breadth", ["市场广度偏多"], priority=6))
            elif dec > adv * 1.5:
                out.append(make_sig(
                    "sell", 0.55, 0.6, self._format_reason("breadth_weak", (adv, dec)),
                    "breadth", ["市场广度偏空"], priority=6))

        elif module_name == "intermarket":
            spx = _to_float(metrics.get("spx_correlation", 0), 0.0)
            gold = _to_float(metrics.get("gold_correlation", 0), 0.0)
            if spx > 0.6:
                out.append(make_sig(
                    "risk_alert", 0.5, 0.55, self._format_reason("spx_correlated", spx),
                    "intermarket", ["与美股相关性高", "风险偏好联动"], priority=6))
            if gold > 0.4:
                out.append(make_sig(
                    "buy", 0.5, 0.55, self._format_reason("gold_correlated", gold),
                    "intermarket", ["与黄金联动", "避险属性显现"], priority=5))

        elif module_name == "calendar":
            upc = _to_float(metrics.get("upcoming_events_count",
                                        metrics.get("calendar_events", 0)), 0.0)
            if upc > 3:
                out.append(make_sig(
                    "hold", 0.45, 0.5, self._format_reason("calendar_dense", upc),
                    "calendar", ["近期事件密集", "建议观望"], priority=6))

        elif module_name == "narrative":
            nar = _to_float(metrics.get("narrative_score", 0.5), 0.5)
            if nar > 0.7:
                out.append(make_sig(
                    "buy", 0.55, 0.55, self._format_reason("narrative_hot", nar),
                    "narrative", ["叙事热度高"], priority=6))

        else:
            score = _to_float(resistance_3d.get("direction_score", 0), 0.0)
            if abs(score) > 0.2:
                sig_type = "buy" if score > 0 else "sell"
                out.append(make_sig(
                    sig_type, 0.45, 0.55, self._format_reason("generic", score),
                    "generic", ["综合方向"], priority=5))

        return out

    # ---------- reason 翻译 ----------
    def _format_reason(self, key: str, value: Any = None) -> str:
        """把技术指标翻译成可理解的中文描述。"""
        key = str(key).lower().strip()

        # 恐惧贪婪指数
        if key == "fear_greed":
            v = float(value) if isinstance(value, (int, float)) else 85.0
            return f"市场极度贪婪(FGI>{int(min(85, v))})，历史上类似时刻后30天回调概率约68%"
        if key == "fear_greed_low":
            v = float(value) if isinstance(value, (int, float)) else 20.0
            return f"市场极度恐惧(FGI<{int(max(15, v))})，历史上类似时刻后60天上涨概率约72%"

        # MVRV / SOPR
        if key == "mvrv_low":
            v = float(value) if isinstance(value, (int, float)) else -1.0
            return f"MVRV Z-Score 进入低估区域({v:+.2f})，历史上该区间后12个月收益显著为正"
        if key == "mvrv_high":
            v = float(value) if isinstance(value, (int, float)) else 2.0
            return f"MVRV Z-Score 进入过热区域({v:+.2f})，历史上该区域后12个月收益显著为负"
        if key == "sopr_loss":
            return "SOPR 处于亏损区间，市场洗盘接近尾声，长期持有者开始积累"
        if key == "sopr_profit":
            return "SOPR 处于盈利区间，部分持有者可能获利回吐，短期回调压力增大"

        # AHR999 / Pi / Mayer
        if key == "ahr_dca":
            v = float(value) if isinstance(value, (int, float)) else 0.45
            return f"AHR999 指数位于定投黄金区({v:.2f})，历史定投收益跑赢持有"
        if key == "pi_top":
            v = float(value) if isinstance(value, (int, float)) else 0.9
            return f"Pi Cycle Top 指标接近预警阈值({v:.2f})，历史周期顶部信号显现"
        if key == "mayer_high":
            v = float(value) if isinstance(value, (int, float)) else 2.4
            return f"Mayer Multiple({v:.2f})处于过热区，价格显著高于 200 日均线，回调概率提升"
        if key == "mayer_low":
            v = float(value) if isinstance(value, (int, float)) else 0.6
            return f"Mayer Multiple({v:.2f})处于过冷区，价格显著低于 200 日均线，是长期布局机会"

        # Flow
        if key == "smart_money_etf":
            if isinstance(value, (tuple, list)) and len(value) >= 2:
                try:
                    sm, etf = value
                    return f"聪明钱方向 + ETF 净流入({float(etf):.0f}百万美元)，机构资金持续进场"
                except Exception:
                    pass
            return "聪明钱方向与 ETF 净流入同步，机构资金持续进场"
        if key == "liquidation":
            v = float(value) if isinstance(value, (int, float)) else 70.0
            return f"清算压力高企({v:.0f})，短期可能出现级联清算，反向机会显现"
        if key == "funding_high":
            v = float(value) if isinstance(value, (int, float)) else 0.05
            return f"永续合约资金费率偏高({v*100:.2f}%)，多头拥挤，建议警惕回调或减仓"
        if key == "stablecoin":
            v = float(value) if isinstance(value, (int, float)) else 0.0
            return f"稳定币供给增加({v:+.2f}%)，新增购买力进入市场，潜在买入机会"
        if key == "whale_exchange":
            if isinstance(value, (tuple, list)) and len(value) >= 2:
                try:
                    whale, ex = value
                    return f"鲸鱼活跃度高({float(whale):.1f})且交易所净流出({float(ex):+.1f})，大户场外积累看涨"
                except Exception:
                    pass
            return "鲸鱼活跃且交易所净流出，大户场外积累看涨"

        # Sentiment
        if key == "sentiment_up":
            v = float(value) if isinstance(value, (int, float)) else 60.0
            return f"情绪指数持续上升({v:.0f})，市场情绪逐步改善"
        if key == "sentiment_down":
            v = float(value) if isinstance(value, (int, float)) else 40.0
            return f"情绪指数持续下降({v:.0f})，市场情绪走弱"
        if key == "fomo":
            v = float(value) if isinstance(value, (int, float)) else 0.8
            return f"叙事热度({v:.2f})偏高且反转风险上升，FOMO 式买入可能触发反向回调"
        if key == "consensus_low":
            v = float(value) if isinstance(value, (int, float)) else 20.0
            return f"共识度极低({v:.0f})，众人皆醉我独醒，逆向思维机会出现"

        # Macro
        if key == "policy_friendly":
            v = float(value) if isinstance(value, (int, float)) else 60.0
            return f"政策转向友好({v:.0f})，流动性环境改善，风险资产受益"
        if key == "policy_restrictive":
            v = float(value) if isinstance(value, (int, float)) else 40.0
            return f"政策偏紧缩({v:.0f})，流动性收紧，风险资产承压"
        if key == "dxy_weak":
            v = float(value) if isinstance(value, (int, float)) else 45.0
            return f"美元走弱(DXY={v:.0f})，风险资产利好，以美元计价资产相对升值"
        if key == "dxy_strong":
            v = float(value) if isinstance(value, (int, float)) else 60.0
            return f"美元走强(DXY={v:.0f})，风险资产承压"
        if key == "rate_shock":
            v = float(value) if isinstance(value, (int, float)) else -0.3
            return f"利率冲击影响放大({v:+.2f})，高利率环境压制风险资产估值"
        if key == "crypto_friendly":
            v = float(value) if isinstance(value, (int, float)) else 70.0
            return f"宏观友好度评分偏高({v:.0f})，整体宏观环境对加密资产偏友好"

        # Onchain
        if key == "whale_accumulate":
            v = float(value) if isinstance(value, (int, float)) else 60.0
            return f"鲸鱼持续积累({v:.0f})，大户吸筹，后续上涨动能增强"
        if key == "exchange_outflow":
            v = float(value) if isinstance(value, (int, float)) else 0.0
            return f"交易所净流出({v:+.1f})，场外投资者持续积累，长期看涨"
        if key == "miner_holding":
            v = float(value) if isinstance(value, (int, float)) else 40.0
            return f"矿工囤币倾向增强({v:.0f})，供给减少长期利好"
        if key == "miner_selling":
            v = float(value) if isinstance(value, (int, float)) else 70.0
            return f"矿工出货倾向增强({v:.0f})，短期抛压增大"
        if key == "gas_hot":
            v = float(value) if isinstance(value, (int, float)) else 80.0
            return f"链上 Gas 费高涨({v:.0f} Gwei)，链上活动活跃，需求提升"

        # 跨市场 / 新闻 / 广度 / 日历 / 叙事
        if key == "news_positive":
            if isinstance(value, (tuple, list)) and len(value) >= 2:
                try:
                    s, vol = value
                    return f"新闻情绪偏正面({float(s):.2f})，热度({float(vol):.0f})，舆论偏多"
                except Exception:
                    pass
            return "新闻情绪正面，舆论偏多"
        if key == "news_negative":
            if isinstance(value, (tuple, list)) and len(value) >= 2:
                try:
                    s, vol = value
                    return f"新闻情绪偏负面({float(s):.2f})，热度({float(vol):.0f})，舆论偏空"
                except Exception:
                    pass
            return "新闻情绪负面，舆论偏空"
        if key == "breadth_strong":
            if isinstance(value, (tuple, list)) and len(value) >= 2:
                try:
                    a, d = value
                    return f"市场广度偏强（上涨{float(a):.0f} vs 下跌{float(d):.0f}），普涨格局"
                except Exception:
                    pass
            return "市场广度偏强，普涨格局"
        if key == "breadth_weak":
            if isinstance(value, (tuple, list)) and len(value) >= 2:
                try:
                    a, d = value
                    return f"市场广度偏弱（上涨{float(a):.0f} vs 下跌{float(d):.0f}），普跌格局"
                except Exception:
                    pass
            return "市场广度偏弱，普跌格局"
        if key == "spx_correlated":
            v = float(value) if isinstance(value, (int, float)) else 0.6
            return f"与美股相关性较高({v:.2f})，风险偏好联动，警惕美股回调传导"
        if key == "gold_correlated":
            v = float(value) if isinstance(value, (int, float)) else 0.4
            return f"与黄金相关性上升({v:.2f})，避险属性显现"
        if key == "calendar_dense":
            v = float(value) if isinstance(value, (int, float)) else 3.0
            return f"近期重要事件密集({int(v)})件，不确定性上升，建议观望"
        if key == "narrative_hot":
            v = float(value) if isinstance(value, (int, float)) else 0.7
            return f"市场叙事热度高({v:.2f})，热点形成合力推动市场情绪"
        if key == "generic":
            v = float(value) if isinstance(value, (int, float)) else 0.0
            if v > 0:
                return f"综合方向偏多({v:+.2f})，建议顺势而为"
            if v < 0:
                return f"综合方向偏空({v:+.2f})，建议谨慎"
            return "综合方向中性，建议观望"

        # 事件兜底
        if isinstance(value, str) and value:
            return value
        return f"{key} 信号触发"

    # ---------- composite 辅助 ----------
    def _build_reasons(self, module_scores: Dict[str, Dict[str, Any]]) -> List[str]:
        reasons: List[str] = []

        if "flow" in module_scores:
            score = _to_float(module_scores["flow"].get("score", 0), 0.0)
            reasons.append(f"资金流模块：{'净流入偏多' if score > 0 else '偏空'}（{score:+.2f}）")
        if "valuation" in module_scores:
            score = _to_float(module_scores["valuation"].get("score", 0), 0.0)
            if score > 0.3:
                reasons.append("估值模块：处于低估区间，适合长期布局")
            elif score > 0:
                reasons.append("估值模块：估值合理")
            elif score > -0.3:
                reasons.append("估值模块：估值偏高")
            else:
                reasons.append("估值模块：估值过热，需警惕回调")
        if "sentiment" in module_scores:
            score = _to_float(module_scores["sentiment"].get("score", 0), 0.0)
            if score > 0.3:
                reasons.append("情绪模块：情绪偏贪婪")
            elif score < -0.3:
                reasons.append("情绪模块：情绪偏恐惧，逆向机会显现")
            else:
                reasons.append("情绪模块：情绪中性")
        if "macro" in module_scores:
            score = _to_float(module_scores["macro"].get("score", 0), 0.0)
            if score > 0.2:
                reasons.append("宏观模块：政策与流动性偏友好")
            elif score < -0.2:
                reasons.append("宏观模块：政策与流动性偏紧")
        if "onchain" in module_scores:
            score = _to_float(module_scores["onchain"].get("score", 0), 0.0)
            if score > 0.2:
                reasons.append("链上模块：鲸鱼与矿工数据偏积极")
            elif score < -0.2:
                reasons.append("链上模块：链上数据偏弱")

        if not reasons:
            reasons.append("各模块信号相对平稳，无明显方向")
        return reasons

    def _build_risk_warnings(self, module_scores: Dict[str, Dict[str, Any]]) -> List[str]:
        warnings: List[str] = []

        val_score = _to_float(module_scores.get("valuation", {}).get("score", 0), 0.0)
        if val_score > 0.7:
            warnings.append("估值已过热，警惕 MVRV Z-Score > 2 的回调风险")

        sent_score = _to_float(module_scores.get("sentiment", {}).get("score", 0), 0.0)
        if sent_score > 0.8:
            warnings.append("情绪极度贪婪，FOMO 式买入增加了回调概率")

        flow_metrics = module_scores.get("flow", {}).get("metrics", {})
        if isinstance(flow_metrics, dict):
            flow_liq = _to_float(flow_metrics.get("liquidation_pressure", 0), 0.0)
            if flow_liq > 70:
                warnings.append("清算压力高企，短时间内可能发生级联清算")

        macro_score = _to_float(module_scores.get("macro", {}).get("score", 0), 0.0)
        if macro_score < -0.5:
            warnings.append("宏观环境偏紧，利率与美元走强压制风险资产")

        if not warnings:
            warnings.append("当前无显著风险警告，但仍需关注市场变化")
        return warnings

    def _build_best_opportunities(
        self, module_scores: Dict[str, Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """找出最强 3 个机会模块。"""
        candidates: List[Dict[str, Any]] = []
        for module_name, info in module_scores.items():
            try:
                score = float(info.get("score", 0))
            except (TypeError, ValueError):
                continue
            strength = abs(score) * 100
            if strength < 15:
                continue
            if score > 0:
                candidates.append({
                    "module": module_name, "signal": "buy",
                    "reason": f"{module_name} 模块偏多({score:+.2f})",
                    "strength": int(round(strength)),
                })
            else:
                candidates.append({
                    "module": module_name, "signal": "sell",
                    "reason": f"{module_name} 模块偏空({score:+.2f})",
                    "strength": int(round(strength)),
                })
        candidates.sort(key=lambda x: x["strength"], reverse=True)
        return candidates[:3]

    def _top_signal_for_module(self, module_name: str, info: Dict[str, Any]) -> Tuple[str, str, int]:
        score = _to_float(info.get("score", 0), 0.0)
        if score > 0.3:
            return "strong_buy", f"{module_name} 综合方向强烈看多，方向得分{score:+.2f}", 9
        if score > 0.15:
            return "buy", f"{module_name} 综合方向偏多，方向得分{score:+.2f}", 7
        if score < -0.3:
            return "strong_sell", f"{module_name} 综合方向强烈看空，方向得分{score:+.2f}", 9
        if score < -0.15:
            return "sell", f"{module_name} 综合方向偏空，方向得分{score:+.2f}", 7
        return "hold", f"{module_name} 综合方向中性", 4


def create_signal_engine() -> SignalEngine:
    """创建信号引擎实例。"""
    return SignalEngine()
