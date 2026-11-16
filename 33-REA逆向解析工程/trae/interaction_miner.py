"""Interaction Miner — 从会话摘要 / 命令信封 / 快照中提取交互案例与基线。

纪律：
- `intent/actions/outcome/learned` 是模型压缩摘要，属 inference，不是原始对话。
- 命令信封与快照是 observation；本轮不做逐会话因果归因（缺少 session_id 关联）。
- 任何缺口候选都必须带 source_file + line_no，便于回查。
"""

from __future__ import annotations

import json
import re
import statistics
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from .common import MEMORY_ROOT, TRAE_DATA, evidence

ACTION_RULES = [
    ("read_analyze", r"分析|阅读|查看|调研|核对|检索|扫描|盘点|梳理|复查"),
    ("edit_write", r"修改|新增|写入|实现|重构|创建|删除|替换|修复"),
    ("test_verify", r"测试|验证|回归|验收|复跑|检查|对比"),
    ("run_deploy", r"启动|运行|部署|重启|提交|推送|同步|安装"),
    ("doc_config", r"文档|索引|配置|规范|登记|更新"),
    ("coordinate", r"评审|讨论|确认|对齐|决策|协作"),
]
GAP_RE = re.compile(r"缺少|未实现|未完成|尚未|缺口|需要补|待补|TODO|未接入|未覆盖")
THEME_RULES = [
    ("路由/分层", r"路由|L0|L1|L2|分层|registry|注册表"),
    ("门禁/验收", r"门禁|验收|判定|校验|回归|通过率"),
    ("trace/观测", r"trace|观测|埋点|日志|span|透传"),
    ("数据/检索", r"数据|检索|索引|向量|sqlite|RAG|库"),
    ("前端/接口", r"前端|接口|API|页面|组件|UI|tab"),
    ("MCP/工具", r"MCP|工具|插件|skill|Skill"),
    ("部署/云端", r"部署|云端|CI|环境|配置|venv"),
    ("文档/规范", r"文档|SPEC|规范|索引|修订"),
]


def _classify(text: str, rules: list[tuple[str, str]]) -> str:
    for name, pat in rules:
        if re.search(pat, text or ""):
            return name
    return "other"


def _discover_project(memory_project: str | None) -> Path:
    if memory_project:
        return Path(memory_project)
    preferred = (
        MEMORY_ROOT / "-Users-zhangjiangtao-WorkBuddy-dreambuddy-v2--p2-5f8e8db8067187fd2690"
    )
    if preferred.exists():
        return preferred
    fallback = MEMORY_ROOT / "-Users-zhangjiangtao-WorkBuddy-dreambuddy-v2"
    return fallback if fallback.exists() else MEMORY_ROOT


def _session_files(project: Path, limit_sessions: int) -> list[Path]:
    files = sorted(
        project.glob("2*/session_memory_*.jsonl"), key=lambda p: (p.parent.name, p.stat().st_mtime)
    )
    return files[-limit_sessions:]


def _parse_session(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            d["_line_no"] = line_no
            d["_file"] = str(path)
            rows.append(d)
    return rows


def _execution_stats() -> dict[str, Any]:
    root = TRAE_DATA / "command-execution"
    files = list(root.glob("*/execution.json"))
    status = Counter()
    cwd = Counter()
    target = Counter()
    durations: list[int] = []
    terminal = Counter()
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            continue
        status[d.get("status")] += 1
        cwd[d.get("cwd")] += 1
        target[d.get("target")] += 1
        terminal[d.get("terminalReason")] += 1
        if d.get("startedAtMs") and d.get("finishedAtMs"):
            durations.append(int(d["finishedAtMs"] - d["startedAtMs"]))
    durations.sort()

    def pct(p: float) -> int | None:
        if not durations:
            return None
        return durations[min(len(durations) - 1, int(len(durations) * p))]

    return {
        "count": len(files),
        "status": dict(status),
        "target": dict(target),
        "terminal_reason": dict(terminal),
        "top_cwd": cwd.most_common(5),
        "duration_ms": {
            "median": int(statistics.median(durations)) if durations else None,
            "p90": pct(0.9),
            "max": max(durations) if durations else None,
        },
    }


def _snapshot_stats() -> dict[str, Any]:
    root = TRAE_DATA / "snapshot"
    dirs = [d for d in root.glob("*") if d.is_dir()]
    repos: list[dict[str, Any]] = []
    for d in dirs:
        git_dir = d / "v2/.git"
        if not git_dir.exists():
            continue
        try:
            out = subprocess.run(
                ["git", "-C", str(d / "v2"), "log", "-1", "--format=%ct|%h|%s"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
        except Exception:
            out = ""
        if out:
            ts, h, subj = (out.split("|", 2) + ["", ""])[:3]
            repos.append(
                {"session": d.name, "last_commit": h, "last_ts": ts, "subject": subj[:120]}
            )
    return {"count": len(dirs), "repos": len(repos), "sample": repos[:10]}


def run_interaction_miner(limit_sessions: int = 50, project: str | None = None) -> dict[str, Any]:
    project_path = _discover_project(project)
    sessions = _session_files(project_path, limit_sessions)
    cases: list[dict[str, Any]] = []
    action_counter: Counter = Counter()
    gap_counter: Counter = Counter()
    theme_counter: Counter = Counter()
    gap_samples: dict[str, dict[str, Any]] = {}
    outcomes = 0
    records = 0

    for sess in sessions:
        session_id = sess.stem.replace("session_memory_", "")
        for d in _parse_session(sess):
            records += 1
            actions = d.get("actions", []) or []
            learned = d.get("learned", []) or []
            intent = str(d.get("intent", ""))
            outcome = str(d.get("outcome", ""))
            if outcome:
                outcomes += 1
            for a in actions:
                action_counter[_classify(str(a), ACTION_RULES)] += 1
            for learned_item in learned:
                text = str(learned_item)
                if GAP_RE.search(text):
                    key = text[:120]
                    gap_counter[key] += 1
                    for theme, pat in THEME_RULES:
                        if re.search(pat, text):
                            theme_counter[theme] += 1
                    gap_samples.setdefault(
                        key,
                        {
                            "text": text,
                            "session_id": session_id,
                            "file": str(sess),
                            "line_no": d.get("_line_no"),
                        },
                    )
            cases.append(
                {
                    "case_id": f"{session_id}-{d.get('_line_no')}",
                    "session_id": session_id,
                    "intent": intent,
                    "actions": actions,
                    "outcome": outcome,
                    "learned": learned,
                    "timestamp": d.get("message_summary_time"),
                    "metrics": {
                        "actions": len(actions),
                        "learned": len(learned),
                        "outcome_chars": len(outcome),
                        "has_outcome": bool(outcome),
                    },
                    "evidence": {
                        "level": "inference",
                        "source_file": str(sess),
                        "line_no": d.get("_line_no"),
                        "known_gaps": [
                            "摘要由模型生成，非原始对话",
                            "无法关联到具体工具调用/token",
                        ],
                    },
                }
            )

    exec_stats = _execution_stats()
    snap_stats = _snapshot_stats()
    top_gaps = [{"text": k, "count": v, **gap_samples[k]} for k, v in gap_counter.most_common(20)]

    ev = [
        evidence(
            {"sessions": len(sessions), "records": records, "project": str(project_path)},
            "observation",
            {"source": "session_memory", "path": str(project_path)},
            known_gaps=["只统计有摘要的会话", "未包含原始 DB（加密）"],
        ),
        evidence(
            {
                "avg_actions": (
                    round(sum(len(c["actions"]) for c in cases) / records, 2) if records else 0
                ),
                "avg_learned": (
                    round(sum(len(c["learned"]) for c in cases) / records, 2) if records else 0
                ),
                "outcome_rate": round(outcomes / records, 3) if records else 0,
            },
            "derivation",
            {"source": "interaction-miner", "records": records},
            confidence=0.7,
            known_gaps=["摘要是模型压缩结果，存在遗漏与自我合理化"],
        ),
        evidence(
            exec_stats,
            "observation",
            {"source": "command-execution", "path": str(TRAE_DATA / "command-execution")},
        ),
        evidence(
            snap_stats, "observation", {"source": "snapshot", "path": str(TRAE_DATA / "snapshot")}
        ),
    ]

    return {
        "summary": f"最近 {len(sessions)} 个会话 / {records} 条交互记录；命令 {exec_stats['count']} 条；快照 {snap_stats['count']} 个",
        "project": str(project_path),
        "sessions": [str(s) for s in sessions],
        "cases": cases,
        "metrics": {
            "session_count": len(sessions),
            "record_count": records,
            "outcome_rate": round(outcomes / records, 3) if records else 0,
            "action_categories": dict(action_counter),
            "gap_themes": dict(theme_counter.most_common()),
            "top_gaps": top_gaps,
        },
        "execution": exec_stats,
        "snapshots": snap_stats,
        "evidence": ev,
    }
