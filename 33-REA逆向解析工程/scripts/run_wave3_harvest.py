#!/usr/bin/env python3
"""wave3（P2）外部真实源拉取，43 源。源清单从 SPEC 附录 A 动态解析。幂等：池中已有同 label 树则跳过。"""
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, ".")
from core.reflection.harvest import ExternalHarvester, HarvestSource
from core.reflection.replay_simulator import ReplayPool

SPEC = "SPEC-33-外部真实源接入.md"
text = open(SPEC, encoding="utf-8").read()
# 列：类别|id|P|仓库|clone|语言|许可|上限MB|提取目标
WAVE3 = re.findall(
    r"^\|[^|]*\|\s*(\S+)\s*\| P2 \|\s*(https://github\.com/[^|]+?)\s*\|[^|]*\|[^|]*\|\s*([^|]+?)\s*\|",
    text, re.M,
)
assert len(WAVE3) == 43, f"expected 43 P2 sources, got {len(WAVE3)}"
print(f"WAVE3_PARSED sources={len(WAVE3)}", flush=True)

pool = ReplayPool("reflection_data/replay_pool")
harvester = ExternalHarvester(pool, work_dir="/tmp/rea_harvest")

existing_labels = {t.source_label for t in pool.list_trees("external")}
todo = [(l, u, lic) for l, u, lic in WAVE3 if l not in existing_labels]
skipped = len(WAVE3) - len(todo)
print(f"WAVE3_START total={len(WAVE3)} skipped_existing={skipped} todo={len(todo)}", flush=True)

sources = [HarvestSource(source_type="github_repo", location=url, label=label) for label, url, _ in todo]
t0 = time.time()
outcome = harvester.harvest(sources)
print(f"harvest done in {time.time() - t0:.1f}s", flush=True)
print(f"injected={len(outcome.injected_trees)} rejected={len(outcome.rejected)} errors={len(outcome.errors)}", flush=True)
for r in outcome.rejected:
    print(f"REJECTED {r}", flush=True)
for e in outcome.errors:
    print(f"ERROR {e}", flush=True)

lic_map = {l: lic for l, _u, lic in WAVE3}
url_map = {l: u for l, u, _ in WAVE3}
new_labels = {t.source_label for t in pool.list_trees("external")} - existing_labels
filled = 0
for label in sorted(new_labels):
    matches = [t for t in pool.list_trees("external") if t.source_label == label]
    for t in matches[1:]:
        os.remove(f"reflection_data/replay_pool/external/{t.tree_id}.json")
        print(f"DEDUP_REMOVED {label} {t.tree_id}", flush=True)
    if not matches:
        continue
    t = matches[0]
    t.source_id = f"p2_{label}"
    t.repo_url = url_map.get(label, "")
    t.license = lic_map.get(label, "")
    t.collected_at = int(time.time() * 1000)
    try:
        c = subprocess.run(
            ["git", "-C", f"/tmp/rea_harvest/{label}", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30,
        )
        t.commit = c.stdout.strip()
    except Exception as exc:
        print(f"COMMIT_FAIL {label}: {exc}", flush=True)
    pool.save(t)
    filled += 1
    print(f"META_FILLED {label} commit={t.commit[:12]}", flush=True)

print(f"WAVE3_DONE injected={len(outcome.injected_trees)} meta_filled={filled}", flush=True)
