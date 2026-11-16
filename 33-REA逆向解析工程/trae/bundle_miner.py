"""Bundle Miner — 对压缩 JS 做字符串级取证，不做结构断言。

目标：只回答「哪些工具 ID / mode / 停止原因字符串出现在 bundle 中」，
不回答「模块依赖 / 调用链 / 架构模式」。所有结论为 observation 级；
涉及语义的结论必须标 inference，并保留 known_gaps。
"""

from __future__ import annotations

import re
from typing import Any

from .common import TRAE_APP, evidence

BUNDLE_CANDIDATES = [
    TRAE_APP / "out/vs/workbench/workbench.desktop.main.js",
    TRAE_APP / "out/vs/workbench/workbench.desktop.main.solo-lite-slim.js",
    TRAE_APP / "extensions/ai-completion/dist/extension.js",
]

# 仅作为「候选词表」，命中不等于该工具存在；需要人工/bundle 上下文复核。
TOOL_KEYWORDS = [
    "runSubagent",
    "readFile",
    "writeFile",
    "runCommand",
    "Exec",
    "create_file",
    "delete_file",
    "view_file",
    "file_search",
    "browser_navigate",
    "browser_snapshot",
    "browser_click",
    "browser_take_screenshot",
    "GenerateImage",
    "GenerateVideo",
    "Schedule",
    "RequestAuthorization",
    "recall",
    "record",
    "verify",
]
MODE_KEYWORDS = [
    "solo_agent",
    "solo_agent_lite",
    "solo_work_lite",
    "solo_design_lite",
    "Explore",
    "Plan",
    "general_purpose_task",
    "browser_use",
    "computer_use",
]
STOP_KEYWORDS = [
    "stop_reason",
    "stopReason",
    "finishReason",
    "abortReason",
    "interrupted",
    "parked",
    "max_steps",
    "maxSteps",
    "stepCount",
]


def _count_keywords(text: str, keywords: list[str]) -> dict[str, int]:
    return {k: len(re.findall(re.escape(k), text)) for k in keywords}


def _extract_tool_ids(text: str, limit: int = 200) -> list[str]:
    """提取 toolId/toolName 的字符串字面量候选。"""
    found: list[str] = []
    for m in re.finditer(
        r'tool(?:Id|Name)\s*(?:===|!==|==|!=|[:=])\s*["\']([A-Za-z0-9_.\-]{2,60})["\']', text
    ):
        found.append(m.group(1))
    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for x in found:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out[:limit]


def _sample_contexts(text: str, keyword: str, limit: int = 3, width: int = 140) -> list[str]:
    samples: list[str] = []
    for m in re.finditer(re.escape(keyword), text):
        start = max(0, m.start() - width)
        end = min(len(text), m.end() + width)
        samples.append(text[start:end].replace("\n", " "))
        if len(samples) >= limit:
            break
    return samples


def run_bundle_miner() -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    evidences: list[dict[str, Any]] = []
    all_tool_ids: set[str] = set()
    for path in BUNDLE_CANDIDATES:
        if not path.exists():
            evidences.append(
                evidence(
                    {"file": str(path), "exists": False},
                    "observation",
                    {"source": "filesystem", "path": str(path)},
                    known_gaps=["文件不存在，无法分析"],
                )
            )
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        tool_counts = _count_keywords(text, TOOL_KEYWORDS)
        mode_counts = _count_keywords(text, MODE_KEYWORDS)
        stop_counts = _count_keywords(text, STOP_KEYWORDS)
        tool_ids = _extract_tool_ids(text)
        all_tool_ids.update(tool_ids)
        files.append(
            {
                "file": str(path),
                "bytes": path.stat().st_size,
                "lines": text.count("\n") + 1,
                "tool_keyword_hits": {k: v for k, v in tool_counts.items() if v},
                "mode_keyword_hits": {k: v for k, v in mode_counts.items() if v},
                "stop_keyword_hits": {k: v for k, v in stop_counts.items() if v},
                "tool_id_candidates": tool_ids,
                "samples": {k: _sample_contexts(text, k) for k, v in tool_counts.items() if v},
            }
        )
        evidences.append(
            evidence(
                {
                    "file": str(path),
                    "bytes": path.stat().st_size,
                    "tool_keyword_hits": sum(tool_counts.values()),
                    "tool_id_candidates": len(tool_ids),
                },
                "observation",
                {"source": "bundle-string-scan", "path": str(path)},
                known_gaps=[
                    "压缩 bundle 无法建立模块/调用图；关键词命中只说明字符串出现",
                    "toolId 提取依赖正则，可能漏掉压缩后的别名",
                ],
            )
        )

    summary = (
        f"扫描 {len(files)} 个 bundle；toolId 候选 {len(all_tool_ids)} 个；"
        "仅字符串级 observation，不可作为架构结论"
    )
    evidences.append(
        evidence(
            summary,
            "derivation",
            {"source": "bundle-miner", "files": len(files)},
            confidence=0.6,
            known_gaps=["未覆盖原生/远端 Agent 运行时", "未解析 WASM / native 模块"],
        )
    )
    return {
        "summary": summary,
        "files": files,
        "all_tool_id_candidates": sorted(all_tool_ids),
        "evidence": evidences,
    }
