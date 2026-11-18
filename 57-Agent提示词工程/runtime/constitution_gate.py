#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""constitution_gate.py — L2 输出宪法校验器（SPEC-57 §4.3 / §7 P2）

性质：确定性校验（正则 / 字段存在性 / 集合成员 / schema），零 token，属 L1 形态。
禁止生成模型自评（C-06）。唯一入口：56 `validate_contracts.py --l2-output`。

输出判定按宪法 §4 冲突裁决分级：
  C-01/C-02/C-03 → deny（不可逆损失）
  C-04/C-05/C-06 → needs_review（审计完整性）
  C-07..C-12     → degraded（工程一致性）

输入契约（一个 JSON 文档）：
  {
    "prompt_id": "l2.debate.core",
    "meta": {IF-P-3 七字段},
    "output": "文本" | {对象},
    "tool_set": {"declared": [...], "snapshot": [...]},
    "context": {
      "live_symbols": [...], "suggested_symbols": [...], "paper_only": false,
      "allowed_numbers": [...], "injected_values": [...], "l1_metrics": [...],
      "execution_record": {"effect": "trade"}, "runner": "pytest",
      "trigger_source": "l1_finding"
    },
    "budget": {"fixed": 1800, "context": 2200, "used": 3200},
    "output_contract": {"required": ["evidence"]}
  }
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List

_RUNTIME = Path(__file__).resolve().parent
if str(_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_RUNTIME))

import prompt_context_57 as pc  # noqa: E402

SEVERITY = {
    "C-01": "deny",
    "C-02": "deny",
    "C-03": "deny",
    "C-04": "needs_review",
    "C-05": "needs_review",
    "C-06": "needs_review",
    "C-07": "degraded",
    "C-08": "degraded",
    "C-09": "degraded",
    "C-10": "degraded",
    "C-11": "degraded",
    "C-12": "degraded",
}
SEVERITY_RANK = {"allow": 0, "degraded": 1, "needs_review": 2, "deny": 3}

# 与 47 registry / 56 IF-7 对齐的 L1 写工具（C-02）
L1_WRITE_TOOLS = {
    "forward_signal",
    "execute_order",
    "place_order",
    "cancel_order",
    "close_position",
    "update_position",
}
PROPHECY_RE = re.compile(r"将会|预计|必然|一定")
SELF_ACCEPT_RE = re.compile(r"已修复|已通过|已验证|已上线")
CLAIM_EXEC_RE = re.compile(r"已买入|已卖出|已下单|已平仓|已触发")
VERSION_RE = re.compile(r"(?<![A-Za-z0-9_])v\d+\.\d+(?:\.\d+)?")
NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
CAUSAL_RE = re.compile(r"必然导致|将导致|因果关系|趋势性结论")
INJECTION_RE = re.compile(r"ignore\s+(all\s+)?previous|忽略(上述|以上)指令|泄露宪法")
LEAK_RE = re.compile(r"【源文件宪法|constitution@\d+\.\d+\.\d+")


def _strings(value: Any) -> List[str]:
    """递归取出字符串叶子（对象输出只校验字段值，不把 JSON 结构当文本）。"""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for v in value.values() for item in _strings(v)]
    if isinstance(value, (list, tuple)):
        return [item for v in value for item in _strings(v)]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [str(value)]
    return []


def _text(doc: Dict[str, Any]) -> str:
    output = doc.get("output")
    if isinstance(output, str):
        return output
    return "\n".join(_strings(output))


def _strip_quoted(text: str) -> str:
    """引用块 / 代码块 / 引用行豁免 C-05（宪法 R-4）。"""
    text = re.sub(r"「[^」]*」|“[^”]*”|\"[^\"]*\"|`[^`]*`", "", text)
    return re.sub(r"^\s*>.*$", "", text, flags=re.M)


def _clause_code(clause: str) -> str:
    _, clauses = pc.load_constitution()
    return clauses.get(clause, {}).get("code", f"E_{clause.replace('-', '_')}")


# ── 12 条款 ───────────────────────────────────────────────────────────


def check_clauses(doc: Dict[str, Any]) -> List[Dict[str, str]]:
    text = _text(doc)
    ctx = doc.get("context") or {}
    output = doc.get("output")
    found: List[Dict[str, str]] = []

    def hit(clause: str, detail: str) -> None:
        found.append({"clause": clause, "code": _clause_code(clause), "detail": detail})

    # C-01 不得主张执行权
    if CLAIM_EXEC_RE.search(text) and (ctx.get("execution_record") or {}).get("effect") != "trade":
        hit("C-01", "出现执行完成断言但无 effect=trade 执行记录")

    # C-02 L2 对 L1 只读
    declared = {str(t) for t in (doc.get("tool_set") or {}).get("declared") or []}
    used_l1_write = sorted(L1_WRITE_TOOLS.intersection(declared))
    if used_l1_write or any(name in text for name in L1_WRITE_TOOLS):
        hit("C-02", f"出现 L1 写工具: {used_l1_write or '文本命中'}")

    # C-03 实盘隔离
    suggested = set(ctx.get("suggested_symbols") or [])
    live = set(ctx.get("live_symbols") or [])
    outside = sorted(suggested - live)
    if outside and not ctx.get("paper_only"):
        hit("C-03", f"未登记标的且未标 paper_only: {outside}")

    # C-04 证据分级必填
    evidence = output.get("evidence") if isinstance(output, dict) else None
    if evidence is None and isinstance(output, dict):
        quality = output.get("quality")
        evidence = quality.get("evidence") if isinstance(quality, dict) else None
    if evidence not in ("none", "partial", "full"):
        hit("C-04", f"缺少合法 evidence（实际 {evidence!r}）")
    elif evidence == "none" and re.search(r"因此|所以|表明|证明", text):
        hit("C-04", "evidence=none 却给出确定性结论")

    # C-05 禁预言词（引用块豁免）
    prophecy = PROPHECY_RE.search(_strip_quoted(text))
    if prophecy:
        hit("C-05", f"命中禁词: {prophecy.group(0)}")

    # C-06 不得自证验收
    if SELF_ACCEPT_RE.search(text) and ctx.get("runner") not in ("pytest", "ci", "gate45"):
        hit("C-06", "出现完成断言但无 runner∈{pytest,ci,gate45} 证据")

    # C-07 发现权在 L1
    trigger = ctx.get("trigger_source")
    if trigger is not None and trigger not in ("l1_finding", "bug_report"):
        hit("C-07", f"trigger_source={trigger} 不属于 L1 发现")

    # C-08 不虚构事实（仅在提供 allowed_numbers 时可判）
    if "allowed_numbers" in ctx:
        allowed = {str(v) for v in ctx.get("allowed_numbers") or []}
        unknown = sorted({n for n in NUMBER_RE.findall(text) if n not in allowed})
        if unknown:
            hit("C-08", f"数值无法回溯: {unknown[:5]}")

    # C-09 注入隔离
    if INJECTION_RE.search(text) or LEAK_RE.search(text):
        hit("C-09", "输出执行了注入指令或泄露宪法原文")

    # C-10 预算优先于完整
    budget = doc.get("budget") or {}
    fixed, ctx_budget, used = budget.get("fixed"), budget.get("context"), budget.get("used")
    if isinstance(fixed, int) and isinstance(ctx_budget, int) and isinstance(used, int):
        degraded = isinstance(output, dict) and output.get("degraded") is True
        if used > fixed + ctx_budget and not degraded:
            hit("C-10", f"tokens_used={used} 超预算但未标 degraded")

    # C-11 版本不得硬编码
    injected = {str(v) for v in ctx.get("injected_values") or []}
    hardcoded = sorted({v for v in VERSION_RE.findall(text) if v not in injected})
    if hardcoded:
        hit("C-11", f"硬编码版本号: {hardcoded[:5]}")

    # C-12 不越层叙述
    if CAUSAL_RE.search(text) and not ctx.get("l1_metrics"):
        hit("C-12", "对 L1 未给出的指标下因果/趋势结论")

    return found


# ── G-P-1..8 ──────────────────────────────────────────────────────────


def _gate(ok: bool, detail: str = "") -> Dict[str, Any]:
    return {"ok": ok, "detail": "" if ok else detail}


def check_gates(doc: Dict[str, Any], violations: List[Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
    meta = doc.get("meta") or {}
    gates: Dict[str, Dict[str, Any]] = {}

    # G-P-1 宪法完整性（fail-closed）
    gates["G-P-1"] = _gate(bool(meta.get("constitution_version")), "meta.constitution_version 为空")

    # G-P-2 版本可溯（与注册表对账）
    missing = [k for k in ("prompt_id", "prompt_version", "prompt_fingerprint") if not meta.get(k)]
    if missing:
        gates["G-P-2"] = _gate(False, f"meta 缺字段: {missing}")
    else:
        try:
            entry = pc.get_prompt(str(meta["prompt_id"]))
            actual = pc.asset_fingerprint(entry)
        except Exception as exc:  # noqa: BLE001
            gates["G-P-2"] = _gate(False, f"注册表查表失败: {exc}")
        else:
            reasons = []
            if meta.get("prompt_version") != entry.get("version"):
                reasons.append(f"版本不符 {meta.get('prompt_version')}≠{entry.get('version')}")
            if meta.get("prompt_fingerprint") != actual:
                reasons.append("指纹不符（E_CONSTITUTION_DRIFT）")
            gates["G-P-2"] = _gate(not reasons, "；".join(reasons))

    # G-P-3 评测回归：由注册表 `--prompts` 校验（status/eval_suite），出口侧不重复判
    gates["G-P-3"] = _gate(True)

    # G-P-4 工具集一致
    tool_set = doc.get("tool_set") or {}
    if "declared" in tool_set and "snapshot" in tool_set:
        declared = sorted(str(t) for t in tool_set.get("declared") or [])
        snapshot = sorted(str(t) for t in tool_set.get("snapshot") or [])
        gates["G-P-4"] = _gate(declared == snapshot, f"declared {declared} ≠ snapshot {snapshot}")
    else:
        gates["G-P-4"] = _gate(True, "未提供 tool_set，跳过")

    # G-P-5 红线与证据（C-01..C-08 + C-12）
    redline = [v for v in violations if v["clause"] in {f"C-0{i}" for i in range(1, 9)} | {"C-12"}]
    gates["G-P-5"] = _gate(not redline, f"命中 {len(redline)} 条红线/证据条款")

    # G-P-6 注入隔离
    injection = [v for v in violations if v["clause"] == "C-09"]
    gates["G-P-6"] = _gate(not injection, "命中 C-09 注入隔离")

    # G-P-7 预算
    budget = doc.get("budget") or {}
    fixed, ctx_budget = budget.get("fixed"), budget.get("context")
    tokens = meta.get("constitution_tokens")
    used = budget.get("used")
    reasons = []
    if isinstance(fixed, int) and isinstance(tokens, int) and tokens > fixed:
        reasons.append(f"constitution_tokens={tokens} > fixed={fixed}")
    if isinstance(fixed, int) and isinstance(ctx_budget, int) and isinstance(used, int):
        if used > fixed + ctx_budget:
            reasons.append(f"used={used} > {fixed + ctx_budget}")
    gates["G-P-7"] = _gate(not reasons, "；".join(reasons))

    # G-P-8 输出契约
    contract = doc.get("output_contract") or {}
    required = contract.get("required") or []
    output = doc.get("output")
    if required:
        if not isinstance(output, dict):
            gates["G-P-8"] = _gate(False, "output 非对象，无法校验 output_contract")
        else:
            absent = [k for k in required if k not in output]
            gates["G-P-8"] = _gate(not absent, f"缺少契约字段: {absent}")
    else:
        gates["G-P-8"] = _gate(True, "未声明 output_contract，跳过")

    return gates


def evaluate(doc: Dict[str, Any]) -> Dict[str, Any]:
    violations = check_clauses(doc)
    gates = check_gates(doc, violations)

    verdict = "allow"
    for item in violations:
        level = SEVERITY.get(item["clause"], "degraded")
        if SEVERITY_RANK[level] > SEVERITY_RANK[verdict]:
            verdict = level
    if not all(g["ok"] for g in gates.values()) and verdict == "allow":
        verdict = "degraded"

    return {
        "ok": verdict == "allow" and all(g["ok"] for g in gates.values()),
        "verdict": verdict,
        "violations": violations,
        "gates": gates,
    }


def render(result: Dict[str, Any]) -> List[str]:
    """把结果展开成校验器可打印的行（与 56 报告格式一致）。"""
    lines = [f"verdict={result['verdict']}；违例 {len(result['violations'])} 条"]
    for gate_id, gate in sorted(result["gates"].items()):
        if not gate["ok"]:
            lines.append(f"{gate_id}: {gate['detail']}")
    for item in result["violations"]:
        lines.append(f"{item['clause']} {item['code']}: {item['detail']}")
    return lines


def validate_doc(doc: Dict[str, Any]) -> List[str]:
    """供 56 校验器直接调用的错误列表接口。"""
    if not isinstance(doc, dict):
        return ["L2 输出文档必须是对象"]
    result = evaluate(doc)
    return render(result) if not result["ok"] else []
