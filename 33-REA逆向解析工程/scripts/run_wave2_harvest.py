#!/usr/bin/env python3
"""wave2（P1）外部真实源拉取，33 源。幂等：池中已有同 label 树则跳过。"""
import subprocess
import sys
import time

sys.path.insert(0, ".")
from core.reflection.harvest import ExternalHarvester, HarvestSource
from core.reflection.replay_simulator import ReplayPool

WAVE2 = [
    ("airbyte", "https://github.com/airbytehq/airbyte", "MIT"),
    ("OpenBB", "https://github.com/OpenBB-finance/OpenBB", "Apache-2.0"),
    ("sqlalchemy", "https://github.com/sqlalchemy/sqlalchemy", "MIT"),
    ("chroma", "https://github.com/chroma-core/chroma", "Apache-2.0"),
    ("bm25s", "https://github.com/xhluca/bm25s", "MIT"),
    ("llama_index", "https://github.com/run-llama/llama_index", "MIT"),
    ("mem0", "https://github.com/mem0ai/mem0", "Apache-2.0"),
    ("dspy", "https://github.com/stanfordnlp/dspy", "MIT"),
    ("pydeps", "https://github.com/thebjorn/pydeps", "BSD-2-Clause"),
    ("pycg", "https://github.com/vitsalis/PyCG", "MIT"),
    ("ast-grep", "https://github.com/ast-grep/ast-grep", "MIT"),
    ("jesse", "https://github.com/jesse-ai/jesse", "MIT"),
    ("freqtrade", "https://github.com/freqtrade/freqtrade", "GPL-3.0"),
    ("FinRL", "https://github.com/AI4Finance-Foundation/FinRL", "MIT"),
    ("shadcn-ui", "https://github.com/shadcn-ui/ui", "MIT"),
    ("vite", "https://github.com/vitejs/vite", "MIT"),
    ("TanStack-query", "https://github.com/TanStack/query", "MIT"),
    ("unsloth", "https://github.com/unslothai/unsloth", "Apache-2.0"),
    ("axolotl", "https://github.com/axolotl-ai-cloud/axolotl", "Apache-2.0"),
    ("temporal-sdk-python", "https://github.com/temporalio/sdk-python", "Apache-2.0"),
    ("autogen", "https://github.com/microsoft/autogen", "MIT"),
    ("dagster", "https://github.com/dagster-io/dagster", "Apache-2.0"),
    ("stevedore", "https://github.com/openstack/stevedore", "Apache-2.0"),
    ("semantic-kernel", "https://github.com/microsoft/semantic-kernel", "MIT"),
    ("ElegantRL", "https://github.com/AI4Finance-Foundation/ElegantRL", "MIT"),
    ("ai-hedge-fund", "https://github.com/virattt/ai-hedge-fund", "MIT"),
    ("causalml", "https://github.com/uber/causalml", "Apache-2.0"),
    ("timesfm", "https://github.com/google-research/timesfm", "Apache-2.0"),
    ("openai-swarm", "https://github.com/openai/swarm", "MIT"),
    ("ufo", "https://github.com/microsoft/UFO", "MIT"),
    ("anthropic-financial-services", "https://github.com/anthropics/financial-services", "MIT"),
    ("deepseek-harness", "https://github.com/deepseek-ai/deepseek-harness", "MIT"),
    ("superpowers", "https://github.com/obra/superpowers", "MIT"),
]

pool = ReplayPool("reflection_data/replay_pool")
harvester = ExternalHarvester(pool, work_dir="/tmp/rea_harvest")

# 幂等保护：池中已有同 label 外部树则跳过
existing_labels = {t.source_label for t in pool.list_trees("external")}
todo = [(l, u, lic) for l, u, lic in WAVE2 if l not in existing_labels]
skipped = len(WAVE2) - len(todo)
print(f"WAVE2_START total={len(WAVE2)} skipped_existing={skipped} todo={len(todo)}", flush=True)

sources = [HarvestSource(source_type="github_repo", location=url, label=label) for label, url, _ in todo]
t0 = time.time()
outcome = harvester.harvest(sources)
print(f"harvest done in {time.time() - t0:.1f}s", flush=True)
print(f"injected={len(outcome.injected_trees)} rejected={len(outcome.rejected)} errors={len(outcome.errors)}", flush=True)
for r in outcome.rejected:
    print(f"REJECTED {r}", flush=True)
for e in outcome.errors:
    print(f"ERROR {e}", flush=True)

# 元数据回填：按 source_label 从池中查找注入树（不依赖 inject_tree 返回值）
lic_map = {l: lic for l, _u, lic in WAVE2}
url_map = {l: u for l, u, _ in WAVE2}
new_labels = {t.source_label for t in pool.list_trees("external")} - existing_labels
filled = 0
for label in sorted(new_labels):
    matches = [t for t in pool.list_trees("external") if t.source_label == label]
    for t in matches[1:]:
        import os
        os.remove(f"reflection_data/replay_pool/external/{t.tree_id}.json")
        print(f"DEDUP_REMOVED {label} {t.tree_id}", flush=True)
    if not matches:
        continue
    t = matches[0]
    t.source_id = f"p1_{label}"
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

print(f"WAVE2_DONE injected={len(outcome.injected_trees)} meta_filled={filled}", flush=True)
