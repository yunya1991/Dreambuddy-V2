#!/usr/bin/env python3
"""52-LobeHub Phase 4.5 — 论证学裁决器（grounded semantics，shadow 并行 A/B）。

SPEC §6 R7：只产出可解释裁决记录，不改变 shadow 决策（仍取启发式 Top1）。
论点 = 每卡 1 个 card 级 + 每 plan_step 1 个 step 级；攻击边 R-a/R-b/R-c 全确定性；
标准最小不动点求 IN/OUT/UNDEC；全部自身论点 IN 的卡为胜者，0 或 >1 → INCONCLUSIVE。
仅标准库。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

RULE_GATE, RULE_ACTION, RULE_RISK = "R-a", "R-b", "R-c"


def _short_tool(tool: Any) -> str:
    return tool.rsplit(".", 1)[-1] if isinstance(tool, str) and tool else ""


def _step_args(card: Mapping[str, Any], side: str) -> list[dict[str, Any]]:
    args: list[dict[str, Any]] = []
    cid = str(card.get("id") or "")
    steps = card.get("plan_steps") if isinstance(card.get("plan_steps"), list) else []
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, Mapping):
            continue
        number = step.get("step") if isinstance(step.get("step"), int) else index
        args.append(
            {
                "id": f"{cid}:step:{number}",
                "claim": str(step.get("action") or ""),
                "source_card": cid,
                "level": "step",
                "step": number,
                "tool": step.get("tool") if isinstance(step.get("tool"), str) else "",
                "side": side,
            }
        )
    return args


def build_arguments(
    scored: Sequence[Mapping[str, Any]], gates: Sequence[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """PlanCard → 论点；返 (全部论点, 各卡自身论点)。gate 根论点仅作攻击者，不计入自身。"""
    verdicts = {str(g.get("card_id")): g for g in gates if isinstance(g, Mapping)}
    arguments: list[dict[str, Any]] = []
    own: dict[str, list[dict[str, Any]]] = {}
    for item in scored:
        card = item.get("card") if isinstance(item, Mapping) else None
        if not isinstance(card, Mapping):
            continue
        cid = str(card.get("id") or "")
        side = str(item.get("side") or "")
        card_arg = {
            "id": f"{cid}:card",
            "claim": f"{card.get('intent') or ''} → {card.get('expected_outcome') or ''}".strip(),
            "source_card": cid,
            "level": "card",
            "side": side,
        }
        steps = _step_args(card, side)
        arguments.extend([card_arg, *steps])
        own[cid] = [card_arg, *steps]

        gate_result = verdicts.get(cid)
        if gate_result and gate_result.get("verdict") == "BLOCK":
            reason = "; ".join(str(r) for r in gate_result.get("reasons") or [])
            arguments.append(
                {
                    "id": f"gate:{cid}",
                    "claim": f"门禁否决：{reason or 'gate_block'}",
                    "source_card": cid,
                    "level": "gate_root",
                    "side": side,
                }
            )
    return arguments, own


def _gate_edges(
    arguments: Sequence[Mapping[str, Any]], own: Mapping[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    return [
        {
            "from": root["id"],
            "to": target["id"],
            "rule": RULE_GATE,
            "reason": f"{root['claim']} → 否决 {root['source_card']} 全部论点",
        }
        for root in arguments
        if root.get("level") == "gate_root"
        for target in own.get(str(root["source_card"]), [])
    ]


def _action_edges(arguments: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    steps = [arg for arg in arguments if arg.get("level") == "step"]
    edges: list[dict[str, Any]] = []
    for i in range(len(steps)):
        for j in range(i + 1, len(steps)):
            left, right = steps[i], steps[j]
            if left.get("side") == right.get("side") or not left.get("tool"):
                continue
            if left.get("tool") != right.get("tool"):
                continue
            if str(left.get("claim") or "") == str(right.get("claim") or ""):
                continue
            reason = f"同 tool={left['tool']} 但 action 不同，互斥攻击"
            edges.append(
                {"from": left["id"], "to": right["id"], "rule": RULE_ACTION, "reason": reason}
            )
            edges.append(
                {"from": right["id"], "to": left["id"], "rule": RULE_ACTION, "reason": reason}
            )
    return edges


def _risk_edges(
    scored: Sequence[Mapping[str, Any]], arguments: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    steps = [arg for arg in arguments if arg.get("level") == "step"]
    edges: list[dict[str, Any]] = []
    for item in scored:
        card = item.get("card") if isinstance(item, Mapping) else None
        if not isinstance(card, Mapping):
            continue
        cid = str(card.get("id") or "")
        flags = [str(f) for f in card.get("risk_flags") or []]
        for target in steps:
            if target.get("source_card") == cid:
                continue
            tool = str(target.get("tool") or "")
            short = _short_tool(tool)
            hit = next((f for f in flags if tool and (tool in f or (short and short in f))), None)
            if hit is None:
                continue
            edges.append(
                {
                    "from": f"{cid}:card",
                    "to": target["id"],
                    "rule": RULE_RISK,
                    "reason": f"{cid} 的 risk_flag『{hit}』命中 {target['id']} 的 tool={tool}",
                }
            )
    return edges


def grounded_semantics(
    argument_ids: Sequence[str], edges: Sequence[Mapping[str, Any]]
) -> tuple[set[str], set[str], set[str]]:
    """IN=攻击者全 OUT；OUT=被任一 IN 攻击；其余 UNDEC；迭代到稳定。"""
    incoming: dict[str, set[str]] = {aid: set() for aid in argument_ids}
    for edge in edges:
        target = str(edge.get("to"))
        if target in incoming:
            incoming[target].add(str(edge.get("from")))

    accepted: set[str] = set()
    rejected: set[str] = set()
    changed = True
    while changed:
        changed = False
        for aid in argument_ids:
            if aid in accepted or aid in rejected:
                continue
            attackers = incoming[aid]
            if any(attacker in accepted for attacker in attackers):
                rejected.add(aid)
                changed = True
            elif all(attacker in rejected for attacker in attackers):
                accepted.add(aid)
                changed = True
    undecided = set(argument_ids) - accepted - rejected
    return accepted, rejected, undecided


def adjudicate(
    scored: Sequence[Mapping[str, Any]], gates: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """执行 grounded 裁决，返回 winner/verdict/in_set/out_set/undec_set/attack_edges/explain。"""
    arguments, own = build_arguments(scored, gates)
    argument_ids = [str(arg["id"]) for arg in arguments]
    edges = _gate_edges(arguments, own) + _action_edges(arguments) + _risk_edges(scored, arguments)
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in edges:
        key = (str(edge["from"]), str(edge["to"]), str(edge["rule"]))
        if key not in seen:
            seen.add(key)
            deduped.append(edge)

    accepted, rejected, undecided = grounded_semantics(argument_ids, deduped)
    winners = [cid for cid, args in own.items() if all(str(arg["id"]) in accepted for arg in args)]
    winner = winners[0] if len(winners) == 1 else None

    explain = [
        f"{edge['rule']} {edge['from']} → {edge['to']}：{edge['reason']}" for edge in deduped
    ]
    if winner:
        explain.append(f"grounded 胜者 {winner}：自身全部论点 IN 且无 OUT")
    else:
        explain.append(f"INCONCLUSIVE：全 IN 卡数量={len(winners)}（需恰好 1 张）")

    return {
        "winner": winner,
        "verdict": "WIN" if winner else "INCONCLUSIVE",
        "in_set": sorted(accepted),
        "out_set": sorted(rejected),
        "undec_set": sorted(undecided),
        "attack_edges": deduped,
        "explain": explain,
    }
