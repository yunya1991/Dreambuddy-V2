#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""幂等重训：重建模型并与现有模型比对，只记录不生效。

口径来源：SPEC §17.6 每日重训口径
  - 同输入必得同输出（忽略 generated_at）；
  - 与现模型比对忽略 generated_at / version；相同 → no_change，不写盘；
  - 不同 → version+1，写 model/optimizer_model.json 与 model/history/YYYYMMDD.json；
  - 权重要 gate_status=evidence 才被消费方使用，本脚本只负责留档。

用法：
    cd platform/lab/content-optimizer-p0 && python3 scripts/retrain_daily.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_DIR = os.path.join(BASE_DIR, "scripts")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import analyze_p0b as p0b  # noqa: E402
import build_model as bm  # noqa: E402

MODEL_PATH = bm.MODEL_PATH
HISTORY_DIR = os.path.join(BASE_DIR, "model", "history")
CN_TZ = timezone(timedelta(hours=8))


def _now() -> str:
    return datetime.now(CN_TZ).isoformat(timespec="seconds")


def canonical(model: dict) -> str:
    """去掉生成时间与版本号后的规范化字符串，用于幂等比对。"""
    payload = {key: value for key, value in model.items() if key not in ("generated_at", "version")}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def diff_models(old: dict, new: dict) -> dict:
    old_rules = {rule.get("id"): rule for rule in old.get("rules") or []}
    new_rules = {rule.get("id"): rule for rule in new.get("rules") or []}
    weight_changes = []
    old_platforms = old.get("platforms") or {}
    for platform, block in (new.get("platforms") or {}).items():
        old_features = {
            f.get("name"): f for f in (old_platforms.get(platform) or {}).get("features") or []
        }
        for feature in block.get("features") or []:
            name = feature.get("name")
            before = float((old_features.get(name) or {}).get("weight") or 0.0)
            after = float(feature.get("weight") or 0.0)
            if before != after:
                weight_changes.append(
                    {"platform": platform, "feature": name, "from": before, "to": after}
                )
    old_source = old.get("source") or {}
    new_source = new.get("source") or {}
    return {
        "rules_added": sorted(set(new_rules) - set(old_rules)),
        "rules_removed": sorted(set(old_rules) - set(new_rules)),
        "weight_changes": weight_changes,
        "samples": {
            "rows_delta": int(new_source.get("rows") or 0) - int(old_source.get("rows") or 0),
            "deduped_delta": int(new_source.get("deduped") or 0)
            - int(old_source.get("deduped") or 0),
        },
        "gate_status": {"from": old.get("gate_status"), "to": new.get("gate_status")},
    }


def _read_json(path: str):
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def retrain(
    model_path: str = MODEL_PATH,
    history_dir: str = HISTORY_DIR,
    generated_at: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    rows=None,
    prep_info=None,
    gates=None,
    verdict=None,
) -> dict:
    """重建模型并按幂等口径写盘；返回状态字典供 CLI/测试断言。"""
    if rows is None or prep_info is None:
        rows, prep_info = p0b.build_rows()
    if gates is None:
        gates, verdict = bm.load_gates()
    new = bm.build_model(rows, prep_info, gates, verdict or "", generated_at=generated_at or _now())
    old = _read_json(model_path)

    if old is not None and not force and canonical(old) == canonical(new):
        return {
            "status": "no_change",
            "path": model_path,
            "version": old.get("version"),
            "generated_at": new["generated_at"],
        }

    new["version"] = int((old or {}).get("version") or 0) + 1
    drift = (
        diff_models(old, new)
        if old
        else {
            "rules_added": sorted(rule.get("id") for rule in new.get("rules") or []),
            "rules_removed": [],
            "weight_changes": [],
            "samples": {
                "rows_delta": new["source"]["rows"],
                "deduped_delta": new["source"]["deduped"],
            },
            "gate_status": {"from": None, "to": new.get("gate_status")},
        }
    )
    result = {
        "status": "updated",
        "path": model_path,
        "version": new["version"],
        "gate_status": new["gate_status"],
        "drift": drift,
    }
    if dry_run:
        result["status"] = "dry_run"
        return result

    bm.write_model(new, model_path)
    date_tag = str(new["generated_at"])[:10].replace("-", "")
    os.makedirs(history_dir, exist_ok=True)
    history_path = os.path.join(history_dir, "{}.json".format(date_tag))
    with open(history_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "date": date_tag,
                "version": new["version"],
                "generated_at": new["generated_at"],
                "drift": drift,
                "model": new,
            },
            fh,
            ensure_ascii=False,
            indent=2,
        )
        fh.write("\n")
    result["history"] = history_path
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="幂等重训 optimizer_model.json")
    parser.add_argument("--samples", default=p0b.SAMPLES_PATH, help="样本 CSV 路径")
    parser.add_argument("--go-no-go", default=bm.GO_NO_GO_PATH, help="go_no_go.json 路径")
    parser.add_argument("--model", default=MODEL_PATH, help="模型路径")
    parser.add_argument("--history-dir", default=HISTORY_DIR, help="历史目录")
    parser.add_argument("--force", action="store_true", help="内容相同也升版本")
    parser.add_argument("--dry-run", action="store_true", help="只比对不写盘")
    args = parser.parse_args(argv)

    p0b.SAMPLES_PATH = args.samples
    rows, prep_info = p0b.build_rows()
    gates, verdict = bm.load_gates(args.go_no_go)
    result = retrain(
        model_path=args.model,
        history_dir=args.history_dir,
        force=args.force,
        dry_run=args.dry_run,
        rows=rows,
        prep_info=prep_info,
        gates=gates,
        verdict=verdict,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
