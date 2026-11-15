# -*- coding: utf-8 -*-
"""点亮历史快照（SPEC-54-L1交易层 §5.3 / B-LT7 标定输入，"LTL-16" 第二步）。

口径（硬约束）：

  - 逐 `as_of` **切片历史**后重跑 D-E15 + I39（不重算：全部走能力层/方法层），
    经 D-E19 投影成 `lights.rows`，一个进程产出 N 个快照的数组；
  - 只产标定输入（`{"as_of": ..., "lights": {"rows": [...]}}[]`），**不写库、不写配置**；
  - 交给 [calibrate_light.py](./calibrate_light.py) 池化分位（单快照最多 48 个样本，
    全样本必须跨日期池化）；
  - 日历取 base 标的的交易日（`--base`，默认 BTC），每期只保留 `day <= as_of` 的样本，
    因此不存在前视（`as_of` 与回测口径一致）。

用法：

    python3 scripts/light_history.py --as-of-count 45 --out /tmp/light_snapshots.json
    python3 scripts/calibrate_light.py --input /tmp/light_snapshots.json --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)
_FRONTEND_SCRIPTS = os.path.normpath(os.path.join(_MODULE_ROOT, "..", "3.1-FRONTEND", "scripts"))
if _FRONTEND_SCRIPTS not in sys.path:
    sys.path.insert(0, _FRONTEND_SCRIPTS)

DEFAULT_AS_OF_COUNT = 45
DEFAULT_DAYS = 1400


class SnapshotError(RuntimeError):
    """历史不足 / 无可用资产（拒绝产出空快照集）。"""


def select_as_of_dates(raw: Mapping[str, Mapping[str, Any]], base: str, count: int) -> List[str]:
    """取 base 标的最近 `count` 个交易日作为 `as_of` 日历（升序）。"""
    dates = sorted((raw.get(base) or {}).keys())
    if not dates:
        raise SnapshotError(f"base 标的无历史: {base}")
    if count <= 0:
        raise SnapshotError(f"as_of-count 必须 >0: {count}")
    return dates[-int(count) :]


def _default_entries(raw, pool, *, as_of=None, base=None):
    import visual_overview as vo

    return vo._lights_entries(raw, pool, as_of=as_of, base=base)


def _default_rows(entries) -> List[Dict[str, Any]]:
    from l1agg.capabilities.lights import lights

    if not entries:
        return []
    env = lights(entries) or {}
    block = (((env.get("data") or {}).get("capabilities")) or {}).get("D-E19") or {}
    return list(block.get("lights") or [])


def build_snapshots(
    raw: Mapping[str, Mapping[str, Any]],
    pool: Any,
    *,
    base: str,
    count: int = DEFAULT_AS_OF_COUNT,
    entries_fn: Optional[Callable[..., Sequence[Mapping[str, Any]]]] = None,
    rows_fn: Optional[Callable[[Sequence[Mapping[str, Any]]], Sequence[Mapping[str, Any]]]] = None,
) -> List[Dict[str, Any]]:
    """逐 `as_of` 产一个点亮快照（`entries_fn`/`rows_fn` 可注入，便于离线测试）。"""
    builder = entries_fn or _default_entries
    projector = rows_fn or _default_rows
    snapshots: List[Dict[str, Any]] = []
    for as_of in select_as_of_dates(raw, base, count):
        entries = builder(raw, pool, as_of=as_of, base=base)
        rows = list(projector(entries))
        snapshots.append({"as_of": as_of, "lights": {"rows": rows}})
    return snapshots


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="点亮历史快照（阈值标定输入）")
    parser.add_argument("--symbols", default="", help="逗号分隔；缺省用 leader_registry 首屏")
    parser.add_argument("--base", default="", help="日历基准标的（默认资产池首个）")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="历史回看深度")
    parser.add_argument("--as-of-count", type=int, default=DEFAULT_AS_OF_COUNT)
    parser.add_argument("--out", default="-", help="输出 JSON 路径（- 走 stdout）")
    args = parser.parse_args(list(argv) if argv is not None else None)

    import visual_overview as vo
    from l1agg.asset_pool import load as load_asset_pool

    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    if not symbols:
        symbols = vo._default_assets()
    symbols = symbols[:12]
    base = (args.base or "").strip().upper() or symbols[0]

    _, _, _, unavailable, raw = vo._load_series(symbols, args.days)
    if not raw or base not in raw:
        print(
            json.dumps(
                {"ok": False, "error": f"无可用历史（base={base}）", "unavailable": unavailable},
                ensure_ascii=False,
            )
        )
        return 2
    try:
        pool = load_asset_pool()
    except Exception:  # 资产池缺失不阻塞（min_rows 回落 lights 默认门槛）
        pool = None

    snapshots = build_snapshots(raw, pool, base=base, count=args.as_of_count)
    text = json.dumps(snapshots, ensure_ascii=False)
    if args.out == "-":
        print(text)
    else:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    rows = sum(len(snapshot["lights"]["rows"]) for snapshot in snapshots)
    print(
        json.dumps(
            {
                "ok": True,
                "snapshots": len(snapshots),
                "rows": rows,
                "as_of_first": snapshots[0]["as_of"] if snapshots else None,
                "as_of_last": snapshots[-1]["as_of"] if snapshots else None,
                "base": base,
                "out": args.out,
                "unavailable": unavailable,
            },
            ensure_ascii=False,
        ),
        file=sys.stderr if args.out == "-" else sys.stdout,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
