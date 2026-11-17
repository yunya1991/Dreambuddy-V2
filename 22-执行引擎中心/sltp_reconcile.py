"""22 公共执行 — 存量持仓 SL/TP 补挂巡检。

从 11 `polling_trader._sltp_reconcile_once` 下沉到 22：任何域（11/23/NN）的持仓
都应在 22 获得统一的止损止盈兜底，避免交易主循环下线后条件单无人补挂。

约束（沿用线上经验）：
- 止损方向必须正确（long 止损 < 当前价，short 止损 > 当前价），否则 OKX 报
  "Order would immediately trigger"；
- 补挂前逐 inst 查询现有 algo 单，已在的一侧传 0，避免重复/覆盖；
- FAIL-OPEN：任何异常只记录，不抛给调用方；
- 只补缺失一侧（OKX 支持 sl-only / tp-only）。
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_AUDIT = _REPO_ROOT / "22-执行引擎中心" / "audit" / "sltp_reconcile.jsonl"

SL_PCT = 0.05
TP_PCT = 0.08
BREAKEVEN_UPL_PCT = 3.0


def _audit(record: dict[str, Any], audit_path: Path | None) -> None:
    try:
        path = audit_path or _DEFAULT_AUDIT
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), **record}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001 — 审计失败不影响补挂
        logger.debug("[SLTP-Reconcile] audit fail: %s", exc)


def _summary(
    audit_path: str | Path | None,
    *,
    patched: int = 0,
    skipped: int = 0,
    failed: int = 0,
    reason: str = "",
) -> None:
    """每轮写一条汇总审计：供监控判断巡检新鲜度，即使无补挂动作也留痕。"""
    _audit(
        {
            "kind": "summary",
            "patched": patched,
            "skipped": skipped,
            "failed": failed,
            "reason": reason,
        },
        Path(audit_path) if audit_path else None,
    )


def _positions(okx_client: Any) -> list[dict[str, Any]]:
    """拉取全部真实持仓（兼容 snake_case / OKX 原始驼峰）。"""
    resp = okx_client.get_positions()
    if not isinstance(resp, dict) or not resp.get("ok", True):
        return []
    raw = resp.get("positions")
    if raw is None:
        raw = resp.get("data") or []
    out: list[dict[str, Any]] = []
    for p in raw:
        inst_id = p.get("inst_id") or p.get("instId") or ""
        pos_side = p.get("pos_side") or p.get("posSide") or ""
        pos_sz = float(p.get("pos", 0) or 0)
        if not inst_id or pos_sz == 0:
            continue
        if pos_side not in ("long", "short"):
            pos_side = "long" if pos_sz > 0 else "short"
        out.append(
            {
                "inst_id": inst_id,
                "pos_side": pos_side,
                "avg_px": float(p.get("avg_px") or p.get("avgPx") or 0),
                "mark_px": float(p.get("mark_px") or p.get("markPx") or 0),
                "upl_ratio": float(p.get("upl_ratio") or p.get("uplRatio") or 0),
            }
        )
    return out


def _has_sltp(okx_client: Any, inst_id: str, pos_side: str) -> tuple[bool, bool]:
    algo = okx_client.get_algo_orders(inst_id=inst_id)
    _has_sl = _has_tp = False
    for o in algo.get("orders") or algo.get("data") or []:
        _side = o.get("pos_side") or o.get("posSide") or ""
        if _side and _side != pos_side:
            continue
        if float(o.get("sl_trigger_px") or o.get("slTriggerPx") or 0) > 0:
            _has_sl = True
        if float(o.get("tp_trigger_px") or o.get("tpTriggerPx") or 0) > 0:
            _has_tp = True
    return _has_sl, _has_tp


def reconcile_sltp(
    okx_client: Any,
    *,
    sl_pct: float = SL_PCT,
    tp_pct: float = TP_PCT,
    breakeven_upl_pct: float = BREAKEVEN_UPL_PCT,
    log_fn: Callable[[str], None] | None = None,
    audit_path: str | Path | None = None,
) -> dict[str, int]:
    """对全部持仓补挂缺失的 SL/TP。返回 {patched, skipped, failed}。"""
    _log = log_fn or (lambda msg: logger.info(msg))
    _t0 = time.time()
    if not (okx_client and hasattr(okx_client, "get_positions")):
        _summary(audit_path, reason="no_client")
        return {"patched": 0, "skipped": 0, "failed": 0}
    try:
        positions = _positions(okx_client)
    except Exception as exc:  # noqa: BLE001
        _log(f"[SLTP-Reconcile] 持仓拉取失败: {exc}")
        _summary(audit_path, reason="fetch_failed")
        return {"patched": 0, "skipped": 0, "failed": 0}
    if not positions:
        _log(f"[SLTP-Reconcile] 无持仓，跳过 耗时={time.time() - _t0:.1f}s")
        _summary(audit_path, reason="no_positions")
        return {"patched": 0, "skipped": 0, "failed": 0}

    patched = skipped = failed = 0
    for pos in positions:
        inst_id = pos["inst_id"]
        pos_side = pos["pos_side"]
        avg_px = pos["avg_px"]
        last_px = pos["mark_px"] or avg_px
        upl_pct = pos["upl_ratio"] * 100

        try:
            has_sl, has_tp = _has_sltp(okx_client, inst_id, pos_side)
        except Exception as exc:  # noqa: BLE001
            _log(f"[SLTP-Reconcile] {inst_id}({pos_side}) algo查询异常: {exc}")
            failed += 1
            continue
        if has_sl and has_tp:
            skipped += 1
            continue
        if avg_px <= 0 or last_px <= 0:
            _log(f"[SLTP-Reconcile] {inst_id}({pos_side}) 无有效均价/现价，跳过")
            skipped += 1
            continue

        if pos_side == "long":
            sl_px = avg_px * (1 - sl_pct)
            tp_px = avg_px * (1 + tp_pct)
            if sl_px >= last_px:
                sl_px = last_px * 0.995
            if upl_pct > breakeven_upl_pct:
                sl_px = max(sl_px, avg_px * 1.005)
        else:
            sl_px = avg_px * (1 + sl_pct)
            tp_px = avg_px * (1 - tp_pct)
            if sl_px <= last_px:
                sl_px = last_px * 1.005
            if upl_pct > breakeven_upl_pct:
                sl_px = min(sl_px, avg_px * 0.995)

        try:
            result = okx_client.place_stop_loss_take_profit(
                inst_id=inst_id,
                pos_side=pos_side,
                stop_loss_px=0 if has_sl else round(sl_px, 6),
                take_profit_px=0 if has_tp else round(tp_px, 6),
                reason=f"sltp_reconcile:avg={avg_px:.2f} upl={upl_pct:.1f}%",
            )
            ok = bool(isinstance(result, dict) and result.get("ok"))
            _audit(
                {
                    "inst_id": inst_id,
                    "pos_side": pos_side,
                    "avg_px": avg_px,
                    "last_px": last_px,
                    "upl_pct": round(upl_pct, 3),
                    "sl_px": 0 if has_sl else round(sl_px, 6),
                    "tp_px": 0 if has_tp else round(tp_px, 6),
                    "ok": ok,
                    "result": result if not ok else "ok",
                },
                Path(audit_path) if audit_path else None,
            )
            if ok:
                patched += 1
                _log(
                    f"[SLTP-Reconcile] 补挂 {inst_id}({pos_side}) "
                    f"SL={sl_px:.4f} TP={tp_px:.4f} upl={upl_pct:.1f}%"
                )
            else:
                failed += 1
                _log(f"[SLTP-Reconcile] {inst_id}({pos_side}) 补挂失败: {result}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            _log(f"[SLTP-Reconcile] {inst_id}({pos_side}) 异常: {exc}")

    _log(
        f"[SLTP-Reconcile] 补挂={patched} 跳过={skipped} 失败={failed} "
        f"耗时={time.time() - _t0:.1f}s"
    )
    _summary(audit_path, patched=patched, skipped=skipped, failed=failed)
    return {"patched": patched, "skipped": skipped, "failed": failed}
