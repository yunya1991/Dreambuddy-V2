#!/usr/bin/env python3
"""
跨体系知识桥接器 — AB Trading ↔ 易经推理系统

核心功能：
1. 定义共享知识格式（JSON Schema）
2. AB Trading 进化参数 → 易经推理可用的外部参考参数
3. 易经推理案例 → AB Trading 可学习的实践经验
4. 双向同步机制

共享目录：.workbuddy/shared_knowledge/
"""
import json
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any


class KnowledgeBridge:
    """
    跨体系知识桥接器

    数据流：
    AB Trading Evolution → shared_knowledge/ → 易经推理系统

    共享数据类型：
    1. evolved_params.json - AB Trading已采纳的进化参数
    2. market_regimes.json - 市场状态识别结果
    3. trading_rules.json - 经验规则（如"缩量不交易"）
    4. contradiction_patterns.json - 矛盾模式（A8发现的矛盾）
    """

    def __init__(self, shared_dir: Optional[Path] = None):
        if shared_dir is None:
            self.shared_dir = Path(".workbuddy/shared_knowledge")
        else:
            self.shared_dir = shared_dir
        self.shared_dir.mkdir(parents=True, exist_ok=True)

        self.evolved_params_file = self.shared_dir / "evolved_params.json"
        self.market_regimes_file = self.shared_dir / "market_regimes.json"
        self.trading_rules_file = self.shared_dir / "trading_rules.json"
        self.contradiction_patterns_file = self.shared_dir / "contradiction_patterns.json"

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ============================================================
    # AB Trading → 易经推理：导出进化参数
    # ============================================================

    def export_ab_evolved_params(
        self,
        adopted_params: Dict[str, Any],
        source: str = "ab_trading",
        description: str = "",
    ) -> Dict:
        """
        导出 AB Trading 已采纳的进化参数

        Args:
            adopted_params: AB Trading进化引擎的已采纳参数
            source: 来源标识
            description: 描述信息

        Returns:
            导出结果
        """
        data = {
            "version": "1.0",
            "source": source,
            "exported_at": self._now_iso(),
            "description": description,
            "params": adopted_params,
            "transformed_for_yijing": self._transform_ab_to_yijing(adopted_params),
        }

        try:
            with open(self.evolved_params_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return {"ok": True, "file": str(self.evolved_params_file), "params_count": len(adopted_params)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _transform_ab_to_yijing(self, ab_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        将 AB Trading 进化参数转换为易经推理系统可用的格式

        AB 参数 → 易经参数映射：
        - momentum_threshold → 趋势强度阈值（影响两仪微观阶段判断）
        - volume_threshold → 量能权重调整（影响矛盾强度评估）
        - rsi_oversold/overbought → 信号置信度调整（影响决策阈值）
        - stop_loss_pct → 风控参数（影响仓位计算）
        - take_profit_pct → 目标参数（影响离场判断）
        """
        transformed = {
            "trend_sensitivity": 1.0,
            "volume_weight": 0.3,
            "signal_confidence_bias": 0.0,
            "risk_aversion": 0.5,
            "profit_target_factor": 1.0,
            "recommended_coins": [],
            "market_bias": "neutral",
        }

        if "momentum_threshold" in ab_params:
            orig_th = ab_params["momentum_threshold"]
            default_th = 0.02
            transformed["trend_sensitivity"] = default_th / orig_th if orig_th > 0 else 1.0

        if "volume_threshold" in ab_params:
            transformed["volume_weight"] = min(0.5, ab_params["volume_threshold"] * 0.25)

        if "rsi_oversold" in ab_params and "rsi_overbought" in ab_params:
            os = ab_params["rsi_oversold"]
            ob = ab_params["rsi_overbought"]
            mid = (os + ob) / 2
            bias = (50 - mid) / 50
            transformed["signal_confidence_bias"] = bias

        if "stop_loss_pct" in ab_params:
            sl = ab_params["stop_loss_pct"]
            transformed["risk_aversion"] = min(1.0, sl / 0.04)

        if "take_profit_pct" in ab_params:
            tp = ab_params["take_profit_pct"]
            transformed["profit_target_factor"] = tp / 0.08

        return transformed

    def export_ab_contradictions(
        self,
        contradictions: List[Dict[str, Any]],
        source: str = "a8_theory_practice",
    ) -> Dict:
        """
        导出 AB Trading 发现的矛盾模式

        Args:
            contradictions: 矛盾列表（来自A8或做梦部）
            source: 来源

        Returns:
            导出结果
        """
        patterns = []
        for c in contradictions:
            pattern = {
                "id": c.get("id", ""),
                "type": c.get("type", ""),
                "description": c.get("description", ""),
                "severity": c.get("severity", "LOW"),
                "hypothesis": c.get("hypothesis", ""),
                "yijing_interpretation": self._interpret_contradiction_for_yijing(c),
                "source": source,
                "timestamp": self._now_iso(),
            }
            patterns.append(pattern)

        data = {
            "version": "1.0",
            "source": source,
            "exported_at": self._now_iso(),
            "patterns": patterns,
            "count": len(patterns),
        }

        try:
            with open(self.contradiction_patterns_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return {"ok": True, "file": str(self.contradiction_patterns_file), "patterns_count": len(patterns)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _interpret_contradiction_for_yijing(self, contradiction: Dict[str, Any]) -> str:
        """
        将矛盾转换为易经推理系统可理解的解释

        矛盾类型 → 易经解读：
        - theory_practice_mismatch → 理论与实践脱节，需调整卦象权重
        - strategy_failure → 策略失效，需重新审视当前卦象
        - risk_management → 风控不足，需加强坎卦（水）属性
        - memory_bloat → 记忆冗余，需清理
        """
        c_type = contradiction.get("type", "")
        interpretations = {
            "theory_practice_mismatch": "理论与实践脱节，当前卦象权重配置可能存在偏差，建议重新评估四象权重分布",
            "strategy_failure": "策略在当前市场环境下失效，需重新审视两仪状态判断和卦象选择",
            "risk_management": "风控机制不足，建议加强坎卦（水）属性的权重，提高保守度",
            "memory_bloat": "记忆系统存在冗余，建议清理重复教训，保持卦象清晰度",
            "compulsive_repetition": "系统陷入强迫性重复，建议引入变爻机制打破现有模式",
            "displacement": "恐惧被移置为客观理由，建议提高决策透明度，直面真实风险",
        }
        return interpretations.get(c_type, "矛盾模式需进一步分析")

    def export_market_regime(self, regime: Dict[str, Any]) -> Dict:
        """
        导出市场状态识别结果

        Args:
            regime: 市场状态

        Returns:
            导出结果
        """
        data = {
            "version": "1.0",
            "timestamp": self._now_iso(),
            "regime": regime,
            "yijing_compatible": self._transform_regime_to_yijing(regime),
        }

        try:
            with open(self.market_regimes_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return {"ok": True, "file": str(self.market_regimes_file)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _transform_regime_to_yijing(self, regime: Dict[str, Any]) -> Dict[str, Any]:
        """
        将市场状态转换为易经两仪状态

        市场状态 → 两仪阶段：
        - bull/trending_up → 宏观复苏/过热，微观生长/成熟
        - bear/trending_down → 宏观衰退/滞胀，微观衰落/萌芽
        - sideways/ranging → 宏观中性，微观成熟/衰落
        """
        state = regime.get("state", "neutral")
        trend_strength = regime.get("trend_strength", 0.5)
        volatility = regime.get("volatility", 0.5)

        if state in ("bull", "trending_up"):
            macro = "recovery" if trend_strength < 0.7 else "overheat"
            micro = "growth" if trend_strength < 0.8 else "mature"
        elif state in ("bear", "trending_down"):
            macro = "recession" if trend_strength < 0.7 else "stagflation"
            micro = "decline" if trend_strength < 0.8 else "sprout"
        else:
            macro = "neutral"
            micro = "mature" if volatility < 0.5 else "decline"

        return {
            "macro_phase": macro,
            "micro_phase": micro,
            "trend_strength": trend_strength,
            "volatility": volatility,
            "market_bias": state,
        }

    # ============================================================
    # 易经推理 → AB Trading：导出实践经验
    # ============================================================

    def export_yijing_cases(self, cases: List[Dict[str, Any]]) -> Dict:
        """
        导出易经推理案例作为 AB Trading 的实践经验

        Args:
            cases: 易经案例列表

        Returns:
            导出结果
        """
        trading_rules = []
        for case in cases:
            outcome = case.get("actual_outcome") or case.get("decision_outcome", {})
            is_correct = outcome.get("is_correct", False)
            hexagram = case.get("hexagram", "")
            direction = case.get("direction", "")
            confidence = case.get("confidence", 0)

            if is_correct and hexagram:
                rule = {
                    "id": f"yijing_{hexagram}_{int(time.time())}",
                    "hexagram": hexagram,
                    "direction": direction,
                    "confidence": confidence,
                    "success": True,
                    "timestamp": self._now_iso(),
                    "description": f"卦象{hexagram}在{direction}方向上的推理成功，置信度{confidence:.2f}",
                }
                trading_rules.append(rule)

        data = {
            "version": "1.0",
            "source": "yijing_reasoning",
            "exported_at": self._now_iso(),
            "rules": trading_rules,
            "total_cases": len(cases),
            "successful_rules": len(trading_rules),
        }

        try:
            with open(self.trading_rules_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return {"ok": True, "file": str(self.trading_rules_file), "rules_count": len(trading_rules)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ============================================================
    # 易经推理系统读取共享知识
    # ============================================================

    def load_ab_evolved_params(self) -> Dict[str, Any]:
        """
        加载 AB Trading 导出的进化参数

        Returns:
            进化参数（含转换后的易经格式）
        """
        if not self.evolved_params_file.exists():
            return {"ok": False, "error": "文件不存在"}

        try:
            with open(self.evolved_params_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                "ok": True,
                "source": data.get("source", ""),
                "exported_at": data.get("exported_at", ""),
                "params": data.get("params", {}),
                "transformed": data.get("transformed_for_yijing", {}),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def load_ab_contradictions(self) -> Dict[str, Any]:
        """
        加载 AB Trading 导出的矛盾模式

        Returns:
            矛盾模式列表
        """
        if not self.contradiction_patterns_file.exists():
            return {"ok": False, "error": "文件不存在"}

        try:
            with open(self.contradiction_patterns_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                "ok": True,
                "source": data.get("source", ""),
                "patterns": data.get("patterns", []),
                "count": data.get("count", 0),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def load_market_regime(self) -> Dict[str, Any]:
        """
        加载市场状态识别结果

        Returns:
            市场状态（含易经兼容格式）
        """
        if not self.market_regimes_file.exists():
            return {"ok": False, "error": "文件不存在"}

        try:
            with open(self.market_regimes_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                "ok": True,
                "timestamp": data.get("timestamp", ""),
                "regime": data.get("regime", {}),
                "yijing_compatible": data.get("yijing_compatible", {}),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def load_trading_rules(self) -> Dict[str, Any]:
        """
        加载共享的交易规则

        Returns:
            交易规则列表
        """
        if not self.trading_rules_file.exists():
            return {"ok": False, "error": "文件不存在"}

        try:
            with open(self.trading_rules_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                "ok": True,
                "source": data.get("source", ""),
                "rules": data.get("rules", []),
                "total_cases": data.get("total_cases", 0),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ============================================================
    # 综合查询
    # ============================================================

    def get_all_shared_knowledge(self) -> Dict[str, Any]:
        """
        获取所有共享知识的汇总

        Returns:
            综合知识汇总
        """
        return {
            "evolved_params": self.load_ab_evolved_params(),
            "contradictions": self.load_ab_contradictions(),
            "market_regime": self.load_market_regime(),
            "trading_rules": self.load_trading_rules(),
            "shared_dir": str(self.shared_dir),
            "last_updated": self._now_iso(),
        }

    def get_knowledge_summary(self) -> Dict[str, Any]:
        """
        获取知识摘要（轻量版本）

        Returns:
            知识摘要
        """
        summary = {
            "evolved_params_count": 0,
            "contradictions_count": 0,
            "trading_rules_count": 0,
            "market_regime_available": False,
            "trend_sensitivity": 1.0,
            "risk_aversion": 0.5,
            "market_bias": "neutral",
        }

        params = self.load_ab_evolved_params()
        if params["ok"]:
            summary["evolved_params_count"] = len(params.get("params", {}))
            transformed = params.get("transformed", {})
            summary["trend_sensitivity"] = transformed.get("trend_sensitivity", 1.0)
            summary["risk_aversion"] = transformed.get("risk_aversion", 0.5)
            summary["market_bias"] = transformed.get("market_bias", "neutral")

        contradictions = self.load_ab_contradictions()
        if contradictions["ok"]:
            summary["contradictions_count"] = contradictions.get("count", 0)

        rules = self.load_trading_rules()
        if rules["ok"]:
            summary["trading_rules_count"] = len(rules.get("rules", []))

        regime = self.load_market_regime()
        summary["market_regime_available"] = regime["ok"]

        return summary
