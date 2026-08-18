#!/usr/bin/env python3
"""V4+波浪策略实盘交易执行器（独立版）

完全独立于三屏趋势系统的实盘执行器。
支持实盘下单（DRY_RUN=false），每60秒轮询一次

核心逻辑：
1. 调用 compute_v4_wave_signal 获取 V4+波浪融合信号
2. 根据信号执行开仓/平仓/加仓操作
3. 使用 AsterExecutor 进行实盘下单
"""

import os
import sys
import json
import time
import signal
import logging
from datetime import datetime, timezone
from pathlib import Path

MODULE_DIR = Path(__file__).parent.parent
PROJECT_ROOT = Path(__file__).parent.parent.parent
ENV_FILE = MODULE_DIR / ".env"
if ENV_FILE.exists():
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

TREND_SYMBOLS = os.environ.get("TREND_SYMBOLS", "BTC,ETH,SOL,UNI").split(",")
RUN_INTERVAL = int(os.environ.get("SCHEDULER_INTERVAL_SECONDS", 60))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
AUTO_EXECUTE = os.environ.get("AUTO_EXECUTE", "true").lower() == "true"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(MODULE_DIR / "logs" / "v4_wave_trader.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

sys.path.insert(0, str(MODULE_DIR))
sys.path.insert(0, str(PROJECT_ROOT / "12-三屏趋势系统"))

from v4_wave_engine import compute_v4_wave_signal

SANPING_LIVE_DIR = PROJECT_ROOT / "12-三屏趋势系统" / "live"
sys.path.insert(0, str(SANPING_LIVE_DIR.parent))
from live.aster_executor import AsterExecutor


SL_BASE_PCT = 0.04
SL_TREND_CONTINUATION_PCT = 0.06
SL_REVERSAL_PCT = 0.025
SL_LOW_CONFIDENCE_MULT = 0.7

TP_TREND_CONTINUATION_PCT = 0.15
TP_REVERSAL_PCT = 0.06
TP_TRAILING_ACTIVATE_PCT = 0.05
TP_TRAILING_CALLBACK_PCT = 0.025

WAVE_TREND_CONTINUATION = {"IMPULSE_5", "W1", "W3", "W5"}
WAVE_REVERSAL = {"CORRECTIVE_3", "W2", "W4", "ABC"}
WAVE_LOW_CONFIDENCE_THRESHOLD = 0.5


def _compute_sltp(full_signal: dict, current_price: float) -> dict:
    """根据 V4+波浪融合信号计算止盈止损

    Returns:
        {
            "stop_loss_pct": float,
            "take_profit_pct": float,
            "trailing_enabled": bool,
            "trailing_activate_pct": float,
            "trailing_callback_pct": float,
            "sltp_mode": str,
            "reason": str,
        }
    """
    final_signal = full_signal.get("final_signal", {})
    wave = final_signal.get("wave_strategy", {}) or {}
    v4 = final_signal.get("v4_strategy", {}) or {}

    wave_label = str(wave.get("wave_label", "")).upper()
    wave_conf = float(wave.get("wave_confidence", 0) or 0)
    wave_dir = str(wave.get("wave_direction", "NEUTRAL")).upper()
    v4_dir = str(v4.get("v4_direction", "NEUTRAL")).upper()

    is_trend_continuation = any(
        label in wave_label for label in WAVE_TREND_CONTINUATION
    ) or (wave_dir == "LONG" and v4_dir == "BULL")
    is_reversal = any(
        label in wave_label for label in WAVE_REVERSAL
    )

    if is_reversal:
        sl_pct = SL_REVERSAL_PCT
        tp_pct = TP_REVERSAL_PCT
        trailing_enabled = False
        mode = "reversal"
        reason = f"反转型({wave_label})：窄止损{sl_pct*100}%+固定止盈{tp_pct*100}%"
    elif is_trend_continuation:
        sl_pct = SL_TREND_CONTINUATION_PCT
        tp_pct = TP_TREND_CONTINUATION_PCT
        trailing_enabled = True
        mode = "trend_continuation"
        reason = f"趋势延续型({wave_label})：宽止损{sl_pct*100}%+移动止盈(激活{TP_TRAILING_ACTIVATE_PCT*100}%/回撤{TP_TRAILING_CALLBACK_PCT*100}%)"
    else:
        sl_pct = SL_BASE_PCT
        tp_pct = TP_TREND_CONTINUATION_PCT * 0.6
        trailing_enabled = False
        mode = "default"
        reason = f"默认模式：止损{sl_pct*100}%+止盈{tp_pct*100}%"

    if wave_conf < WAVE_LOW_CONFIDENCE_THRESHOLD and wave_conf > 0:
        sl_pct = sl_pct * SL_LOW_CONFIDENCE_MULT
        mode = mode + "_low_conf"
        reason += f" | 低置信度({wave_conf:.0%})止损收紧至{sl_pct*100:.1f}%"

    return {
        "stop_loss_pct": round(sl_pct, 4),
        "take_profit_pct": round(tp_pct, 4),
        "trailing_enabled": trailing_enabled,
        "trailing_activate_pct": TP_TRAILING_ACTIVATE_PCT,
        "trailing_callback_pct": TP_TRAILING_CALLBACK_PCT,
        "sltp_mode": mode,
        "reason": reason,
    }


class V4WaveTrader:
    def __init__(self):
        self.executor = None
        self._running = False
        self._last_positions = {}
        self._position_sltp = {}
        self._position_meta_path = MODULE_DIR / "data" / "v4_position_sltp.json"
        self._load_position_meta()

    def _load_position_meta(self):
        try:
            if self._position_meta_path.exists():
                with open(self._position_meta_path) as f:
                    self._position_sltp = json.load(f)
                logger.info(f"[SL/TP] 加载 {len(self._position_sltp)} 个持仓元数据")
        except Exception as e:
            logger.warning(f"[SL/TP] 加载元数据失败: {e}")

    def _save_position_meta(self):
        try:
            self._position_meta_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._position_meta_path, "w") as f:
                json.dump(self._position_sltp, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"[SL/TP] 保存元数据失败: {e}")

    def initialize(self):
        try:
            self.executor = AsterExecutor()
            logger.info(f"[Aster] 执行器已加载 owner={self.executor.config.owner[:14]}... dry_run={self.executor.config.dry_run}")
            if AUTO_EXECUTE and not self.executor.config.dry_run:
                logger.warning("⚠️ 实盘模式已启用，将执行真实交易")
            else:
                logger.info("模拟模式：所有交易仅记录，不实际下单")
            return True
        except Exception as e:
            logger.error(f"执行器初始化失败: {e}")
            return False

    def get_positions(self):
        try:
            if not self.executor:
                return {}
            positions = self.executor.get_positions()
            pos_dict = {}
            for pos in positions:
                coin = pos.get("coin", "")
                if coin:
                    pos_dict[coin.upper()] = pos
            return pos_dict
        except Exception as e:
            logger.error(f"获取持仓失败: {e}")
            return {}

    def run_once(self):
        logger.info(f"{'='*60}")
        logger.info(f"V4+波浪策略轮询 @ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        logger.info(f"{'='*60}")

        positions = self.get_positions()
        logger.info(f"当前持仓: {list(positions.keys())}")

        for sym, pos_data in positions.items():
            meta = self._position_sltp.get(sym)
            if not meta:
                continue
            if float(meta.get("qty", 0) or 0) <= 0:
                actual_qty = abs(float(pos_data.get("position_amt", 0) or 0))
                if actual_qty > 0:
                    meta["qty"] = actual_qty
                    logger.info(f"[SL/TP] {sym} 补全 qty={actual_qty}")
                    self._save_position_meta()
            if float(meta.get("qty", 0) or 0) > 0 and not meta.get("sl_order_id"):
                if self.executor and not self.executor.config.dry_run:
                    logger.info(f"[SL/TP] {sym} 补挂交易所 SL/TP 硬单")
                    self._sync_sltp_orders(sym, meta)

        self._check_sltp(positions)

        for sym in list(self._position_sltp.keys()):
            if sym not in positions:
                logger.info(f"[SL/TP] {sym} 已无持仓，清理元数据 + 取消残留挂单")
                try:
                    if self.executor and not self.executor.config.dry_run:
                        self.executor.cancel_symbol_orders(sym)
                except Exception as e:
                    logger.warning(f"[SL/TP] {sym} 取消残留挂单失败: {e}")
                del self._position_sltp[sym]
                self._save_position_meta()

        full_signal_map = {}
        for symbol in TREND_SYMBOLS:
            symbol_upper = symbol.upper()
            logger.info(f"\n[{symbol_upper}] 分析...")

            try:
                spot_inst = f"{symbol_upper}-USDT"
                full_signal = compute_v4_wave_signal(spot_inst, is_btc=(symbol_upper == "BTC"))
                full_signal_map[symbol_upper] = full_signal

                final_signal = full_signal.get("final_signal", {})
                action = final_signal.get("action", "WAIT")
                direction = final_signal.get("direction", "NEUTRAL")
                confidence = final_signal.get("confidence", 0)

                logger.info(f"  信号: action={action}, direction={direction}, confidence={confidence:.1f}%")

                if action in ("ENTER_LONG", "ENTER_SHORT"):
                    if symbol_upper in positions:
                        amt = float(positions[symbol_upper].get("position_amt", 0) or 0)
                        pos_side = "long" if amt > 0 else "short"
                        logger.info(f"  已持{pos_side} {symbol_upper}，跳过开仓信号（继续持有）")
                    else:
                        self._handle_entry(symbol_upper, action, direction, confidence, full_signal)
                elif action == "EXIT_LONG" or action == "EXIT_SHORT":
                    self._handle_exit(symbol_upper, action, direction)
                else:
                    logger.info(f"  无交易信号，继续持有")

            except Exception as e:
                logger.error(f"[{symbol_upper}] 分析失败: {e}")

        self._dynamic_adjust_sltp(positions, full_signal_map)

        logger.info(f"本轮轮询完成\n")

    def _check_sltp(self, positions: dict):
        if not positions:
            return

        for symbol, pos_data in positions.items():
            meta = self._position_sltp.get(symbol)
            if not meta:
                continue

            entry_px = float(meta.get("entry_px", 0))
            side = meta.get("side", "long")
            sl_pct = float(meta.get("sl_pct", 0))
            tp_pct = float(meta.get("tp_pct", 0))
            trailing_enabled = meta.get("trailing_enabled", False)
            trailing_activate = float(meta.get("trailing_activate_pct", 0))
            trailing_callback = float(meta.get("trailing_callback_pct", 0))

            mark_px = float(pos_data.get("mark_px", 0) or pos_data.get("markPrice", 0) or 0)
            if mark_px <= 0 or entry_px <= 0:
                continue

            if side == "long":
                pnl_pct = (mark_px - entry_px) / entry_px
            else:
                pnl_pct = (entry_px - mark_px) / entry_px

            if trailing_enabled and pnl_pct > 0:
                if side == "long":
                    peak_px = float(meta.get("peak_px", mark_px))
                    if mark_px > peak_px:
                        meta["peak_px"] = mark_px
                        peak_px = mark_px
                    drawdown_from_peak = (peak_px - mark_px) / peak_px
                else:
                    peak_px = float(meta.get("peak_px", mark_px))
                    if mark_px < peak_px:
                        meta["peak_px"] = mark_px
                        peak_px = mark_px
                    drawdown_from_peak = (mark_px - peak_px) / peak_px

                if pnl_pct >= trailing_activate and drawdown_from_peak >= trailing_callback:
                    logger.info(f"  [{symbol}] 🎯 移动止盈触发: pnl={pnl_pct*100:.2f}%, "
                                f"峰值回撤={drawdown_from_peak*100:.2f}% (阈值{trailing_callback*100:.1f}%)")
                    self._handle_exit(symbol, "EXIT_LONG" if side == "long" else "EXIT_SHORT",
                                      "BULL" if side == "long" else "BEAR",
                                      reason="trailing_take_profit")
                    continue
                else:
                    logger.info(f"  [{symbol}] 移动止盈监控: pnl={pnl_pct*100:.2f}%, "
                                f"峰值回撤={drawdown_from_peak*100:.2f}% "
                                f"(需pnl≥{trailing_activate*100}%且回撤≥{trailing_callback*100}%)")

            if sl_pct != 0 and pnl_pct <= -sl_pct:
                sl_desc = f"pnl≤-{sl_pct*100:.1f}%" if sl_pct > 0 else f"pnl≤+{-sl_pct*100:.1f}%(锁利润)"
                logger.info(f"  [{symbol}] 🛑 止损触发: pnl={pnl_pct*100:.2f}%, 阈值{sl_desc}")
                self._handle_exit(symbol, "EXIT_LONG" if side == "long" else "EXIT_SHORT",
                                  "BULL" if side == "long" else "BEAR",
                                  reason="stop_loss")
                continue

            if not trailing_enabled and tp_pct > 0 and pnl_pct >= tp_pct:
                logger.info(f"  [{symbol}] 🎯 止盈触发: pnl={pnl_pct*100:.2f}%, 阈值={tp_pct*100:.1f}%")
                self._handle_exit(symbol, "EXIT_LONG" if side == "long" else "EXIT_SHORT",
                                  "BULL" if side == "long" else "BEAR",
                                  reason="take_profit")
                continue

            logger.info(f"  [{symbol}] SL/TP 监控: pnl={pnl_pct*100:.2f}%, "
                        f"SL={sl_pct*100:+.1f}%, TP=+{tp_pct*100:.1f}%, mode={meta.get('sltp_mode','--')}")

        self._save_position_meta()

    def _dynamic_adjust_sltp(self, positions: dict, full_signal_map: dict):
        if not positions:
            return

        for symbol, pos_data in positions.items():
            meta = self._position_sltp.get(symbol)
            full_signal = full_signal_map.get(symbol)
            if not meta or not full_signal:
                continue

            current_price = full_signal.get("price", 0)
            if current_price <= 0:
                continue

            new_sltp = _compute_sltp(full_signal, current_price)
            old_sl = float(meta.get("sl_pct", 0))
            old_tp = float(meta.get("tp_pct", 0))
            old_mode = meta.get("sltp_mode", "")
            old_trailing = meta.get("trailing_enabled", False)

            new_sl = new_sltp["stop_loss_pct"]
            new_tp = new_sltp["take_profit_pct"]
            new_mode = new_sltp["sltp_mode"]
            new_trailing = new_sltp["trailing_enabled"]

            entry_px = float(meta.get("entry_px", 0))
            side = meta.get("side", "long")
            if entry_px <= 0:
                continue
            pnl_pct = ((current_price - entry_px) / entry_px) if side == "long" \
                      else ((entry_px - current_price) / entry_px)

            final_signal = full_signal.get("final_signal", {})
            wave = final_signal.get("wave_strategy", {}) or {}
            wave_conf = float(wave.get("wave_confidence", 0) or 0)
            wave_label = str(wave.get("wave_label", "")).upper()
            wave_dir = str(wave.get("wave_direction", "NEUTRAL")).upper()

            old_reason = meta.get("reason", "")
            old_wave_conf = float(meta.get("wave_conf_at_open", wave_conf))
            if "wave_conf_at_open" not in meta:
                meta["wave_conf_at_open"] = old_wave_conf

            risk_increasing = False
            risk_reasons = []

            if wave_conf > 0 and old_wave_conf > 0 and (old_wave_conf - wave_conf) > 0.15:
                risk_increasing = True
                risk_reasons.append(f"波浪置信度下降 {old_wave_conf:.0%}→{wave_conf:.0%}")

            old_is_reversal = any(label in old_mode.upper() for label in WAVE_REVERSAL)
            new_is_reversal = any(label in wave_label for label in WAVE_REVERSAL)
            if new_is_reversal and not old_is_reversal:
                risk_increasing = True
                risk_reasons.append(f"浪型转反转({wave_label})")

            pos_side = meta.get("side", "long")
            if (pos_side == "long" and wave_dir == "SHORT") or \
               (pos_side == "short" and wave_dir == "LONG"):
                risk_increasing = True
                risk_reasons.append(f"波浪方向({wave_dir})与持仓({pos_side})冲突")

            trend_strengthening = False
            trend_reasons = []

            if wave_conf > 0 and old_wave_conf > 0 and (wave_conf - old_wave_conf) > 0.1:
                trend_strengthening = True
                trend_reasons.append(f"波浪置信度上升 {old_wave_conf:.0%}→{wave_conf:.0%}")

            new_is_continuation = any(label in wave_label for label in WAVE_TREND_CONTINUATION)
            if new_is_continuation and "trend_continuation" not in old_mode:
                trend_strengthening = True
                transition = "反转" if old_is_reversal else "默认"
                trend_reasons.append(f"浪型{transition}→趋势延续({wave_label})")

            if pnl_pct > 0.03 and ((pos_side == "long" and wave_dir == "LONG") or \
                                    (pos_side == "short" and wave_dir == "SHORT")):
                if not risk_increasing:
                    trend_strengthening = True
                    trend_reasons.append(f"已盈利{pnl_pct*100:.1f}%+方向一致")

            adjusted_sl = old_sl
            adjusted_tp = old_tp
            adjusted_trailing = old_trailing
            adjustment_log = []

            if risk_increasing:
                if new_sl < old_sl:
                    adjusted_sl = new_sl
                    adjustment_log.append(f"SL收紧 {old_sl*100:.1f}%→{new_sl*100:.1f}%")
                if new_tp < old_tp:
                    adjusted_tp = new_tp
                    adjustment_log.append(f"TP降低 {old_tp*100:.1f}%→{new_tp*100:.1f}%")
                if old_trailing:
                    adjusted_trailing = False
                    adjustment_log.append("移动止盈关闭")
                logger.info(f"  [{symbol}] ⚠️ 风险升高: {', '.join(risk_reasons)}")
                if adjustment_log:
                    logger.info(f"  [{symbol}] SL/TP 调整(只收不松): {', '.join(adjustment_log)}")

            elif trend_strengthening and not risk_increasing:
                if new_tp > old_tp:
                    adjusted_tp = new_tp
                    adjustment_log.append(f"TP上调 {old_tp*100:.1f}%→{new_tp*100:.1f}%")
                if new_trailing and not old_trailing:
                    adjusted_trailing = True
                    adjustment_log.append("移动止盈开启")
                logger.info(f"  [{symbol}] 📈 趋势增强: {', '.join(trend_reasons)}")
                if adjustment_log:
                    logger.info(f"  [{symbol}] SL/TP 调整(放松): {', '.join(adjustment_log)}")
                else:
                    logger.info(f"  [{symbol}] 趋势增强但无需调整 SL/TP")
            else:
                pass

            if pnl_pct >= 0.05:
                if adjusted_sl > 0:
                    adjusted_sl = 0.0
                    adjustment_log.append(f"利润保护:SL锁成本价(pnl={pnl_pct*100:.1f}%)")
                if pnl_pct >= 0.08:
                    locked_sl = -0.03
                    if adjusted_sl > locked_sl:
                        adjusted_sl = locked_sl
                        adjustment_log.append(f"利润保护:SL锁3%利润(pnl={pnl_pct*100:.1f}%)")

            if adjustment_log:
                meta["sl_pct"] = adjusted_sl
                meta["tp_pct"] = adjusted_tp
                meta["trailing_enabled"] = adjusted_trailing
                meta["sltp_mode"] = new_mode + ("_risk_adj" if risk_increasing else ("_trend_adj" if trend_strengthening else ""))
                meta["last_adjusted_at"] = datetime.now(timezone.utc).isoformat()
                meta["last_adjustment"] = "; ".join(adjustment_log)
                self._save_position_meta()
                self._sync_sltp_orders(symbol, meta)
            else:
                meta["wave_conf_current"] = wave_conf
                self._save_position_meta()

    def _sync_sltp_orders(self, symbol: str, meta: dict):
        if not self.executor or self.executor.config.dry_run:
            return

        entry_px = float(meta.get("entry_px", 0) or 0)
        side = meta.get("side", "long")
        sl_pct = float(meta.get("sl_pct", 0) or 0)
        tp_pct = float(meta.get("tp_pct", 0) or 0)
        qty = float(meta.get("qty", 0) or 0)
        trailing_enabled = meta.get("trailing_enabled", False)

        if entry_px <= 0 or qty <= 0:
            logger.warning(f"  [{symbol}] 跳过挂 SL/TP 硬单: entry={entry_px}, qty={qty}")
            return

        old_sl_oid = meta.get("sl_order_id")
        old_tp_oid = meta.get("tp_order_id")
        if old_sl_oid:
            r = self.executor.cancel_order(symbol, old_sl_oid)
            if r.get("ok"):
                meta.pop("sl_order_id", None)
                meta.pop("sl_order_price", None)
        if old_tp_oid:
            r = self.executor.cancel_order(symbol, old_tp_oid)
            if r.get("ok"):
                meta.pop("tp_order_id", None)
                meta.pop("tp_order_price", None)

        if side == "long":
            sl_price = entry_px * (1 - sl_pct)
        else:
            sl_price = entry_px * (1 + sl_pct)
        sl_price = round(sl_price, 6)
        sl_r = self.executor.place_stop_loss_order(symbol, side, qty, sl_price)
        if sl_r.get("ok"):
            meta["sl_order_id"] = sl_r.get("order_id")
            meta["sl_order_price"] = sl_price
            sl_desc = f"pnl≤-{sl_pct*100:.1f}%" if sl_pct > 0 else (
                "保本" if sl_pct == 0 else f"pnl≤+{-sl_pct*100:.1f}%(锁利润)"
            )
            logger.info(f"  [{symbol}] 🛡️ 止损硬单已挂: @${sl_price} ({sl_desc}) orderId={sl_r.get('order_id')}")
        else:
            logger.error(f"  [{symbol}] ❌ 止损硬单挂单失败: {sl_r.get('error')}")

        if not trailing_enabled and tp_pct > 0:
            if side == "long":
                tp_price = entry_px * (1 + tp_pct)
            else:
                tp_price = entry_px * (1 - tp_pct)
            tp_price = round(tp_price, 6)
            tp_r = self.executor.place_take_profit_order(symbol, side, qty, tp_price)
            if tp_r.get("ok"):
                meta["tp_order_id"] = tp_r.get("order_id")
                meta["tp_order_price"] = tp_price
                logger.info(f"  [{symbol}] 🎯 止盈硬单已挂: @${tp_price} (+{tp_pct*100:.1f}%) orderId={tp_r.get('order_id')}")
            else:
                logger.error(f"  [{symbol}] ❌ 止盈硬单挂单失败: {tp_r.get('error')}")
        else:
            logger.info(f"  [{symbol}] 移动止盈模式: TP 由程序端追踪，不挂硬止盈单")

        self._save_position_meta()

    def _handle_entry(self, symbol, action, direction, confidence, full_signal):
        if not AUTO_EXECUTE:
            logger.info(f"  [模拟] AUTO_EXECUTE=false，跳过开仓")
            return

        try:
            current_price = full_signal.get("price", 0)
            if not current_price:
                logger.warning(f"  当前价格未知，跳过开仓")
                return

            position_pct = full_signal.get("final_signal", {}).get("position", {}).get("position_pct", 0.05)
            leverage = full_signal.get("final_signal", {}).get("leverage", 3)

            pos_side = "long" if direction == "BULL" else "short"
            notional_usd = self._calc_notional(symbol, position_pct)

            if notional_usd < 5:
                logger.warning(f"  名义价值 ${notional_usd:.2f} < 最小$5，跳过")
                return

            sltp = _compute_sltp(full_signal, current_price)
            logger.info(f"  开仓: {pos_side} {symbol} @ ${current_price:.2f}, 名义价值=${notional_usd:.2f}, 杠杆={leverage}x")
            logger.info(f"  [SL/TP] 模式={sltp['sltp_mode']}: {sltp['reason']}")
            logger.info(f"  [SL/TP] 止损=-{sltp['stop_loss_pct']*100:.1f}%, 止盈=+{sltp['take_profit_pct']*100:.1f}%, "
                        f"移动止盈={'开' if sltp['trailing_enabled'] else '关'}")

            result = self.executor.place_market_order(
                coin=symbol,
                side=pos_side,
                notional_usd=notional_usd,
                leverage=leverage
            )

            if result.get("ok"):
                logger.info(f"  ✅ 开仓成功: {result}")
                actual_qty = 0.0
                try:
                    fresh_positions = self.get_positions()
                    pos_data = fresh_positions.get(symbol, {})
                    actual_qty = abs(float(pos_data.get("position_amt", 0) or 0))
                except Exception as e:
                    logger.warning(f"  查询实际持仓数量失败: {e}")
                    actual_qty = float(result.get("quantity", 0) or 0)
                self._position_sltp[symbol] = {
                    "entry_px": current_price,
                    "side": pos_side,
                    "qty": actual_qty,
                    "sl_pct": sltp["stop_loss_pct"],
                    "tp_pct": sltp["take_profit_pct"],
                    "trailing_enabled": sltp["trailing_enabled"],
                    "trailing_activate_pct": sltp["trailing_activate_pct"],
                    "trailing_callback_pct": sltp["trailing_callback_pct"],
                    "sltp_mode": sltp["sltp_mode"],
                    "reason": sltp["reason"],
                    "peak_px": current_price,
                    "opened_at": datetime.now(timezone.utc).isoformat(),
                    "leverage": leverage,
                    "notional_usd": notional_usd,
                }
                self._save_position_meta()
                self._sync_sltp_orders(symbol, self._position_sltp[symbol])
            else:
                logger.error(f"  ❌ 开仓失败: {result.get('err', '未知错误')}")

        except Exception as e:
            logger.error(f"  开仓执行失败: {e}")

    def _handle_exit(self, symbol, action, direction, reason=None):
        if not AUTO_EXECUTE:
            logger.info(f"  [模拟] AUTO_EXECUTE=false，跳过平仓")
            return

        try:
            exit_label = f"（原因: {reason}）" if reason else ""
            logger.info(f"  平仓: {symbol}{exit_label}")
            result = self.executor.close_position(coin=symbol)

            if result.get("ok"):
                logger.info(f"  ✅ 平仓成功: {result}")
                try:
                    self.executor.cancel_symbol_orders(symbol)
                except Exception as e:
                    logger.warning(f"  取消 SL/TP 挂单失败: {e}")
                if symbol in self._position_sltp:
                    del self._position_sltp[symbol]
                    self._save_position_meta()
            else:
                logger.error(f"  ❌ 平仓失败: {result.get('err', '未知错误')}")

        except Exception as e:
            logger.error(f"  平仓执行失败: {e}")

    def _calc_notional(self, symbol, position_pct):
        try:
            balance = self.executor.get_balance("USDT")
            available = self.executor.get_available_balance("USDT")
            max_position_pct = float(os.environ.get("MAX_POSITION_PCT", 25)) / 100
            effective_pct = min(position_pct, max_position_pct)
            return available * effective_pct
        except Exception:
            initial_capital = float(os.environ.get("INITIAL_CAPITAL", 200))
            return initial_capital * position_pct

    def run_forever(self):
        self._running = True

        def signal_handler(sig, frame):
            logger.info("\n接收到停止信号，正在退出...")
            self._running = False

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        logger.info(f"V4+波浪策略实盘执行器启动（独立版）")
        logger.info(f"交易对: {TREND_SYMBOLS}")
        logger.info(f"轮询间隔: {RUN_INTERVAL}秒")
        logger.info(f"自动执行: {AUTO_EXECUTE}")
        logger.info(f"按 Ctrl+C 停止...\n")

        while self._running:
            try:
                self.run_once()
                for _ in range(RUN_INTERVAL):
                    if not self._running:
                        break
                    time.sleep(1)
            except Exception as e:
                logger.error(f"运行异常: {e}")
                time.sleep(10)

        logger.info("执行器已停止")


def main():
    trader = V4WaveTrader()

    if not trader.initialize():
        logger.error("初始化失败，退出")
        sys.exit(1)

    trader.run_forever()


if __name__ == "__main__":
    main()
