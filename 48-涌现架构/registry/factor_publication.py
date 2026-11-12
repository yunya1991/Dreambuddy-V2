"""factor_publication.py — P3 接线：verdict → 下游消费白名单（SPEC §10.1 P3）。

单向数据流（不可逆）：
    runtime/factor_verdicts.jsonl（append-only，SSOT）
        → publish() → runtime/factor_registry.json（发布视图）
        → 48 metrics / 40 priors 只能读 factor_registry.json

硬约束（SPEC §11 红线 1）：
  - 只有 `candidate` / `candidate_weak` 可发布；`inconclusive` / `falsified` /
    `insufficient_data` 一律不发布，并在 `excluded` 中留痕
  - 本模块**只读** verdict，不产出、不修改 verdict（E-2 边界）
  - 下游不得回读原始 `factor_verdicts.jsonl` 绕过门禁；`load_approved()` 不提供该回落
  - `verify_two_way()` 校验「发布视图」与「SSOT 最新记录」双读一致；SSOT 后来降级
    而 registry 仍旧是 candidate 时判为 stale（防止陈旧发布继续被消费）

用法：
    python -m registry.factor_publication --publish
    python -m registry.factor_publication --verify
    python -m registry.factor_publication --show
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REGISTRY_VERSION = "factor-registry-v1"

#: 只有这两态可进入下游消费链
CONSUMABLE = ("candidate", "candidate_weak")

#: 双读一致比对的字段（发布视图必须与 SSOT 完全一致）
COMPARED_FIELDS = ("verdict", "ic", "t_stat", "n_obs", "horizon")

_BASE = Path(__file__).resolve().parents[1]
VERDICTS_PATH = _BASE / "runtime" / "factor_verdicts.jsonl"
REGISTRY_PATH = _BASE / "runtime" / "factor_registry.json"


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # 容忍历史坏行
    return rows


def _latest(rows: list[dict]) -> dict[str, dict]:
    """append-only 语义：同一 factor_id 以最后一条为准。"""
    latest: dict[str, dict] = {}
    for row in rows:
        fid = row.get("factor_id")
        if fid:
            latest[fid] = row
    return latest


def _entry(row: dict) -> dict:
    out = {key: row.get(key) for key in COMPARED_FIELDS if key != "verdict"}
    out["verdict"] = row.get("verdict")
    out["trial_id"] = row.get("trial_id")
    out["gate_version"] = row.get("gate_version")
    out["written_at"] = row.get("written_at")
    out["script"] = row.get("script")
    return out


def publish(
    verdicts_path: Path | None = None,
    registry_path: Path | None = None,
) -> dict:
    """把 SSOT 最新 verdict 投影为发布视图；非可消费态只记录在 excluded。"""
    src = Path(verdicts_path or VERDICTS_PATH)
    dst = Path(registry_path or REGISTRY_PATH)
    latest = _latest(_read_jsonl(src))

    approved: dict[str, dict] = {}
    excluded: dict[str, dict] = {}
    for fid, row in latest.items():
        if row.get("verdict") in CONSUMABLE:
            approved[fid] = _entry(row)
        else:
            excluded[fid] = _entry(row)

    doc = {
        "version": REGISTRY_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(src),
        "approved": approved,
        "excluded": excluded,
        "counts": {"approved": len(approved), "excluded": len(excluded)},
    }
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc


def load_registry(registry_path: Path | None = None) -> dict:
    """读发布视图；文件缺失返回空视图（下游不得因此回退到原始 verdict）。"""
    path = Path(registry_path or REGISTRY_PATH)
    if not path.is_file():
        return {"version": REGISTRY_VERSION, "approved": {}, "excluded": {}, "missing": True}
    return json.loads(path.read_text(encoding="utf-8"))


def load_approved(registry_path: Path | None = None) -> dict[str, dict]:
    """下游消费入口：只返回已通过门禁的因子。"""
    return load_registry(registry_path).get("approved", {})


def is_consumable(factor_id: str, registry_path: Path | None = None) -> bool:
    return factor_id in load_approved(registry_path)


def verify_two_way(
    verdicts_path: Path | None = None,
    registry_path: Path | None = None,
) -> dict:
    """双读一致（P3 验收）：发布视图 ↔ SSOT 最新记录。

    三类问题分开报，避免把"尚未发布"误判成"数据损坏"：
      - mismatches：字段值不一致（篡改或口径漂移）
      - stale：SSOT 已不再是可消费态，registry 仍挂着
      - unpublished：SSOT 可消费，但 registry 尚未发布
    """
    src = Path(verdicts_path or VERDICTS_PATH)
    dst = Path(registry_path or REGISTRY_PATH)
    latest = _latest(_read_jsonl(src))
    registry = load_registry(dst)
    approved = registry.get("approved", {})

    mismatches: list[dict] = []
    stale: list[str] = []
    for fid, entry in approved.items():
        row = latest.get(fid)
        if row is None:
            stale.append(fid)
            continue
        if row.get("verdict") not in CONSUMABLE:
            stale.append(fid)
            continue
        for field in COMPARED_FIELDS:
            if entry.get(field) != row.get(field):
                mismatches.append(
                    {
                        "factor_id": fid,
                        "field": field,
                        "registry": entry.get(field),
                        "source": row.get(field),
                    }
                )

    unpublished = [
        fid
        for fid, row in latest.items()
        if row.get("verdict") in CONSUMABLE and fid not in approved
    ]
    return {
        "ok": not mismatches and not stale and not unpublished,
        "checked": len(approved),
        "mismatches": mismatches,
        "stale": sorted(stale),
        "unpublished": sorted(unpublished),
        "registry_version": registry.get("version"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="因子发布视图（P3 接线）")
    ap.add_argument("--publish", action="store_true", help="从 SSOT 重建 factor_registry.json")
    ap.add_argument("--verify", action="store_true", help="双读一致校验")
    ap.add_argument("--show", action="store_true", help="打印当前发布视图摘要")
    args = ap.parse_args(argv)

    if args.publish:
        doc = publish()
        print(json.dumps(doc["counts"], ensure_ascii=False))
        return 0
    if args.verify:
        report = verify_two_way()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    if args.show:
        registry = load_registry()
        summary = {
            "version": registry.get("version"),
            "missing": registry.get("missing", False),
            "approved": sorted(registry.get("approved", {})),
            "excluded": {
                fid: entry.get("verdict") for fid, entry in registry.get("excluded", {}).items()
            },
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
