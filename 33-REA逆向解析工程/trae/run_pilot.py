"""R1+R2 试点入口 — 运行三个 miner，产出机制卡 / 交互案例 / 试点报告。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .bundle_miner import run_bundle_miner
from .common import write_json, write_jsonl
from .interaction_miner import run_interaction_miner
from .manifest_miner import run_manifest_miner


def _md_table(headers: list[str], rows: list[list[object]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


def build_mechanism_cards(manifest: dict, bundle: dict, interaction: dict) -> str:
    agent_rows = []
    for agent, s in manifest["agent_summary"].items():
        agent_rows.append([agent, s["models"], s["skill_count_min"], s["skill_count_max"]])
    mcp_rows = [[m, v["tool_count"]] for m, v in manifest["mcp_surface"]["modes"].items()]
    exec_stats = interaction["execution"]
    snap = interaction["snapshots"]

    parts: list[str] = []
    parts.append("# Trae Harness 机制卡（R1）— v0.1\n")
    parts.append(
        "> 生成方式：`trae/run_pilot.py`；证据分级沿用 33-REA（observation / derivation / inference / unknown）。\n"
    )

    parts.append("## M1 `agent_type × model → skill bundle`\n")
    parts.append("**Observation**：内置 manifest 按 agent_type 与 model 两层组织 skills。\n")
    parts.append(_md_table(["agent_type", "models", "skills_min", "skills_max"], agent_rows))
    parts.append(
        "\n**Derivation**：技能面按模型能力裁剪，而不是全局暴露；`work` 的技能数最多（产物型任务），`trae` 居中。\n"
    )
    parts.append(
        "**Evidence**：`~/.trae-cn/builtin/baseline/manifests/{trae,solo,global}.json`。\n"
    )
    parts.append(
        "**对应 56**：能力聚合/路由（capability catalog）；建议映射到 `CapabilityCard` 与 L2 路线选择。\n"
    )
    parts.append("**Gap**：manifest 是声明，运行时是否按会话再次裁剪未知。\n")

    parts.append("## M2 `session × mode → tool_set 快照`\n")
    parts.append(
        f"**Observation**：{manifest['mcp_surface']['sessions']} 个会话目录下物化了 mode 级工具 JSON。\n"
    )
    parts.append(_md_table(["mode", "tool_count"], mcp_rows))
    parts.append(
        "\n**Observation**：内置物化面 = browser 20 + code_mode 1（Exec）+ default 4；原生 chat 工具（如 `runSubagent`）不物化。\n"
    )
    parts.append("**Derivation**：工具可见性来自「会话+mode」快照，具备可审计/可回放潜力。\n")
    parts.append("**对应 56**：IF-7 `tool_set.schema.json`、G-L2-11。\n")
    parts.append("**Gap**：缺少同一会话内多次 tool_set 变更的版本记录；原生工具是黑盒。\n")

    parts.append("## M3 `command → sandbox envelope`\n")
    parts.append(
        f"**Observation**：命令信封 {exec_stats['count']} 条；status={exec_stats['status']}；"
        f"target={exec_stats['target']}；耗时 median/p90/max = "
        f"{exec_stats['duration_ms']['median']}/{exec_stats['duration_ms']['p90']}/{exec_stats['duration_ms']['max']} ms。\n"
    )
    parts.append(f"**Observation**：Top cwd = {exec_stats['top_cwd']}。\n")
    parts.append(
        "**Derivation**：每条命令都有 ownerHash/requestDigest/退出码/终止原因/受限路径，可作为回归证据。\n"
    )
    parts.append("**对应 56**：L2Envelope.trace、span、G-L2-8 回归门禁。\n")
    parts.append("**Gap**：信封不含 session_id，无法直接归因到某次对话。\n")

    parts.append("## M4 `session → checkpoint`\n")
    parts.append(
        f"**Observation**：{snap['count']} 个会话快照目录，其中 {snap['repos']} 个是 git 仓库。\n"
    )
    parts.append("**Derivation**：快照提供断点续跑与变更回溯的物理载体。\n")
    parts.append("**对应 56**：Ticket 可续、ADR-10 可逆性。\n")
    parts.append("**Gap**：未验证快照与 Ticket 状态的绑定关系。\n")

    parts.append("## M5 `session → summary memory`\n")
    parts.append(
        f"**Observation**：试点 {interaction['metrics']['session_count']} 个会话 / {interaction['metrics']['record_count']} 条记录；"
        f"动作条目分布={interaction['metrics']['action_categories']}；outcome_rate={interaction['metrics']['outcome_rate']}。\n"
    )
    parts.append(
        "**Derivation**：交互可压缩为 `intent → actions → outcome → learned`，适合做案例检索与训练。\n"
    )
    parts.append("**对应 56**：G 层四分流、33 训练案例库。\n")
    parts.append("**Gap**：摘要是模型生成，必须与命令/快照交叉验证；原始对话在加密库。\n")

    parts.append("## Bundle 取证（辅助）\n")
    parts.append("**Observation**：\n")
    for f in bundle["files"]:
        parts.append(
            f"- `{f['file']}`：{f['bytes']} B，toolId 候选 {len(f['tool_id_candidates'])} 个，mode 命中 {len(f['mode_keyword_hits'])} 类。\n"
        )
    parts.append("**Unknown**：压缩 bundle 无法建立模块/调用图；不得据此断言架构。\n")
    return "\n".join(parts)


def build_pilot_report(interaction: dict) -> str:
    m = interaction["metrics"]
    e = interaction["execution"]
    gaps = m["top_gaps"]
    gap_rows = [[g["text"][:80], g["count"], g["session_id"], g["line_no"]] for g in gaps]
    theme_rows = [[k, v] for k, v in m.get("gap_themes", {}).items()]
    action_rows = [[k, v] for k, v in sorted(m["action_categories"].items(), key=lambda x: -x[1])]
    parts = [
        "# Trae 交互试点报告（R2）— v0.1\n",
        "> 仅基于本地会话摘要与命令信封；摘要为模型生成，属 inference。\n",
        "## 1. 数据\n",
        f"- 项目：`{interaction['project']}`",
        f"- 会话：{m['session_count']}；记录：{m['record_count']}；outcome_rate：{m['outcome_rate']}",
        f"- 命令：{e['count']}；状态：{e['status']}",
        "",
        "## 2. 动作条目分布\n",
        _md_table(["action_category", "count"], action_rows),
        "",
        "## 3. 缺口主题分布\n",
        _md_table(["theme", "count"], theme_rows),
        "",
        "## 4. 缺口候选（Top 20）\n",
        _md_table(["text", "count", "session", "line"], gap_rows),
        "",
        "## 5. 解释与局限\n",
        "- 动作分类基于关键词，非真实工具调用；只能作趋势判断。",
        "- 缺口候选来自 `learned` 文本，可能是模型自述；需回查会话与代码确认。",
        "- 命令信封无 session_id，本轮不做逐会话因果归因。",
        "- 原始 prompt / tool call 在加密 DB，未纳入。",
        "",
        "## 6. 建议\n",
        "- 先人工复核 Top 20 缺口候选，保留可证实项进入 56 GAP 清单。",
        "- 下一轮给命令信封补 session_id/trace_id，才能做真正的因果归因。",
    ]
    return "\n".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--sessions", type=int, default=50)
    ap.add_argument("--memory-project", default=None)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    manifest = run_manifest_miner()
    bundle = run_bundle_miner()
    interaction = run_interaction_miner(args.sessions, args.memory_project)

    write_json(out / "manifest.json", manifest)
    write_json(out / "bundle.json", bundle)
    write_json(
        out / "interaction_summary.json", {k: v for k, v in interaction.items() if k != "cases"}
    )
    write_jsonl(out / "interaction_cases.jsonl", interaction["cases"])
    write_json(
        out / "evidence.json",
        {
            "manifest": manifest["evidence"],
            "bundle": bundle["evidence"],
            "interaction": interaction["evidence"],
        },
    )
    (out / "mechanism_cards.md").write_text(
        build_mechanism_cards(manifest, bundle, interaction), encoding="utf-8"
    )
    (out / "pilot_report.md").write_text(build_pilot_report(interaction), encoding="utf-8")

    print(
        json.dumps(
            {
                "out": str(out),
                "manifest": manifest["summary"],
                "bundle": bundle["summary"],
                "interaction": interaction["summary"],
                "cases": len(interaction["cases"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
