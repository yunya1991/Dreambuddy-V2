#!/usr/bin/env python3
"""调研文档 → 外部源清单：自动抽取 / 去重 / 归类 / 登记 / 知识库归档（无人值守）。

对应 SPEC-33-外部源自动沉淀流水线 S1→S3→S2：
  S1 抽取：扫描文档，正则抽 github.com/owner/repo
  S2 去重：幂等键 = location（小写去尾斜杠）
  S3 归类：owner/repo + 文档路径关键词打分，映射到 10 大类
  S4 登记：atomic upsert 到 reflection_data/external_sources.json（文件锁）
  S5 归档：2-KNOWLEDGE/7-EXTERNAL-RESEARCH/external-sources/<category>/<id>.md（只新增）
  S6 报告：reflection_data/sync_reports/<date>.json

用法：
  python scripts/sync_external_sources.py --dry-run
  python scripts/sync_external_sources.py --unattended --roots 1-ARCHITECTURE 2-KNOWLEDGE/7-EXTERNAL-RESEARCH
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REA_DIR = PROJECT_ROOT / "33-REA逆向解析工程"
SOURCES_JSON = REA_DIR / "reflection_data" / "external_sources.json"
REPORT_DIR = REA_DIR / "reflection_data" / "sync_reports"
INBOX_DIR = REA_DIR / "reflection_data" / "inbox"
INBOX_FILE = INBOX_DIR / "external_sources.local.json"
KB_DIR = PROJECT_ROOT / "2-KNOWLEDGE" / "7-EXTERNAL-RESEARCH" / "external-sources"
DEFAULT_ROOTS = ["."]  # 全仓扫描，依赖库文档由 NOISE_MARKERS 排除

URL_RE = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")
SKIP_OWNER = {"topics", "search", "features", "about", "login", "orgs", "sponsors"}
# 占位符 / 自引用仓库：不是外部项目
PLACEHOLDER_OWNERS = {"your-username", "your-org", "your-name", "org", "owner", "user", "example"}
SELF_REPOS = {"yunya1991/dreambuddy-v2"}
# 依赖库文档目录：其中的 GitHub 链接是第三方依赖，不是本系统调研结论
NOISE_MARKERS = (
    "node_modules", ".venv", "site-packages", "/dist/", "/build/", ".git/",
    "third_party", "vendor", ".trae-cn", "package-lock", "pnpm-lock", "yarn.lock",
)

# 归类关键词（owner/repo 全名命中，按顺序优先匹配更具体类目）
CATEGORY_RULES: dict[str, list[str]] = {
    "reverse_engineering": [
        "code2flow", "pydeps", "pycg", "ast-grep", "pyright", "semgrep", "tree-sitter",
        "call-graph", "reverse", "decompil",
    ],
    "dsh": [
        "mcp", "pluggy", "stevedore", "semantic-kernel", "aider", "superpowers",
        "harness", "skill", "subagent", "claude-code", "browser-use", "browser-skill",
        "agent-skill-router", "grok-build", "hermes-agent",
    ],
    "dreamos": [
        "langgraph", "temporal", "autogen", "dagster", "airflow", "prefect", "crewai",
        "openhands", "metagpt", "ufo", "swarm", "swe-agent", "agent-os", "autogpt",
        "auto-gpt",
    ],
    "search_engine": [
        "whoosh", "bm25", "llama_index", "llama-index", "graphrag", "txtai", "langchain",
        "retrieval", "rag", "vector-search", "search-engine",
    ],
    "database": [
        "sqlite", "sqlalchemy", "chroma", "duckdb", "postgres", "clickhouse", "lancedb",
        "database", "orm", "kafka", "eventstore", "event-store", "neo4j",
        "graph-data-science", "feast",
    ],
    "data_acquisition": [
        "dlt", "airbyte", "openbb", "scrapy", "akshare", "tavily", "ingest", "etl",
        "collector", "crawler",
    ],
    "cognitive_system": [
        "letta", "mem0", "dspy", "reflexion", "cognitive", "memory", "rasa", "knowledge-graph",
    ],
    "frontend": [
        "zustand", "shadcn", "vite", "tanstack", "next.js", "nextjs", "react", "vue",
        "frontend", "tailwind",
    ],
    "llm_training": [
        "peft", "unsloth", "axolotl", "lightning", "vllm", "transformers", "timesfm",
        "nixtla", "time-moe", "moment", "neural-sde", "signature", "signatory", "bert",
        "finbert", "fingpt", "llm", "training", "finetune",
        "ymcui", "macbert", "electra", "xlnet", "textbrewer", "hfl", "chinese-bert",
    ],
    "finance_models": [
        "backtrader", "jesse", "freqtrade", "vnpy", "qlib", "finrl", "tradingagents",
        "finrobot", "hedge-fund", "regime", "skfolio", "causalml", "nautilus", "finclaw",
        "trading", "quant", "portfolio", "alpha",
        "vectorbt", "darts", "statsmodels", "evidently", "whylogs", "market-regime",
    ],
}

LANGS = {"py": "Python", "ts": "TypeScript"}


def _log(msg: str) -> None:
    print(f"[sync] {msg}", flush=True)


def _norm(location: str) -> str:
    return location.rstrip("/").lower()


def extract_urls(docs: list[Path]) -> list[tuple[str, str, str]]:
    """返回 [(location, owner_repo, doc_path)]，去重按 location（保留首个来源）。"""
    found: dict[str, tuple[str, str, str]] = {}
    for doc in docs:
        try:
            text = doc.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in URL_RE.finditer(text):
            owner, repo = m.group(1), m.group(2)
            if owner.lower() in SKIP_OWNER or owner.lower() in PLACEHOLDER_OWNERS:
                continue
            if f"{owner}/{repo}".lower() in SELF_REPOS:
                continue
            repo = re.sub(r"\.git$", "", repo)
            loc = f"https://github.com/{owner}/{repo}"
            key = _norm(loc)
            if key not in found:
                found[key] = (loc, f"{owner}/{repo}", str(doc.relative_to(PROJECT_ROOT)))
    return list(found.values())


def classify(owner_repo: str, doc_path: str) -> str:
    """关键词打分归类；文档路径作为次级信号；无命中默认 finance_models（本库主域）。"""
    hay = f"{owner_repo} {doc_path}".lower()
    scores: Counter[str] = Counter()
    for cat, kws in CATEGORY_RULES.items():
        for kw in kws:
            if kw.lower() in hay:
                scores[cat] += 2 if kw.lower() in owner_repo.lower() else 1
    if not scores:
        return "finance_models"
    best = max(scores.values())
    winners = [c for c, v in scores.items() if v == best]
    return winners[0] if len(winners) == 1 else ("finance_models" if "finance_models" in winners else winners[0])


def make_id(owner_repo: str, taken: set[str]) -> str:
    base = owner_repo.split("/")[1].lower()
    base = re.sub(r"[^a-z0-9._-]+", "-", base).strip("-") or "repo"
    cand, n = base, 2
    while cand in taken:
        cand = f"{base}-{n}"
        n += 1
    return cand


def build_entry(loc: str, owner_repo: str, doc_path: str, cat: str, taken: set[str]) -> dict:
    repo_id = make_id(owner_repo, taken)
    return {
        "id": repo_id,
        "category": cat,
        "level": "candidate",
        "priority": "P3",
        "wave": 4,
        "source_type": "github_repo",
        "location": loc,
        "label": owner_repo,
        "language": "unknown",
        "license": "unknown",
        "patterns": ["src", "docs"],
        "expected_analyzers": ["architecture_pattern_detector", "python_analyzer"],
        "extract_target": "待人工补全（自动抽取，未评估架构映射）",
        "size_cap_mb": 50,
        "discovered_from": doc_path,
        "discovered_at": dt.date.today().isoformat(),
        "verified": False,
    }


def load_json() -> dict:
    return json.loads(SOURCES_JSON.read_text(encoding="utf-8"))


def save_json_atomic(data: dict) -> None:
    lock_path = SOURCES_JSON.with_suffix(".json.lock")
    with open(lock_path, "w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        tmp = SOURCES_JSON.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, SOURCES_JSON)
        fcntl.flock(lock_fd, fcntl.LOCK_UN)


def archive_stub(entry: dict) -> Path | None:
    """知识库归档 stub（HC-8 只新增不修改）。"""
    path = KB_DIR / entry["category"] / f"{entry['id']}.md"
    if path.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    body = f"""---
source_type: external_repo
repo_url: {entry['location']}
repo_id: {entry['id']}
category: {entry['category']}
license: {entry['license']}
stars: null
discovered_from: {entry['discovered_from']}
discovered_at: {entry['discovered_at']}
rea_wave: {entry['wave']}
verified: false
---

# {entry['label']}

- 仓库：{entry['location']}
- 归类：{entry['category']}（自动归类，待人工复核）
- 抽取目标：{entry['extract_target']}

## 历次调研结论

- {entry['discovered_at']} 自动抽取自 `{entry['discovered_from']}`，尚未评估架构映射。
"""
    path.write_text(body, encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--roots", nargs="*", default=DEFAULT_ROOTS)
    ap.add_argument("--emit-inbox", action="store_true",
                    help="本地模式：只写 inbox 提案，不改主清单（主清单唯一写者是云端）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-new", type=int, default=50, help="单次新增上限（超出告警并截断）")
    args = ap.parse_args()
    unattended = True  # D4：无人值守，不再设人工确认门禁

    docs: list[Path] = []
    for root in args.roots:
        root_path = PROJECT_ROOT / root if not os.path.isabs(root) else Path(root)
        if root_path.is_dir():
            docs.extend(
                d for d in sorted(root_path.rglob("*.md"))
                if not any(k in str(d) for k in NOISE_MARKERS)
            )
    _log(f"docs_scanned={len(docs)}")

    found = extract_urls(docs)
    _log(f"urls_found={len(found)}")

    data = load_json()
    dims = data["dimensions"]
    existing = {_norm(s["location"]): s for s in data["sources"]}
    taken_ids = {s["id"] for s in data["sources"]}

    new_items, updated, skipped = [], [], 0
    for loc, owner_repo, doc_path in found:
        key = _norm(loc)
        if key in existing:
            cur = existing[key]
            changed = False
            if not cur.get("discovered_from"):
                cur["discovered_from"] = doc_path
                changed = True
            if cur.get("verified") is None:
                cur["verified"] = False
                changed = True
            if changed:
                updated.append({"id": cur["id"], "location": loc})
            else:
                skipped += 1
            continue
        cat = classify(owner_repo, doc_path)
        cat = cat if cat in dims else "finance_models"
        entry = build_entry(loc, owner_repo, doc_path, cat, taken_ids)
        taken_ids.add(entry["id"])
        new_items.append(entry)

    truncated = False
    if len(new_items) > args.max_new:
        _log(f"ALERT new_items={len(new_items)} 超过上限 {args.max_new}，截断（需人工复核）")
        new_items = new_items[: args.max_new]
        truncated = True

    do_write = not args.dry_run
    if do_write and args.emit_inbox:
        INBOX_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "generator": "local",
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "base_schema": data.get("version"),
            "sources": new_items,
        }
        tmp = INBOX_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, INBOX_FILE)
        _log(f"inbox={INBOX_FILE.relative_to(PROJECT_ROOT)} new={len(new_items)}")
    elif do_write and new_items:
        data["sources"].extend(new_items)
        data["version"] = data.get("version", "2.1")
        data["generated_at"] = dt.date.today().isoformat()
        save_json_atomic(data)

    archived = []
    if do_write:
        for entry in new_items:
            p = archive_stub(entry)
            if p:
                archived.append(str(p.relative_to(PROJECT_ROOT)))

    report = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "dry_run": args.dry_run,
        "roots": args.roots,
        "docs_scanned": len(docs),
        "urls_found": len(found),
        "total_sources": len(data["sources"]),
        "new": len(new_items),
        "updated": len(updated),
        "skipped": skipped,
        "truncated": truncated,
        "new_items": [{"id": e["id"], "location": e["location"], "category": e["category"]} for e in new_items],
        "updated_items": updated,
        "archived": archived,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"{dt.date.today().isoformat()}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"new={len(new_items)} updated={len(updated)} skipped={skipped} total={len(data['sources'])}")
    _log(f"report={report_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
