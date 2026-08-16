"""C-series HedgeExecutor — 双腿市场中性对冲策略（PROP-20260816，用户批准 2026-08-16）。

设计文档: 3-EVOLUTION/proposals/PROP-20260816-DREAMOS-双腿对冲策略与币池动态排名.md

策略要点（与 V15 并列的新策略，V9 基线零改动）:
    - 仅 regime 含 RANGE_BOUND 激活
    - 长腿 = 多池合并分 top1，短腿 = 空池合并分 top1
    - B层双向验证: 长腿 dir=LONG、短腿 dir=SHORT，双腿 conf 均 ≥ 0.62
    - 每腿 150U 名义 1:1，5x 杠杆（保证金 30U/腿）
    - 合并离场: combined_pnl_pct ≥ +4% → 双腿同平 (hedge_tp_combined)
                combined_pnl_pct ≤ -6% → 熔断双腿同平 (hedge_sl_combined)
      combined_pnl_pct = combined_pnl / (2 × 单腿名义)
    - 单腿无独立 TP/SL、无马丁加仓
    - 孤儿腿保护: 第二腿开仓失败 → 立即平掉第一腿
    - 并发上限: 同时最多 1 个 OPEN 对冲对
    - dry_run 门禁复用 DREAMOS_TRADING_DRY_RUN（默认 paper，实盘另行审批）

PnL 口径说明: 浮盈用标记价计算 (mark-entry)×size，与交易所 unrealized 等价
（不计 funding）；真单实盘冒烟曾发现 get_account 返回缺 unrealized 字段，
标记价口径确定性更强且可单元验证。
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 对冲账本（独立于 V15 账本；conftest 测试隔离重定向）
HEDGE_POSITIONS_FILE = (
    Path(__file__).resolve().parent.parent.parent
    / "cli" / "scheduler_data" / "hedge_positions.json"
)

# ── 策略参数（PROP-20260816 已确认）─────────────────────────────
NOTIONAL_PER_LEG = 150.0      # 每腿名义 USDT
LEVERAGE = 5                  # 与 V15 一致
MIN_LEG_CONF = 0.62           # 双腿 B层 conf 门槛
TP_COMBINED_PCT = 0.04        # 合并止盈 +4%
SL_COMBINED_PCT = -0.06       # 合并熔断 -6%
MAX_OPEN_PAIRS = 1            # 同时最多 1 个对冲对


def _margin_per_leg(notional: float) -> float:
    return notional / LEVERAGE


@dataclass
class HedgePair:
    """一个双腿对冲对（账本记录）。"""
    pair_id: str
    long_symbol: str
    long_entry: float
    long_size: float
    short_symbol: str
    short_entry: float
    short_size: float
    notional_per_leg: float = NOTIONAL_PER_LEG
    long_conf: float = 0.0
    short_conf: float = 0.0
    regime: str = ""
    opened_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    status: str = "OPEN"  # OPEN / CLOSED / ORPHAN_RECOVERED
    close_reason: Optional[str] = None
    closed_at: Optional[str] = None
    realized_pnl: float = 0.0


class HedgeExecutor:
    """双腿对冲执行器（独立账本，不触碰 V15 状态）。

    Args:
        dry_run: None → 读 env DREAMOS_TRADING_DRY_RUN（默认 true=paper）。
            实盘真单需显式 dry_run=False + 另行审批（dreamos-testing §10）。
        client: 可注入的交易所客户端（测试用 fake；None 时实盘路径懒加载）。
        notional_per_leg: 每腿名义 USDT（默认 150）。
    """

    def __init__(
        self,
        dry_run: Optional[bool] = None,
        client: Any = None,
        notional_per_leg: float = NOTIONAL_PER_LEG,
    ):
        if dry_run is None:
            dry_run = os.environ.get("DREAMOS_TRADING_DRY_RUN", "true").strip().lower() != "false"
        self.dry_run = bool(dry_run)
        self._client = client
        self.notional_per_leg = float(notional_per_leg)
        self._pairs: Dict[str, HedgePair] = {}
        self._load_pairs()

    # ── 账本持久化（原子写，tmp+rename）──────────────────────────

    def _load_pairs(self) -> None:
        try:
            if not HEDGE_POSITIONS_FILE.exists():
                return
            with open(HEDGE_POSITIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for pair_id, raw in (data.get("pairs") or {}).items():
                try:
                    self._pairs[pair_id] = HedgePair(**raw)
                except Exception as e:
                    logger.warning(f"HedgeExecutor 恢复对冲对 {pair_id} 失败,跳过: {e}")
            open_n = sum(1 for p in self._pairs.values() if p.status == "OPEN")
            if self._pairs:
                logger.info(f"HedgeExecutor 账本已恢复: {len(self._pairs)} 对(OPEN={open_n})")
        except Exception as e:
            logger.warning(f"HedgeExecutor 账本恢复失败(使用空账本): {e}")

    def _save_pairs(self) -> None:
        try:
            HEDGE_POSITIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "pairs": {pid: asdict(p) for pid, p in self._pairs.items()},
                "saved_at": datetime.utcnow().isoformat() + "Z",
            }
            tmp_path = str(HEDGE_POSITIONS_FILE) + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, HEDGE_POSITIONS_FILE)
        except Exception as e:
            logger.warning(f"HedgeExecutor 账本落盘失败: {e}")

    # ── 状态查询 ────────────────────────────────────────────────

    def has_open_pair(self) -> bool:
        return any(p.status == "OPEN" for p in self._pairs.values())

    def get_open_pair(self) -> Optional[HedgePair]:
        for p in self._pairs.values():
            if p.status == "OPEN":
                return p
        return None

    # ── 入场 ────────────────────────────────────────────────────

    def evaluate_entry(
        self,
        long_cand: Optional[Dict[str, Any]],
        short_cand: Optional[Dict[str, Any]],
        long_signal: Dict[str, Any],
        short_signal: Dict[str, Any],
        regime: str,
        prices: Dict[str, float],
    ) -> Dict[str, Any]:
        """评估是否开新对冲对（每 orchestration_cycle 一次）。

        Args:
            long_cand/short_cand: 池条目 {"symbol", "score", "merged_score", ...}
            long_signal/short_signal: B层信号 {"direction", "confidence", ...}
            regime: coin_pool.json 的 regime 字符串
            prices: {symbol: 标记价}，paper 成交价 / 名义换算用

        Returns:
            {"status": "OPEN"|"SKIPPED"|"REJECTED"|"ORPHAN_RECOVERED", "reason"?: ...}
        """
        # 门禁1: regime
        if "RANGE_BOUND" not in (regime or "").upper():
            return {"status": "SKIPPED", "reason": "regime_not_range_bound", "regime": regime}
        # 门禁2: 并发上限
        if self.has_open_pair():
            return {"status": "SKIPPED", "reason": "open_pair_exists"}
        # 门禁3: 候选有效
        lsym = (long_cand or {}).get("symbol", "")
        ssym = (short_cand or {}).get("symbol", "")
        if not lsym or not ssym:
            return {"status": "SKIPPED", "reason": "missing_candidates"}
        if lsym == ssym:
            return {"status": "SKIPPED", "reason": "same_symbol"}
        # 门禁4: B层双向验证
        ldir = (long_signal or {}).get("direction", "")
        sdir = (short_signal or {}).get("direction", "")
        if ldir != "LONG" or sdir != "SHORT":
            return {
                "status": "SKIPPED",
                "reason": "direction_mismatch",
                "long_dir": ldir,
                "short_dir": sdir,
            }
        # 门禁5: 双腿 conf
        lconf = float((long_signal or {}).get("confidence", 0.0) or 0.0)
        sconf = float((short_signal or {}).get("confidence", 0.0) or 0.0)
        if lconf < MIN_LEG_CONF or sconf < MIN_LEG_CONF:
            return {
                "status": "SKIPPED",
                "reason": "conf_below_gate",
                "long_conf": lconf,
                "short_conf": sconf,
                "min_conf": MIN_LEG_CONF,
            }
        return self.open_pair(lsym, ssym, lconf, sconf, regime, prices)

    def open_pair(
        self,
        long_symbol: str,
        short_symbol: str,
        long_conf: float,
        short_conf: float,
        regime: str,
        prices: Dict[str, float],
    ) -> Dict[str, Any]:
        """开对冲对。paper: 按标记价模拟成交；实盘: 先多后空+孤儿腿保护。"""
        long_entry = float(prices.get(long_symbol, 0.0) or 0.0)
        short_entry = float(prices.get(short_symbol, 0.0) or 0.0)
        if long_entry <= 0 or short_entry <= 0:
            return {"status": "REJECTED", "reason": "no_entry_price",
                    "long_symbol": long_symbol, "short_symbol": short_symbol}

        pair_id = f"HP-{datetime.utcnow():%Y%m%d}-{len(self._pairs) + 1:03d}"
        notional = self.notional_per_leg

        if self.dry_run:
            pair = HedgePair(
                pair_id=pair_id,
                long_symbol=long_symbol,
                long_entry=long_entry,
                long_size=notional / long_entry,
                short_symbol=short_symbol,
                short_entry=short_entry,
                short_size=notional / short_entry,
                notional_per_leg=notional,
                long_conf=long_conf,
                short_conf=short_conf,
                regime=regime,
            )
            self._pairs[pair_id] = pair
            self._save_pairs()
            logger.info(
                f"对冲对开仓(paper): {pair_id} LONG {long_symbol}@{long_entry} × "
                f"SHORT {short_symbol}@{short_entry} | 每腿{notional}U | conf={long_conf}/{short_conf}"
            )
            return {"status": "OPEN", "pair_id": pair_id, "dry_run": True}

        # ── 实盘路径（需另行审批）──────────────────────────────
        client = self._get_client()
        margin = _margin_per_leg(notional)
        try:
            client.set_leverage(long_symbol, LEVERAGE)
            client.set_leverage(short_symbol, LEVERAGE)
        except Exception:
            pass  # 杠杆已设置时可能失败，与 V15 同策略

        # 第一腿: 多
        try:
            r1 = client.open_long(long_symbol, margin, leverage=LEVERAGE, tag="hedge")
        except Exception as e:
            r1 = {"ok": False, "error": str(e)}
        if not r1.get("ok"):
            logger.warning(f"对冲长腿开仓失败: {long_symbol} {r1.get('error', r1)}")
            return {"status": "REJECTED", "reason": "long_leg_failed", "detail": r1.get("error")}

        l_fill = r1.get("filled") or {}
        long_entry = float(l_fill.get("avgPx") or long_entry)
        long_size = float(r1.get("sz") or notional / long_entry)

        # 第二腿: 空（失败 → 孤儿腿保护，立即平多腿）
        try:
            r2 = client.open_short(short_symbol, margin, leverage=LEVERAGE, tag="hedge")
        except Exception as e:
            r2 = {"ok": False, "error": str(e)}
        if not r2.get("ok"):
            logger.warning(
                f"对冲短腿开仓失败 → 孤儿腿保护平多腿: {short_symbol} {r2.get('error', r2)}"
            )
            try:
                cr = client.close_position(long_symbol, tag="hedge")
            except Exception as e:
                cr = {"ok": False, "error": str(e)}
            pair = HedgePair(
                pair_id=pair_id,
                long_symbol=long_symbol, long_entry=long_entry, long_size=long_size,
                short_symbol=short_symbol, short_entry=short_entry, short_size=0.0,
                notional_per_leg=notional, long_conf=long_conf, short_conf=short_conf,
                regime=regime, status="ORPHAN_RECOVERED",
                close_reason="orphan_leg_protection",
                closed_at=datetime.utcnow().isoformat() + "Z",
            )
            self._pairs[pair_id] = pair
            self._save_pairs()
            return {
                "status": "ORPHAN_RECOVERED", "pair_id": pair_id,
                "orphan_close_ok": bool(cr.get("ok")), "detail": r2.get("error"),
            }

        s_fill = r2.get("filled") or {}
        short_entry = float(s_fill.get("avgPx") or short_entry)
        short_size = float(r2.get("sz") or notional / short_entry)

        pair = HedgePair(
            pair_id=pair_id,
            long_symbol=long_symbol, long_entry=long_entry, long_size=long_size,
            short_symbol=short_symbol, short_entry=short_entry, short_size=short_size,
            notional_per_leg=notional, long_conf=long_conf, short_conf=short_conf,
            regime=regime,
        )
        self._pairs[pair_id] = pair
        self._save_pairs()
        logger.info(
            f"对冲对开仓(实盘): {pair_id} LONG {long_symbol}@{long_entry} × "
            f"SHORT {short_symbol}@{short_entry} | 每腿{notional}U"
        )
        return {"status": "OPEN", "pair_id": pair_id, "dry_run": False}

    # ── 离场 ────────────────────────────────────────────────────

    @staticmethod
    def combined_pnl(pair: HedgePair, long_price: float, short_price: float):
        """合并浮盈: (USD, pct)。pct 相对 2×单腿名义。"""
        long_pnl = (long_price - pair.long_entry) * pair.long_size
        short_pnl = (pair.short_entry - short_price) * pair.short_size
        combined = long_pnl + short_pnl
        denom = 2.0 * pair.notional_per_leg
        pct = combined / denom if denom > 0 else 0.0
        return combined, pct

    def manage_exits(self, prices: Dict[str, float]) -> List[Dict[str, Any]]:
        """巡检所有 OPEN 对冲对，按合并 PnL 离场。返回动作列表。"""
        actions: List[Dict[str, Any]] = []
        for pair in list(self._pairs.values()):
            if pair.status != "OPEN":
                continue
            lp = float(prices.get(pair.long_symbol, 0.0) or 0.0)
            sp = float(prices.get(pair.short_symbol, 0.0) or 0.0)
            if lp <= 0 or sp <= 0:
                actions.append({"pair_id": pair.pair_id, "action": "SKIPPED",
                                "reason": "missing_price"})
                continue
            pnl, pct = self.combined_pnl(pair, lp, sp)
            # 浮点容差: 仅吸收 IEEE754 边界噪声(如 -5.999999999999996% vs -6%),
            # 熔断侧容差方向保守(宁可早熔断), 经济意义上无差别
            _EPS = 1e-9
            if pct >= TP_COMBINED_PCT - _EPS:
                reason = "hedge_tp_combined"
            elif pct <= SL_COMBINED_PCT + _EPS:
                reason = "hedge_sl_combined"
            else:
                continue  # 区间内持有
            result = self._close_pair(pair, reason, pnl, pct)
            result.update({"combined_pnl": round(pnl, 4), "combined_pct": round(pct, 4)})
            actions.append(result)
            logger.info(
                f"对冲离场: {pair.pair_id} reason={reason} pnl={pnl:.4f} ({pct:+.2%})"
            )
        return actions

    def _close_pair(self, pair: HedgePair, reason: str, pnl: float, pct: float) -> Dict[str, Any]:
        if self.dry_run:
            pair.status = "CLOSED"
            pair.close_reason = reason
            pair.closed_at = datetime.utcnow().isoformat() + "Z"
            pair.realized_pnl = round(pnl, 6)
            self._save_pairs()
            return {"pair_id": pair.pair_id, "action": "CLOSED", "reason": reason,
                    "dry_run": True}

        client = self._get_client()
        failures = []
        for sym in (pair.long_symbol, pair.short_symbol):
            try:
                r = client.close_position(sym, tag="hedge")
                if not r.get("ok"):
                    failures.append(f"{sym}:{r.get('error', 'unknown')}")
            except Exception as e:
                failures.append(f"{sym}:{e}")
        if failures:
            # 部分失败: 不标记 CLOSED，下周期重试（避免账本与交易所漂移）
            logger.critical(f"对冲平仓部分失败 {pair.pair_id}: {failures} — 下周期重试")
            return {"pair_id": pair.pair_id, "action": "CLOSE_PARTIAL",
                    "reason": reason, "errors": failures}
        pair.status = "CLOSED"
        pair.close_reason = reason
        pair.closed_at = datetime.utcnow().isoformat() + "Z"
        pair.realized_pnl = round(pnl, 6)
        self._save_pairs()
        return {"pair_id": pair.pair_id, "action": "CLOSED", "reason": reason,
                "dry_run": False}

    # ── 实盘客户端懒加载（与 V15 同路径）────────────────────────

    def _get_client(self):
        if self._client is not None:
            return self._client
        import sys as _sys
        _ab_dir = Path(__file__).resolve().parent.parent.parent.parent / "experiments" / "ab-trading"
        if str(_ab_dir) not in _sys.path:
            _sys.path.insert(0, str(_ab_dir))
        from dotenv import load_dotenv
        load_dotenv(_ab_dir / "config" / ".env")
        from execution.aster_spot import HyperliquidClient
        self._client = HyperliquidClient("c")
        return self._client
