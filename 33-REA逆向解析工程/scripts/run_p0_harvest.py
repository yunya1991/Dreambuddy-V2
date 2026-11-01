#!/usr/bin/env python3
"""P0 波次外部真实源拉取（SPEC-33-外部真实源接入 附录 A wave1，11 源）。"""
import subprocess
import sys
import time

sys.path.insert(0, ".")
from core.reflection.harvest import ExternalHarvester, HarvestSource
from core.reflection.replay_simulator import ReplayPool

P0_SOURCES = [
    ("dlt", "https://github.com/dlt-hub/dlt", "Apache-2.0"),
    ("sqlite-utils", "https://github.com/simonw/sqlite-utils", "Apache-2.0"),
    ("whoosh", "https://github.com/mchaput/whoosh", "BSD-2-Clause"),
    ("letta", "https://github.com/letta-ai/letta", "Apache-2.0"),
    ("code2flow", "https://github.com/scottrogowski/code2flow", "MIT"),
    ("backtrader", "https://github.com/mementum/backtrader", "GPL-3.0"),
    ("zustand", "https://github.com/pmndrs/zustand", "MIT"),
    ("peft", "https://github.com/huggingface/peft", "Apache-2.0"),
    ("langgraph", "https://github.com/langchain-ai/langgraph", "MIT"),
    ("mcp-python-sdk", "https://github.com/modelcontextprotocol/python-sdk", "MIT"),
    ("pluggy", "https://github.com/pytest-dev/pluggy", "MIT"),
]

pool = ReplayPool("reflection_data/replay_pool")
harvester = ExternalHarvester(pool, work_dir="/tmp/rea_harvest")
sources = [
    HarvestSource(source_type="github_repo", location=url, label=label)
    for label, url, _lic in P0_SOURCES
]

print("P0_HARVEST_START", flush=True)
t0 = time.time()
outcome = harvester.harvest(sources)
print(f"harvest done in {time.time() - t0:.1f}s", flush=True)
print(f"injected={len(outcome.injected_trees)} rejected={len(outcome.rejected)} errors={len(outcome.errors)}", flush=True)
for r in outcome.rejected:
    print(f"REJECTED {r}", flush=True)
for e in outcome.errors:
    print(f"ERROR {e}", flush=True)

# A2 元数据回填：source_id/repo_url/commit/license/collected_at
lic_map = {label: lic for label, _url, lic in P0_SOURCES}
url_map = {label: url for label, url, _lic in P0_SOURCES}
for tree_id in outcome.injected_trees:
    tree = pool.load(tree_id)
    if tree is None:
        continue
    label = tree.source_label or ""
    tree.source_id = f"p0_{label}"
    tree.repo_url = url_map.get(label, "")
    tree.license = lic_map.get(label, "")
    tree.collected_at = int(time.time() * 1000)
    dest = f"/tmp/rea_harvest/{label}"
    try:
        commit = subprocess.run(
            ["git", "-C", dest, "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30,
        )
        tree.commit = commit.stdout.strip()
    except Exception as exc:
        print(f"commit lookup failed for {label}: {exc}", flush=True)
    pool.save(tree)
    print(f"META_FILLED {label} commit={tree.commit[:12]}", flush=True)

print(f"P0_HARVEST_DONE injected={len(outcome.injected_trees)}", flush=True)
