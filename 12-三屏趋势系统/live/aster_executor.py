"""Aster 执行器 — 趋势策略专用

用途：
    trend-system 独立 aster 环境的下单执行模块，
    与 ab-trading 的 Hyperliquid/OKX 链路隔离。

核心功能：
    - 加载 trend-system/.env 中的 aster 凭证
    - 封装 ml_trade_service 的下单接口
    - 支持市价单、止盈止损单
    - 账户与持仓查询

调用方式：
    from live.aster_executor import AsterExecutor

    executor = AsterExecutor()
    result = executor.place_market_order("BTC", "long", 10.0)  # 10 USDT 名义价值
    pos = executor.get_positions()

文件: trend-system/live/aster_executor.py
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

# 加载 trend-system/.env
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

    封装 ml_trade_service 的下单接口，专门为 trend-system 设计。
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

    # ─────────────────────────────────────────────────────────────
    # 账户查询
    # ─────────────────────────────────────────────────────────────

    def get_account_summary(self) -> Dict[str, Any]:
        """获取账户摘要"""
        try:
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

            if self.config.dry_run:
                logger.info(f"[AsterExecutor] [DRY_RUN] 平仓 {coin} {close_side} qty={abs(pos_qty)}")
                return {"ok": True, "dry_run": True, "closed_qty": abs(pos_qty)}

            # 执行平仓
            result = self._ml._aster_market_order_qty(
                coin=coin,
                side=close_side,
                qty=abs(pos_qty),
                reduce_only=True,
                owner=self.config.owner,
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