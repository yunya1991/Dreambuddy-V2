"""Aster 执行器 — 趋势策略专用

用途：
    12-三屏趋势系统 独立 aster 环境的下单执行模块，
    与 ab-trading 的 Hyperliquid/OKX 链路隔离。

核心功能：
    - 加载 12-三屏趋势系统/.env 中的 aster 凭证
    - 封装 ml_trade_service 的下单接口
    - 支持市价单、止盈止损单
    - 账户与持仓查询

调用方式：
    from live.aster_executor import AsterExecutor

    executor = AsterExecutor()
    result = executor.place_market_order("BTC", "long", 10.0)  # 10 USDT 名义价值
    pos = executor.get_positions()

文件: 12-三屏趋势系统/live/aster_executor.py
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone

# 加载 12-三屏趋势系统/.env
ENV_FILE = Path(__file__).parent.parent / ".env"
if ENV_FILE.exists():
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# 导入 ml_trade_service（共享 aster v3 EVM 签名逻辑）
ML_SERVICE_PATH = Path(__file__).parent.parent.parent / "10-经典指标系统"
if str(ML_SERVICE_PATH) not in sys.path:
    sys.path.insert(0, str(ML_SERVICE_PATH))

# L4 TradeEvent 注册（跨系统统一交易记录）
try:
    _L4_ROOT = Path(__file__).resolve().parents[2] / "11-易经推理系统"
    if str(_L4_ROOT) not in sys.path:
        sys.path.insert(0, str(_L4_ROOT))
    from scripts.memory_l4.trade_event import TradeEvent
    from scripts.memory_l4.case_registry import UnifiedCaseRegistry
    _L4_ENABLED = True
except Exception as _e:
    _L4_ENABLED = False

try:
    import ml_trade_service as _ml
    ML_AVAILABLE = True
except ImportError as e:
    ML_AVAILABLE = False
    _ml = None
    logging.warning(f"[aster_executor] ml_trade_service 加载失败: {e}")

logger = logging.getLogger(__name__)


@dataclass
class AsterConfig:
    """Aster 执行器配置"""
    owner: str = None
    signer: str = None
    private_key: str = None
    dry_run: bool = True
    default_leverage: int = 3
    max_position_pct: float = 0.25
    min_notional_usd: float = 5.0

    def __post_init__(self):
        if self.owner is None:
            self.owner = os.environ.get("ASTER_USER", "")
        if self.signer is None:
            self.signer = os.environ.get("ASTER_SIGNER", "")
        if self.private_key is None:
            self.private_key = os.environ.get("ASTER_SIGNER_PRIVATE_KEY", "")
        if os.environ.get("DRY_RUN", "true").lower() == "false":
            self.dry_run = False


class AsterExecutor:
    """Aster 执行器

    封装 ml_trade_service 的下单接口，专门为 12-三屏趋势系统 设计。
    """

    def __init__(self, config: AsterConfig = None):
        self.config = config or AsterConfig()
        self._ml = _ml

        if not ML_AVAILABLE:
            raise RuntimeError("ml_trade_service 未加载，无法执行 aster 交易")

        # 验证凭证
        if not self.config.owner or not self.config.signer or not self.config.private_key:
            raise ValueError("缺少 aster 凭证（ASTER_USER/SIGNER/PRIVATE_KEY）")

        logger.info(f"[AsterExecutor] 初始化完成 owner={self.config.owner[:10]}... dry_run={self.config.dry_run}")

    def _register_trade_to_l4(self, coin: str, side: str, entry_px: float, exit_px: float,
                              qty: float, pnl: float, exit_reason: str, leverage: int = 3,
                              screen_signals: Dict = None):
        """将三屏趋势策略交易记录注册到 L4 统一案例库"""
        if not _L4_ENABLED:
            return None, False
        try:
            trade_id = f"three_screen_{int(datetime.now(timezone.utc).timestamp())}_{coin}"
            event = TradeEvent(
                event_id=TradeEvent.generate_event_id(),
                system_source="three_screen",
                trade_id=trade_id,
                ts_entry=datetime.now(timezone.utc).isoformat(),
                ts_exit=datetime.now(timezone.utc).isoformat(),
                symbol=f"{coin}-USDT-SWAP",
                direction=side.lower(),
                entry_price=entry_px,
                exit_price=exit_px,
                position_size=qty,
                pnl=pnl,
                pnl_pct=(pnl / (entry_px * qty) * 100) if entry_px > 0 and qty > 0 else 0,
                exit_reason=exit_reason,
                decision_context={
                    "screen_signals": screen_signals or {},
                    "strategy_type": "three_screen_trend",
                },
                leverage=leverage,
            )
            registry = UnifiedCaseRegistry()
            case_id, success = registry.register_trade_event(event)
            if success:
                logger.info(f"[{coin}] L4 案例已注册: {case_id}")
            else:
                logger.warning(f"[{coin}] L4 案例注册失败")
            return case_id, success
        except Exception as e:
            logger.error(f"[{coin}] L4 注册异常: {e}")
            return None, False

    # ─────────────────────────────────────────────────────────────
    # 账户查询
    # ─────────────────────────────────────────────────────────────

    def get_account_summary(self) -> Dict[str, Any]:
        """获取账户摘要"""
        try:
            os.environ["ASTER_USER"] = self.config.owner
            os.environ["ASTER_SIGNER"] = self.config.signer
            os.environ["ASTER_SIGNER_PRIVATE_KEY"] = self.config.private_key
            r = self._ml._aster_fetch_account_summary(owner=self.config.owner)
            return r
        except Exception as e:
            logger.error(f"[AsterExecutor] 账户查询失败: {e}")
            return {"ok": False, "error": str(e)}

    def get_balance(self, asset: str = "USDT") -> Optional[float]:
        """获取指定资产余额"""
        summary = self.get_account_summary()
        if not summary.get("ok"):
            return None

        assets = summary.get("assets", {})
        asset_info = assets.get(asset, {})
        return float(asset_info.get("walletBalance", 0) or 0)

    def get_available_balance(self, asset: str = "USDT") -> Optional[float]:
        """获取可用余额"""
        summary = self.get_account_summary()
        if not summary.get("ok"):
            return None

        assets = summary.get("assets", {})
        asset_info = assets.get(asset, {})
        return float(asset_info.get("availableBalance", 0) or 0)

    def get_positions(self) -> List[Dict[str, Any]]:
        """获取当前持仓"""
        try:
            os.environ["ASTER_USER"] = self.config.owner
            os.environ["ASTER_SIGNER"] = self.config.signer
            os.environ["ASTER_SIGNER_PRIVATE_KEY"] = self.config.private_key
            positions, _ = self._ml._aster_fetch_positions(owner=self.config.owner)
            return positions or []
        except Exception as e:
            logger.error(f"[AsterExecutor] 持仓查询失败: {e}")
            return []

    # ─────────────────────────────────────────────────────────────
    # 下单接口
    # ─────────────────────────────────────────────────────────────

    def place_market_order(
        self,
        coin: str,
        side: str,
        notional_usd: float,
        reduce_only: bool = False,
        leverage: int = None,
    ) -> Dict[str, Any]:
        """市价单（按名义金额）

        Args:
            coin: 币种符号（如 BTC）
            side: 方向（long/short/buy/sell）
            notional_usd: 名义价值（USDT）
            reduce_only: 是否仅减仓
            leverage: 杠杆（可选）

        Returns:
            {
                "ok": bool,
                "symbol": str,
                "side": str,
                "quantity": float,
                "reduce_only": bool,
                "resp": dict,
                "error": str (if failed)
            }
        """
        if self.config.dry_run:
            logger.info(f"[AsterExecutor] [DRY_RUN] 市价单 {coin} {side} ${notional_usd:.2f}")
            return {
                "ok": True,
                "dry_run": True,
                "symbol": f"{coin}USDT",
                "side": side,
                "notional_usd": notional_usd,
                "reduce_only": reduce_only,
            }

        try:
            # 设置杠杆（如果指定）
            if leverage:
                self._set_leverage(coin, leverage)

            # 下单
            result = self._ml._aster_market_order(
                coin=coin,
                side=side,
                notional_usd=float(notional_usd),
                reduce_only=bool(reduce_only),
                allow_adjust=True,
                owner=self.config.owner,
            )

            logger.info(f"[AsterExecutor] 市价单成功 {coin} {side} ${notional_usd:.2f} qty={result.get('quantity')}")
            return {"ok": True, **result}

        except Exception as e:
            logger.error(f"[AsterExecutor] 市价单失败: {e}")
            return {"ok": False, "error": str(e)}

    def place_market_order_qty(
        self,
        coin: str,
        side: str,
        qty: float,
        reduce_only: bool = False,
        leverage: int = None,
    ) -> Dict[str, Any]:
        """市价单（按数量）

        Args:
            coin: 币种符号
            side: 方向
            qty: 数量（张数或币数）
            reduce_only: 是否仅减仓
            leverage: 杠杆（可选）

        Returns:
            同 place_market_order
        """
        if self.config.dry_run:
            logger.info(f"[AsterExecutor] [DRY_RUN] 市价单 {coin} {side} qty={qty}")
            return {
                "ok": True,
                "dry_run": True,
                "symbol": f"{coin}USDT",
                "side": side,
                "quantity": qty,
                "reduce_only": reduce_only,
            }

        try:
            if leverage:
                self._set_leverage(coin, leverage)

            result = self._ml._aster_market_order_qty(
                coin=coin,
                side=side,
                qty=float(qty),
                reduce_only=bool(reduce_only),
                owner=self.config.owner,
            )

            logger.info(f"[AsterExecutor] 市价单成功 {coin} {side} qty={qty}")
            return {"ok": True, **result}

        except Exception as e:
            logger.error(f"[AsterExecutor] 市价单失败: {e}")
            return {"ok": False, "error": str(e)}

    def close_position(self, coin: str, side: str = None) -> Dict[str, Any]:
        """平仓

        Args:
            coin: 币种符号
            side: 方向（可选，默认自动检测）

        Returns:
            {"ok": bool, "closed_qty": float, "error": str (if failed)}
        """
        try:
            # 获取当前持仓
            positions = self.get_positions()
            target_pos = None
            for pos in positions:
                if pos.get("coin", "").upper() == coin.upper():
                    target_pos = pos
                    break

            if not target_pos:
                return {"ok": False, "error": f"无 {coin} 持仓"}

            pos_qty = float(target_pos.get("position_amt", 0) or 0)
            if abs(pos_qty) < 1e-8:
                return {"ok": False, "error": f"{coin} 持仓数量为 0"}

            # 确定平仓方向
            close_side = "sell" if pos_qty > 0 else "buy"
            if side:
                close_side = side

            entry_px = float(target_pos.get("entry_px", 0) or 0)
            exit_px = float(target_pos.get("mark_px", 0) or target_pos.get("current_price", 0) or 0)
            pnl = (exit_px - entry_px) * abs(pos_qty) * (1 if pos_qty > 0 else -1) if entry_px > 0 else 0

            if self.config.dry_run:
                logger.info(f"[AsterExecutor] [DRY_RUN] 平仓 {coin} {close_side} qty={abs(pos_qty)}")
                # dry_run 也注册到 L4（用于测试验证）
                self._register_trade_to_l4(
                    coin=coin, side="long" if pos_qty > 0 else "short",
                    entry_px=entry_px, exit_px=exit_px,
                    qty=abs(pos_qty), pnl=pnl,
                    exit_reason="dry_run_close",
                    leverage=self.config.default_leverage,
                )
                return {"ok": True, "dry_run": True, "closed_qty": abs(pos_qty)}

            # 执行平仓
            result = self._ml._aster_market_order_qty(
                coin=coin,
                side=close_side,
                qty=abs(pos_qty),
                reduce_only=True,
                owner=self.config.owner,
            )

            # 注册到 L4
            self._register_trade_to_l4(
                coin=coin, side="long" if pos_qty > 0 else "short",
                entry_px=entry_px, exit_px=exit_px,
                qty=abs(pos_qty), pnl=pnl,
                exit_reason="close_position",
                leverage=self.config.default_leverage,
            )

            logger.info(f"[AsterExecutor] 平仓成功 {coin} {close_side} qty={abs(pos_qty)}")
            return {"ok": True, "closed_qty": abs(pos_qty), **result}

        except Exception as e:
            logger.error(f"[AsterExecutor] 平仓失败: {e}")
            return {"ok": False, "error": str(e)}

    def _set_leverage(self, coin: str, leverage: int):
        """设置杠杆"""
        try:
            self._ml._aster_update_leverage(coin, int(leverage), owner=self.config.owner)
            logger.info(f"[AsterExecutor] 杠杆设置 {coin} -> {leverage}x")
        except Exception as e:
            logger.warning(f"[AsterExecutor] 杠杆设置失败: {e}")

    # ─────────────────────────────────────────────────────────────
    # 止盈止损硬单（交易所级别）
    # ─────────────────────────────────────────────────────────────

    def place_stop_loss_order(self, coin: str, position_side: str, qty: float,
                               stop_price: float) -> Dict[str, Any]:
        """挂止损单（STOP_MARKET, reduceOnly）

        Args:
            coin: 币种（如 BTC）
            position_side: 持仓方向（long/short）
            qty: 数量（正数）
            stop_price: 止损触发价

        Returns:
            {"ok": bool, "order_id": int, "resp": dict, ...}
        """
        if self.config.dry_run:
            logger.info(f"[AsterExecutor] [DRY_RUN] 止损单 {coin} pos={position_side} qty={qty} @ {stop_price}")
            return {"ok": True, "dry_run": True, "coin": coin, "stop_price": stop_price}

        # 持仓方向 → 平仓方向
        close_side = "sell" if position_side.lower() == "long" else "buy"
        try:
            os.environ["ASTER_USER"] = self.config.owner
            os.environ["ASTER_SIGNER"] = self.config.signer
            os.environ["ASTER_SIGNER_PRIVATE_KEY"] = self.config.private_key
            result = self._ml._aster_stop_market_order_qty(
                coin=str(coin),
                side=close_side,
                qty=float(abs(qty)),
                stop_price=float(stop_price),
                reduce_only=True,
                owner=self.config.owner,
            )
            order_id = None
            try:
                resp = result.get("resp", {}) or {}
                if isinstance(resp, dict):
                    order_id = resp.get("orderId")
            except Exception:
                pass
            logger.info(f"[AsterExecutor] 止损单成功 {coin} {close_side} qty={qty} @ {stop_price} orderId={order_id}")
            return {"ok": True, "order_id": order_id, "coin": coin, **result}
        except Exception as e:
            logger.error(f"[AsterExecutor] 止损单失败: {e}")
            return {"ok": False, "error": str(e)}

    def place_take_profit_order(self, coin: str, position_side: str, qty: float,
                                 trigger_price: float) -> Dict[str, Any]:
        """挂止盈单（TAKE_PROFIT_MARKET, reduceOnly）

        Args:
            coin: 币种
            position_side: 持仓方向（long/short）
            qty: 数量
            trigger_price: 止盈触发价

        Returns:
            {"ok": bool, "order_id": int, ...}
        """
        if self.config.dry_run:
            logger.info(f"[AsterExecutor] [DRY_RUN] 止盈单 {coin} pos={position_side} qty={qty} @ {trigger_price}")
            return {"ok": True, "dry_run": True, "coin": coin, "trigger_price": trigger_price}

        close_side = "sell" if position_side.lower() == "long" else "buy"
        try:
            os.environ["ASTER_USER"] = self.config.owner
            os.environ["ASTER_SIGNER"] = self.config.signer
            os.environ["ASTER_SIGNER_PRIVATE_KEY"] = self.config.private_key
            result = self._ml._aster_take_profit_market_order_qty(
                coin=str(coin),
                side=close_side,
                qty=float(abs(qty)),
                trigger_price=float(trigger_price),
                reduce_only=True,
                owner=self.config.owner,
            )
            order_id = None
            try:
                resp = result.get("resp", {}) or {}
                if isinstance(resp, dict):
                    order_id = resp.get("orderId")
            except Exception:
                pass
            logger.info(f"[AsterExecutor] 止盈单成功 {coin} {close_side} qty={qty} @ {trigger_price} orderId={order_id}")
            return {"ok": True, "order_id": order_id, "coin": coin, **result}
        except Exception as e:
            logger.error(f"[AsterExecutor] 止盈单失败: {e}")
            return {"ok": False, "error": str(e)}

    def cancel_order(self, coin: str, order_id: int) -> Dict[str, Any]:
        """取消挂单"""
        if self.config.dry_run:
            return {"ok": True, "dry_run": True}
        if not order_id:
            return {"ok": True, "skipped": "no_order_id"}
        try:
            os.environ["ASTER_USER"] = self.config.owner
            os.environ["ASTER_SIGNER"] = self.config.signer
            os.environ["ASTER_SIGNER_PRIVATE_KEY"] = self.config.private_key
            sym = self._ml._aster_symbol_from_coin(str(coin))
            self._ml._aster_order_cancel(symbol=sym, order_id=order_id, owner=self.config.owner)
            logger.info(f"[AsterExecutor] 取消挂单 {coin} orderId={order_id}")
            return {"ok": True, "coin": coin, "order_id": order_id}
        except Exception as e:
            logger.error(f"[AsterExecutor] 取消挂单失败 {coin} orderId={order_id}: {e}")
            return {"ok": False, "error": str(e)}

    def fetch_open_orders(self, coin: str = None) -> List[Dict[str, Any]]:
        """查询挂单（可选币种过滤）"""
        if self.config.dry_run:
            return []
        try:
            os.environ["ASTER_USER"] = self.config.owner
            os.environ["ASTER_SIGNER"] = self.config.signer
            os.environ["ASTER_SIGNER_PRIVATE_KEY"] = self.config.private_key
            orders, _ = self._ml._aster_fetch_open_orders(owner=self.config.owner)
            if not orders:
                return []
            if coin:
                target_sym = self._ml._aster_symbol_from_coin(str(coin)).upper()
                orders = [o for o in orders if str(o.get("symbol", "")).upper() == target_sym]
            return orders or []
        except Exception as e:
            logger.error(f"[AsterExecutor] 查询挂单失败: {e}")
            return []

    def cancel_symbol_orders(self, coin: str) -> Dict[str, Any]:
        """取消某币种的所有挂单（便利方法）

        Returns:
            {"ok": bool, "canceled": int, "failed": int}
        """
        if self.config.dry_run:
            return {"ok": True, "dry_run": True, "canceled": 0, "failed": 0}
        orders = self.fetch_open_orders(coin=coin)
        canceled = 0
        failed = 0
        for o in orders:
            oid = o.get("orderId")
            if oid is None:
                continue
            r = self.cancel_order(coin, oid)
            if r.get("ok"):
                canceled += 1
            else:
                failed += 1
        logger.info(f"[AsterExecutor] 批量取消 {coin} 挂单: 成功{canceled} 失败{failed}")
        return {"ok": failed == 0, "canceled": canceled, "failed": failed}

    # ─────────────────────────────────────────────────────────────
    # 辅助方法
    # ─────────────────────────────────────────────────────────────

    def get_position_for_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取指定币种的持仓"""
        positions = self.get_positions()
        for pos in positions:
            if pos.get("coin", "").upper() == symbol.upper():
                return pos
        return None

    def has_position(self, symbol: str) -> bool:
        """检查是否有持仓"""
        pos = self.get_position_for_symbol(symbol)
        if pos:
            qty = float(pos.get("position_amt", 0) or 0)
            return abs(qty) > 1e-8
        return False

    def get_position_side(self, symbol: str) -> Optional[str]:
        """获取持仓方向"""
        pos = self.get_position_for_symbol(symbol)
        if not pos:
            return None
        qty = float(pos.get("position_amt", 0) or 0)
        if abs(qty) < 1e-8:
            return None
        return "LONG" if qty > 0 else "SHORT"


# ─────────────────────────────────────────────────────────────
# CLI 测试入口
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Aster 执行器测试")
    parser.add_argument("action", choices=["balance", "positions", "open", "close"], help="操作类型")
    parser.add_argument("--coin", default="BTC", help="币种")
    parser.add_argument("--side", default="long", help="方向")
    parser.add_argument("--notional", type=float, default=5.0, help="名义价值（USDT）")
    parser.add_argument("--leverage", type=int, default=3, help="杠杆")
    parser.add_argument("--live", action="store_true", help="实盘下单（默认 dry_run）")

    args = parser.parse_args()

    # 配置
    config = AsterConfig(dry_run=not args.live)

    try:
        executor = AsterExecutor(config)

        if args.action == "balance":
            balance = executor.get_balance("USDT")
            available = executor.get_available_balance("USDT")
            print(f"USDT 余额: {balance:.2f}")
            print(f"USDT 可用: {available:.2f}")

        elif args.action == "positions":
            positions = executor.get_positions()
            print(f"持仓数: {len(positions)}")
            for pos in positions:
                print(f"  {pos.get('coin')}: {pos.get('position_amt')} @ {pos.get('entry_px')}")

        elif args.action == "open":
            result = executor.place_market_order(
                coin=args.coin,
                side=args.side,
                notional_usd=args.notional,
                leverage=args.leverage,
            )
            print(f"开仓结果: {json.dumps(result, indent=2, default=str)}")

        elif args.action == "close":
            result = executor.close_position(coin=args.coin)
            print(f"平仓结果: {json.dumps(result, indent=2, default=str)}")

    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()