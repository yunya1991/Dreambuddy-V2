#!/usr/bin/env python3
"""X1 验证指标计算入口（骨架）：强制过滤真实源记录，检查样本量门槛。

SPEC 边界红线 6：代理信号(12_proxy)记录仅验证管道用途，不得进入任何验证指标或报告。
X1 完整四项指标（方向准确率/方向IC/概率校准度/分周期段表现）待 X0 意图流
积累 >= 2 周且样本 >= 100 笔后启用；本入口当前输出样本量门槛检查与方向分布。
"""
import json
import os
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
CONFIG_PATH = os.path.join(BASE, "config.json")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    cfg = load_json(CONFIG_PATH)
    vm = cfg["validation_metrics"]
    allowed = set(vm["allowed_sources"])
    trades_path = os.path.join(ROOT, cfg["output"]["trades"])

    records = []
    excluded = 0
    if os.path.exists(trades_path):
        with open(trades_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                src = (r.get("signal_snapshot") or {}).get("source")
                if src in allowed:
                    records.append(r)
                else:
                    excluded += 1

    dates = sorted({r.get("intent_date") for r in records if r.get("intent_date")})
    n_days = len(dates)
    # 覆盖周数：首末日期跨度（粗略，X1 正式启用时按自然周计）
    span_days = 0
    if dates:
        from datetime import date as _d
        d0 = _d.fromisoformat(dates[0])
        d1 = _d.fromisoformat(dates[-1])
        span_days = (d1 - d0).days + 1
    weeks = span_days / 7.0

    dist = {}
    for r in records:
        d = (r.get("intent") or {}).get("direction", "N/A")
        dist[d] = dist.get(d, 0) + 1

    gate = {
        "samples": len(records),
        "min_samples": vm["min_samples"],
        "samples_ok": len(records) >= vm["min_samples"],
        "weeks": round(weeks, 2),
        "min_weeks": vm["min_weeks"],
        "weeks_ok": weeks >= vm["min_weeks"],
        "distinct_days": n_days,
    }
    gate["x1_ready"] = gate["samples_ok"] and gate["weeks_ok"]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stage": "X1-entry",
        "allowed_sources": sorted(allowed),
        "excluded_proxy_records": excluded,
        "direction_distribution": dist,
        "gate": gate,
        "note": "代理信号记录已强制排除；X1 四项指标待门槛满足后启用",
    }
    out = os.path.join(ROOT, "x1_metrics_status.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
