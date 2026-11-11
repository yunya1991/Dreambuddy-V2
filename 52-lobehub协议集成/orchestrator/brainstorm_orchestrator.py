#!/usr/bin/env python3
"""52-LobeHub 协议集成 Phase 4.5 — 脑暴编排器（Brainstorm Orchestrator，shadow 模式）。

SPEC §7.7：默认低成本协作（双链各发散 N 张 → 池内确定性收敛 → Top1 定选），
命中争议触发器 T1-T4 才升级 Debate。shadow 模式为默认：
**只记录 trace / outbox，绝不执行任何 DreamOS 执行链**（executed 恒为 false）。
Phase 4.5：`--n-per-side`（1-3，默认 2）控制每侧候选数；grounded 裁决器
与启发式打分并行写 trace `adjudication`（不参与决策）；铁律⑤ fail-closed
（model 空/unknown 或跨侧同 model/证据路径 → 拒绝开题且不写 outbox）。

用法：
  python3 brainstorm_orchestrator.py --intent "评估是否给离场模块增加波动率自适应阈值" \
      --side-a-plancard /tmp/side_a.json --disable-recall --n-per-side 2

仅标准库依赖。
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Callable, Sequence

ORCHESTRATOR_DIR = Path(__file__).resolve().parent
REPO_ROOT = ORCHESTRATOR_DIR.parents[1]
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from adjudicator import adjudicate  # noqa: E402
from debate_client import (  # noqa: E402
    DebateTransportError,
    StdioShellClient,
    start_debate,
)
from plancard import validate_plancard  # noqa: E402
from proposers import (  # noqa: E402
    Proposer,
    SideAProposer,
    build_proposers,
)
from registry_tools import RegistryView, load_registry  # noqa: E402
from router import ROUTE_RULES_VERSION  # noqa: E402
from router import route as route_intent  # noqa: E402
from scoring import gate, score, triggers, validate_diversity  # noqa: E402

DEFAULT_TRACE_PATH = ORCHESTRATOR_DIR / "traces" / "brainstorm.jsonl"
DEFAULT_OUTBOX_PATH = REPO_ROOT / "52-lobehub协议集成" / "bridge" / "outbox.jsonl"
DEFAULT_COGNITION_SERVER = REPO_ROOT / "4-MEMORY" / "9-工具与接口" / "cognitive_mcp_server.py"

OUTBOX_CONTENT_MAX = 300
DEBATE_ROUNDS = int(os.environ.get("BRAINSTORM_DEBATE_ROUNDS", "1"))
RECALL_TOP_K = 5


# ── recall 取证（cognition MCP 只读） ─────────────────────────────


def recall_via_mcp(intent: str, top_k: int = RECALL_TOP_K) -> list[dict[str, Any]]:
    """经 cognition MCP 壳取 recall 记忆列表；失败抛异常由调用方降级。"""
    command = os.environ.get("COGNITION_MCP_CMD") or sys.executable
    server = os.environ.get("COGNITION_MCP_SERVER", str(DEFAULT_COGNITION_SERVER))
    client = StdioShellClient(
        command=command,
        args=[server],
        env={
            "COGNITIVE_MCP_MODE": "local",
            "COGNITIVE_MCP_WRITE_ENABLED": "false",
        },
        allowed_tools={"recall"},
        client_name="brainstorm-orchestrator-recall",
    )
    try:
        envelope = client.call_tool(
            "recall", {"context": intent, "top_k": top_k, "min_quality": "C"}
        )
    finally:
        client.close()

    data = envelope.get("data")
    memories = data.get("memories") if isinstance(data, dict) else None
    if memories is None and isinstance(envelope, dict):
        memories = envelope.get("memories")
    return [m for m in memories or [] if isinstance(m, dict)]


# ── 多样性校验（铁律⑤，fail-closed 见 scoring.validate_diversity） ─────────


def check_diversity(proposals: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """兼容入口：转调 scoring.validate_diversity（Phase 4.5 加固版）。"""
    return validate_diversity(proposals)


# ── 提案收集 ────────────────────────────────────────────────────


def _load_card_file(path: str | Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        raw = Path(path).read_text(encoding="utf-8")
        card = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"side_a_plancard_read_failed:{type(exc).__name__}: {exc}"
    if not isinstance(card, dict):
        return None, "side_a_plancard_not_object"
    return card, None


def collect_proposals(
    intent: str,
    context_refs: list[str],
    proposers: Sequence[Proposer],
    side_a_plancard: str | Path | None = None,
    n_per_side: int = 1,
) -> list[dict[str, Any]]:
    """收集双方全部候选卡（每侧 N 张）；任一失败只记 error，不中断。"""
    proposals: list[dict[str, Any]] = []
    for proposer in proposers:
        is_side_a = isinstance(proposer, SideAProposer)
        if is_side_a and side_a_plancard is not None:
            card, error = _load_card_file(side_a_plancard)
            proposals.append(
                {
                    "proposer_id": proposer.proposer_id,
                    "model": os.environ.get("SIDE_A_MODEL", "offline-plancard"),
                    "evidence_path": os.environ.get("SIDE_A_EVIDENCE_PATH", "plancard_file"),
                    "model_kind": "llm",
                    "variant": 0,
                    "selection_basis": "offline_plancard",
                    "card": card,
                    "error": error,
                }
            )
            continue

        try:
            results = proposer.propose(intent, context_refs, n=n_per_side)
        except Exception as exc:  # noqa: BLE001 — 单个提案方失败不中断另一侧
            results = []
            proposals.append(
                {
                    "proposer_id": proposer.proposer_id,
                    "model": proposer.model,
                    "evidence_path": proposer.evidence_path,
                    "model_kind": getattr(proposer, "model_kind", "unknown"),
                    "variant": None,
                    "selection_basis": None,
                    "card": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

        for result in results:
            proposals.append(
                {
                    "proposer_id": proposer.proposer_id,
                    "model": proposer.model,
                    "evidence_path": proposer.evidence_path,
                    "model_kind": getattr(proposer, "model_kind", "unknown"),
                    "variant": result.get("variant"),
                    "selection_basis": result.get("selection_basis"),
                    "card": result.get("card"),
                    "error": None,
                }
            )
        for error in getattr(proposer, "last_errors", []):
            proposals.append(
                {
                    "proposer_id": proposer.proposer_id,
                    "model": proposer.model,
                    "evidence_path": proposer.evidence_path,
                    "model_kind": getattr(proposer, "model_kind", "unknown"),
                    "variant": None,
                    "selection_basis": None,
                    "card": None,
                    "error": error,
                }
            )
    return proposals


def dedupe_pool(proposals: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """候选池按 card_id 去重（保留首次出现）。"""
    seen: set[str] = set()
    pool: list[dict[str, Any]] = []
    for proposal in proposals:
        card = proposal.get("card")
        if not isinstance(card, dict):
            continue
        card_id = str(card.get("id") or "")
        if card_id in seen:
            continue
        seen.add(card_id)
        pool.append(proposal)
    return pool


# ── 收敛：门禁 + 评分 ────────────────────────────────────────────


def evaluate_proposals(
    proposals: Sequence[dict[str, Any]], registry: RegistryView
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """对每张有效卡跑 gate + score，返回 (gates, scored)。"""
    gates: list[dict[str, Any]] = []
    scored: list[dict[str, Any]] = []
    for proposal in proposals:
        card = proposal.get("card")
        if not isinstance(card, dict):
            continue
        gate_result = gate(card, registry)
        score_result = score(card)
        gates.append(
            {
                "card_id": card.get("id"),
                "side": proposal.get("proposer_id"),
                "verdict": gate_result["verdict"],
                "reasons": gate_result["reasons"],
            }
        )
        scored.append(
            {
                "card": card,
                "side": proposal.get("proposer_id"),
                "model": proposal.get("model"),
                "score": score_result["score"],
                "breakdown": score_result["breakdown"],
                "gate_verdict": gate_result["verdict"],
            }
        )
    return gates, scored


# ── 定选 / 升级 ────────────────────────────────────────────────


def _build_debate_background(scored: Sequence[dict[str, Any]]) -> str:
    lines = ["脑暴候选方案（已收敛评分，未执行）："]
    for item in scored:
        card = item.get("card") or {}
        lines.append(
            f"- {item.get('side')} | plancard={card.get('id')} | score={item.get('score')} | "
            f"intent={card.get('intent')} | expected={card.get('expected_outcome')}"
        )
        lines.append(f"  plancard_json={json.dumps(card, ensure_ascii=False)}")
    return "\n".join(lines)


def _start_debate(
    intent: str,
    scored: Sequence[dict[str, Any]],
    opener: Callable[[str, str, list[str], list[dict[str, Any]]], str] | None,
) -> dict[str, Any]:
    """升级 Debate：只记录 debate_id（shadow 不等待裁决结果）。"""
    if len(scored) < 2:
        return {
            "debate_id": None,
            "error": "need_two_sides",
            "note": "T 命中但仅一方有效提案，无法开题（shadow 记录）",
        }
    model_pair = [str(item.get("model") or "unknown") for item in scored[:2]]
    plancards = [item.get("card") for item in scored[:2] if isinstance(item.get("card"), dict)]
    background = _build_debate_background(scored[:2])
    try:
        if opener is not None:
            debate_id = opener(intent, background, model_pair, plancards)
        else:
            with StdioShellClient() as client:
                debate_id = start_debate(
                    client,
                    topic=intent,
                    background=background,
                    model_pair=model_pair,
                    plancards=plancards,
                    rounds=DEBATE_ROUNDS,
                )
        return {"debate_id": debate_id, "model_pair": model_pair}
    except (DebateTransportError, OSError, ValueError, AssertionError) as exc:
        return {"debate_id": None, "error": f"{type(exc).__name__}: {exc}"}


# ── trace / outbox ─────────────────────────────────────────────


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    """append-only jsonl（父目录缺失则创建）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _shorten(text: str, limit: int = OUTBOX_CONTENT_MAX) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_outbox_entries(
    intent: str,
    scored: Sequence[dict[str, Any]],
    gates: Sequence[dict[str, Any]],
    run_id: str,
    loser_extra: str = "",
) -> list[dict[str, Any]]:
    """胜方 → brainstorm_winner（B）；其余有效卡 → brainstorm_loser（D，附裁决证据）。"""
    if not scored:
        return []
    ordered = sorted(scored, key=lambda item: float(item.get("score") or 0.0), reverse=True)
    winner = ordered[0]
    winner_card = winner.get("card") or {}
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    entries: list[dict[str, Any]] = [
        {
            "type": "brainstorm_winner",
            "content": _shorten(
                f"[脑暴胜出][{intent}] plancard={winner_card.get('id')} "
                f"side={winner.get('side')} score={winner.get('score')} "
                f"steps={len(winner_card.get('plan_steps') or [])} "
                f"expected={winner_card.get('expected_outcome')}"
            ),
            "tags": ["protocol-bridge", "brainstorm", "52-lobehub", "winner"],
            "source_ref": f"{run_id}:{winner_card.get('id')}",
            "bridge_ts": timestamp,
        }
    ]
    winner_score = float(winner.get("score") or 0.0)
    for item in ordered[1:]:
        card = item.get("card") or {}
        reasons = next((g.get("reasons") for g in gates if g.get("card_id") == card.get("id")), [])
        entries.append(
            {
                "type": "brainstorm_loser",
                "content": _shorten(
                    f"[脑暴落选][{intent}] plancard={card.get('id')} side={item.get('side')} "
                    f"score={item.get('score')} < winner {winner_score} "
                    f"gate={item.get('gate_verdict')} reasons={reasons} {loser_extra}"
                ),
                "tags": ["protocol-bridge", "brainstorm", "52-lobehub", "loser"],
                "source_ref": f"{run_id}:{card.get('id')}",
                "bridge_ts": timestamp,
            }
        )
    return entries


# ── 主流程 ─────────────────────────────────────────────────────


def run(
    intent: str,
    context_refs: list[str] | None = None,
    shadow: bool = True,
    user_requested_debate: bool = False,
    trace_path: str | Path | None = None,
    outbox_path: str | Path | None = None,
    side_a_plancard: str | Path | None = None,
    disable_recall: bool = False,
    proposers: Sequence[Proposer] | None = None,
    recall_fetcher: Callable[[str], list[dict[str, Any]]] | None = None,
    debate_opener: Callable[[str, str, list[str], list[dict[str, Any]]], str] | None = None,
    registry: RegistryView | None = None,
    n_per_side: int = 1,
    adjudicator_mode: str = "both",
    route_hint: dict[str, Any] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """执行一次脑暴（shadow）。任何子步骤失败降级记录，不中断。

    n_per_side：每侧发散候选数（CLI 默认 2）；adjudicator_mode：
    heuristic（不跑 grounded）/ grounded / both（默认，shadow 并行记录）。
    Phase 4.6：候选池生成前先跑 router（五分流）；force=False 且 route ∉
    {debate, workers} 时只写 trace 后返回 skipped；workers 单边不升级 Debate。
    """
    if not shadow:
        raise NotImplementedError(
            "live 执行分支属 Phase 5（竞争模式激活），当前仅支持 shadow 模式；"
            "请移除 --no-shadow 或等待 Phase 5 落地。"
        )

    trace_file = Path(trace_path) if trace_path else DEFAULT_TRACE_PATH
    outbox_file = Path(outbox_path) if outbox_path else DEFAULT_OUTBOX_PATH
    refs = list(context_refs or [])
    run_id = f"bs-{int(time.time() * 1000)}-{random.randint(0, 0xFFFFFF):06x}"
    errors: list[dict[str, str]] = []

    # ⓪ 意图路由（Phase 4.6）：必须在候选池生成之前分流（铁律⑥）
    if isinstance(route_hint, dict) and route_hint.get("route"):
        routing = dict(route_hint)
        routing.setdefault("version", ROUTE_RULES_VERSION)
    elif user_requested_debate:
        routing = {
            "route": "debate",
            "reason": "T4 用户显式要求辩论（跳过关键词路由）",
            "matched": ["user_requested_debate"],
            "version": ROUTE_RULES_VERSION,
        }
    else:
        routing = route_intent(intent)
    route_name = str(routing.get("route") or "workers")
    # workers = 单边规划（不升级 Debate）；--force 跳过路由直接脑暴
    mode = "debate" if force or route_name == "debate" else "workers"
    effective_n = 1 if mode == "workers" else n_per_side

    if not force and route_name not in ("debate", "workers"):
        # 交易执行 / 高风险 / 直答：不生成候选、不调 Debate、不写 outbox
        skipped_record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "run_id": run_id,
            "intent": intent,
            "shadow": shadow,
            "route": route_name,
            "route_reason": routing.get("reason"),
            "route_rules_version": ROUTE_RULES_VERSION,
            "route_matched": routing.get("matched") or [],
            "mode": "skip",
            "decision": {
                "kind": "route_skipped",
                "route": route_name,
                "reason": routing.get("reason"),
                "executed": False,
            },
            "dispatch": {"intent": None, "executed": False},
            "errors": [],
        }
        try:
            append_jsonl(trace_file, skipped_record)
        except OSError as exc:
            errors.append({"step": "trace", "error": f"{type(exc).__name__}: {exc}"})
        return {
            "run_id": run_id,
            "trace_id": run_id,
            "intent": intent,
            "shadow": shadow,
            "skipped": True,
            "route": route_name,
            "route_reason": routing.get("reason"),
            "reason": routing.get("reason"),
            "route_rules_version": ROUTE_RULES_VERSION,
            "mode": "skip",
            "force": force,
            "winner": None,
            "adjudication": None,
            "diversity_violations": [],
            "outbox_written": 0,
            "trace_path": str(trace_file),
            "decision": skipped_record["decision"],
            "errors": errors,
        }

    registry = registry if registry is not None else load_registry()
    if len(registry) == 0:
        errors.append({"step": "registry", "error": "registry_empty_or_missing"})

    # ① 发散：双方独立提案（每侧 N 张，不互相评判）
    proposer_list = (
        list(proposers) if proposers is not None else build_proposers(registry.allowed())
    )
    try:
        proposals = collect_proposals(
            intent, refs, proposer_list, side_a_plancard, n_per_side=effective_n
        )
    except Exception as exc:  # noqa: BLE001 — 降级不中断
        proposals = []
        errors.append({"step": "collect_proposals", "error": f"{type(exc).__name__}: {exc}"})
    for proposal in proposals:
        if proposal.get("error"):
            errors.append(
                {"step": "propose", "error": f"{proposal.get('proposer_id')}:{proposal['error']}"}
            )

    # ② 候选池去重 → 多样性校验（铁律⑤ fail-closed）
    pool = dedupe_pool(proposals)
    violations = check_diversity(pool)
    for violation in violations:
        errors.append({"step": "diversity", "error": json.dumps(violation, ensure_ascii=False)})

    # ③ 收敛：池内每张各自 gate + score
    gates, scored = evaluate_proposals(pool, registry)

    # ④ recall 取证（可禁用；失败 FAIL-OPEN）
    recall_hits: list[dict[str, Any]] | None = None
    recall_step: dict[str, Any] = {"status": "skipped", "reason": "disabled"}
    if not disable_recall:
        fetcher = recall_fetcher or recall_via_mcp
        try:
            recall_hits = fetcher(intent)
            recall_step = {"status": "ok", "hits": len(recall_hits)}
        except Exception as exc:  # noqa: BLE001
            recall_hits = None
            recall_step = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            errors.append({"step": "recall", "error": recall_step["error"]})

    # ⑤ 触发器 T1-T4
    trigger_result = triggers(
        scored, gates, recall_hits=recall_hits, user_requested=user_requested_debate
    )
    if mode == "workers" and trigger_result["escalate"]:
        # workers 路由：单边语义，不升级 Debate（T1-T4 仅记录不触发）
        trigger_result["escalate"] = False
        trigger_result["bypassed"] = "workers_route"

    # ⑥ 论证学裁决器（shadow 并行 A/B，不改变决策）
    scored_by_score = sorted(scored, key=lambda item: float(item.get("score") or 0.0), reverse=True)
    heuristic_top = (scored_by_score[0].get("card") or {}).get("id") if scored_by_score else None
    adjudication: dict[str, Any] = {
        "mode": adjudicator_mode,
        "heuristic_top": heuristic_top,
        "grounded_winner": None,
        "agree": None,
    }
    if adjudicator_mode in ("grounded", "both") and scored:
        grounded = adjudicate(scored, gates)
        adjudication.update(
            {
                "grounded_winner": grounded["winner"],
                "grounded_verdict": grounded["verdict"],
                "agree": grounded["winner"] == heuristic_top,
                "in_set": grounded["in_set"],
                "out_set": grounded["out_set"],
                "undec_set": grounded["undec_set"],
                "attack_edges": grounded["attack_edges"],
                "explain": grounded["explain"],
            }
        )

    # ⑦ 决策
    debate_info: dict[str, Any] = {"debate_id": None}
    dispatch: dict[str, Any] = {"intent": None, "executed": False}
    viable = [item for item in scored if item.get("gate_verdict") == "PASS"]
    viable_sorted = sorted(viable, key=lambda item: float(item.get("score") or 0.0), reverse=True)

    if violations:
        decision = {
            "kind": "diversity_violation",
            "reason": "铁律⑤ fail-closed：model 为空/unknown 或两侧 model/evidence_path 相同",
            "violations": violations,
            "executed": False,
        }
    elif not scored:
        decision = {"kind": "no_proposal", "reason": "双方均未产出有效 PlanCard", "executed": False}
    elif trigger_result["escalate"]:
        debate_info = _start_debate(intent, viable_sorted or scored, debate_opener)
        decision = {
            "kind": "escalate_debate",
            "fired": trigger_result["fired"],
            "debate_id": debate_info.get("debate_id"),
            "executed": False,
        }
    elif not viable:
        decision = {
            "kind": "no_viable_plan",
            "reason": "全部候选被门禁 BLOCK",
            "executed": False,
        }
    else:
        top = viable_sorted[0]
        top_card = top.get("card") or {}
        dispatch = {
            "intent": "dispatch",
            "selected": top.get("side"),
            "plancard_id": top_card.get("id"),
            "score": top.get("score"),
            "executed": False,
            "shadow": True,
        }
        decision = {
            "kind": "dispatch",
            "selected": top.get("side"),
            "plancard_id": top_card.get("id"),
            "score": top.get("score"),
            "executed": False,
            "note": "shadow：仅记录 dispatch 意图，不执行 DreamOS 链路",
        }

    # ⑧ trace（append-only）
    trace_record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "run_id": run_id,
        "intent": intent,
        "shadow": shadow,
        "route": route_name,
        "route_reason": routing.get("reason"),
        "route_rules_version": ROUTE_RULES_VERSION,
        "mode": mode,
        "n_per_side": effective_n,
        "pool_size": len(pool),
        "proposals": [
            {
                "proposer_id": p.get("proposer_id"),
                "model": p.get("model"),
                "model_kind": p.get("model_kind"),
                "evidence_path": p.get("evidence_path"),
                "variant": p.get("variant"),
                "selection_basis": p.get("selection_basis"),
                "card_id": (
                    (p.get("card") or {}).get("id") if isinstance(p.get("card"), dict) else None
                ),
                "schema_ok": validate_plancard(p.get("card"))[0] if p.get("card") else False,
                "error": p.get("error"),
            }
            for p in proposals
        ],
        "diversity_violations": violations,
        "gates": gates,
        "scores": [
            {
                "side": item.get("side"),
                "card_id": (item.get("card") or {}).get("id"),
                "score": item.get("score"),
                "breakdown": item.get("breakdown"),
            }
            for item in scored
        ],
        "recall": recall_step,
        "triggers": trigger_result,
        "adjudication": adjudication,
        "decision": decision,
        "debate": debate_info,
        "dispatch": dispatch,
        "errors": errors,
    }
    try:
        append_jsonl(trace_file, trace_record)
    except OSError as exc:
        errors.append({"step": "trace", "error": f"{type(exc).__name__}: {exc}"})

    # ⑨ outbox（胜方 B / 败方 D，附裁决证据）；铁律⑤拒绝时不写 outbox
    outbox_entries: list[dict[str, Any]] = []
    if not violations:
        outbox_entries = build_outbox_entries(
            intent,
            scored,
            gates,
            run_id,
            loser_extra=(
                f"debate={debate_info.get('debate_id')}" if debate_info.get("debate_id") else ""
            ),
        )
    written_outbox = 0
    for entry in outbox_entries:
        try:
            append_jsonl(outbox_file, entry)
            written_outbox += 1
        except OSError as exc:
            errors.append({"step": "outbox", "error": f"{type(exc).__name__}: {exc}"})

    return {
        "run_id": run_id,
        "trace_id": run_id,
        "intent": intent,
        "shadow": shadow,
        "skipped": False,
        "route": route_name,
        "route_reason": routing.get("reason"),
        "route_rules_version": ROUTE_RULES_VERSION,
        "mode": mode,
        "force": force,
        "winner": decision.get("plancard_id") if decision.get("kind") == "dispatch" else None,
        "n_per_side": effective_n,
        "pool_size": len(pool),
        "proposals": len(proposals),
        "scored": len(scored),
        "diversity_violations": violations,
        "adjudication": adjudication,
        "decision": decision,
        "debate": debate_info,
        "triggers": {"escalate": trigger_result["escalate"], "fired": trigger_result["fired"]},
        "trace_path": str(trace_file),
        "outbox_written": written_outbox,
        "errors": errors,
    }


def _compact_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """CLI --json-out / 3.1 API 消费的单行摘要（字段稳定，便于前端渲染）。"""
    return {
        "ok": True,
        "route": summary.get("route"),
        "route_rules_version": summary.get("route_rules_version"),
        "skipped": bool(summary.get("skipped")),
        "reason": summary.get("reason") or summary.get("route_reason"),
        "mode": summary.get("mode"),
        "winner": summary.get("winner"),
        "trace_id": summary.get("trace_id") or summary.get("run_id"),
        "trace_path": summary.get("trace_path"),
        "outbox_written": summary.get("outbox_written", 0),
        "diversity_violations": summary.get("diversity_violations") or [],
        "adjudication": summary.get("adjudication"),
        "decision": summary.get("decision"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="52 Phase 4 脑暴编排器（shadow：只记录 trace/outbox，不执行）"
    )
    parser.add_argument("--intent", required=True, help="议题/用户意图原文")
    parser.add_argument("--context-refs", nargs="*", default=[], help="上下文引用列表")
    parser.add_argument(
        "--shadow",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="默认 shadow（True）；--no-shadow 为 Phase 5 预留（当前直接报错）",
    )
    parser.add_argument("--user-requested-debate", action="store_true", help="T4：用户显式要求辩论")
    parser.add_argument("--trace-path", default=str(DEFAULT_TRACE_PATH))
    parser.add_argument("--outbox-path", default=str(DEFAULT_OUTBOX_PATH))
    parser.add_argument(
        "--side-a-plancard", default=None, help="给定则跳过 A 侧 HTTP 取卡（离线测试用）"
    )
    parser.add_argument("--disable-recall", action="store_true", help="禁用 cognition recall 取证")
    parser.add_argument(
        "--force",
        action="store_true",
        help="跳过意图路由直接脑暴（人工指定；用于强制观察 debate/workers 全链路）",
    )
    parser.add_argument(
        "--json-out",
        action="store_true",
        help="stdout 只输出单行 JSON 摘要（无日志噪音，供 3.1 /api/agent/brainstorm 消费）",
    )
    parser.add_argument(
        "--n-per-side",
        type=int,
        default=2,
        help="每侧发散候选数（1-3，默认 2；超范围直接报错退出）",
    )
    parser.add_argument(
        "--adjudicator",
        choices=("heuristic", "grounded", "both"),
        default="both",
        help="裁决器模式（默认 both：grounded 仅 shadow 并行记录）",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.n_per_side <= 3:
        parser.error(f"--n-per-side 必须在 1-3 之间，收到 {args.n_per_side}")

    try:
        summary = run(
            intent=args.intent,
            context_refs=args.context_refs,
            shadow=args.shadow,
            user_requested_debate=args.user_requested_debate,
            trace_path=args.trace_path,
            outbox_path=args.outbox_path,
            side_a_plancard=args.side_a_plancard,
            disable_recall=args.disable_recall,
            n_per_side=args.n_per_side,
            adjudicator_mode=args.adjudicator,
            force=args.force,
        )
    except NotImplementedError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    if args.json_out:
        print(json.dumps(_compact_summary(summary), ensure_ascii=False))
        return 0

    print(json.dumps({"ok": True, "data": summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
