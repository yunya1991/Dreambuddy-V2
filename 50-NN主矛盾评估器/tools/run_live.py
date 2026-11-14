#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""50 live 决策调度入口（灰度单标的）。

读取 42 总线 → 过滤过期 evidence → 按标的调用 make_decision(mode="live")
→ 落盘 runtime/live/outbox.jsonl 供 22 执行层消费。

硬约束：
- 仅 allowlist 内标的产出 live 决策（默认 BTC-USDT-SWAP）
- 必须同时满足 execution_rights=live:50-bypass + Mandate + kill-switch 关闭
- 过期 evidence 一律丢弃，禁止拿陈旧信号下传
- 无新鲜 evidence：记录 skipped 后正常退出，不产出决策

用法：
  python3 tools/run_live.py [--bus-state PATH] [--symbols BTC-USDT-SWAP]
                            [--mandate ID] [--out-dir PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_50_ROOT = _REPO_ROOT / "50-NN主矛盾评估器"
_42_ROOT = _REPO_ROOT / "42-神经网络交易协调层"
for _p in (str(_50_ROOT), str(_42_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from adapters.bus_reader import load_evidences  # noqa: E402
from adapters.constraint_loader import load_constraints  # noqa: E402
from adapters.execution_writer import (  # noqa: E402
    is_kill_switch_on,
    load_rights,
)
from core.decision import make_decision  # noqa: E402
from core.resonance_propagator import propagate as propagate_resonance  # noqa: E402

DEFAULT_BUS_STATE = _42_ROOT / "runtime" / "bus_state.json"
DEFAULT_OUT_DIR = _50_ROOT / "runtime" / "live"
DEFAULT_MANDATE = os.environ.get("50_LIVE_MANDATE", "mandate-20261114-50-live-multi")
# 动态 allowlist：总线里置信度 ≥ 阈值的 long/short 且注册表内可交易标的
MIN_CONFIDENCE = float(os.environ.get("50_LIVE_MIN_CONFIDENCE", "0.8"))
_SYMBOL_REGISTRY = _REPO_ROOT / "22-执行引擎中心" / "config" / "live_symbols.json"


def _load_registry() -> dict[str, dict[str, str]]:
    """读取 22 域 live 标的注册表（base -> {inst_id, asset_class}）。"""
    try:
        data = json.loads(_SYMBOL_REGISTRY.read_text(encoding="utf-8"))
        return {
            str(k).upper(): {
                "inst_id": str(v.get("inst_id") or "").upper(),
                "asset_class": str(v.get("asset_class") or "crypto_usdt"),
            }
            for k, v in (data.get("symbols") or {}).items()
        }
    except (OSError, json.JSONDecodeError):
        return {"BTC": {"inst_id": "BTC-USDT-SWAP", "asset_class": "crypto_usdt"}}


_REGISTRY = _load_registry()

# 42 总线符号 → OKX 合约 instId
_SYMBOL_MAP = {
    "BTC": "BTC-USDT-SWAP",
    "BTC-USDT": "BTC-USDT-SWAP",
    "BTC/USDT": "BTC-USDT-SWAP",
    "BTCUSDT": "BTC-USDT-SWAP",
    "BTC-USDT-SWAP": "BTC-USDT-SWAP",
    "ETH": "ETH-USDT-SWAP",
    "ETH-USDT": "ETH-USDT-SWAP",
    "ETH/USDT": "ETH-USDT-SWAP",
    "ETHUSDT": "ETH-USDT-SWAP",
    "ETH-USDT-SWAP": "ETH-USDT-SWAP",
}

# 宏观/资产类别级证据：不绑定单一标的，per-symbol 决策时作为上下文并入
_MACRO_SYMBOLS = {"", "MACRO", "MULTI", "CRYPTO", "CRYPTO_USDT"}
_MACRO_SOURCES = {"40-cycle", "40-divergence", "40-resonance", "43-strategic"}


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o664)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_fresh(ev: dict[str, Any], now: datetime) -> bool:
    expires = _parse_ts(ev.get("expires_at"))
    if expires is None:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > now


def _to_inst_id(symbol: str) -> str | None:
    """符号 → instId：优先 22 域注册表，其次兼容旧映射表。"""
    raw = (symbol or "").strip().upper()
    base = raw.replace("/", "-").split("-")[0]
    entry = _REGISTRY.get(base)
    if entry and entry.get("inst_id"):
        return entry["inst_id"]
    return _SYMBOL_MAP.get(raw)


def _asset_class_of(inst_id: str) -> str:
    for entry in _REGISTRY.values():
        if entry.get("inst_id") == inst_id:
            return entry.get("asset_class") or "crypto_usdt"
    return "crypto_usdt"


def _dynamic_allowlist(fresh: list[dict[str, Any]]) -> set[str]:
    """从新鲜证据中挑选置信度 ≥MIN_CONFIDENCE 的 long/short 可交易标的。"""
    allow: set[str] = set()
    for ev in fresh:
        if str(ev.get("direction") or "").lower() not in ("long", "short"):
            continue
        try:
            conf = float(ev.get("confidence") or 0)
        except (TypeError, ValueError):
            continue
        if conf < MIN_CONFIDENCE:
            continue
        inst_id = _to_inst_id(str(ev.get("symbol") or ""))
        if inst_id:
            allow.add(inst_id)
    return allow


def _evidence_key(ev: dict[str, Any]) -> str:
    """证据稳定身份：优先 signal_id，缺失时用来源字段拼接。"""
    sid = str(ev.get("signal_id") or "").strip()
    if sid:
        return sid
    return "|".join(
        str(ev.get(k) or "") for k in ("source", "symbol", "ts", "direction", "confidence")
    )


def stable_decision_id(inst_id: str, group: list[dict[str, Any]]) -> str:
    """按证据批次生成稳定 decision_id。

    同一批证据（42 总线未刷新）重复调度必须得到同一 id，22 的 processed 幂等才生效；
    证据集变化 → 新 id（视为新信号）。
    """
    keys = sorted({_evidence_key(ev) for ev in group})
    digest = hashlib.sha1("\n".join([inst_id, *keys]).encode("utf-8")).hexdigest()[:16]
    return f"50-nn|{digest}"


def run(
    bus_state: Path,
    out_dir: Path,
    symbols: tuple[str, ...],
    mandate: str,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    result: dict[str, Any] = {
        "run_ts": now.isoformat().replace("+00:00", "Z"),
        "status": "ok",
        "reason": None,
        "decisions": [],
        "skipped": [],
    }

    if is_kill_switch_on():
        result["status"] = "skipped"
        result["reason"] = "50_KILL_SWITCH=1（kill switch 开启）"
        return result

    evidences = load_evidences(str(bus_state))
    fresh = [ev for ev in evidences if _is_fresh(ev, now)]
    result["evidence_count"] = len(evidences)
    result["fresh_evidence_count"] = len(fresh)
    if not fresh:
        result["status"] = "skipped"
        result["reason"] = "no_fresh_evidences（42 总线无可用的未过期信号）"
        return result

    # 显式 --symbols 时按指定清单；否则按总线高置信度动态选取
    allow = {s.strip().upper() for s in symbols if s.strip()} or _dynamic_allowlist(fresh)
    result["allowlist"] = sorted(allow)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for inst_id in allow:
        group: list[dict[str, Any]] = []
        for ev in fresh:
            raw_symbol = str(ev.get("symbol") or "")
            source = str(ev.get("source") or "")
            if (
                _to_inst_id(raw_symbol) == inst_id
                or raw_symbol.strip().upper() in _MACRO_SYMBOLS
                or source in _MACRO_SOURCES
            ):
                group.append(ev)
        if group:
            grouped[inst_id] = group

    rights = load_rights()
    constraints = load_constraints()

    for inst_id, group in sorted(grouped.items()):
        if inst_id not in allow:
            result["skipped"].append({"symbol": inst_id, "reason": "not_in_allowlist"})
            continue
        decision = make_decision(
            group,
            symbol=inst_id,
            asset_class=_asset_class_of(inst_id),
            constraints=constraints,
            rights=rights,
            mandate=mandate,
            kill_switch=False,
            now=now,
            mode="live",
        )
        # 龙头共振传导：只调 confidence，不改 direction；矩阵不可用时原样返回
        propagate_resonance(decision, fresh, _asset_class_of(inst_id))
        outcome = (decision.get("execution") or {}).get("outcome")
        if outcome != "live:50-bypass" or decision.get("direction") not in ("long", "short"):
            result["skipped"].append(
                {
                    "symbol": inst_id,
                    "reason": f"not_executable:{outcome}:{decision.get('direction')}",
                }
            )
            continue
        decision["decision_id"] = stable_decision_id(inst_id, group)
        decision["mandate_id"] = mandate
        result["decisions"].append(decision)

    if not result["decisions"]:
        result["status"] = "skipped"
        result["reason"] = "no_live_decisions（无满足执行权与方向的标的）"
        return result

    _atomic_write_text(
        out_dir / "latest.json",
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
    )
    lines: list[str] = []
    outbox = out_dir / "outbox.jsonl"
    if outbox.exists():
        lines = [ln for ln in outbox.read_text(encoding="utf-8").splitlines() if ln.strip()]
    for decision in result["decisions"]:
        lines.append(json.dumps(decision, ensure_ascii=False))
    _atomic_write_text(outbox, "\n".join(lines[-500:]) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="50 live 决策调度入口")
    parser.add_argument("--bus-state", default=str(DEFAULT_BUS_STATE))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument(
        "--symbols",
        default="",
        help="显式标的清单（逗号分隔）；留空则按总线置信度动态选取",
    )
    parser.add_argument("--mandate", default=DEFAULT_MANDATE)
    args = parser.parse_args()

    symbols = tuple(s for s in args.symbols.split(",") if s.strip())
    result = run(Path(args.bus_state), Path(args.out_dir), symbols, args.mandate)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
