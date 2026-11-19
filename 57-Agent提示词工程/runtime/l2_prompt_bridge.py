#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2_prompt_bridge.py — 存量 prompt 资产的统一运行时桥（SPEC-57 §8 P6）

用途：把「只登记未接入」的资产接进真实运行时，四件事一次做完：
  1. render  —— 读注册表资产（file/tree），按需截取小节，拼宪法 + 人格注入块；
  2. meta    —— 输出 IF-P-3 七字段（prompt_id/version/fingerprint/...）；
  3. gate    —— 对 lane 输出跑 C-01..C-12 + G-P-1..8 出口门禁；
  4. verify  —— 指纹对账 + 评测集覆盖自查。

硬约束：
  - 不改任何 prompt 资产字节；注入只发生在运行时拼接；
  - 任何异常对业务 FAIL-OPEN：render 返回空注入块、gate 返回 verdict=unknown；
  - 本模块不做模型调用，也不替代各 lane 自己的业务逻辑。

CLI：
  python3 57-Agent提示词工程/runtime/l2_prompt_bridge.py list
  python3 57-Agent提示词工程/runtime/l2_prompt_bridge.py verify --prompt-id l2.worker.rea
  python3 57-Agent提示词工程/runtime/l2_prompt_bridge.py render \
      --prompt-id l2.app.trade_ops --section "三、" --vars '{"screen_session_id":"s2-001"}'
  python3 57-Agent提示词工程/runtime/l2_prompt_bridge.py gate \
      --prompt-id l2.worker.rea --output out.json --evidence partial
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

RUNTIME = Path(__file__).resolve().parent
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import l2_output_gate as output_gate  # noqa: E402
import prompt_context_57 as pc  # noqa: E402

HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
SECTION_HINT_RE = re.compile(r"^([一二三四五六七八九十]+、)")


# ── 资产读取 ──────────────────────────────────────────────────────────


def load_asset_text(prompt_id: str) -> str:
    """读取注册资产正文；tree 按相对路径字典序拼接（带文件小标题）。"""
    entry = pc.get_prompt(prompt_id)
    asset = entry.get("asset_path")
    if not isinstance(asset, str) or not asset:
        raise pc.PromptContextError(f"{prompt_id}: asset_path 非法")
    target = pc.REPO_ROOT / asset
    if entry.get("asset_kind") == "tree":
        if not target.is_dir():
            raise pc.PromptContextError(f"{asset}: 不是目录")
        chunks: List[str] = []
        for path in sorted(p for p in target.rglob("*") if p.is_file()):
            rel = path.relative_to(target).as_posix()
            chunks.append(f"<!-- {rel} -->\n{path.read_text(encoding='utf-8', errors='replace')}")
        return "\n\n".join(chunks)
    if not target.is_file():
        raise pc.PromptContextError(f"{asset}: 不是文件")
    return target.read_text(encoding="utf-8", errors="replace")


def extract_section(text: str, heading: str) -> str:
    """按二级标题前缀截取小节；heading 支持「三、」这类序号或标题关键词。

    找不到时返回空串，由调用方决定回退（本模块不猜测）。
    """
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if HEADING_RE.match(line)]
    for pos, idx in enumerate(starts):
        title = HEADING_RE.match(lines[idx]).group(1)  # type: ignore[union-attr]
        if title.startswith(heading) or heading in title:
            end = starts[pos + 1] if pos + 1 < len(starts) else len(lines)
            return "\n".join(lines[idx:end]).strip()
    return ""


def load_output_contract(prompt_id: str) -> Optional[Dict[str, Any]]:
    """注册表 output_contract 为路径时加载契约；null/缺失返回 None。"""
    entry = pc.get_prompt(prompt_id)
    ref = entry.get("output_contract")
    if not isinstance(ref, str) or not ref:
        return None
    path = pc.REPO_ROOT / ref
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


# ── render ────────────────────────────────────────────────────────────


def render(
    prompt_id: str,
    *,
    variables: Optional[Dict[str, Any]] = None,
    section: str = "",
    tools: Iterable[str] = (),
    include_asset: bool = True,
) -> Dict[str, Any]:
    """返回 {prompt_id, version, asset_text, constitution_block, system_prompt, meta, injected}。

    FAIL-OPEN：注册表/资产不可读时 injected=False、meta=None，system_prompt 回落为
    asset_text（或不含注入的 base），调用方按原逻辑继续。
    """
    result: Dict[str, Any] = {
        "prompt_id": prompt_id,
        "version": "",
        "asset_text": "",
        "section_text": "",
        "constitution_block": "",
        "system_prompt": "",
        "meta": None,
        "injected": False,
    }
    try:
        entry = pc.get_prompt(prompt_id)
        result["version"] = str(entry.get("version") or "")
        asset_text = load_asset_text(prompt_id)
        result["asset_text"] = asset_text
        if section:
            result["section_text"] = extract_section(asset_text, section)
    except Exception as exc:  # noqa: BLE001 — 资产不可读不得阻断业务
        _warn(f"render({prompt_id}) 资产不可读: {type(exc).__name__}: {exc}")
        return result

    meta, block = pc.try_build_meta(prompt_id, tools=tools)
    result["meta"] = meta
    result["constitution_block"] = block
    result["injected"] = bool(block)

    body_parts: List[str] = []
    if include_asset:
        body = result["section_text"] or result["asset_text"]
        if body:
            body_parts.append(body)
    if variables:
        body_parts.append(
            "## 运行时变量\n```json\n"
            + json.dumps(variables, ensure_ascii=False, indent=2)
            + "\n```"
        )
    if block:
        body_parts.append(block)
    result["system_prompt"] = "\n\n".join(part for part in body_parts if part)
    return result


# ── gate / verify ─────────────────────────────────────────────────────


def gate(
    prompt_id: str,
    output: Any,
    *,
    evidence: Optional[str] = None,
    tools: Iterable[str] = (),
    context: Optional[Dict[str, Any]] = None,
    contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """出口宪法门禁；契约/预算缺省从注册表加载。

    evidence 显式提到 output 顶层（G-P-8 契约字段与 C-04 同源），避免只落在
    quality.evidence 而与 output_contract.required 对不上。
    """
    payload = output
    if evidence and isinstance(output, dict) and "evidence" not in output:
        payload = {**output, "evidence": evidence}
    resolved = contract if contract is not None else load_output_contract(prompt_id)
    budget: Optional[Dict[str, int]] = None
    try:
        tb = pc.get_prompt(prompt_id).get("token_budget") or {}
        if isinstance(tb.get("fixed"), int) and isinstance(tb.get("context"), int):
            budget = {
                "fixed": int(tb["fixed"]),
                "context": int(tb["context"]),
                "used": int(tb["fixed"]) + int(tb["context"]),
            }
    except Exception:  # noqa: BLE001 — 预算取不到就交给门禁按缺省处理
        budget = None
    return output_gate.gate_output(
        prompt_id,
        payload,
        context=context or {},
        tools=tools,
        budget=budget,
        evidence=evidence,
        output_contract=resolved,
    )


def verify(prompt_id: str) -> Dict[str, Any]:
    """指纹对账 + 评测集覆盖自查（严格模式，异常直接抛出）。"""
    entry = pc.get_prompt(prompt_id)
    actual = pc.verify_fingerprint(entry)
    suite_ref = entry.get("eval_suite")
    cases: Any = None
    suite_ok = False
    if isinstance(suite_ref, str):
        path = pc.REPO_ROOT / suite_ref
        if path.is_file():
            import yaml

            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for suite in doc.get("suites") or []:
                if isinstance(suite, dict) and suite.get("prompt_id") == prompt_id:
                    raw = suite.get("cases")
                    cases = raw if isinstance(raw, int) else len(raw or [])
                    suite_ok = isinstance(cases, int) and cases >= 20
                    break
    return {
        "prompt_id": prompt_id,
        "version": entry.get("version"),
        "status": entry.get("status"),
        "fingerprint": actual,
        "fingerprint_ok": entry.get("fingerprint") == actual,
        "eval_suite": suite_ref,
        "eval_cases": cases,
        "eval_ok": suite_ok,
        "output_contract": entry.get("output_contract"),
        "injection_mode": pc.injection_mode(entry),
    }


def list_prompts() -> List[Dict[str, Any]]:
    out = []
    for item in pc.load_registry().get("prompts") or []:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "prompt_id": item.get("prompt_id"),
                "version": item.get("version"),
                "status": item.get("status"),
                "task": item.get("task"),
                "owner_module": item.get("owner_module"),
                "injection_mode": pc.injection_mode(item),
            }
        )
    return out


def _warn(message: str) -> None:
    print(f"[57/bridge] {message}", file=sys.stderr)


# ── CLI ───────────────────────────────────────────────────────────────


def _read_json_arg(raw: str) -> Dict[str, Any]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise SystemExit("--vars/--context 必须是 JSON 对象")
    return data


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="L2 存量 prompt 运行时桥")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list")

    p_verify = sub.add_parser("verify")
    p_verify.add_argument("--prompt-id", required=True)

    p_render = sub.add_parser("render")
    p_render.add_argument("--prompt-id", required=True)
    p_render.add_argument("--section", default="")
    p_render.add_argument("--vars", default="")
    p_render.add_argument("--tools", default="")
    p_render.add_argument("--no-asset", action="store_true")
    p_render.add_argument("--out", default="")

    p_gate = sub.add_parser("gate")
    p_gate.add_argument("--prompt-id", required=True)
    p_gate.add_argument("--output", default="", help="输出 JSON 文件；缺省读 stdin")
    p_gate.add_argument("--evidence", choices=["none", "partial", "full"], default=None)
    p_gate.add_argument("--tools", default="")
    p_gate.add_argument("--context", default="")

    args = ap.parse_args(argv)

    if args.cmd == "list":
        print(json.dumps(list_prompts(), ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "verify":
        print(json.dumps(verify(args.prompt_id), ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "render":
        payload = render(
            args.prompt_id,
            variables=_read_json_arg(args.vars) if args.vars else None,
            section=args.section,
            tools=[t for t in args.tools.split(",") if t.strip()],
            include_asset=not args.no_asset,
        )
        if args.out:
            Path(args.out).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    raw = Path(args.output).read_text(encoding="utf-8") if args.output else sys.stdin.read()
    payload = json.loads(raw)
    result = gate(
        args.prompt_id,
        payload,
        evidence=args.evidence,
        tools=[t for t in args.tools.split(",") if t.strip()],
        context=_read_json_arg(args.context) if args.context else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
