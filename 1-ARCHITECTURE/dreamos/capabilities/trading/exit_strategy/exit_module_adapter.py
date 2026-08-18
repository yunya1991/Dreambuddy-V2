#!/usr/bin/env python3
"""
离场模块统一适配器 (Exit Module Adapter)
======================================

将多个离场模块（ClassicExitSystem / YijingExitSystem / 基本面信号反转）
封装为统一接口，供 ExitModuleSelector 按场景选优调用。

统一输出 ExitDecision:
    action:     HOLD / CLOSE / REDUCE / RAISE_TP
    reason:     触发原因
    stop_loss:  动态止损价
    take_profit: 动态止盈价
    exit_price: 触发离场时的价格（CLOSE 时有效）
    confidence: 决策置信度
    source:     来源模块名
"""

from __future__ import annotations

import os
import sys
import time
import logging
import importlib.util
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── 统一输出 ────────────────────────────────────────────────────────────

@dataclass
class UnifiedExitDecision:
    """统一离场决策（跨模块）"""
    action: str = "HOLD"           # HOLD / CLOSE / REDUCE / RAISE_TP
    reason: str = ""
    stop_loss: float = 0.0
    take_profit: float = 0.0
    exit_price: float = 0.0
    confidence: float = 0.5
    source: str = "unknown"        # classic / yijing / fundamental / simple
    reduce_frac: float = 0.0
    new_tp_price: float = 0.0
    new_trailing_armed: Optional[bool] = None
    new_trailing_stop: float = 0.0
    raw: Optional[Any] = None      # 原始决策对象（调试用）

    @property
    def should_exit(self) -> bool:
        return self.action in ("CLOSE", "REDUCE")


# ── ClassicExitSystem 适配器 ────────────────────────────────────────────

class ClassicExitAdapter:
    """封装 ClassicExitSystem 为 DreamOS 统一接口

    自动处理:
    - 模块加载（从 10-经典指标系统/classic_exit_system.py 动态 import）
    - DreamOS market_data → PositionState 转换
    - K线数据获取（从 market_data 中提取或用 ATR 估算）
    - ExitDecision → UnifiedExitDecision 转换
    """

    def __init__(self):
        self._system = None
        self._load_error = None

    def _load_system(self):
        """懒加载 ClassicExitSystem"""
        if self._system is not None:
            return self._system
        if self._load_error:
            return None

        try:
            # 优先从 dreamos 包路径加载
            from dreamos.capabilities.trading.exit_strategy.classic_exit_loader import get_classic_system
            self._system = get_classic_system()
            return self._system
        except Exception:
            pass

        # 回退: 直接从文件路径加载
        try:
            project_root = os.environ.get("DREAMBUDDY_ROOT", "")
            if not project_root:
                # 从当前文件路径向上查找项目根（含 10-经典指标系统 目录）
                current = os.path.dirname(os.path.abspath(__file__))
                for _ in range(8):
                    if os.path.isdir(os.path.join(current, "10-经典指标系统")):
                        project_root = current
                        break
                    current = os.path.dirname(current)

            classic_path = os.path.join(project_root, "10-经典指标系统", "classic_exit_system.py")
            if not os.path.exists(classic_path):
                self._load_error = f"ClassicExitSystem 文件不存在: {classic_path}"
                logger.warning(self._load_error)
                return None

            spec = importlib.util.spec_from_file_location("classic_exit_system", classic_path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules["classic_exit_system"] = mod
            spec.loader.exec_module(mod)

            ClassicExitSystem = mod.ClassicExitSystem
            self._system = ClassicExitSystem()
            logger.info("ClassicExitSystem 加载成功 (from file)")
            return self._system
        except Exception as e:
            self._load_error = str(e)
            logger.warning(f"ClassicExitSystem 加载失败: {e}")
            return None

    def evaluate(
        self,
        symbol: str,
        entry_price: float,
        current_price: float,
        direction: str,
        market_data: Dict[str, Any],
        position_age_sec: float = 0.0,
        unrealized_pnl_pct: float = 0.0,
        leverage: float = 1.0,
        atr_pct: float = 0.02,
        mfe_pnl_pct: float = 0.0,
        max_dd_pct: float = 0.0,
        trailing_armed: bool = False,
        trailing_stop_price: float = 0.0,
        scenario_id: str = "",
    ) -> UnifiedExitDecision:
        """评估离场条件（统一接口）"""
        system = self._load_system()
        if system is None:
            # 加载失败时降级为简单止损
            return UnifiedExitDecision(
                action="HOLD",
                reason=f"ClassicExitSystem 不可用({self._load_error}), 降级",
                source="classic_fallback",
            )

        try:
            # 构造 PositionState
            PositionState = type(system).mro()  # 获取模块引用
            # 直接从 sys.modules 获取 PositionState
            mod = sys.modules.get("classic_exit_system") or sys.modules.get(
                "dreamos.capabilities.trading.exit_strategy.classic_exit_loader"
            )
            if mod is None:
                # 尝试从系统对象的模块获取
                mod = getattr(system, "__module__", None)
                if isinstance(mod, str):
                    mod = sys.modules.get(mod)

            PositionStateCls = getattr(mod, "PositionState", None) if mod else None
            if PositionStateCls is None:
                return UnifiedExitDecision(
                    action="HOLD",
                    reason="无法获取 PositionState 类",
                    source="classic_error",
                )

            pos = PositionStateCls(
                coin=symbol,
                side="long" if direction == "LONG" else "short",
                entry_price=entry_price,
                current_price=current_price,
                position_age_sec=position_age_sec,
                unrealized_pnl_pct=unrealized_pnl_pct,
                leverage=leverage,
                atr_pct=atr_pct,
                mfe_pnl_pct=mfe_pnl_pct,
                max_dd_pct=max_dd_pct,
                trailing_armed=bool(trailing_armed),
                trailing_stop_price=float(trailing_stop_price),
                entry_ts=int(time.time() - position_age_sec) if position_age_sec > 0 else 0,
            )

            # 从 market_data 提取 K线（如果有）
            raw_candles = market_data.get("candles_1h") or market_data.get("candles") or []

            # ClassicExitSystem 期望 List[Dict] 格式（c.get("c", c.get("close"))）
            # 如果传入的是 List[List]（[ts, o, h, l, c, v]），需要转换为 dict 格式
            candles = []
            if isinstance(raw_candles, list):
                for c in raw_candles:
                    if isinstance(c, dict):
                        candles.append(c)
                    elif isinstance(c, (list, tuple)) and len(c) >= 5:
                        candles.append({
                            "t": c[0], "o": c[1], "h": c[2], "l": c[3], "c": c[4],
                            "v": c[5] if len(c) > 5 else 0,
                        })

            # 判断 regime
            regime = "trend"
            if scenario_id:
                if "RANGE" in scenario_id or "CHOP" in scenario_id:
                    regime = "ranging"
                elif "BULL" in scenario_id:
                    regime = "trend"
                elif "BEAR" in scenario_id:
                    regime = "trend"

            # 调用 ClassicExitSystem.evaluate_full
            raw_decision = system.evaluate_full(
                pos=pos,
                candles_1h=candles,
                regime=regime,
            )

            # 转换为统一格式
            action_str = str(raw_decision.action) if hasattr(raw_decision, "action") else "HOLD"
            # 去除枚举前缀
            if "." in action_str:
                action_str = action_str.split(".")[-1]
            action_str = action_str.lower().replace("raise_tp", "RAISE_TP").upper()

            return UnifiedExitDecision(
                action=action_str,
                reason=getattr(raw_decision, "reason", ""),
                stop_loss=float(getattr(raw_decision, "stop_loss", 0) or 0),
                take_profit=float(getattr(raw_decision, "take_profit", 0) or 0),
                exit_price=float(getattr(raw_decision, "suggested_price", 0) or 0),
                confidence=float(getattr(raw_decision, "confidence", 0.5) or 0.5),
                source="classic",
                reduce_frac=float(getattr(raw_decision, "reduce_frac", 0) or 0),
                new_tp_price=float(getattr(raw_decision, "new_tp_price", 0) or 0),
                raw=raw_decision,
            )
        except Exception as e:
            logger.warning(f"ClassicExitSystem 评估异常({symbol}): {e}")
            return UnifiedExitDecision(
                action="HOLD",
                reason=f"Classic 评估异常: {e}",
                source="classic_error",
            )

    @property
    def name(self) -> str:
        return "classic"

    @property
    def is_available(self) -> bool:
        return self._load_system() is not None


# ── 简单离场适配器（当前 DreamOS 内置逻辑的封装）─────────────────────────

class SimpleExitAdapter:
    """封装当前 DreamOS auto_trader.py check_exit 的简单逻辑

    作为 baseline 和降级方案：时间衰减 + ATR 止损 + 移动止盈
    """

    def __init__(self):
        from dreamos.capabilities.trading.exit_strategy.stop_take_profit import (
            calculate_stop_take_profit,
        )
        self._calc_sttp = calculate_stop_take_profit

    def evaluate(
        self,
        symbol: str,
        entry_price: float,
        current_price: float,
        direction: str,
        market_data: Dict[str, Any],
        position_age_sec: float = 0.0,
        unrealized_pnl_pct: float = 0.0,
        leverage: float = 1.0,
        atr_pct: float = 0.02,
        mfe_pnl_pct: float = 0.0,
        max_dd_pct: float = 0.0,
        trailing_armed: bool = False,
        trailing_stop_price: float = 0.0,
        scenario_id: str = "",
    ) -> UnifiedExitDecision:
        """简单离场评估：ATR 止损 + 移动止盈"""
        bars_held = max(1, int(position_age_sec / 3600))

        # 时间衰减因子
        if bars_held <= 20:
            time_factor = 1.5
        elif bars_held <= 50:
            time_factor = 1.5 - (bars_held - 20) * (0.5 / 30)
        else:
            time_factor = 1.0

        # 简单 regime 判断
        regime = "ranging" if "RANGE" in scenario_id or "CHOP" in scenario_id else "trend_bull" if "BULL" in scenario_id else "trend_bear"
        confidence = max(0.3, 0.8 - bars_held * 0.01)

        try:
            sltp = self._calc_sttp(
                direction=direction,
                entry_price=entry_price,
                atr_pct=atr_pct,
                confidence=confidence,
                stop_strategy="atr",
                take_strategy="ratio",
                take_ratio=2.0,
                min_rr_ratio=1.5,
                market_regime=regime,
            )
            stop_loss = sltp.get("stop_loss", 0)
            take_profit = sltp.get("take_profit", 0)
        except Exception:
            sl_pct = atr_pct * 1.0 * time_factor
            tp_pct = atr_pct * 2.0
            if direction == "LONG":
                stop_loss = entry_price * (1 - sl_pct)
                take_profit = entry_price * (1 + tp_pct)
            else:
                stop_loss = entry_price * (1 + sl_pct)
                take_profit = entry_price * (1 - tp_pct)

        # 移动止盈（20+ 根 K 线后启用）
        if bars_held > 20 and unrealized_pnl_pct > 0:
            if direction == "LONG":
                trail_stop = entry_price * (1 + unrealized_pnl_pct * 0.5)
                stop_loss = max(stop_loss, trail_stop)
            else:
                trail_stop = entry_price * (1 - unrealized_pnl_pct * 0.5)
                stop_loss = min(stop_loss, trail_stop)

        # 判断是否触发离场
        action = "HOLD"
        reason = f"继续持有 (持仓{bars_held}根, time_factor={time_factor:.2f})"
        exit_price = 0.0

        if direction == "LONG":
            if current_price <= stop_loss:
                action = "CLOSE"
                reason = f"止损触发: {current_price:.4f} <= {stop_loss:.4f}"
                exit_price = stop_loss
            elif current_price >= take_profit:
                action = "CLOSE"
                reason = f"止盈触发: {current_price:.4f} >= {take_profit:.4f}"
                exit_price = take_profit
        else:
            if current_price >= stop_loss:
                action = "CLOSE"
                reason = f"止损触发: {current_price:.4f} >= {stop_loss:.4f}"
                exit_price = stop_loss
            elif current_price <= take_profit:
                action = "CLOSE"
                reason = f"止盈触发: {current_price:.4f} <= {take_profit:.4f}"
                exit_price = take_profit

        return UnifiedExitDecision(
            action=action,
            reason=reason,
            stop_loss=stop_loss,
            take_profit=take_profit,
            exit_price=exit_price,
            confidence=confidence,
            source="simple",
        )

    @property
    def name(self) -> str:
        return "simple"

    @property
    def is_available(self) -> bool:
        return True


# ── YijingExitAdapter ────────────────────────────────────────────────────

class YijingExitAdapter:
    """易经离场适配器

    封装 11-易经推理系统/scripts/memory_l4/yijing_exit_system.py 的
    YijingExitSystem 为 DreamOS 统一接口。

    卦象数据来源（三级降级）：
    L1: market_data['hexagram_result']  — 未来 A_YJ_INFER 节点注入
    L2: market_data['yijing_hexagram']   — A2 综合感知节点注入
    L3: _synthesize_hexagram()            — 基于 scenario_id+change24h+rsi+atr 合成
        （回测/冷启动无卦象数据时自动启用，保证零回归可用）

    决策映射（9→4）：
        FORCE_CLOSE                   → CLOSE
        LOWER_TP（风险升高提前锁定）   → CLOSE
        RAISE_TP                      → RAISE_TP + new_tp_price
        LOWER_SL / TIGHTEN_SL /
        ADJUST_SL_TP                  → HOLD + 动态调整 stop_loss/take_profit
        VETO_CLOSE / VETO_REDUCE /
        NO_INTERVENE                  → HOLD
    """

    def __init__(self):
        self._system = None
        self._load_error = None

    # ── 懒加载 YijingExitSystem ─────────────────────────────────────────

    def _load_system(self):
        """懒加载 YijingExitSystem（两级路径查找）"""
        if self._system is not None:
            return self._system
        if self._load_error:
            return None

        # L1: 优先从 dreamos 包路径（若未来有镜像封装）
        try:
            from dreamos.capabilities.trading.exit_strategy.yijing_exit_loader import get_yijing_system
            self._system = get_yijing_system()
            logger.info("YijingExitSystem 加载成功 (from package)")
            return self._system
        except Exception:
            pass

        # L2: 从项目根 11-易经推理系统 目录加载（冷启动标准路径）
        try:
            project_root = os.environ.get("DREAMBUDDY_ROOT", "")
            if not project_root:
                current = os.path.dirname(os.path.abspath(__file__))
                for _ in range(8):
                    if os.path.isdir(os.path.join(current, "11-易经推理系统")):
                        project_root = current
                        break
                    current = os.path.dirname(current)

            yj_path = os.path.join(
                project_root, "11-易经推理系统", "scripts", "memory_l4", "yijing_exit_system.py"
            )
            if not os.path.exists(yj_path):
                self._load_error = f"YijingExitSystem 文件不存在: {yj_path}"
                logger.warning(self._load_error)
                return None

            spec = importlib.util.spec_from_file_location("yijing_exit_system", yj_path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules["yijing_exit_system"] = mod
            spec.loader.exec_module(mod)

            YijingExitSystemCls = mod.YijingExitSystem
            self._system = YijingExitSystemCls()
            logger.info("YijingExitSystem 加载成功 (from file)")
            return self._system
        except Exception as e:
            self._load_error = str(e)
            logger.warning(f"YijingExitSystem 加载失败: {e}")
            return None

    # ── 卦象合成（无卦象数据时 fallback） ──────────────────────────────

    @staticmethod
    def _synthesize_hexagram(
        scenario_id: str,
        market_data: Dict[str, Any],
        direction: str,
    ) -> Dict[str, Any]:
        """基于场景ID + 技术指标合成卦象（保证回测/冷启动可用）

        映射规则：
        - BULL_* + 低波动 → 飞龙在天/九五 (成长期/成熟期)
        - BULL_* + 高波动 → 或跃在渊/九四
        - BEAR_* + 低波动 → 亢龙有悔/上九 (衰退期)
        - BEAR_* + 高波动 → 终日乾乾/九三
        - RANGE/NEUTRAL → 见龙在田/九二 或 潜龙勿用/初九
        """
        sid = (scenario_id or "").upper()
        change_24h = float(market_data.get("change_24h", 0) or 0)
        rsi = float(market_data.get("rsi14", 50) or 50)
        atr_pct = float(market_data.get("atr_pct", 0.02) or 0.02)

        # 趋势方向
        is_bull = "BULL" in sid or change_24h > 0.02
        is_bear = "BEAR" in sid or change_24h < -0.02
        is_extreme = "EXTREME" in sid or abs(change_24h) > 0.05
        high_vol = atr_pct > 0.03 or "HIGH" in sid or "EXTREME" in sid

        # 持仓方向与场景一致性
        dir_consistent = (is_bull and direction == "LONG") or (is_bear and direction == "SHORT")

        # ── 六爻阶段 (current_phase) + 发展阶段 (development_stage) ──
        if is_extreme and is_bear:
            current_phase = "上九"      # 亢龙有悔
            development_stage = "衰退期"
            risk_level = "高"
            direction_hint = "DOWN"
            hex_name = "坤为地"
        elif is_extreme and is_bull:
            current_phase = "九五"      # 飞龙在天
            development_stage = "成熟期"
            risk_level = "中"
            direction_hint = "UP"
            hex_name = "乾为天"
        elif is_bull and high_vol:
            current_phase = "九四"      # 或跃在渊
            development_stage = "成长期"
            risk_level = "中"
            direction_hint = "UP" if dir_consistent else "TRANSITIONING"
            hex_name = "水天需"
        elif is_bull:
            current_phase = "九五"      # 飞龙在天
            development_stage = "成熟期"
            risk_level = "低"
            direction_hint = "UP"
            hex_name = "乾为天"
        elif is_bear and high_vol:
            current_phase = "九三"      # 终日乾乾
            development_stage = "衰退期"
            risk_level = "高"
            direction_hint = "DOWN" if dir_consistent else "TRANSITIONING"
            hex_name = "水雷屯"
        elif is_bear:
            current_phase = "上九"      # 亢龙有悔
            development_stage = "衰退期"
            risk_level = "中"
            direction_hint = "DOWN"
            hex_name = "坤为地"
        elif rsi < 40:
            current_phase = "初九"      # 潜龙勿用
            development_stage = "萌芽期"
            risk_level = "中"
            direction_hint = "TRANSITIONING"
            hex_name = "地雷复"
        elif rsi > 60:
            current_phase = "九三"      # 终日乾乾
            development_stage = "成熟期"
            risk_level = "中"
            direction_hint = "TRANSITIONING"
            hex_name = "天风姤"
        else:
            current_phase = "九二"      # 见龙在田
            development_stage = "成长期"
            risk_level = "低"
            direction_hint = "FLAT"
            hex_name = "水火既济"

        # 置信度：ATR 越小、change 越明确，置信度越高
        confidence = max(0.3, min(0.9, 0.55 + abs(change_24h) * 3 - atr_pct * 4))

        return {
            "hexagram_name": hex_name,
            "hexagram_name_cn": hex_name,
            "risk_level": risk_level,
            "current_phase": current_phase,
            "development_stage": development_stage,
            "direction_hint": direction_hint,
            "confidence": round(confidence, 3),
            "_synthesized": True,
        }

    # ── SL/TP 基准计算 ──────────────────────────────────────────────────

    @staticmethod
    def _base_sltp(
        direction: str,
        entry_price: float,
        atr_pct: float,
    ) -> Tuple[float, float]:
        """基于 ATR 的基准 SL/TP（SL=1.5×ATR, TP=3.0×ATR，RR=2）"""
        atr_amt = entry_price * max(0.005, atr_pct)
        if direction == "LONG":
            sl = entry_price - 1.5 * atr_amt
            tp = entry_price + 3.0 * atr_amt
        else:
            sl = entry_price + 1.5 * atr_amt
            tp = entry_price - 3.0 * atr_amt
        return max(1e-9, sl), max(1e-9, tp)

    # ── 统一接口 ────────────────────────────────────────────────────────

    def evaluate(
        self,
        symbol: str,
        entry_price: float,
        current_price: float,
        direction: str,
        market_data: Dict[str, Any],
        position_age_sec: float = 0.0,
        unrealized_pnl_pct: float = 0.0,
        leverage: float = 1.0,
        atr_pct: float = 0.02,
        mfe_pnl_pct: float = 0.0,
        max_dd_pct: float = 0.0,
        trailing_armed: bool = False,
        trailing_stop_price: float = 0.0,
        scenario_id: str = "",
    ) -> UnifiedExitDecision:
        """易经离场评估（统一接口）"""
        system = self._load_system()
        if system is None:
            return UnifiedExitDecision(
                action="HOLD",
                reason=f"YijingExitSystem 不可用({self._load_error}), 降级",
                source="yijing_fallback",
            )

        try:
            # ── Step 1: 获取/合成卦象 ──
            hexagram = (
                market_data.get("hexagram_result")
                or market_data.get("yijing_hexagram")
                or self._synthesize_hexagram(scenario_id, market_data, direction)
            )
            synthesized = bool(hexagram and hexagram.get("_synthesized")) if isinstance(hexagram, dict) else False

            # ── Step 2: 构造参数 ──
            pos_side = "long" if direction == "LONG" else "short"
            open_time_sec = max(0.0, time.time() - position_age_sec)

            # ── Step 3: 调用易经主系统（main 模式，守1h门禁）──
            yj_decision = system.evaluate(
                hexagram=hexagram,
                pos_side=pos_side,
                entry_price=float(entry_price),
                current_price=float(current_price),
                position_age_sec=float(position_age_sec),
                unrealized_pnl_pct=float(unrealized_pnl_pct),
                coin=symbol,
                open_time_sec=open_time_sec,
                mode="main",
            )

            # ── Step 4: 基准 SL/TP + 易经调整 ──
            base_sl, base_tp = self._base_sltp(direction, float(entry_price), float(atr_pct))
            sl, tp = base_sl, base_tp
            new_tp_price = 0.0

            # 应用 sl_adjust_pct（正数=放宽，负数=收紧）
            if yj_decision.sl_adjust_pct:
                # LONG: SL = entry - (1 + sl_adj) * dist  — 放宽即向不利方向移
                # SHORT: 对称处理
                if direction == "LONG":
                    sl_dist = entry_price - base_sl
                    sl = entry_price - sl_dist * (1.0 + yj_decision.sl_adjust_pct)
                else:
                    sl_dist = base_sl - entry_price
                    sl = entry_price + sl_dist * (1.0 + yj_decision.sl_adjust_pct)

            # 应用 tp_adjust_pct（正数=提高，负数=降低）
            if yj_decision.tp_adjust_pct:
                if direction == "LONG":
                    tp_dist = base_tp - entry_price
                    tp = entry_price + tp_dist * (1.0 + yj_decision.tp_adjust_pct)
                else:
                    tp_dist = entry_price - base_tp
                    tp = entry_price - tp_dist * (1.0 + yj_decision.tp_adjust_pct)

            sl = max(1e-9, sl)
            tp = max(1e-9, tp)

            # ── Step 5: 决策映射（9→4）──
            action_str = str(yj_decision.action.value) if hasattr(yj_decision.action, "value") else str(yj_decision.action)

            mapped_action = "HOLD"
            exit_price = 0.0
            reduce_frac = 0.0

            if action_str == "force_close":
                mapped_action = "CLOSE"
                exit_price = current_price
            elif action_str == "lower_tp":
                # 风险升高提前锁定利润 → 直接 CLOSE（统一接口无 LOWER_TP）
                mapped_action = "CLOSE"
                exit_price = current_price
            elif action_str == "raise_tp":
                mapped_action = "RAISE_TP"
                new_tp_price = tp

            # ── Step 6: 构造 reason（标注合成卦象）──
            synth_tag = "[SYN]" if synthesized else ""
            reason = (
                f"{synth_tag}yijing:{action_str} "
                f"risk={yj_decision.yijing_risk_score:.2f} "
                f"value={yj_decision.yijing_value_score:.2f} "
                f"phase={yj_decision.current_phase or '-'} "
                f"stage={yj_decision.development_stage or '-'} "
                f"dir={'T' if yj_decision.direction_consistent else 'F'} | "
                f"{yj_decision.reason}"
            )

            return UnifiedExitDecision(
                action=mapped_action,
                reason=reason,
                stop_loss=float(sl),
                take_profit=float(tp),
                exit_price=float(exit_price),
                confidence=float(yj_decision.confidence or 0.5),
                source="yijing",
                reduce_frac=float(reduce_frac),
                new_tp_price=float(new_tp_price),
                raw=yj_decision,
            )
        except Exception as e:
            logger.warning(f"YijingExitSystem 评估异常({symbol}): {e}")
            # fail-open：异常时 HOLD + 基准 SL/TP
            base_sl, base_tp = self._base_sltp(direction, float(entry_price), float(atr_pct))
            return UnifiedExitDecision(
                action="HOLD",
                reason=f"yijing_error: {e}",
                stop_loss=base_sl,
                take_profit=base_tp,
                source="yijing_error_fallback",
            )

    @property
    def name(self) -> str:
        return "yijing"

    @property
    def is_available(self) -> bool:
        return self._load_system() is not None


# ── FundamentalExitAdapter (预留, 未实现) ────────────────────────────────

class FundamentalExitAdapter:
    """基本面离场适配器（预留接口）

    基于基本面信号反转（如估值偏离、资金流逆转、情绪极端）触发离场。
    需要接入 F 链基本面数据，实现后通过 ExitModuleSelector 选优。
    """

    def evaluate(self, **kwargs) -> UnifiedExitDecision:
        return UnifiedExitDecision(
            action="HOLD",
            reason="FundamentalExitAdapter 尚未集成",
            source="fundamental_unavailable",
        )

    @property
    def name(self) -> str:
        return "fundamental"

    @property
    def is_available(self) -> bool:
        return False


# ── 适配器注册表 ────────────────────────────────────────────────────────

def get_all_adapters() -> Dict[str, Any]:
    """获取所有已注册的离场适配器"""
    return {
        "classic": ClassicExitAdapter(),
        "simple": SimpleExitAdapter(),
        "yijing": YijingExitAdapter(),
        "fundamental": FundamentalExitAdapter(),
    }
