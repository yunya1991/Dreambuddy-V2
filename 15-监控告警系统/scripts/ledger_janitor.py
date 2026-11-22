#!/usr/bin/env python3
"""账本 janitor（SPEC-LEDGER-DOMAIN-ATTRIBUTION §6.1，P1-6 shadow 模式）。

职责（唯一允许迁移 open→stale→closed 的进程）：
  1. 用交易所持仓快照刷新 verified_at / miss_count，stale 恢复 open；
  2. 连续缺失达到时间与确认次数阈值 → 标记 stale /（enforce 时）closed；
  3. 交易所存在但账本缺失 → 补录 + missing_in_ledger 工单；
  4. 数量/均价漂移 → qty_drift / price_drift 工单；
  5. 释放过期 reservation；写 heartbeat；
  6. 交易所接口失败只记 feed_state=degraded，不累加 miss_count。

P1 默认 shadow：`janitor_enforce=off`，只写工单与 miss 计数，不改 status。
仅生产云端运行（进程归属 15，代码复用 22 PositionLedger），文件锁保证单实例。

用法：
  python3 scripts/ledger_janitor.py --once --positions-json /tmp/okx_positions.json
  python3 scripts/ledger_janitor.py --once --positions-json ... --enforce on
"""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent
_LEDGER_DIR = REPO_ROOT / "22-执行引擎中心"
if str(_LEDGER_DIR) not in sys.path:
    sys.path.insert(0, str(_LEDGER_DIR))

from position_ledger import _EPS, PositionLedger, _parse_ts, domain_of  # noqa: E402

logger = logging.getLogger("ledger_janitor")


def _now(ts: Optional[datetime] = None) -> datetime:
    return ts or datetime.now(timezone.utc)


def _key(inst_id: Any, pos_side: Any) -> tuple:
    return (str(inst_id or ""), str(pos_side or "").lower())


def _resolve_open_break(
    ledger: PositionLedger, kind: str, inst_id: str, pos_side: str, domain: str = ""
) -> None:
    for b in ledger.list_breaks(state="OPEN", kind=kind, limit=200):
        if (
            str(b.get("inst_id")) == inst_id
            and str(b.get("pos_side")) == pos_side
            and (not domain or str(b.get("domain")) == domain)
        ):
            ledger.resolve_break(int(b["break_id"]), resolution="auto:exchange_recovered")


def run_once(
    ledger: PositionLedger,
    positions: List[Dict[str, Any]],
    *,
    enforce: Optional[bool] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """执行一轮对账（纯函数式，测试可直接注入快照）。"""
    ref = _now(now)
    ref_ts = ref.isoformat().replace("+00:00", "Z")
    if enforce is None:
        enforce = str(ledger.get_setting("janitor_enforce", "off")).lower() == "on"
    stale_after = float(ledger.get_setting("stale_after_seconds", "600") or 600)
    close_after = float(ledger.get_setting("close_after_seconds", "3600") or 3600)
    min_conf = int(float(ledger.get_setting("min_confirmations", "3") or 3))

    snap = {}
    for p in positions or []:
        k = _key(p.get("inst_id"), p.get("pos_side"))
        qty = float(p.get("qty") or p.get("pos") or 0.0)
        if not k[0] or k[1] not in ("long", "short") or qty <= _EPS:
            continue
        snap[k] = {
            "inst_id": k[0],
            "pos_side": k[1],
            "qty": qty,
            "avg_entry": float(p.get("avg_entry") or p.get("avg_px") or 0.0),
        }

    rows = {_key(r.get("inst_id"), r.get("pos_side")): r for r in ledger.list_positions()}
    verified = stale = closed = breaks = 0

    # ① 匹配：刷新 verified / miss，stale 恢复 open
    for k, sp in snap.items():
        ledger.mark_verified([{"inst_id": k[0], "pos_side": k[1]}], ts=ref_ts)
        verified += 1
        row = rows.get(k)
        if row is None:
            # ⑤ 交易所存在但账本缺失 → 补录 + 工单
            ledger.record_fill(
                k[0],
                k[1],
                "open",
                sp["qty"],
                sp["avg_entry"],
                source="22-reconciled",
                domain="22",
                ts=ref_ts,
            )
            ledger.upsert_break(
                "missing_in_ledger",
                k[0],
                k[1],
                "22",
                {"qty": sp["qty"], "avg_entry": sp["avg_entry"]},
                ts=ref_ts,
            )
            breaks += 1
            continue
        if str(row.get("status")) == "stale":
            ledger.set_status(k[0], k[1], "open", ts=ref_ts)
            _resolve_open_break(ledger, "stale_position", k[0], k[1])
        if abs(float(row.get("qty") or 0) - sp["qty"]) > _EPS:
            ledger.upsert_break(
                "qty_drift",
                k[0],
                k[1],
                "",
                {"ledger": float(row.get("qty") or 0), "exchange": sp["qty"]},
                ts=ref_ts,
            )
            breaks += 1
        _avg = float(row.get("avg_entry") or 0)
        if _avg > _EPS and sp["avg_entry"] > _EPS and abs(_avg - sp["avg_entry"]) > _EPS:
            ledger.upsert_break(
                "price_drift",
                k[0],
                k[1],
                "",
                {"ledger": _avg, "exchange": sp["avg_entry"]},
                ts=ref_ts,
            )
            breaks += 1

    # ② 缺失：累加 miss，达阈值标记 stale /（enforce）closed
    for k, row in rows.items():
        if k in snap:
            continue
        miss = ledger.note_miss(k[0], k[1], ts=ref_ts)
        if not miss.get("ok"):
            continue
        first = _parse_ts(miss.get("first_miss_at"))
        elapsed = (ref - first).total_seconds() if first is not None else 0.0
        if elapsed >= stale_after and int(miss["miss_count"]) >= min_conf:
            ledger.upsert_break(
                "stale_position",
                k[0],
                k[1],
                domain_of(row.get("source")),
                {"elapsed_sec": elapsed, "miss_count": miss["miss_count"]},
                ts=ref_ts,
            )
            breaks += 1
            if enforce:
                ledger.set_status(k[0], k[1], "stale", ts=ref_ts)
                stale += 1
        if elapsed >= close_after and enforce:
            ledger.close_position(
                domain_of(row.get("source")),
                k[0],
                k[1],
                float(row.get("qty") or 0),
                px=float(row.get("avg_entry") or 0),
                source="22-janitor",
                exit_reason="ghost_exchange_flat",
                set_cooldown=False,
            )
            ledger.set_status(k[0], k[1], "closed", ts=ref_ts)
            closed += 1

    released = ledger.expire_reservations()
    ledger.set_feed_state("ok", ts=ref_ts)
    ledger.heartbeat(ts=ref_ts)
    return {
        "ok": True,
        "enforce": bool(enforce),
        "verified": verified,
        "stale": stale,
        "closed": closed,
        "breaks_created": breaks,
        "reservations_expired": released,
        "open_breaks": ledger.count_breaks("OPEN"),
    }


def run_fetch_failed(ledger: PositionLedger, error: str, now: Optional[datetime] = None) -> Dict:
    """交易所接口失败：只标 degraded，不累加 miss_count（§6.1-8）。"""
    ledger.set_feed_state("degraded", ts=(now or datetime.now(timezone.utc)).isoformat())
    return {"ok": False, "feed_state": "degraded", "error": str(error)[:200]}


class _SingleInstance:
    """同一账本只允许一个 janitor 实例（跨进程文件锁）。"""

    def __init__(self, db_path: Path) -> None:
        self._lock_path = Path(str(db_path) + ".janitor.lock")
        self._fh = None

    def __enter__(self) -> bool:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self._lock_path.open("w")
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._fh.close()
            self._fh = None
            return False
        return True

    def __exit__(self, *exc) -> None:
        if self._fh is not None:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None


def _load_positions(path: str) -> List[Dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("positions") or []
    return list(data or [])


def _fetch_okx_positions() -> List[Dict[str, Any]]:
    """直接经 14/V15 的 OKX 客户端拉全量持仓（生产云端默认路径）。"""
    lib = REPO_ROOT / "14-V15经典马丁策略" / "lib"
    if str(lib) not in sys.path:
        sys.path.insert(0, str(lib))
    from okx_client import OKXSimulatedClient  # noqa: PLC0415 — 延迟导入避免本地无依赖

    data = OKXSimulatedClient().get_positions() or {}
    if not data.get("ok", True):
        raise RuntimeError(str(data.get("error") or "okx_get_positions_failed"))
    return list(data.get("positions") or [])


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="22 账本 janitor（P1 shadow）")
    parser.add_argument("--once", action="store_true", help="执行一轮后退出")
    parser.add_argument("--positions-json", help="交易所持仓快照 JSON（数组或 {positions:[]}）")
    parser.add_argument("--okx", action="store_true", help="直接经 OKX 客户端拉取持仓（生产）")
    parser.add_argument("--enforce", choices=["on", "off"], help="覆盖 janitor_enforce 设置")
    parser.add_argument("--db", default=os.getenv("POSITION_LEDGER_PATH"), help="账本 DB 路径")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    ledger = PositionLedger(args.db)
    enforce = None if args.enforce is None else (args.enforce == "on")

    with _SingleInstance(ledger.path) as acquired:
        if not acquired:
            logger.error("已有 janitor 实例在运行（文件锁占用），本轮退出")
            return 3
        try:
            if args.okx:
                positions = _fetch_okx_positions()
            elif args.positions_json:
                positions = _load_positions(args.positions_json)
            else:
                positions = []
        except (OSError, ValueError, RuntimeError, ImportError) as exc:
            out = run_fetch_failed(ledger, f"positions_fetch_failed: {exc}")
            logger.error("交易所持仓获取失败: %s", exc)
            print(json.dumps(out, ensure_ascii=False))
            return 2
        out = run_once(ledger, positions, enforce=enforce)
        print(json.dumps(out, ensure_ascii=False))
        return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
