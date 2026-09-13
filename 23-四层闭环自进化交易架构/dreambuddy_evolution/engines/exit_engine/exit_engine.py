"""EvolutionExitEngine — 自进化系统独立离场决策引擎

与 KlineEventHandler 对称：开仓由 KlineEventHandler，离场由 EvolutionExitEngine。
不修改 KlineEventHandler / ReflectionEngine 现有接口，仅新增模块。

决策规则（优化版，含 ATR 自适应 + 分批止盈 + 超时信号评估）：
  0. OKX algo 触达 → force_close（仓位已被平）
  1. hold：保护期内（< 60min）
  2. 信号反转（R 向量相反 + ESS<0.4）→ force_close
  3. 超时 29H 信号评估：
     a. 盈利 + 有更强信号 → force_close 换仓
     b. 盈利 + 无更强信号 → hold 继续持有
     c. 亏损 → hold 继续持有（不因超时强平亏损仓）
  4. 分批止盈：+1R→partial_close 50%, +2R→partial_close 30%, +3R→trailing 剩余
  5. trailing 触发（peak tracking，回撤不退化）
  6. adjust_sl_tp 保本位（trailing 未触发时）
  7. ATR 自适应止损：SL = entry × (1 - max(ATR×mult, SL_floor))

FAIL-OPEN：任何异常 → 返回 hold ExitDecision，不阻塞主链路。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from dreambuddy_evolution.engines.exit_engine.exit_decision import ExitDecision
from dreambuddy_evolution.engines.exit_engine.exit_strategy_params import (
    ExitStrategyParams,
)

logger = logging.getLogger(__name__)


class EvolutionExitEngine:
    """自进化系统独立离场决策引擎

    被 PollingTrader._evolution_check_exit() 调用，不接入 _execute_trade（Phase 0 已隔离）。
    """

    # tier 分层 SL/TP 间距（ATR 缺失时兜底，2026-09-09 放大与 BCRM 对齐）
    TIER_SL_PCT = {"probe": 0.04, "standard": 0.04, "trend": 0.04}  # SL 下限统一 4%
    TIER_TP_PCT = {"probe": 0.12, "standard": 0.12, "trend": 0.12}  # TP 下限统一 12%

    # trailing 触发阈值（按 tier）
    TRAILING_ARM_PCT = {"probe": 0.08, "standard": 0.06, "trend": 0.06}

    # 保本位收紧触发阈值（盈亏达到此值 → SL 移到保本位）
    BREAK_EVEN_ARM_PCT = 0.03

    # 保护期 60min
    PROTECTION_PERIOD_SEC = 60 * 60

    # trend tier 超时阈值 24h（保留用于 trend tier 无进展判断）
    TREND_TIMEOUT_SEC = 24 * 3600

    # 优化3: 超时 29H 信号评估阈值
    TIMEOUT_SIGNAL_EVAL_SEC = 29 * 3600

    # 信号反转 ESS 阈值
    SIGNAL_REVERSE_ESS_THRESHOLD = 0.4

    # 优化1: ATR 自适应止损参数（2026-09-09 放大，与 BCRM 对齐）
    # SL = entry × (1 - ATR_mult × atr_pct)，但不低于 SL_FLOOR_PCT
    ATR_SL_MULTIPLIER = {"probe": 4.0, "standard": 4.5, "trend": 5.0}  # Chandelier 风格
    SL_FLOOR_PCT = 0.04  # SL 硬约束下限 4%（防低波扫损）
    SL_CEILING_PCT = {"probe": 0.15, "standard": 0.15, "trend": 0.15}  # SL 上限 15%

    # 优化2: 分批止盈 R 倍数阈值
    PARTIAL_TP_R_THRESHOLDS = [1.0, 2.0, 3.0]  # +1R, +2R, +3R
    PARTIAL_TP_PCTAGES = [0.5, 0.3, 0.2]  # 50%, 30%, 20%(trailing)

    # 规则 2b: BCRM2.0 反向信号减仓参数
    BCRM_REVERSE_CONF_TIERS = [(0.99, 0.70), (0.95, 0.50), (0.85, 0.30)]  # 高→低匹配
    BCRM_REVERSE_CONF_FLOOR = 0.85  # 最低触发置信度
    BCRM_REVERSE_STALE_SEC = 1800  # 30min 信号新鲜度
    # 规则 2b 冷却期：减仓后 4H 内不再触发（防连续扫射，SKHYNIX 47min×7 案例修复）
    BCRM_REDUCE_COOLDOWN_SEC = 4 * 3600  # 4 小时

    def __init__(
        self,
        okx_client: Any = None,
        ess_provider: Any = None,
        ftc_bridge: Any = None,
        shadow_rl_tracker: Any = None,
        log_fn: Optional[Callable[[str, str], None]] = None,
        strategy_params: Optional[ExitStrategyParams] = None,
    ):
        """
        Args:
            okx_client: OKX 客户端（用于 algo 触达检测，Phase 2 可为 None）
            ess_provider: ESSDirectionProvider（用于读取策略组合 ESS）
            ftc_bridge: FTCEvolutionBridge（用于读取 FTC 轨道）
            shadow_rl_tracker: ShadowRLTracker（用于记录离场决策 (s,a,R,s')）
            log_fn: 日志回调 fn(msg, level)
            strategy_params: 离场策略参数基因（Phase 5 参数自适应）
        """
        self.okx_client = okx_client
        self.ess_provider = ess_provider
        self.ftc_bridge = ftc_bridge
        self.shadow_rl_tracker = shadow_rl_tracker
        self._log_fn = log_fn or (lambda msg, level="INFO": None)
        self.strategy_params = strategy_params or ExitStrategyParams()
        # P4: peak price tracking — 记录每个 symbol 的 peak upl_ratio
        # trailing 触发后，只要 upl_ratio 仍 > BREAK_EVEN_ARM_PCT，保持 trailing
        self._peak_upl_ratio: Dict[str, float] = {}
        # 优化2: 记录每个 symbol 已执行的分批止盈批次
        self._partial_tp_executed: Dict[str, int] = {}
        # 规则 2b 冷却期：记录每个 symbol 上次 BCRM2.0 反向减仓的时间戳
        #   减仓后 4H 内不再触发，避免震荡中连续扫射（SKHYNIX 47min×7 案例修复）
        self._last_bcrm_reduce_ts: Dict[str, float] = {}

    def _log(self, msg: str, level: str = "INFO") -> None:
        try:
            self._log_fn(msg, level)
        except Exception:
            pass

    def decide(self, context: Dict[str, Any]) -> ExitDecision:
        """离场决策主入口

        Args:
            context: 见模块 docstring 字段清单

        Returns:
            ExitDecision: action/params/reason/sl_px/tp_px/confidence

        FAIL-OPEN: 任何异常 → 返回 hold
        """
        try:
            return self._decide_impl(context)
        except Exception as exc:
            self._log(
                f"[EvolutionExitEngine] decide crash (FAIL-OPEN): {exc}",
                "WARN",
            )
            return ExitDecision(
                action="hold",
                reason=f"evolution_exit:hold:fail_open:{type(exc).__name__}",
            )

    def _decide_impl(self, ctx: Dict[str, Any]) -> ExitDecision:
        """实际决策逻辑（不带 try/except，由 decide() 兜底）"""
        symbol = str(ctx.get("symbol", "UNKNOWN"))
        pos_side = str(ctx.get("pos_side", "long")).lower()
        entry_price = float(ctx.get("entry_price", 0.0) or 0.0)
        current_price = float(ctx.get("current_price", 0.0) or 0.0)
        upl_ratio = float(ctx.get("upl_ratio", 0.0) or 0.0)
        position_age_sec = float(ctx.get("position_age_sec", 0.0) or 0.0)
        ess = float(ctx.get("ess", 0.5) or 0.5)
        tier = str(ctx.get("tier", "standard")).lower()
        okx_algo_triggered = bool(ctx.get("okx_algo_triggered", False))
        r_vector = ctx.get("r_vector") or {}
        current_sl_px = float(ctx.get("current_sl_px", 0.0) or 0.0)
        current_tp_px = float(ctx.get("current_tp_px", 0.0) or 0.0)

        # 优化1: ATR 自适应止损（从 context 读取，缺失时用固定百分比兜底）
        atr_pct = float(ctx.get("atr_pct", 0.0) or 0.0)

        # 优化2: 分批止盈 R 倍数（从 context 读取或计算）
        r_multiple = float(ctx.get("r_multiple", 0.0) or 0.0)

        # 优化3: 超时信号评估所需信息
        has_stronger_signal = bool(ctx.get("has_stronger_signal", False))
        stronger_signal_info = ctx.get("stronger_signal_info") or {}

        # ── 规则 0：OKX algo 已触达 → force_close（仓位已被平，走同步流程）
        if okx_algo_triggered:
            self._log(
                f"[EvolutionExitEngine] {symbol} OKX algo 触达 → force_close",
                "INFO",
            )
            return ExitDecision(
                action="force_close",
                reason=f"evolution_exit:force_close:okx_algo_triggered",
                confidence=1.0,
            )

        # ── 规则 1：保护期 60min 内 → hold（仅用开仓静态 SL/TP 防护）
        if position_age_sec < self.PROTECTION_PERIOD_SEC:
            return ExitDecision(
                action="hold",
                reason=f"evolution_exit:hold:protection_period_{int(position_age_sec)}s",
            )

        # ── 规则 2：信号反转（R 向量方向相反 + ESS < 0.4）→ force_close
        if self._is_signal_reverse(r_vector, pos_side, ess):
            self._log(
                f"[EvolutionExitEngine] {symbol} 信号反转 + ESS={ess:.2f}<0.4 → force_close",
                "WARN",
            )
            return ExitDecision(
                action="force_close",
                reason=f"evolution_exit:force_close:signal_reverse_ess_{ess:.2f}",
                confidence=0.7,
            )

        # ── 规则 2b：BCRM2.0 高置信度反向信号 → partial_close 减仓（非全平）
        bcrm_reduce_decision = self._check_bcrm_reverse_signal(ctx)
        if bcrm_reduce_decision is not None:
            return bcrm_reduce_decision

        # ── 规则 3a：tier=trend 超时 24h 无进展（|upl_ratio| < 0.01）→ force_close
        if tier == "trend" and position_age_sec > self.TREND_TIMEOUT_SEC:
            if abs(upl_ratio) < 0.01:
                self._log(
                    f"[EvolutionExitEngine] {symbol} trend 超时 {int(position_age_sec/3600)}h 无进展 → force_close",
                    "INFO",
                )
                return ExitDecision(
                    action="force_close",
                    reason=f"evolution_exit:force_close:timeout_{int(position_age_sec/3600)}h",
                    confidence=0.6,
                )

        # ── 规则 3b：优化3 超时 29H 信号强度评估
        if position_age_sec >= self.TIMEOUT_SIGNAL_EVAL_SEC:
            if upl_ratio > 0:
                # 盈利 + 有更强信号 → 止盈平仓换仓
                if has_stronger_signal:
                    _is_opposite = bool(stronger_signal_info.get("is_opposite", False))
                    _sig_coin = stronger_signal_info.get("coin", "?")
                    _sig_dir = stronger_signal_info.get("direction", "?")
                    _sig_conf = float(stronger_signal_info.get("confidence", 0.0))
                    _rotate_type = "opposite" if _is_opposite else "same"
                    self._log(
                        f"[EvolutionExitEngine] {symbol} 超时 {int(position_age_sec/3600)}h "
                        f"盈利 {upl_ratio:.2%} + 更强信号({_sig_coin} {_sig_dir} "
                        f"conf={_sig_conf:.2f} {_rotate_type}) → force_close 换仓",
                        "INFO",
                    )
                    return ExitDecision(
                        action="force_close",
                        reason=f"evolution_exit:force_close:timeout_{int(position_age_sec/3600)}h_stronger_signal_rotate_{_rotate_type}",
                        confidence=0.75,
                    )
                else:
                    # 盈利 + 无更强信号 → 继续持有
                    self._log(
                        f"[EvolutionExitEngine] {symbol} 超时 {int(position_age_sec/3600)}h "
                        f"盈利 {upl_ratio:.2%} 无更强信号 → 继续持有",
                        "INFO",
                    )
                    return ExitDecision(
                        action="hold",
                        reason=f"evolution_exit:hold:timeout_profit_no_stronger_signal_{upl_ratio:.2%}",
                        confidence=0.6,
                    )
            else:
                # 亏损 → 继续持有（不因超时强平亏损仓）
                self._log(
                    f"[EvolutionExitEngine] {symbol} 超时 {int(position_age_sec/3600)}h "
                    f"亏损 {upl_ratio:.2%} → 继续持有（不超时强平亏损仓）",
                    "INFO",
                )
                return ExitDecision(
                    action="hold",
                    reason=f"evolution_exit:hold:timeout_loss_continue_hold_{upl_ratio:.2%}",
                    confidence=0.6,
                )

        # ── 规则 4：优化2 分批止盈（R 倍数驱动）
        if r_multiple > 0 and entry_price > 0 and current_sl_px > 0:
            partial_decision = self._check_partial_tp(symbol, r_multiple, current_price, pos_side, current_tp_px)
            if partial_decision:
                return partial_decision

        # ── 规则 5：trailing 触发（tier 对应 arm 阈值）
        trailing_arm = self.TRAILING_ARM_PCT.get(tier, 0.06)
        # P4: peak tracking — 更新 peak upl_ratio
        prev_peak = self._peak_upl_ratio.get(symbol, 0.0)
        current_peak = max(prev_peak, upl_ratio)
        self._peak_upl_ratio[symbol] = current_peak

        # trailing 已触发过（peak ≥ arm）且当前仍 > BREAK_EVEN → 保持 trailing
        trailing_already_armed = prev_peak >= trailing_arm
        if trailing_already_armed and upl_ratio > self.BREAK_EVEN_ARM_PCT and entry_price > 0:
            retrace = self.strategy_params.trailing_retrace_pct
            if pos_side == "long":
                new_sl_px = current_price * (1 - retrace)
            else:
                new_sl_px = current_price * (1 + retrace)
            self._log(
                f"[EvolutionExitEngine] {symbol} trailing 持续 peak={current_peak:.2%} "
                f"cur={upl_ratio:.2%} SL→{new_sl_px:.4f}",
                "INFO",
            )
            return ExitDecision(
                action="trailing",
                params={
                    "trailing_arm_pct": trailing_arm,
                    "trailing_retrace_pct": retrace,
                    "peak_upl_ratio": current_peak,
                },
                sl_px=new_sl_px,
                tp_px=current_tp_px,
                reason=f"evolution_exit:trailing:peak_{current_peak:.2%}_cur_{upl_ratio:.2%}",
                confidence=0.8,
            )

        # 首次触发 trailing（upl_ratio ≥ arm）
        if upl_ratio >= trailing_arm and entry_price > 0:
            retrace = self.strategy_params.trailing_retrace_pct
            if pos_side == "long":
                new_sl_px = current_price * (1 - retrace)
            else:
                new_sl_px = current_price * (1 + retrace)
            self._log(
                f"[EvolutionExitEngine] {symbol} trailing 触发 arm={trailing_arm:.2%} retrace={retrace:.2%}",
                "INFO",
            )
            return ExitDecision(
                action="trailing",
                params={
                    "trailing_arm_pct": trailing_arm,
                    "trailing_retrace_pct": retrace,
                    "peak_upl_ratio": current_peak,
                },
                sl_px=new_sl_px,
                tp_px=current_tp_px,
                reason=f"evolution_exit:trailing:armed_at_{trailing_arm:.2%}",
                confidence=0.8,
            )

        # ── 规则 6：adjust_sl_tp（盈亏触达 +3% → SL 收紧到保本位）
        # P4: 仅在 trailing 未触发过时执行（避免 trailing 状态退化到保本位）
        if not trailing_already_armed and upl_ratio >= self.BREAK_EVEN_ARM_PCT and entry_price > 0:
            # 优化1: ATR 自适应保本位收紧
            new_sl_px = self._calc_atr_adaptive_sl(
                entry_price, current_price, atr_pct, tier, pos_side, mode="break_even"
            )
            self._log(
                f"[EvolutionExitEngine] {symbol} adjust_sl_tp 保本位 SL→{new_sl_px:.4f} "
                f"(ATR={atr_pct:.2%} tier={tier})",
                "INFO",
            )
            return ExitDecision(
                action="adjust_sl_tp",
                params={"mode": "break_even", "atr_adaptive": atr_pct > 0, "atr_pct": atr_pct},
                sl_px=new_sl_px,
                tp_px=current_tp_px,
                reason=f"evolution_exit:adjust_sl_tp:break_even_{upl_ratio:.2%}_atr_{atr_pct:.2%}",
                confidence=0.6,
            )

        # ── 默认：hold（ATR 自适应 SL 在开仓时已设置，此处不重复）
        return ExitDecision(
            action="hold",
            reason=f"evolution_exit:hold:safe_zone_{upl_ratio:.2%}_atr_{atr_pct:.2%}",
            params={"atr_adaptive": atr_pct > 0, "atr_pct": atr_pct},
        )

    def _check_bcrm_reverse_signal(self, ctx: Dict[str, Any]) -> Optional[ExitDecision]:
        """规则 2b: BCRM2.0 高置信度反向信号 → partial_close 减仓

        当 BCRM2.0 对持仓方向给出高置信度反向信号时，分批减仓而非全仓平仓：
        - 0.85-0.95 → 30% 减仓
        - 0.95-0.99 → 50% 减仓
        - ≥0.99 + BDSM 方向一致 → 70% 减仓

        冷却期：减仓后 BCRM_REDUCE_COOLDOWN_SEC（4H）内不再触发，
        避免 5min 轮询间隔下震荡信号连续扫射（SKHYNIX 47min×7 案例修复）。
        冷却期内落回后续规则（trailing/adjust_sl_tp/hold）。

        FAIL-OPEN: 任何异常 → 返回 None（落回后续规则）
        """
        try:
            bcrm_dir = str(ctx.get("bcrm_reverse_dir", "") or "").lower()
            bcrm_conf = float(ctx.get("bcrm_reverse_conf", 0.0) or 0.0)
            bcrm_ts = float(ctx.get("bcrm_reverse_ts", 0.0) or 0.0)
            pos_side = str(ctx.get("pos_side", "")).lower()
            symbol = str(ctx.get("symbol", "UNKNOWN"))
            bdsm_constraint = str(ctx.get("bdsm_direction_constraint", "") or "").upper()

            # 信号缺失或方向为空 → 不触发
            if not bcrm_dir or bcrm_dir not in ("long", "short"):
                return None

            # 置信度低于阈值 → 不触发
            if bcrm_conf < self.BCRM_REVERSE_CONF_FLOOR:
                return None

            # 同向信号 → 不触发（只对反向信号减仓）
            if bcrm_dir == pos_side:
                return None

            # 信号新鲜度检查（30min 内有效）
            if bcrm_ts > 0:
                import time as _time
                if _time.time() - bcrm_ts > self.BCRM_REVERSE_STALE_SEC:
                    return None

            # ★ 冷却期检查：减仓后 4H 内不再触发
            #   避免震荡中 BCRM2.0 信号反复扫射（SKHYNIX 案例：47min 减仓 7 次，仓位 100%→8%）
            import time as _time_now
            _now = _time_now.time()
            _last_reduce = self._last_bcrm_reduce_ts.get(symbol, 0.0)
            if _last_reduce > 0 and (_now - _last_reduce) < self.BCRM_REDUCE_COOLDOWN_SEC:
                _remain_min = (self.BCRM_REDUCE_COOLDOWN_SEC - (_now - _last_reduce)) / 60
                self._log(
                    f"[EvolutionExitEngine] {symbol} BCRM2.0 反向信号减仓冷却期内 "
                    f"(剩余 {_remain_min:.0f}min) → 跳过规则 2b，落回后续规则",
                    "DEBUG",
                )
                return None

            # 按置信度分层匹配减仓比例（高→低）
            partial_pct = 0.30  # 默认 30%
            for conf_thresh, pct in self.BCRM_REVERSE_CONF_TIERS:
                if bcrm_conf >= conf_thresh:
                    partial_pct = pct
                    break

            # BDSM 方向一致时升级到 70%（仅当 BCRM 方向与 BDSM 约束一致）
            # 持仓 long + BCRM short + BDSM SHORT_ONLY → 共振看空
            # 持仓 short + BCRM long + BDSM LONG_ONLY → 共振看多
            if bdsm_constraint:
                bcrm_is_short = (bcrm_dir == "short")
                bdsm_is_short_only = ("SHORT" in bdsm_constraint)
                bcrm_is_long = (bcrm_dir == "long")
                bdsm_is_long_only = ("LONG" in bdsm_constraint)
                if (bcrm_is_short and bdsm_is_short_only) or (bcrm_is_long and bdsm_is_long_only):
                    partial_pct = 0.70

            self._log(
                f"[EvolutionExitEngine] {symbol} BCRM2.0 反向信号 dir={bcrm_dir} "
                f"conf={bcrm_conf:.2f} → partial_close {partial_pct*100:.0f}%"
                f"{' (BDSM 共振升级)' if partial_pct == 0.70 and bdsm_constraint else ''}",
                "INFO",
            )
            # ★ 触发减仓后记录冷却时间戳
            self._last_bcrm_reduce_ts[symbol] = _now
            return ExitDecision(
                action="partial_close",
                params={"partial_pct": partial_pct, "source": "bcrm_reverse"},
                reason=f"evolution_exit:partial_close:external_signal_reduce_conf{bcrm_conf:.2f}",
                confidence=bcrm_conf,
            )
        except Exception as e:
            self._log(
                f"[EvolutionExitEngine] BCRM 反向信号检查异常(FAIL-OPEN): {e}",
                "WARN",
            )
            return None

    def _check_partial_tp(
        self, symbol: str, r_multiple: float, current_price: float,
        pos_side: str, current_tp_px: float,
    ) -> Optional[ExitDecision]:
        """优化2: 分批止盈检查

        +1R → partial_close 50%
        +2R → partial_close 30%
        +3R → trailing 剩余 20%（返回 trailing 决策）
        """
        executed = self._partial_tp_executed.get(symbol, 0)

        for i, (r_thresh, pct) in enumerate(zip(self.PARTIAL_TP_R_THRESHOLDS, self.PARTIAL_TP_PCTAGES)):
            if r_multiple >= r_thresh and executed <= i:
                self._partial_tp_executed[symbol] = i + 1
                if i < 2:  # +1R, +2R → partial_close
                    self._log(
                        f"[EvolutionExitEngine] {symbol} 分批止盈 batch{i+1} "
                        f"+{r_thresh}R → partial_close {pct*100:.0f}%",
                        "INFO",
                    )
                    return ExitDecision(
                        action="partial_close",
                        params={"partial_pct": pct, "r_multiple": r_multiple, "batch": i + 1},
                        tp_px=current_tp_px,
                        reason=f"evolution_exit:partial_close:batch{i+1}_r{r_thresh:.0f}_pct{pct:.0%}",
                        confidence=0.7,
                    )
                else:  # +3R → trailing 剩余
                    self._log(
                        f"[EvolutionExitEngine] {symbol} 分批止盈 batch3 "
                        f"+{r_thresh}R → trailing 剩余 {pct*100:.0f}%",
                        "INFO",
                    )
                    return None  # 返回 None 让 trailing 规则接管
        return None

    def _calc_atr_adaptive_sl(
        self, entry_price: float, current_price: float,
        atr_pct: float, tier: str, pos_side: str,
        mode: str = "initial",
    ) -> float:
        """优化1: ATR 自适应止损计算

        SL = entry × (1 - ATR_mult × atr_pct)，受 floor/ceiling 约束
        mode=break_even: SL = entry_price（保本位，不随 ATR 变化）
        mode=initial: SL = entry × (1 - max(ATR_mult×atr, floor))
        """
        if mode == "break_even":
            return entry_price  # 保本位不随 ATR 变化

        if atr_pct <= 0:
            # ATR 缺失，用固定百分比兜底
            sl_pct = self.TIER_SL_PCT.get(tier, 0.03)
        else:
            atr_mult = self.ATR_SL_MULTIPLIER.get(tier, 2.5)
            sl_pct = atr_mult * atr_pct
            # 约束到 [floor, ceiling]
            floor = self.SL_FLOOR_PCT
            ceiling = self.SL_CEILING_PCT.get(tier, 0.06)
            sl_pct = max(floor, min(ceiling, sl_pct))

        if pos_side == "long":
            return entry_price * (1 - sl_pct)
        else:
            return entry_price * (1 + sl_pct)

    def _is_signal_reverse(
        self, r_vector: Dict[str, Any], pos_side: str, ess: float
    ) -> bool:
        """判断 R 向量是否与持仓方向相反 + ESS < 0.4"""
        if ess >= self.SIGNAL_REVERSE_ESS_THRESHOLD:
            return False  # ESS 足够高，不判定反转
        r_up = float(r_vector.get("R_up", 0.5) or 0.5)
        r_down = float(r_vector.get("R_down", 0.5) or 0.5)
        if pos_side == "long":
            # 多头持仓，R_down > R_up → 反转信号
            return r_down > r_up and r_down > 0.6
        else:
            # 空头持仓，R_up > R_down → 反转信号
            return r_up > r_down and r_up > 0.6
