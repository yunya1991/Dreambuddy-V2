#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""issue_45_credential.py — 把 P4 晋升报告投递到 45 并签发 deploy 凭证（SPEC-57 P5）

目的：不再只产「45 口径兼容报告」，而是真正调用 45 的仓库与门禁：
  InMemoryRepo ← 受理记录 / Run / Items / Evidence / Report
  Gate.issue(eval_id, "deploy") → Credential
  Gate.verify(credential, "deploy") → 回验通过

用法：
  python3 57-Agent提示词工程/runtime/issue_45_credential.py \
      --report 57-Agent提示词工程/evals/out/promotions/l2.intent.router-0.2.0.report.json \
      --write

退出码：0 签发并通过回验；1 拒绝（非 PASS / 过期 / 绑定漂移等）。

边界：
  - 45 当前本地实现是 InMemoryRepo，凭证进程内可验证，跨进程需 PgRepo（云端）或重放报告；
  - 本模块不修改报告判定，只做「投递 + 签发 + 回验 + 留痕」；
  - 报告与证据哈希必须一致，否则 45 fail-closed 拒绝。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

RUNTIME = Path(__file__).resolve().parent
REPO_ROOT = RUNTIME.parents[1]
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

EVAL_SYSTEM = REPO_ROOT / "45-评测系统"
if str(EVAL_SYSTEM) not in sys.path:
    sys.path.insert(0, str(EVAL_SYSTEM))

from core.gate import Gate, GateError  # noqa: E402
from core.gateway import EvalRequestRecord  # noqa: E402
from storage.evidence import chain_hash  # noqa: E402
from storage.repo import (  # noqa: E402
    EvalItemRecord,
    EvalRunRecord,
    EvidenceRow,
    InMemoryRepo,
)

PROMOTION_LOG = RUNTIME.parent / "registry" / "promotion_log.jsonl"
EVALUATOR_ID = "prompt.ab"
EVALUATOR_VERSION = "1.0.0"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _prompt_id_from_eval(eval_id: str) -> str:
    return eval_id[len("prompt.") :] if eval_id.startswith("prompt.") else eval_id


def _seed_repo(report: Dict[str, Any]) -> InMemoryRepo:
    repo = InMemoryRepo()
    now = _now()
    eval_id = str(report["eval_id"])
    run_id = str(report["run_id"])
    spec_hash = str(report["spec_hash"])

    repo.insert_request(
        EvalRequestRecord(
            eval_id=eval_id,
            idempotency_key=f"p57:{run_id}",
            object_ref=report.get("object_ref") or eval_id,
            category="prompt",
            object_type="prompt",
            submitter="57-Agent提示词工程",
            purpose="deploy",
            priority="P2",
            spec_id="SPEC-57",
            env_manifest={"source": "run_prompt_ab", "arm": "injection"},
            spec_hash=spec_hash,
            status="succeeded",
            created_at=now,
        )
    )
    repo.insert_run(
        EvalRunRecord(
            run_id=run_id,
            eval_id=eval_id,
            evaluator_id=EVALUATOR_ID,
            evaluator_version=EVALUATOR_VERSION,
            scorer_versions={"delta_pp": "1", "json_ok_rate": "1", "tokens_ratio": "1"},
            attempt=1,
            spec_hash=spec_hash,
            code_commit=None,
            env_snapshot={"harness": "57/A-B"},
            budget_ms=None,
            degraded=False,
            started_at=now,
            ended_at=now,
            status="succeeded",
        )
    )
    repo.insert_items(
        [
            EvalItemRecord(
                item_id=f"{run_id}-{idx}",
                run_id=run_id,
                name=str(item.get("name", f"item{idx}")),
                kind=str(item.get("kind", "weighted")),
                score=item.get("score"),
                n=item.get("n"),
                ci_lower=item.get("ci_lower"),
                ci_upper=item.get("ci_upper"),
                weight=item.get("weight"),
                status=str(item.get("status", "PASS")),
                evidence_id=item.get("evidence_id"),
                detail=item.get("detail"),
            )
            for idx, item in enumerate(report.get("items") or [])
        ]
    )
    evidence = report.get("evidence") or {}
    sha = str(evidence.get("sha256", ""))
    uri = str(evidence.get("uri", ""))
    if not sha or not uri:
        raise GateError("no_evidence", "报告缺 evidence.uri / evidence.sha256（Evidence-First）")
    repo.insert_evidence(
        EvidenceRow(
            evidence_id=f"{run_id}-ev1",
            run_id=run_id,
            sha256=sha,
            uri=uri,
            prev_hash=None,
            hash=chain_hash(None, sha, uri),
            signed_by="57-promote",
            created_at=now,
        )
    )
    repo.insert_report(report)
    return repo


def issue_from_report(report_path: Path, *, write: bool = False) -> Dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    repo = _seed_repo(report)
    gate = Gate(repo)
    credential = gate.issue(str(report["eval_id"]), "deploy")
    verified = gate.verify(credential, "deploy")

    prompt_id = str(report.get("prompt_id") or _prompt_id_from_eval(str(report["eval_id"])))
    to_version = str(report.get("to_version") or "")
    if not to_version:
        suffix = ".report.json"
        name = report_path.name
        if name.startswith(f"{prompt_id}-") and name.endswith(suffix):
            to_version = name[len(prompt_id) + 1 : -len(suffix)]

    result = {
        "eval_id": report["eval_id"],
        "prompt_id": prompt_id,
        "to_version": to_version,
        "run_id": report["run_id"],
        "purpose": "deploy",
        "verified": True,
        "credential": asdict(verified),
        "report": report_path.relative_to(REPO_ROOT).as_posix(),
    }

    if write:
        report["credential"] = result["credential"]
        report["credential_verified"] = True
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        event = {
            "type": "credential_issued",
            "at": result["credential"]["issued_at"],
            "prompt_id": result["prompt_id"],
            "experiment_id": report.get("experiment_id") or report.get("run_id"),
            "to_version": result["to_version"],
            "purpose": "deploy",
            "verified": True,
            "credential": result["credential"],
            "report": result["report"],
        }
        with PROMOTION_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="45 deploy 凭证签发与回验（P5）")
    ap.add_argument("--report", required=True, type=Path, help="45 口径报告 json")
    ap.add_argument("--write", action="store_true", help="把凭证写回报告并追加 promotion_log")
    args = ap.parse_args()
    try:
        result = issue_from_report(args.report.resolve(), write=args.write)
    except GateError as exc:
        print(f"E_GATE: {exc.code}: {exc.detail}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
