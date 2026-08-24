"""
shadow-mode 全局闸门 单元测试（BLOCKED-OPEN 验证）

设计口径：
  当 shadow_mode=True 时，PollingTrader._open_position(inference) 必须：
    1. 记录一条 WARN 级 "[SHADOW MODE BLOCKED-OPEN]" 日志
    2. 在日志打印完后 **立刻 return**，绝对不能执行任何下游真实下单
       包括：okx_client.get_balance / get_positions / _usdt_to_sz /
             market_open_long / market_open_short 全部 0 次调用
    3. 与 direction=UP / DOWN 无关（多空都必须拦截）
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ── 确保可以导入目标模块（与 test_strategy_algo_stage1 同口径） ─────────────────────────
import os as _os
import sys as _sys
_PROJECT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
_ROOT = _os.path.dirname(_PROJECT)
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))


def _make_bare_trader(shadow_mode: bool):
    """用 __new__ 绕过 __init__，仅注入 _open_position 闸门 + 下游依赖所需最小属性。

    这样不会触发真实 bcrm 模型加载、OKX 连接初始化等重型逻辑。
    """
    from scripts.memory_l4.polling_trader import PollingTrader

    t = PollingTrader.__new__(PollingTrader)

    # ── 闸门用属性（测试核心目标） ──────────────────────────────────────────────────────────
    t.shadow_mode = bool(shadow_mode)

    # ── 日志 spy：将 self._log 调用收集到 list ───────────────────────────────────────────
    t.logs: list[tuple[str, str]] = []

    def _log_spy(msg: str, level: str = "INFO"):
        t.logs.append((str(msg), str(level)))

    t._log = _log_spy

    # ── okx_client：所有方法都是 MagicMock，调用次数可以断言 0 ────────────────────────────────
    t.okx_client = MagicMock()
    t.okx_client.cfg = {"default_leverage": 3, "td_mode": "isolated"}
    t.okx_client.get_balance.return_value = {
        "ok": True, "total_eq": 1293.71,
        "assets": {"USDT": {"avail": 1293.71}},
    }
    t.okx_client.get_positions.return_value = {"ok": True, "positions": []}
    t.okx_client._usdt_to_sz.return_value = 123  # 随便 >0，表示最小合约单位通过
    t.okx_client.market_open_long.return_value = {"ok": True, "ord_id": "shadow-mock-long-42", "estimated_price": 60000.0, "dry_run": False}
    t.okx_client.market_open_short.return_value = {"ok": True, "ord_id": "shadow-mock-short-42", "estimated_price": 60000.0, "dry_run": False}
    t.okx_client.place_stop_loss_take_profit.return_value = {"ok": True}

    # ── 性能 / 风控 tracker（下游要用到 current_equity / calc_position_size） ─────────────────
    perf_tracker = SimpleNamespace(current_equity=1293.71)
    risk_mgr = MagicMock()
    risk_mgr.calc_position_size.return_value = {
        "position_usdt": 181.12,
        "position_pct": 0.14,
        "confidence_factor": 1.0,
        "reason": "unit-test-reason",
    }
    t.perf_tracker = perf_tracker
    t.risk_manager = risk_mgr
    t.guardian = None  # 下游 if self.guardian 分支，None → 跳过

    # position tracker + 轻量开仓事件：MagicMock 即可（我们只关心调用发生，不验证返回）
    t.position_tracker = MagicMock()
    t._record_opening_event = MagicMock()
    t._last_volatility = 0.03  # H2

    # 其他可选辅助方法：保持 MagicMock，不重要（只要不被执行就 0 次调用）
    t._compute_p2_dynamic_sizing_factors = MagicMock(return_value={
        "kelly_factor": 1.0, "consecutive_loss_factor": 1.0,
        "hexagram_factor": 1.0, "vol_regime_factor": 1.0,
        "hexagram_class": "NEUTRAL", "win_rate": 0.5,
        "avg_win": 1.0, "avg_loss": 1.0, "loss_streak": 0,
        "vol_regime_class": "MID", "vol_adaptive_sl_mult": 2.5,
        "vol_adaptive_tp_mult": 5.0, "p2_base_multiplier": 1.0,
    })
    t._compute_short_position_multiplier = MagicMock(return_value=1.0)
    t._compute_long_position_multiplier = MagicMock(return_value=1.0)
    t._price_change_to_roi = MagicMock(return_value=0.075)
    t._calc_sl_price = MagicMock(return_value=0.0)
    t._calc_tp_price = MagicMock(return_value=0.0)

    # 战略层 / 策略层：None，不需要注入
    t._strategy_algo_layer = None
    t._five_domain_state_cache = None
    t.US_STOCK_COINS = {"AAPL", "TSLA", "GOOGL"}

    # 资金调控（下游需要用到 _apply_capital_control_to_position）：原样透传
    t._apply_capital_control_to_position = MagicMock(side_effect=lambda coin, pos, eq: (pos, "ok"))

    return t


# ── inference 最小化构造：只放闸门会直接读取的键 + 后续会用到的键 ───────────────────────────
def _make_inference(direction: str) -> dict:
    price = 60000.0
    if direction == "UP":
        sl, tp = price * 0.975, price * 1.05
    else:
        sl, tp = price * 1.025, price * 0.95
    return {
        "coin": "BTC",
        "inst_id": "BTC-USDT-SWAP",
        "direction": direction,
        "confidence": 0.88,
        "volatility": 0.031,
        "hexagram": "qian",
        "reason": "unit-test-fake-inference-42",
        "stop_loss_px": sl,
        "take_profit_px": tp,
        "price": price,
        "risk_level": "NORMAL",
        "leverage_factor": 1.0,
        "position_factor": 1.0,
        "sl_tighten_factor": 1.0,
        "tp_adjustment": 1.0,
        "spring_bearish_score": "NONE",
        "spring_bullish_score": "NONE",
        "_regime_multipliers": {"position_mult": 1.0, "sl_mult": 1.0, "tp_mult": 1.0},
        "_regime_pred": "TRENDING_UP",
        "enhance_result": None,
    }


class TestShadowGateBlockedOpen:
    """shadow=True 时必须拦截所有真实下游调用（闸门在函数头，L7354-7365）。"""

    # ── 1) UP ───────────────────────────────────────────────────────────────────────────
    def test_shadow_true_UP_writes_BLOCKED_OPEN_warn_log(self):
        t = _make_bare_trader(shadow_mode=True)
        inf = _make_inference("UP")

        ret = t._open_position(inf)

        # 立刻 return，返回值 None（函数没有 return anything else when return explicit None）
        assert ret is None, "闸门应该立刻 return None，不进入下游"
        msgs = [m for m, _lv in t.logs]
        levels = [lv for _, lv in t.logs]
        any_blocked = any("SHADOW MODE BLOCKED-OPEN" in m for m in msgs)
        assert any_blocked, f"必须包含 BLOCKED-OPEN 日志，实际日志={msgs}"
        # BLOCKED 日志级别必须是 WARN（高可见性，避免淹没在 INFO 里）
        blocked_level = [lv for m, lv in t.logs if "SHADOW MODE BLOCKED-OPEN" in m]
        assert blocked_level == ["WARN"], f"BLOCKED 日志级别必须是 WARN，实际={blocked_level}"
        # 方向/币种必须被正确打印
        assert any("BTC-USDT-SWAP" in m and "UP" in m for m in msgs), f"日志未包含币种/方向信息：{msgs}"

    def test_shadow_true_UP_calls_zero_downstream_methods(self):
        t = _make_bare_trader(shadow_mode=True)
        inf = _make_inference("UP")

        t._open_position(inf)

        # 关键真实副作用方法：0 次调用
        c = t.okx_client
        assert c.market_open_long.call_count == 0, "shadow=True 不能调 market_open_long"
        assert c.market_open_short.call_count == 0, "shadow=True 不能调 market_open_short"
        # 更严格：闸门必须在 get_balance / _usdt_to_sz / calc / 风控之前 return
        assert c.get_balance.call_count == 0, "闸门在 get_balance 之前，0 次才对"
        assert c.get_positions.call_count == 0
        assert c._usdt_to_sz.call_count == 0
        assert t.risk_manager.calc_position_size.call_count == 0
        assert t._compute_p2_dynamic_sizing_factors.call_count == 0
        assert t._apply_capital_control_to_position.call_count == 0

    # ── 2) DOWN（多空对称） ───────────────────────────────────────────────────────────────
    def test_shadow_true_DOWN_writes_BLOCKED_OPEN_warn_log(self):
        t = _make_bare_trader(shadow_mode=True)
        inf = _make_inference("DOWN")

        ret = t._open_position(inf)

        assert ret is None
        msgs = [m for m, _ in t.logs]
        assert any("SHADOW MODE BLOCKED-OPEN" in m for m in msgs), f"实际日志={msgs}"
        blocked_level = [lv for m, lv in t.logs if "SHADOW MODE BLOCKED-OPEN" in m]
        assert blocked_level == ["WARN"]
        assert any("BTC-USDT-SWAP" in m and "DOWN" in m for m in msgs), f"日志未包含DOWN信息：{msgs}"

    def test_shadow_true_DOWN_calls_zero_downstream_methods(self):
        t = _make_bare_trader(shadow_mode=True)
        inf = _make_inference("DOWN")

        t._open_position(inf)

        c = t.okx_client
        assert c.market_open_short.call_count == 0, "shadow=True 不能调 market_open_short"
        assert c.market_open_long.call_count == 0
        assert c.get_balance.call_count == 0
        assert c._usdt_to_sz.call_count == 0
        assert t.risk_manager.calc_position_size.call_count == 0
        assert t._apply_capital_control_to_position.call_count == 0

    # ── 3) 反向 sanity：shadow=False 时闸门不生效，允许走到 get_balance ─────────────────────
    #    （下游真实下单会被 mock 的 market_open_long 捕获，不需要真交易所返回）
    def test_shadow_FALSE_does_NOT_block_so_risk_calc_is_called(self):
        t = _make_bare_trader(shadow_mode=False)
        inf = _make_inference("UP")
        # 最小化：让 _calc_sl / _calc_tp 返回正数，避免进入"无 sl/tp 保护"的跳过分支
        t._calc_sl_price.return_value = 58500.0
        t._calc_tp_price.return_value = 63000.0

        t._open_position(inf)

        # 关键：闸门不生效 → 风控 & get_balance 必须至少 1 次
        assert t.risk_manager.calc_position_size.call_count >= 1, (
            "shadow=False 闸门不生效，应走到 calc_position_size"
        )
        assert t.okx_client.get_balance.call_count >= 1
