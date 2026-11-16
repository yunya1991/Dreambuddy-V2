"""R3 差距映射 — 把 M1–M5 映射到 56 GAP/门禁/契约，产出候选缺口。

原则：
- 先映射现有 GAP，确认「已覆盖/部分覆盖/未覆盖」，避免重复开缺口。
- 新候选统一用 `GAP-T*` 前缀，状态 `candidate`，不直接改 56 官方 GAP 表。
- 每条候选必须有 `contract_ref`、`evidence_refs`、`proposed_check`。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .common import write_json

MECHANISM_MAP = [
    {
        "mechanism": "M1",
        "name": "agent_type × model → skill bundle",
        "observed": "manifest 按 agent_type/model 两层装配 skills；L2 无等价的模型感知装配。",
        "existing": ["GAP-02", "GAP-13", "GAP-19"],
        "gates": ["G-L2-1", "G-L2-6"],
        "contracts": ["IF-1", "IF-7"],
        "verdict": "部分覆盖（缺模型维度与 bundle 标识）",
        "candidate": "GAP-T1",
    },
    {
        "mechanism": "M2",
        "name": "session × mode → tool_set 快照",
        "observed": "工具按会话+mode 物化；L2 有单一快照（A1-2），缺会话级版本/差异审计。",
        "existing": ["GAP-19", "GAP-23", "GAP-25"],
        "gates": ["G-L2-11"],
        "contracts": ["IF-7"],
        "verdict": "部分覆盖（契约已有，版本/审计缺）",
        "candidate": "GAP-T2",
    },
    {
        "mechanism": "M3",
        "name": "command → sandbox envelope",
        "observed": "命令信封有 ownerHash/退出码/受限路径，但无 trace_id/session_id。",
        "existing": ["GAP-01", "GAP-24", "GAP-30"],
        "gates": ["G-L2-8"],
        "contracts": ["IF-3", "IF-7"],
        "verdict": "契约覆盖，归因字段缺失（阻塞 R2 门禁）",
        "candidate": "GAP-T3",
    },
    {
        "mechanism": "M4",
        "name": "session → checkpoint",
        "observed": "19 个 git 快照；L2 Ticket 有 paused，但无 checkpoint 契约与恢复验证。",
        "existing": ["GAP-20", "GAP-24"],
        "gates": ["G-L2-10"],
        "contracts": ["IF-4", "ADR-10"],
        "verdict": "未覆盖（缺 checkpoint 契约）",
        "candidate": "GAP-T4",
    },
    {
        "mechanism": "M5",
        "name": "session → summary memory",
        "observed": "627 条摘要案例；learned 为 inference，未接入训练/台账，缺证据门控。",
        "existing": ["GAP-15", "GAP-29"],
        "gates": ["G-L2-5", "G-L2-7"],
        "contracts": ["IF-5", "ADR-06"],
        "verdict": "部分覆盖（缺证据门控与训练接线）",
        "candidate": "GAP-T5",
    },
]

CANDIDATES = [
    {
        "gap_id": "GAP-T1",
        "title": "能力装配缺少「模型感知的 skill/tool bundle」标识",
        "layer": "L2",
        "severity": "P1",
        "mechanism": "M1",
        "existing_gaps": ["GAP-02", "GAP-13", "GAP-19"],
        "contract_ref": ["IF-1 route_signal", "IF-7 tool_set", "ADR-09"],
        "proposed_check": [
            "route_signal 必须含 capability_bundle_id 与 model_profile",
            "tool_set 快照必须引用 skill_bundle_id",
            "无 bundle 时不得静默降级，必须回 L1 或标 needs_review",
        ],
        "promotion_note": "先核对 GAP-02/GAP-13 的 l2_route 实现，避免与裁决层重复开缺口。",
    },
    {
        "gap_id": "GAP-T2",
        "title": "tool_set 只有单快照，无会话级版本/差异审计",
        "layer": "L2",
        "severity": "P1",
        "mechanism": "M2",
        "existing_gaps": ["GAP-19", "GAP-23", "GAP-25"],
        "contract_ref": ["IF-7 tool_set.schema.json", "G-L2-11"],
        "proposed_check": [
            "每个 L2 会话产出 tool_set_hash",
            "工具面变更产出 diff 事件（added/removed/changed）",
            "审计可对比「LLM 可见工具」与「审批工具」是否同源",
        ],
        "promotion_note": "A1-2 已生成唯一快照；先确认是否已有 hash/版本字段，再决定是否新增。",
    },
    {
        "gap_id": "GAP-T3",
        "title": "执行信封缺 trace_id/session_id，命令与交互不可归因",
        "layer": "L2",
        "severity": "P1",
        "mechanism": "M3",
        "existing_gaps": ["GAP-01", "GAP-24", "GAP-30"],
        "contract_ref": ["IF-3 L2Envelope.trace", "IF-7 span.schema.json", "G-L2-8"],
        "proposed_check": [
            "每条命令/工具执行 span 必含 trace_id、run_id、session_id",
            "交互记录与执行信封的 join_rate ≥95%",
            "无 ID 的信封不得作为回归/验收证据",
        ],
        "promotion_note": "这是 R2 门禁失败的直接原因；建议优先修，且只改我方执行链，不改 Trae。",
    },
    {
        "gap_id": "GAP-T4",
        "title": "无会话检查点契约（checkpoint → resume）",
        "layer": "L2",
        "severity": "P2",
        "mechanism": "M4",
        "existing_gaps": ["GAP-20", "GAP-24"],
        "contract_ref": ["IF-4 Ticket", "ADR-10", "G-L2-10"],
        "proposed_check": [
            "paused ticket 必须引用 checkpoint_id + content hash",
            "resume 必须从 checkpoint 恢复并复跑验证",
            "无 checkpoint 时不得声明 resumable=true",
        ],
        "promotion_note": "先验证 Ticket paused 是否已有等价物；若已有，改为补字段而非新建机制。",
    },
    {
        "gap_id": "GAP-T5",
        "title": "交互摘要未进入训练/台账，且缺证据门控",
        "layer": "L2",
        "severity": "P1",
        "mechanism": "M5",
        "existing_gaps": ["GAP-15", "GAP-29"],
        "contract_ref": ["IF-5 RepairLedger", "ADR-06", "G-L2-5", "G-L2-7"],
        "proposed_check": [
            "只有 ≥1 条 observation 级交叉证据的案例可入 training_cases",
            "纯 inference 案例标 inference，不用于优化结论",
            "settled 台账必须引用 case_ref",
        ],
        "promotion_note": "与 GAP-29 的 L1 发现门禁联动；摘要缺口主题不能直接当 L1 finding。",
    },
]


def build(manifest: dict[str, Any], interaction: dict[str, Any]) -> dict[str, Any]:
    agent = manifest.get("agent_summary", {})
    mcp = manifest.get("mcp_surface", {})
    execution = interaction.get("execution", {})
    metrics = interaction.get("metrics", {})
    snapshots = interaction.get("snapshots", {})

    facts = {
        "GAP-T1": {
            "agent_types": {k: v.get("models") for k, v in agent.items()},
            "skill_range": {
                k: [v.get("skill_count_min"), v.get("skill_count_max")] for k, v in agent.items()
            },
        },
        "GAP-T2": {
            "mcp_sessions": mcp.get("sessions"),
            "modes": {k: v.get("tool_count") for k, v in mcp.get("modes", {}).items()},
        },
        "GAP-T3": {
            "executions": execution.get("count"),
            "records": metrics.get("record_count"),
            "cross_evidence_rate": 0.0,
        },
        "GAP-T4": {"snapshots": snapshots.get("count"), "repos": snapshots.get("repos")},
        "GAP-T5": {
            "records": metrics.get("record_count"),
            "sessions": metrics.get("session_count"),
            "gap_themes": metrics.get("gap_themes", {}),
        },
    }

    candidates = []
    for c in CANDIDATES:
        item = dict(c)
        item["facts"] = facts.get(c["gap_id"], {})
        item["evidence_refs"] = [
            "manifest.json",
            "interaction_summary.json",
            "mechanism_cards.md",
            "pilot_report.md",
            "interaction_cases.jsonl",
        ]
        item["confidence"] = 0.9 if c["gap_id"] == "GAP-T3" else 0.7
        item["status"] = "candidate"
        candidates.append(item)

    return {
        "summary": f"映射 {len(MECHANISM_MAP)} 个机制，产出 {len(candidates)} 个候选缺口",
        "mechanism_map": MECHANISM_MAP,
        "candidates": candidates,
        "priority_order": ["GAP-T3", "GAP-T5", "GAP-T1", "GAP-T2", "GAP-T4"],
    }


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


def render_markdown(result: dict[str, Any]) -> str:
    rows = [
        [
            m["mechanism"],
            m["name"],
            ", ".join(m["existing"]),
            ", ".join(m["contracts"]),
            m["verdict"],
            m["candidate"],
        ]
        for m in result["mechanism_map"]
    ]
    parts = [
        "# Trae → 56 差距映射（R3）— v0.1\n",
        "> 输入：`mechanism_cards.md` + `manifest.json` + `interaction_summary.json`。",
        "> 原则：先映射现有 GAP，确认覆盖度；新候选用 `GAP-T*`，状态 `candidate`，不改 56 官方 GAP 表。\n",
        "## §0 结论\n",
        f"- 共映射 {len(result['mechanism_map'])} 个机制，产出 {len(result['candidates'])} 个候选缺口。",
        "- **M3（命令信封）是唯一有硬证据的阻塞项**：1,006 条信封无 trace/session ID，导致 R2 的交叉证据门禁为 0%。",
        "- M1/M2/M5 属于「契约已有、实现缺字段/缺版本/缺门控」，不应重复新建机制，应先核对 A1-2/A1-3/GAP-29 的现状。",
        "",
        "## §1 机制 × 现有 GAP 映射\n",
        _md_table(["机制", "名称", "现有 GAP", "契约", "判定", "候选"], rows),
        "",
        "## §2 候选缺口\n",
    ]
    for c in result["candidates"]:
        parts.append(f"### {c['gap_id']} {c['title']}\n")
        parts.append(
            f"- 层级/优先级：{c['layer']} / **{c['severity']}**（confidence={c['confidence']}）"
        )
        parts.append(f"- 机制：{c['mechanism']}；现有 GAP：{', '.join(c['existing_gaps'])}")
        parts.append(f"- 契约：{', '.join(c['contract_ref'])}")
        parts.append(f"- 事实：`{json.dumps(c['facts'], ensure_ascii=False)}`")
        parts.append("- 判据：")
        for chk in c["proposed_check"]:
            parts.append(f"  - {chk}")
        parts.append(f"- 推广前核对：{c['promotion_note']}\n")
    parts.extend(
        [
            "## §3 推荐顺序\n",
            "1. **GAP-T3**：补 trace_id/session_id，先让执行信封可归因（只改我方执行链）。",
            "2. **GAP-T5**：给交互案例加证据门控，避免 inference 污染训练/台账。",
            "3. **GAP-T1**：能力 bundle 标识，接 IF-1/IF-7。",
            "4. **GAP-T2**：tool_set 会话级版本与 diff 审计。",
            "5. **GAP-T4**：checkpoint→resume 契约（先确认 Ticket 是否已有等价物）。",
            "",
            "## §4 局限\n",
            "- 本映射基于 Trae 的声明与运行时产物，不证明我方现有实现缺失；每条候选推广前必须代码复核。",
            "- R2 案例全部为摘要级 inference；GAP-T5 的「证据门控」是纪律建议，不是统计结论。",
            "- `GAP-T*` 尚未合并进 56 官方 GAP-31+；需评审后登记。",
            "",
            "## §5 复跑\n",
            "```bash",
            "PYTHONPATH=. python3 -m trae.gap_mapper --pilot reports/trae-20261117 --out reports/trae-20261117",
            "```",
        ]
    )
    return "\n".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", required=True, help="run_pilot 输出目录")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    pilot = Path(args.pilot)
    manifest = json.loads((pilot / "manifest.json").read_text(encoding="utf-8"))
    interaction = json.loads((pilot / "interaction_summary.json").read_text(encoding="utf-8"))
    result = build(manifest, interaction)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "gap_candidates.json", result)
    (out / "gap_mapping.md").write_text(render_markdown(result), encoding="utf-8")
    print(json.dumps({"out": str(out), "summary": result["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
