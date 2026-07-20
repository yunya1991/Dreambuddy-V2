"""易经推理专属离场系统（主离场模块）

基于易经卦象的风险-价值评估，输出 FORCE_CLOSE / RAISE_TP / HOLD 决策。

架构（v2 - 架构反转后）：
- yijing_exit_system 作为主离场模块，polling_trader 先调用其 evaluate()
- classic_exit_system 降为备用，仅在 yijing 不可用（无卦象）或信号中性时调用
- 主决策路径：FORCE_CLOSE / RAISE_TP / HOLD（风险低+价值高+方向一致）
- 降级路径：NO_INTERVENE 且风险偏高/价值偏低 → 调用 classic 评估
- 备用路径：yijing_hexagram is None → 直接调用 classic

决策原则（主离场模式）：
1. 卦象 risk_level=高 + 方向冲突 + 风险分≥0.80 → FORCE_CLOSE
2. 卦象价值分>0.70 + 成长期/成熟期 + 飞龙在天/或跃在渊 + 已盈利 → RAISE_TP
3. 卦象风险分<0.35 + 价值分>0.60 + 方向一致 + 亏损未破-3% + 未超48h → HOLD
4. 其他情况 → NO_INTERVENE，降级调用 classic 备用层
5. 无卦象数据 → polling_trader 直接调用 classic（fail-open）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, List
import time


class YijingExitAction(Enum):
    """易经离场决策动作"""
    NO_INTERVENE = "no_intervene"  # 不干预，保持 classic 决策
    VETO_CLOSE = "veto_close"      # 否决 close，保持持仓
    VETO_REDUCE = "veto_reduce"    # 否决 reduce
    RAISE_TP = "raise_tp"          # 提高止盈位（价值高时）
    LOWER_SL = "lower_sl"          # 降低止损（风险低时，放宽止损空间）
    LOWER_TP = "lower_tp"          # 降低止盈（风险升高时，提前锁定利润）
    ADJUST_SL_TP = "adjust_sl_tp"  # 同时调整止损止盈
    FORCE_CLOSE = "force_close"    # 强制离场（卦象极度危险）


@dataclass
class YijingExitDecision:
    """易经离场决策"""
    action: YijingExitAction = YijingExitAction.NO_INTERVENE
    reason: str = ""
    # 易经风险评估
    yijing_risk_score: float = 0.5     # 0-1，越高越危险
    yijing_value_score: float = 0.5    # 0-1，越高越有价值
    # 卦象信息
    hexagram_name: str = ""
    risk_level: str = ""               # 高/中/低
    current_phase: str = ""            # 潜龙勿用/见龙在田/.../亢龙有悔
    development_stage: str = ""         # 萌芽期/成长期/成熟期/衰退期
    direction_consistent: bool = True  # 卦象方向与持仓方向是否一致
    # TP/SL 调整
    tp_adjust_pct: float = 0.0         # RAISE_TP/LOWER_TP 时的调整比例
    sl_adjust_pct: float = 0.0         # LOWER_SL 时的调整比例（正数表示放宽）
    # 决策元信息
    confidence: float = 0.5
    should_log: bool = True            # 是否记录日志


@dataclass
class YijingExitConfig:
    """易经离场配置"""
    # ── 风险评分权重 ──
    weight_risk_level: float = 0.35        # risk_level 高/中/低
    weight_phase: float = 0.25            # current_phase 六阶段
    weight_development: float = 0.20      # development_stage 四阶段
    weight_direction_consistency: float = 0.20  # 卦象方向与持仓方向

    # ── 否决阈值 ──
    # 否决 classic CLOSE/REDUCE 的条件：风险低 + 价值高 + 持仓未破关键位
    veto_risk_threshold: float = 0.35     # yijing_risk_score < 此值才允许否决
    veto_value_threshold: float = 0.60    # yijing_value_score > 此值才允许否议
    veto_max_loss_pct: float = -0.03       # 亏损超过 -3% 不否决（让 classic 止损生效）
    veto_max_hold_sec: float = 172800      # 持仓超过 48h 不否决

    # ── 提高止盈阈值 ──
    raise_tp_min_profit_pct: float = 0.02  # 至少盈利 2% 才考虑提高 TP
    raise_tp_adjust_pct: float = 0.30      # TP 上浮 30%（叠加在原 TP 之上）
    raise_tp_value_threshold: float = 0.70 # 价值分 > 0.70 才提高 TP

    # ── 降低止损阈值（放宽止损空间）──
    lower_sl_max_loss_pct: float = -0.02   # 亏损不超过 -2% 才考虑放宽止损
    lower_sl_min_risk_score: float = 0.30  # 风险分 < 0.30 才放宽止损
    lower_sl_adjust_pct: float = 0.50      # SL 放宽 50%（从 1.5×ATR → 2.25×ATR）

    # ── 降低止盈阈值（提前锁定利润）──
    lower_tp_min_profit_pct: float = 0.03  # 至少盈利 3% 才考虑降低 TP
    lower_tp_max_risk_score: float = 0.60  # 风险分 > 0.60 才降低 TP
    lower_tp_adjust_pct: float = 0.30     # TP 下调 30%

    # ── 强制离场阈值 ──
    force_close_risk_threshold: float = 0.80  # 风险分 > 0.80 且方向冲突 → 强制 close

    # ── 卦象阶段映射 ──
    # current_phase 六阶段的风险/价值（易经六爻）
    phase_risk_map: Dict[str, float] = field(default_factory=lambda: {
        "初九": 0.65,  # 潜龙勿用：低位潜伏，风险偏高（方向未明）
        "九二": 0.40,  # 见龙在田：初露锋芒，风险降低
        "九三": 0.55,  # 终日乾乾：警惕反复，风险中等
        "九四": 0.45,  # 或跃在渊：进退关键，风险中等偏低
        "九五": 0.25,  # 飞龙在天：主升浪，风险最低
        "上九": 0.85,  # 亢龙有悔：顶部反转，风险最高
    })
    phase_value_map: Dict[str, float] = field(default_factory=lambda: {
        "初九": 0.35,  # 潜龙勿用：价值未显现
        "九二": 0.65,  # 见龙在田：价值初现
        "九三": 0.55,  # 终日乾乾：价值待验证
        "九四": 0.70,  # 或跃在渊：价值较高
        "九五": 0.90,  # 飞龙在天：价值最高
        "上九": 0.20,  # 亢龙有悔：价值已尽
    })

    # development_stage 四阶段的风险/价值
    stage_risk_map: Dict[str, float] = field(default_factory=lambda: {
        "萌芽期": 0.65,   # 萌芽期风险高（方向未明）
        "成长期": 0.30,   # 成长期风险低（趋势已立）
        "成熟期": 0.45,   # 成熟期风险中等（接近顶部）
        "衰退期": 0.80,  # 衰退期风险高（趋势反转）
    })
    stage_value_map: Dict[str, float] = field(default_factory=lambda: {
        "萌芽期": 0.40,  # 萌芽期价值低
        "成长期": 0.85,  # 成长期价值最高
        "成熟期": 0.65,  # 成熟期价值中等
        "衰退期": 0.25,  # 衰退期价值最低
    })

    # risk_level 映射
    risk_level_map: Dict[str, float] = field(default_factory=lambda: {
        "高": 0.80, "high": 0.80,
        "中": 0.50, "medium": 0.50,
        "低": 0.25, "low": 0.25,
    })

    # 卦象方向 → 与持仓方向是否一致
    # direction_hint: UP/DOWN/FLAT/TRANSITIONING/UNKNOWN
    direction_consistency_map: Dict[str, Dict[str, float]] = field(default_factory=lambda: {
        "UP": {"long": 0.20, "short": 0.85},    # UP 卦做多：风险低；做空：风险高
        "DOWN": {"long": 0.85, "short": 0.20},  # DOWN 卦做空：风险低；做多：风险高
        "FLAT": {"long": 0.50, "short": 0.50},  # FLAT 中性
        "TRANSITIONING": {"long": 0.60, "short": 0.60},  # 转换期风险中等
        "UNKNOWN": {"long": 0.50, "short": 0.50},
    })


class YijingExitSystem:
    """易经推理专属离场系统

    使用方式：
        yijing_decision = yijing_exit.evaluate(
            hexagram=inference.get("hexagram_result"),
            pos_side="long",
            entry_price=...,
            current_price=...,
            position_age_sec=...,
            unrealized_pnl_pct=...,
            classic_decision=classic_exit_decision,  # 可选，用于否决
        )
        if yijing_decision.action == YijingExitAction.VETO_CLOSE:
            # 否决 classic 的 CLOSE，保持持仓
            pass
    """

    def __init__(self, config: Optional[YijingExitConfig] = None):
        self.config = config or YijingExitConfig()
        self._log_callback = None

    def set_log_callback(self, callback):
        """设置日志回调函数"""
        self._log_callback = callback

    def _log(self, msg: str, level: str = "INFO"):
        if self._log_callback:
            self._log_callback(msg, level)

    def evaluate(
        self,
        hexagram: Any,
        pos_side: str,
        entry_price: float,
        current_price: float,
        position_age_sec: float,
        unrealized_pnl_pct: float,
        classic_decision: Any = None,
        mfe_pnl_pct: float = 0.0,
    ) -> YijingExitDecision:
        """评估离场决策

        Args:
            hexagram: 卦象对象（YijingResult 或 dict），需含 risk_level/current_phase/development_stage/direction_hint
            pos_side: 持仓方向 long/short
            entry_price: 入场价
            current_price: 当前价
            position_age_sec: 持仓时长（秒）
            unrealized_pnl_pct: 未实现盈亏比例（如 0.02 = +2%）
            classic_decision: classic_exit_system 的决策（可选，用于否决判断）
            mfe_pnl_pct: 最大盈利幅度

        Returns:
            YijingExitDecision
        """
        decision = YijingExitDecision(
            action=YijingExitAction.NO_INTERVENE,
            reason="no_hexagram_data",
        )

        # ── 提取卦象字段 ──
        hex_data = self._extract_hexagram(hexagram)
        if not hex_data:
            # 无卦象数据：fail-open，不干预
            decision.reason = "no_hexagram_data_fail_open"
            decision.should_log = False
            return decision

        decision.hexagram_name = hex_data.get("hexagram_name_cn", "") or hex_data.get("hexagram_name", "")
        decision.risk_level = str(hex_data.get("risk_level", "")).lower()
        decision.current_phase = str(hex_data.get("current_phase", ""))
        decision.development_stage = str(hex_data.get("development_stage", ""))
        direction_hint = str(hex_data.get("direction_hint", "UNKNOWN")).upper()

        # ── 计算风险分（0-1，越高越危险）──
        decision.yijing_risk_score = self._calc_risk_score(
            decision.risk_level,
            decision.current_phase,
            decision.development_stage,
            direction_hint,
            pos_side,
        )

        # ── 计算价值分（0-1，越高越有价值）──
        decision.yijing_value_score = self._calc_value_score(
            decision.current_phase,
            decision.development_stage,
            decision.risk_level,
        )

        # ── 卦象方向与持仓方向一致性 ──
        direction_consistency = self.config.direction_consistency_map.get(
            direction_hint, {"long": 0.50, "short": 0.50}
        )
        direction_risk = direction_consistency.get(pos_side, 0.50)
        decision.direction_consistent = direction_risk < 0.50
        # 方向不一致时风险分加权提升
        if not decision.direction_consistent:
            decision.yijing_risk_score = (
                decision.yijing_risk_score * 0.7 + direction_risk * 0.3
            )

        decision.confidence = float(hex_data.get("confidence", 0.5) or 0.5)

        # ── 1. 强制离场判定：卦象风险极高 + 方向冲突 ──
        if (decision.yijing_risk_score >= self.config.force_close_risk_threshold
                and not decision.direction_consistent):
            decision.action = YijingExitAction.FORCE_CLOSE
            decision.reason = (
                f"yijing_force_close:risk={decision.yijing_risk_score:.2f},"
                f"direction_conflict({direction_hint}_vs_{pos_side})"
            )
            self._log(
                f"[易经离场][强制平仓] {decision.hexagram_name} "
                f"风险={decision.yijing_risk_score:.2f} 价值={decision.yijing_value_score:.2f} "
                f"卦象方向={direction_hint} 与持仓{pos_side}冲突"
            )
            return decision

        # ── 2. 提高止盈判定：卦象价值高 + 当前盈利 ──
        if (unrealized_pnl_pct >= self.config.raise_tp_min_profit_pct
                and decision.yijing_value_score >= self.config.raise_tp_value_threshold
                and decision.direction_consistent):
            # 仅在成长期/成熟期 + 飞龙在天/或跃在渊时提高 TP
            valuable_phase = decision.current_phase in ("九二", "九四", "九五")
            valuable_stage = decision.development_stage in ("成长期", "成熟期")
            if valuable_phase and valuable_stage:
                decision.action = YijingExitAction.RAISE_TP
                decision.tp_adjust_pct = self.config.raise_tp_adjust_pct
                decision.reason = (
                    f"yijing_raise_tp:value={decision.yijing_value_score:.2f},"
                    f"phase={decision.current_phase},stage={decision.development_stage}"
                )
                self._log(
                    f"[易经离场][提高止盈] {decision.hexagram_name} "
                    f"价值={decision.yijing_value_score:.2f} 卦象阶段={decision.current_phase}"
                    f"({decision.development_stage}) → TP 上浮 {decision.tp_adjust_pct:.0%}"
                )
                return decision

        # ── 3. 降低止损判定：卦象风险低 + 亏损可控 → 放宽止损空间 ──
        # 场景：趋势刚刚启动，暂时回撤但卦象显示风险低，不应该被止损洗出去
        if (unrealized_pnl_pct > self.config.lower_sl_max_loss_pct
                and decision.yijing_risk_score < self.config.lower_sl_min_risk_score
                and decision.direction_consistent):
            # 仅在萌芽期/成长期放宽止损（趋势刚刚启动）
            early_stage = decision.development_stage in ("萌芽期", "成长期")
            if early_stage:
                decision.action = YijingExitAction.LOWER_SL
                decision.sl_adjust_pct = self.config.lower_sl_adjust_pct
                decision.reason = (
                    f"yijing_lower_sl:risk={decision.yijing_risk_score:.2f},"
                    f"stage={decision.development_stage},loss={unrealized_pnl_pct:.2%}"
                )
                self._log(
                    f"[易经离场][放宽止损] {decision.hexagram_name} "
                    f"风险={decision.yijing_risk_score:.2f} 阶段={decision.development_stage} "
                    f"亏损={unrealized_pnl_pct:.2%} → SL 放宽 {decision.sl_adjust_pct:.0%}"
                )
                return decision

        # ── 4. 降低止盈判定：卦象风险升高 + 已有利润 → 提前锁定 ──
        # 场景：卦象显示接近顶部（风险升高），但还没到强制平仓的程度，提前锁定部分利润
        if (unrealized_pnl_pct >= self.config.lower_tp_min_profit_pct
                and decision.yijing_risk_score >= self.config.lower_tp_max_risk_score):
            # 仅在成熟期/衰退期降低止盈（接近顶部）
            late_stage = decision.development_stage in ("成熟期", "衰退期")
            high_risk_phase = decision.current_phase in ("九三", "上九")
            if late_stage or high_risk_phase:
                decision.action = YijingExitAction.LOWER_TP
                decision.tp_adjust_pct = -self.config.lower_tp_adjust_pct
                decision.reason = (
                    f"yijing_lower_tp:risk={decision.yijing_risk_score:.2f},"
                    f"stage={decision.development_stage},profit={unrealized_pnl_pct:.2%}"
                )
                self._log(
                    f"[易经离场][降低止盈] {decision.hexagram_name} "
                    f"风险={decision.yijing_risk_score:.2f} 阶段={decision.development_stage} "
                    f"盈利={unrealized_pnl_pct:.2%} → TP 下调 {abs(decision.tp_adjust_pct):.0%}"
                )
                return decision

        # ── 5. 否决 classic 离场判定 ──
        if classic_decision is not None:
            classic_action_str = ""
            if hasattr(classic_decision, "action"):
                classic_action_str = str(classic_decision.action).split(".")[-1].lower()
            elif isinstance(classic_decision, dict):
                classic_action_str = str(classic_decision.get("action", "")).lower()

            classic_reason = ""
            if hasattr(classic_decision, "reason"):
                classic_reason = str(classic_decision.reason or "")
            elif isinstance(classic_decision, dict):
                classic_reason = str(classic_decision.get("reason", ""))

            # 仅否决 CLOSE/REDUCE
            should_veto = (
                classic_action_str in ("close", "reduce")
                # 风险低 + 价值高
                and decision.yijing_risk_score < self.config.veto_risk_threshold
                and decision.yijing_value_score > self.config.veto_value_threshold
                # 亏损未超阈值（让 classic 的硬止损生效）
                and unrealized_pnl_pct > self.config.veto_max_loss_pct
                # 持仓未超时
                and position_age_sec < self.config.veto_max_hold_sec
                # 方向一致
                and decision.direction_consistent
            )

            if should_veto:
                # 进一步过滤：仅否决噪音类止损（TB_STOP_LOSS、trailing_stop、risk_gate）
                # 不否决 L0 硬止损、信号反转、TSTP 衰减
                noise_reasons = ("tb_stop_loss", "trailing_stop", "risk_gate", "l2_reduce", "l2_close")
                is_noise_stop = any(nr in classic_reason.lower() for nr in noise_reasons)

                if is_noise_stop:
                    if classic_action_str == "close":
                        decision.action = YijingExitAction.VETO_CLOSE
                    else:
                        decision.action = YijingExitAction.VETO_REDUCE
                    decision.reason = (
                        f"yijing_veto:risk={decision.yijing_risk_score:.2f},"
                        f"value={decision.yijing_value_score:.2f},"
                        f"classic={classic_reason}"
                    )
                    self._log(
                        f"[易经离场][否决{classic_action_str.upper()}] {decision.hexagram_name} "
                        f"风险={decision.yijing_risk_score:.2f} 价值={decision.yijing_value_score:.2f} "
                        f"卦象阶段={decision.current_phase} → 否决 classic 的 {classic_reason} "
                        f"盈亏={unrealized_pnl_pct:.2%} 持仓{position_age_sec/3600:.1f}h"
                    )
                    return decision

        # ── 4. 默认不干预 ──
        decision.action = YijingExitAction.NO_INTERVENE
        decision.reason = (
            f"no_intervene:risk={decision.yijing_risk_score:.2f},"
            f"value={decision.yijing_value_score:.2f}"
        )
        return decision

    def _calc_risk_score(
        self,
        risk_level: str,
        current_phase: str,
        development_stage: str,
        direction_hint: str,
        pos_side: str,
    ) -> float:
        """计算卦象风险分（0-1，越高越危险）"""
        cfg = self.config

        # risk_level 分量
        rl_risk = cfg.risk_level_map.get(risk_level, 0.50)

        # current_phase 分量
        phase_risk = cfg.phase_risk_map.get(current_phase, 0.50)

        # development_stage 分量
        stage_risk = cfg.stage_risk_map.get(development_stage, 0.50)

        # 方向一致性分量
        direction_map = cfg.direction_consistency_map.get(
            direction_hint, {"long": 0.50, "short": 0.50}
        )
        dir_risk = direction_map.get(pos_side, 0.50)

        # 加权
        risk_score = (
            cfg.weight_risk_level * rl_risk
            + cfg.weight_phase * phase_risk
            + cfg.weight_development * stage_risk
            + cfg.weight_direction_consistency * dir_risk
        )
        return max(0.0, min(1.0, risk_score))

    def _calc_value_score(
        self,
        current_phase: str,
        development_stage: str,
        risk_level: str,
    ) -> float:
        """计算卦象价值分（0-1，越高越有价值）"""
        cfg = self.config

        # current_phase 价值
        phase_value = cfg.phase_value_map.get(current_phase, 0.50)

        # development_stage 价值
        stage_value = cfg.stage_value_map.get(development_stage, 0.50)

        # risk_level 反向价值（高风险=低价值）
        rl_risk = cfg.risk_level_map.get(risk_level, 0.50)
        rl_value = 1.0 - rl_risk

        # 加权（phase 和 stage 为主）
        value_score = 0.45 * phase_value + 0.40 * stage_value + 0.15 * rl_value
        return max(0.0, min(1.0, value_score))

    def _extract_hexagram(self, hexagram: Any) -> Optional[Dict[str, Any]]:
        """从卦象对象提取字段（兼容 YijingResult / dict / None）"""
        if hexagram is None:
            return None
        if isinstance(hexagram, dict):
            return hexagram
        if hasattr(hexagram, "to_dict"):
            try:
                return hexagram.to_dict()
            except Exception:
                pass
        # 尝试直接读属性
        try:
            return {
                "hexagram_name": getattr(hexagram, "hexagram_name", ""),
                "hexagram_name_cn": getattr(hexagram, "hexagram_name_cn", ""),
                "risk_level": getattr(hexagram, "risk_level", ""),
                "current_phase": getattr(hexagram, "current_phase", ""),
                "development_stage": getattr(hexagram, "development_stage", ""),
                "direction_hint": getattr(hexagram, "direction_hint", "UNKNOWN"),
                "confidence": getattr(hexagram, "confidence", 0.5),
            }
        except Exception:
            return None

    # ── 数据驱动校准（P1: 基于回测统计反向校准卦象参数）──

    def calibrate_from_trades(self, trades: List[Any], min_samples: int = 5) -> Dict[str, Any]:
        """
        基于历史交易数据反向校准卦象风险/价值映射参数（P1数据驱动校准）

        原理：
        - 统计每个 phase/stage/risk_level 的实际胜率和收益
        - 用实际表现反向推导其"真实风险"和"真实价值"
        - 与先验假设对比，生成校准建议

        Args:
            trades: 交易列表，每笔需含 hexagram_name/current_phase/development_stage
                    /risk_level/pnl_pct 字段（或 Trade 对象）
            min_samples: 最少样本数，低于此值不校准

        Returns:
            dict: 校准结果，含建议参数和与先验的偏差
        """
        if not trades:
            return {"status": "no_data", "suggestions": []}

        # 提取交易数据
        trade_data = []
        for t in trades:
            if hasattr(t, "hexagram_name"):
                # Trade dataclass
                hex_name = t.hexagram_name
                pnl = t.pnl_pct
                phase = getattr(t, "current_phase", "") or ""
                stage = getattr(t, "development_stage", "") or ""
                risk = getattr(t, "risk_level", "") or ""
            elif isinstance(t, dict):
                hex_name = t.get("hexagram_name", "")
                pnl = t.get("pnl_pct", 0)
                phase = t.get("current_phase", "") or ""
                stage = t.get("development_stage", "") or ""
                risk = t.get("risk_level", "") or ""
            else:
                continue
            if hex_name:
                trade_data.append({
                    "hexagram_name": hex_name,
                    "pnl_pct": pnl,
                    "current_phase": phase,
                    "development_stage": stage,
                    "risk_level": risk,
                    "is_win": pnl > 0,
                })

        if not trade_data:
            return {"status": "no_hexagram_data", "suggestions": []}

        total = len(trade_data)
        total_win_rate = sum(1 for t in trade_data if t["is_win"]) / max(total, 1)
        total_avg_pnl = sum(t["pnl_pct"] for t in trade_data) / max(total, 1)

        # ── 按 current_phase 统计 ──
        phase_stats = self._group_stats(trade_data, "current_phase", min_samples)
        # ── 按 development_stage 统计 ──
        stage_stats = self._group_stats(trade_data, "development_stage", min_samples)
        # ── 按 risk_level 统计 ──
        risk_stats = self._group_stats(trade_data, "risk_level", min_samples)

        # ── 生成校准建议 ──
        suggestions = []
        cfg = self.config

        # Phase 校准建议
        for phase, stats in phase_stats.items():
            prior_risk = cfg.phase_risk_map.get(phase, 0.5)
            prior_value = cfg.phase_value_map.get(phase, 0.5)
            actual_win = stats["win_rate"]
            actual_pnl = stats["avg_pnl"]
            # 偏差方向：实际胜率远低于先验风险预期 → 风险被低估
            risk_alignment = self._assess_risk_alignment(prior_risk, actual_win, total_win_rate)
            if risk_alignment != "aligned" and stats["count"] >= min_samples:
                suggestions.append({
                    "dimension": "phase",
                    "key": phase,
                    "type": risk_alignment,
                    "prior_risk": prior_risk,
                    "actual_win_rate": actual_win,
                    "actual_avg_pnl": actual_pnl,
                    "sample_count": stats["count"],
                    "suggestion": f"{phase} 先验风险={prior_risk:.2f}，实际胜率={actual_win:.0%}，"
                                  f"建议{'上调' if risk_alignment == 'underestimated' else '下调'}风险分",
                })

        # Stage 校准建议
        for stage, stats in stage_stats.items():
            prior_risk = cfg.stage_risk_map.get(stage, 0.5)
            actual_win = stats["win_rate"]
            risk_alignment = self._assess_risk_alignment(prior_risk, actual_win, total_win_rate)
            if risk_alignment != "aligned" and stats["count"] >= min_samples:
                suggestions.append({
                    "dimension": "stage",
                    "key": stage,
                    "type": risk_alignment,
                    "prior_risk": prior_risk,
                    "actual_win_rate": actual_win,
                    "actual_avg_pnl": stats["avg_pnl"],
                    "sample_count": stats["count"],
                    "suggestion": f"{stage} 先验风险={prior_risk:.2f}，实际胜率={actual_win:.0%}，"
                                  f"建议{'上调' if risk_alignment == 'underestimated' else '下调'}风险分",
                })

        return {
            "status": "ok",
            "total_trades": total,
            "overall_win_rate": total_win_rate,
            "overall_avg_pnl": total_avg_pnl,
            "phase_stats": phase_stats,
            "stage_stats": stage_stats,
            "risk_stats": risk_stats,
            "calibration_suggestions": suggestions,
            "suggestion_count": len(suggestions),
        }

    @staticmethod
    def _group_stats(trades: List[Dict], key: str, min_samples: int) -> Dict[str, Dict]:
        """按维度分组统计"""
        groups = {}
        for t in trades:
            k = t.get(key, "")
            if not k:
                continue
            if k not in groups:
                groups[k] = {"count": 0, "wins": 0, "total_pnl": 0.0, "pnls": []}
            groups[k]["count"] += 1
            groups[k]["total_pnl"] += t["pnl_pct"]
            groups[k]["pnls"].append(t["pnl_pct"])
            if t["is_win"]:
                groups[k]["wins"] += 1

        result = {}
        for k, g in groups.items():
            if g["count"] >= min_samples:
                result[k] = {
                    "count": g["count"],
                    "win_rate": g["wins"] / g["count"],
                    "avg_pnl": g["total_pnl"] / g["count"],
                }
        return result

    @staticmethod
    def _assess_risk_alignment(prior_risk: float, actual_win_rate: float, baseline_win_rate: float) -> str:
        """
        评估先验风险与实际表现的一致性
        - underestimated: 先验风险太低（实际表现远差于预期）
        - overestimated: 先验风险太高（实际表现远好于预期）
        - aligned: 基本一致
        """
        # 先验风险越高 → 预期胜率越低
        # 用 1 - prior_risk 作为预期胜率的相对基准
        expected_relative = 1.0 - prior_risk
        actual_relative = actual_win_rate / max(baseline_win_rate, 0.01)
        diff = actual_relative - expected_relative
        if diff < -0.25:
            return "underestimated"  # 实际更差 → 风险被低估
        elif diff > 0.25:
            return "overestimated"   # 实际更好 → 风险被高估
        return "aligned"

    # ── 参数版本管理（P2-2: 回滚机制）──

    def snapshot_config(self, label: str = "") -> Dict[str, Any]:
        """创建当前配置的快照（用于回滚）"""
        import copy
        import time
        return {
            "version": "1.0",
            "timestamp": time.time(),
            "label": label,
            "config": copy.deepcopy({
                "weight_risk_level": self.config.weight_risk_level,
                "weight_phase": self.config.weight_phase,
                "weight_development": self.config.weight_development,
                "weight_direction_consistency": self.config.weight_direction_consistency,
                "veto_risk_threshold": self.config.veto_risk_threshold,
                "veto_value_threshold": self.config.veto_value_threshold,
                "veto_max_loss_pct": self.config.veto_max_loss_pct,
                "veto_max_hold_sec": self.config.veto_max_hold_sec,
                "raise_tp_min_profit_pct": self.config.raise_tp_min_profit_pct,
                "raise_tp_adjust_pct": self.config.raise_tp_adjust_pct,
                "raise_tp_value_threshold": self.config.raise_tp_value_threshold,
                "force_close_risk_threshold": self.config.force_close_risk_threshold,
                "phase_risk_map": dict(self.config.phase_risk_map),
                "phase_value_map": dict(self.config.phase_value_map),
                "stage_risk_map": dict(self.config.stage_risk_map),
                "stage_value_map": dict(self.config.stage_value_map),
                "risk_level_map": dict(self.config.risk_level_map),
                "direction_consistency_map": {k: dict(v) for k, v in self.config.direction_consistency_map.items()},
            }),
        }

    def restore_config(self, snapshot: Dict[str, Any]) -> bool:
        """从快照恢复配置（回滚）"""
        try:
            cfg_data = snapshot.get("config", {})
            for key, value in cfg_data.items():
                if hasattr(self.config, key):
                    setattr(self.config, key, value)
            return True
        except Exception:
            return False
