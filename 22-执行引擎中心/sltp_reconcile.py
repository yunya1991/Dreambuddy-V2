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
# 审计来源标签：区分「22 全局兜底补挂」与 11/23 主动挂单
SOURCE_TAG = "22-sltp_reconcile"
# 逐持仓查询 OKX algo 单的节流与限流重试：持仓多时连续查询会在尾部触发
# 50011 Too Many Requests（实测 AMZN 作为最后一个 inst 每轮必失败、误报 P1）。
POSITION_PACE_SEC = 0.2
QUERY_RETRY_SLEEP_SEC = 1.0
QUERY_RATE_LIMIT_CODE = "50011"


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
    deduped: int = 0,
    query_failed: int = 0,
    reason: str = "",
) -> None:
    """每轮写一条汇总审计：供监控判断巡检新鲜度，即使无补挂动作也留痕。"""
    _audit(
        {
            "kind": "summary",
            "source": SOURCE_TAG,
            "patched": patched,
            "skipped": skipped,
            "failed": failed,
            "deduped": deduped,
            "query_failed": query_failed,
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


def _algo_snapshot(
    okx_client: Any, inst_id: str, pos_side: str
) -> tuple[list[dict[str, Any]], str]:
    """返回同方向 algo 单与查询错误；查询失败绝不能当作"无挂单"处理。

    命中 50011（限流）时退避重试一次，避免连续查询尾部被限流误记为补挂失败。
    """
    err = ""
    for attempt in range(2):
        algo = okx_client.get_algo_orders(inst_id=inst_id)
        if not isinstance(algo, dict):
            err = "algo_query_invalid"
        elif algo.get("query_ok") is False:
            err = "; ".join(algo.get("errors") or []) or "algo_query_failed"
        else:
            out = []
            for o in algo.get("orders") or algo.get("data") or []:
                _side = o.get("pos_side") or o.get("posSide") or ""
                if _side and _side != pos_side:
                    continue
                out.append(o)
            return out, ""
        if QUERY_RATE_LIMIT_CODE not in err or attempt:
            break
        logger.info(
            "[SLTP-Reconcile] %s(%s) algo查询限流，%.1fs 后重试",
            inst_id,
            pos_side,
            QUERY_RETRY_SLEEP_SEC,
        )
        time.sleep(QUERY_RETRY_SLEEP_SEC)
    return [], err


def _dedupe_algo_orders(
    okx_client: Any,
    inst_id: str,
    pos_side: str,
    orders: list[dict[str, Any]],
    audit_path: Path | None,
    log_fn: Callable[[str], None],
) -> tuple[list[dict[str, Any]], int, str]:
    """同一持仓只保留最新一条 SL/TP 单，撤掉历史重复单。"""
    live = []
    for o in orders:
        has_px = (
            float(o.get("sl_trigger_px") or o.get("slTriggerPx") or 0) > 0
            or float(o.get("tp_trigger_px") or o.get("tpTriggerPx") or 0) > 0
        )
        state = str(o.get("state") or "live")
        if has_px and state in ("live", "ordering", "partially_filled"):
            live.append(o)
    if len(live) <= 1:
        return orders, 0, ""

    live.sort(key=lambda o: int(str(o.get("algo_id") or o.get("algoId") or 0)))
    keep = live[-1]
    cancelled = 0
    for o in live[:-1]:
        aid = o.get("algo_id") or o.get("algoId")
        try:
            if not hasattr(okx_client, "cancel_algo_order"):
                return orders, cancelled, "client_without_cancel_algo_order"
            r = okx_client.cancel_algo_order(inst_id=inst_id, algo_id=aid)
            ok = isinstance(r, dict) and bool(r.get("ok"))
        except Exception as exc:  # noqa: BLE001
            ok = False
            r = {"error": str(exc)}
        _audit(
            {
                "kind": "dedupe",
                "source": SOURCE_TAG,
                "inst_id": inst_id,
                "pos_side": pos_side,
                "kept_algo_id": keep.get("algo_id") or keep.get("algoId"),
                "cancelled_algo_id": aid,
                "ok": ok,
                "result": "ok" if ok else r,
            },
            audit_path,
        )
        if not ok:
            return orders, cancelled, f"dedupe_cancel_failed algo={aid}"
        cancelled += 1
        log_fn(f"[SLTP-Reconcile] 去重 {inst_id}({pos_side}) 撤销重复单 algo={aid}")
    return [keep] + [o for o in orders if o not in live], cancelled, ""


def reconcile_sltp(
    okx_client: Any,
    *,
    sl_pct: float = SL_PCT,
    tp_pct: float = TP_PCT,
    breakeven_upl_pct: float = BREAKEVEN_UPL_PCT,
    log_fn: Callable[[str], None] | None = None,
    audit_path: str | Path | None = None,
) -> dict[str, int]:
    """对全部持仓补挂缺失的 SL/TP。

    返回 {patched, skipped, failed, deduped, query_failed}。
    `failed` 只统计「确认需要保护却没补上」（下单/去重失败），供 P1 使用；
    `query_failed` 是「查不到、无法判断」的 algo 查询失败（多为 50011 限流），
    单独计数并落审计，避免把限流误报成「仓位缺少止损保护」。
    """
    _log = log_fn or (lambda msg: logger.info(msg))
    _t0 = time.time()
    if not (okx_client and hasattr(okx_client, "get_positions")):
        _summary(audit_path, reason="no_client")
        return {"patched": 0, "skipped": 0, "failed": 0, "deduped": 0, "query_failed": 0}
    try:
        positions = _positions(okx_client)
    except Exception as exc:  # noqa: BLE001
        _log(f"[SLTP-Reconcile] 持仓拉取失败: {exc}")
        _summary(audit_path, reason="fetch_failed")
        return {"patched": 0, "skipped": 0, "failed": 0, "deduped": 0, "query_failed": 0}
    if not positions:
        _log(f"[SLTP-Reconcile] 无持仓，跳过 耗时={time.time() - _t0:.1f}s")
        _summary(audit_path, reason="no_positions")
        return {"patched": 0, "skipped": 0, "failed": 0, "deduped": 0, "query_failed": 0}

    patched = skipped = failed = deduped = query_failed = 0
    for idx, pos in enumerate(positions):
        if idx:
            time.sleep(POSITION_PACE_SEC)
        inst_id = pos["inst_id"]
        pos_side = pos["pos_side"]
        avg_px = pos["avg_px"]
        last_px = pos["mark_px"] or avg_px
        upl_pct = pos["upl_ratio"] * 100

        try:
            algo_orders, algo_err = _algo_snapshot(okx_client, inst_id, pos_side)
        except Exception as exc:  # noqa: BLE001
            _log(f"[SLTP-Reconcile] {inst_id}({pos_side}) algo查询异常: {exc}")
            _audit(
                {
                    "kind": "algo_query_fail",
                    "source": SOURCE_TAG,
                    "inst_id": inst_id,
                    "pos_side": pos_side,
                    "error": f"exception: {exc}",
                },
                Path(audit_path) if audit_path else None,
            )
            query_failed += 1
            continue
        if algo_err:
            # 查询失败不能当作"无 SL/TP"，否则会重复补挂；但也不等于缺保护（P1）
            _log(f"[SLTP-Reconcile] {inst_id}({pos_side}) algo查询失败: {algo_err}")
            _audit(
                {
                    "kind": "algo_query_fail",
                    "source": SOURCE_TAG,
                    "inst_id": inst_id,
                    "pos_side": pos_side,
                    "error": algo_err,
                },
                Path(audit_path) if audit_path else None,
            )
            query_failed += 1
            continue

        algo_orders, n_deduped, dedupe_err = _dedupe_algo_orders(
            okx_client,
            inst_id,
            pos_side,
            algo_orders,
            Path(audit_path) if audit_path else None,
            _log,
        )
        deduped += n_deduped
        if dedupe_err:
            failed += 1
            continue

        has_sl = any(
            float(o.get("sl_trigger_px") or o.get("slTriggerPx") or 0) > 0 for o in algo_orders
        )
        has_tp = any(
            float(o.get("tp_trigger_px") or o.get("tpTriggerPx") or 0) > 0 for o in algo_orders
        )
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
                source=SOURCE_TAG,
            )
            ok = bool(isinstance(result, dict) and result.get("ok"))
            _audit(
                {
                    "kind": "patch",
                    "source": SOURCE_TAG,
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
        f"[SLTP-Reconcile] 补挂={patched} 跳过={skipped} 失败={failed} 去重={deduped} "
        f"查询失败={query_failed} 耗时={time.time() - _t0:.1f}s"
    )
    _summary(
        audit_path,
        patched=patched,
        skipped=skipped,
        failed=failed,
        deduped=deduped,
        query_failed=query_failed,
    )
    return {
        "patched": patched,
        "skipped": skipped,
        "failed": failed,
        "deduped": deduped,
        "query_failed": query_failed,
    }
