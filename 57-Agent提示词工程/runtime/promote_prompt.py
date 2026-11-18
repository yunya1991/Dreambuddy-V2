#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""promote_prompt.py — prompt 版本晋升门禁（SPEC-57 §8 P4 / §5.3）

链路：实验编号（48 D2）→ 度量（A/B 轮次结果）→ 45 口径判定 → 版本/状态晋升留痕。

用法：
  # 1) 跑实验（写入 experiment_id）
  python3 57-Agent提示词工程/evals/run_prompt_ab.py \
      --task intent --round 4 --arm lite --limit 20 \
      --experiment-id D2B-P57-INT-20261118

  # 2) 预检（默认 dry-run，不写任何文件）
  python3 57-Agent提示词工程/runtime/promote_prompt.py \
      --prompt-id l2.intent.router \
      --from-round 57-Agent提示词工程/evals/out/intent_round4_lite.json \
      --to gated --bump minor

  # 3) 落账
  ... --apply

判定（45 口径 PASS / BLOCK / INCONCLUSIVE）：
  - INCONCLUSIVE：用例数 < golden.min_cases，或缺少配对指标
  - BLOCK：json_ok_rate < 阈值、delta_pp < 阈值、token 涨幅 > 40%
  - PASS：以上都过（非劣性；是否「提升」单独标记）

硬约束：
  - 只允许 draft→gated、gated→active（§5.3，禁止跳级/回退）；
  - MAJOR 需显式 `--output-contract-changed`（破坏输出 schema）；
  - 资产字节不动；晋升只改注册表 version/status/changelog；
  - 每次 --apply 追加 `registry/promotion_log.jsonl`（append-only）与 45 口径报告。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

RUNTIME = Path(__file__).resolve().parent
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import prompt_context_57 as pc  # noqa: E402

PROMOTION_LOG = pc.PROMPT_HOME / "registry" / "promotion_log.jsonl"
REPORT_DIR = pc.PROMPT_HOME / "evals" / "out" / "promotions"
EXPERIMENT_RE = re.compile(r"^(D2B|D3B|XA)-[A-Za-z0-9._-]{3,}$")
ALLOWED_TRANSITIONS = {("draft", "gated"), ("gated", "active")}
TOKEN_RATIO_MAX = 1.40
CREDENTIAL_TTL_DAYS = 7


class PromotionError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _zulu(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def bump_version(version: str, kind: str) -> str:
    major, minor, patch = (int(x) for x in version.split("."))
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def golden_suite(prompt_id: str) -> Dict[str, Any]:
    entry = pc.get_prompt(prompt_id)
    suite_path = entry.get("eval_suite")
    if not suite_path:
        raise PromotionError(f"{prompt_id}: eval_suite 为空，不得晋升（G-P-3）")
    path = pc.REPO_ROOT / str(suite_path)
    if not path.is_file():
        raise PromotionError(f"{prompt_id}: eval_suite 不存在: {suite_path}")
    import yaml

    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for suite in doc.get("suites") or []:
        if suite.get("prompt_id") == prompt_id:
            suite["_golden_version"] = str(doc.get("version", ""))
            return suite
    raise PromotionError(f"{prompt_id}: golden set 无对应 suite")


def compute_metrics(round_doc: Dict[str, Any]) -> Dict[str, Any]:
    arm = round_doc.get("arm")
    if arm in (None, "", "none"):
        raise PromotionError("round 结果缺少 B 臂（arm=none 不可用于晋升）")
    arms = round_doc.get("arms") or {}
    a = (arms.get("none") or {}).get("metrics")
    b = (arms.get(arm) or {}).get("metrics")
    if not a or not b:
        raise PromotionError("round 结果缺少 A/B metrics")
    paired = round_doc.get("paired") or {}
    delta = paired.get("delta_pp", paired.get("delta_joint_pp"))
    if delta is None:
        raise PromotionError("round 结果缺少配对 delta（paired.delta_pp）")
    n = len((arms.get("none") or {}).get("rows") or [])
    tokens_ratio = None
    if a.get("avg_tokens"):
        tokens_ratio = round(float(b["avg_tokens"]) / float(a["avg_tokens"]), 4)
    return {
        "task": round_doc.get("task"),
        "arm": arm,
        "n": n,
        "delta_pp": float(delta),
        "mcnemar_p": paired.get("mcnemar_p"),
        "json_ok_rate": b.get("json_ok_rate"),
        "evidence_declared_rate": b.get("evidence_declared_rate", b.get("evidence_rate")),
        "violation_cases": b.get("violation_cases"),
        "tokens_ratio": tokens_ratio,
        "avg_tokens_b": b.get("avg_tokens"),
    }


def judge(metrics: Dict[str, Any], suite: Dict[str, Any]) -> Tuple[str, List[str]]:
    """45 口径三值判定；返回 (verdict, block_reasons)。"""
    reasons: List[str] = []
    min_cases = int(suite.get("min_cases") or 20)
    if metrics["n"] < min_cases:
        return "INCONCLUSIVE", [f"用例数 {metrics['n']} < {min_cases}"]

    th = suite.get("threshold") or {}
    delta_min = float(th.get("delta_pp_min", -3.0))
    if metrics["delta_pp"] < delta_min:
        reasons.append(f"delta_pp={metrics['delta_pp']} < {delta_min}")

    json_min = th.get("json_ok_rate_min")
    if json_min is not None and metrics["json_ok_rate"] is not None:
        if float(metrics["json_ok_rate"]) < float(json_min):
            reasons.append(f"json_ok_rate={metrics['json_ok_rate']} < {json_min}")

    evidence_min = th.get("evidence_declared_rate_min")
    if evidence_min is not None and metrics["evidence_declared_rate"] is not None:
        if float(metrics["evidence_declared_rate"]) < float(evidence_min):
            reasons.append(
                f"evidence_declared_rate={metrics['evidence_declared_rate']} < {evidence_min}"
            )

    if metrics["tokens_ratio"] is not None and metrics["tokens_ratio"] > TOKEN_RATIO_MAX:
        reasons.append(f"tokens_ratio={metrics['tokens_ratio']} > {TOKEN_RATIO_MAX}")

    return ("BLOCK" if reasons else "PASS"), reasons


def _edit_registry_entry(
    text: str, prompt_id: str, version: str, status: str, changelog_suffix: str
) -> str:
    lines = text.splitlines(keepends=True)
    start = next(
        (i for i, line in enumerate(lines) if line.strip() == f"- prompt_id: {prompt_id}"),
        None,
    )
    if start is None:
        raise PromotionError(f"注册表未找到 {prompt_id}")
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("  - prompt_id:"):
            end = j
            break

    touched = {"version": False, "status": False, "changelog": False}
    for i in range(start, end):
        line = lines[i]
        if re.match(r"^    version: ", line):
            lines[i] = f"    version: {version}\n"
            touched["version"] = True
        elif re.match(r"^    status: ", line):
            lines[i] = f"    status: {status}\n"
            touched["status"] = True
        elif re.match(r"^    changelog: ", line):
            raw = line.rstrip("\n")
            if not raw.endswith('"'):
                raise PromotionError(f"{prompt_id}: changelog 非行内字符串，需人工处理")
            lines[i] = raw[:-1] + changelog_suffix + '"\n'
            touched["changelog"] = True
    missing = [k for k, ok in touched.items() if not ok]
    if missing:
        raise PromotionError(f"{prompt_id}: 注册表缺字段 {missing}")
    return "".join(lines)


def _build_45_report(
    prompt_id: str,
    experiment_id: str,
    verdict: str,
    metrics: Dict[str, Any],
    suite: Dict[str, Any],
    entry: Dict[str, Any],
    round_path: Path,
    reasons: List[str],
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    spec_hash = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(entry, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
    )
    items = [
        {
            "name": "delta_pp",
            "kind": "paired_delta",
            "status": "PASS" if not any("delta_pp" in r for r in reasons) else "BLOCK",
            "score": metrics["delta_pp"],
            "n": metrics["n"],
            "ci_lower": None,
            "ci_upper": None,
            "weight": 0.5,
            "evidence_id": experiment_id,
            "detail": f"mcnemar_p={metrics['mcnemar_p']}",
        },
        {
            "name": "json_ok_rate",
            "kind": "guardrail",
            "status": ("PASS" if not any("json_ok_rate" in r for r in reasons) else "BLOCK"),
            "score": metrics["json_ok_rate"],
            "n": metrics["n"],
            "ci_lower": None,
            "ci_upper": None,
            "weight": 0.3,
            "evidence_id": experiment_id,
            "detail": "",
        },
        {
            "name": "tokens_ratio",
            "kind": "guardrail",
            "status": ("PASS" if not any("tokens_ratio" in r for r in reasons) else "BLOCK"),
            "score": metrics["tokens_ratio"],
            "n": metrics["n"],
            "ci_lower": None,
            "ci_upper": None,
            "weight": 0.2,
            "evidence_id": experiment_id,
            "detail": f"max={TOKEN_RATIO_MAX}",
        },
    ]
    return {
        "eval_id": f"prompt.{prompt_id}",
        "run_id": experiment_id,
        "spec_hash": spec_hash,
        "verdict": verdict,
        "score": metrics["delta_pp"],
        "n": metrics["n"],
        "ci": None,
        "items": items,
        "block_reasons": reasons,
        "evidence": {
            "uri": round_path.relative_to(pc.REPO_ROOT).as_posix(),
            "sha256": _sha256_file(round_path),
        },
        "thresholds_version": f"golden@{suite.get('_golden_version', '')}",
        "baseline_run_id": f"{experiment_id}-A",
        "evaluated_at": _zulu(now),
        "expires_at": _zulu(now + timedelta(days=CREDENTIAL_TTL_DAYS)),
    }


def promote(args: argparse.Namespace) -> int:
    entry = pc.get_prompt(args.prompt_id)
    round_path = Path(args.from_round).resolve()
    if not round_path.is_file():
        raise PromotionError(f"round 结果不存在: {round_path}")
    round_doc = json.loads(round_path.read_text(encoding="utf-8"))

    experiment_id = str(round_doc.get("experiment_id") or "")
    if not EXPERIMENT_RE.match(experiment_id):
        raise PromotionError(f"experiment_id={experiment_id!r} 不符合 48 D2 口径（D2B-/D3B-/XA-）")
    if round_doc.get("prompt_id") and round_doc["prompt_id"] != args.prompt_id:
        raise PromotionError("round 结果与 --prompt-id 不一致")

    current_status = str(entry.get("status", ""))
    current_version = str(entry.get("version", ""))
    if (current_status, args.to) not in ALLOWED_TRANSITIONS:
        raise PromotionError(
            f"非法状态迁移 {current_status}→{args.to}（仅允许 draft→gated、gated→active）"
        )
    if args.to == "active" and not entry.get("output_contract"):
        raise PromotionError("active 需先冻结 output_contract（G-P-8）")
    if args.bump == "major" and not args.output_contract_changed:
        raise PromotionError("MAJOR 需显式 --output-contract-changed（破坏输出 schema）")

    suite = golden_suite(args.prompt_id)
    metrics = compute_metrics(round_doc)
    verdict, reasons = judge(metrics, suite)
    new_version = bump_version(current_version, args.bump)

    report = _build_45_report(
        args.prompt_id, experiment_id, verdict, metrics, suite, entry, round_path, reasons
    )

    print(
        json.dumps(
            {
                "prompt_id": args.prompt_id,
                "experiment_id": experiment_id,
                "verdict": verdict,
                "block_reasons": reasons,
                "transition": f"{current_status}→{args.to}",
                "version": f"{current_version}→{new_version}（{args.bump}）",
                "metrics": metrics,
                "evidence": report["evidence"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if verdict != "PASS":
        print(f"\n判定 {verdict}，不执行晋升。", file=sys.stderr)
        return 1
    if not args.apply:
        print("\n[dry-run] 未写入。加 --apply 落账。")
        return 0

    suffix = f"；P4 晋升 {experiment_id} {current_version}→{new_version}（{args.bump}）"
    text = pc.REGISTRY_PATH.read_text(encoding="utf-8")
    updated = _edit_registry_entry(text, args.prompt_id, new_version, args.to, suffix)
    pc.REGISTRY_PATH.write_text(updated, encoding="utf-8")

    # 写 45 口径报告（晋升后复算指纹应不变）
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"{args.prompt_id}-{new_version}.report.json"
    report["prompt_id"] = args.prompt_id
    report["to_version"] = new_version
    report["experiment_id"] = experiment_id
    report["promoted_at"] = _zulu(datetime.now(timezone.utc))
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    credential = None
    if args.issue_credential:
        from issue_45_credential import issue_from_report

        credential = issue_from_report(report_path, write=True)

    record = {
        "at": _zulu(datetime.now(timezone.utc)),
        "prompt_id": args.prompt_id,
        "experiment_id": experiment_id,
        "from_version": current_version,
        "to_version": new_version,
        "bump": args.bump,
        "from_status": current_status,
        "to_status": args.to,
        "verdict": verdict,
        "metrics": metrics,
        "constitution_version": pc.constitution_version(),
        "fingerprint": pc.asset_fingerprint(pc.get_prompt(args.prompt_id)),
        "report": report_path.relative_to(pc.REPO_ROOT).as_posix(),
        "evidence": report["evidence"],
        "credential": credential,
    }
    with PROMOTION_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(
        f"\n已晋升：{args.prompt_id} {current_version}→{new_version}，状态 {current_status}→{args.to}"
    )
    print(f"留痕：{PROMOTION_LOG.relative_to(pc.REPO_ROOT)}")
    print(f"报告：{report_path.relative_to(pc.REPO_ROOT)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="prompt 版本晋升门禁（P4）")
    ap.add_argument("--prompt-id", required=True)
    ap.add_argument("--from-round", required=True, help="run_prompt_ab 的单轮结果 json")
    ap.add_argument("--to", choices=["gated", "active"], required=True)
    ap.add_argument("--bump", choices=["major", "minor", "patch"], default="minor")
    ap.add_argument("--output-contract-changed", action="store_true")
    ap.add_argument("--apply", action="store_true", help="真实写注册表与留痕")
    ap.add_argument(
        "--issue-credential",
        action="store_true",
        help="落账后把报告投递 45 并签发/回验 deploy 凭证（P5）",
    )
    args = ap.parse_args()
    try:
        return promote(args)
    except PromotionError as exc:
        print(f"E_PROMOTION: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
