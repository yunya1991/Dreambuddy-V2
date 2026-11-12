"""Emergence — T-G3 涌现回灌：方法论模板 → 候选规则 → 八门禁 → rea_rules.yaml

SPEC-33-G §2.12.3 / G-G3：
  - 模式候选：≥5 条同类 Case 且跨 ≥3 次迭代；模板 Evidence ≥2
  - C 级记忆不进候选池（硬约束 13）
  - 候选规则必须八门禁全 pass 才可写入 `rea_rules.yaml`（Policy 账本之外的规则回灌）
  - 回灌留痕：来源模板 / Evidence / 晋级时间 / rule_id

工程约束：纯标准库；候选走 jsonl 追加；规则注册表为 JSON 事实源，
`rea_rules.yaml` 每次由注册表确定性重写（不自解析 YAML）。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

ALLOWED_QUALITY = {"S", "A", "B"}
_RULE_FILE = re.compile(r"^RULE-(\d+)$")


class CandidateError(ValueError):
    """候选规则契约违约（硬拒绝）。"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CandidateError(message)


def _yaml_scalar(value: Any) -> str:
    text = str(value if value is not None else "")
    return json.dumps(text, ensure_ascii=False)


class EmergenceEngine:
    def __init__(
        self,
        root: str | Path,
        *,
        clock: Optional[Callable[[], datetime]] = None,
        min_cases: int = 5,
        min_iterations: int = 3,
        min_evidence: int = 2,
    ):
        self.root = Path(root)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.min_cases = int(min_cases)
        self.min_iterations = int(min_iterations)
        self.min_evidence = int(min_evidence)

    # ---------------------------------------------------------------- 候选

    def candidates_from_template(
        self, template: Dict[str, Any], cases: Iterable[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        template = dict(template or {})
        template_id = str(template.get("template_id") or "").strip()
        name = str(template.get("name") or "").strip()
        condition = str(template.get("when") or "").strip()
        action = str(template.get("then") or "").strip()
        _require(bool(template_id), "template_id is required")
        _require(bool(name and condition and action), "模板必须包含 name / when / then")
        evidence = [
            str(ref).strip() for ref in (template.get("evidence_refs") or []) if str(ref).strip()
        ]
        _require(
            len(evidence) >= self.min_evidence,
            f"模板 Evidence 不足：需 ≥{self.min_evidence} 条（当前 {len(evidence)}）",
        )

        case_list = [dict(case) for case in (cases or [])]
        _require(
            len(case_list) >= self.min_cases,
            f"涌现候选需 ≥{self.min_cases} 条同类 Case（当前 {len(case_list)}）",
        )
        iterations = {
            str(case.get("iteration_id") or "").strip()
            for case in case_list
            if str(case.get("iteration_id") or "").strip()
        }
        _require(
            len(iterations) >= self.min_iterations,
            f"涌现候选需跨 ≥{self.min_iterations} 次迭代（当前 {len(iterations)}）",
        )
        low_quality = sorted(
            {
                str(case.get("quality_level") or "").strip().upper()
                for case in case_list
                if str(case.get("quality_level") or "").strip().upper() not in ALLOWED_QUALITY
            }
        )
        _require(
            not low_quality,
            f"C 级记忆不进候选池（命中等级 {low_quality}，仅允许 {sorted(ALLOWED_QUALITY)}）",
        )

        candidate = {
            "candidate_id": self._next_candidate_id(),
            "name": name,
            "when": condition,
            "then": action,
            "source_template": template_id,
            "evidence_refs": evidence,
            "case_ids": [str(case.get("case_id")) for case in case_list],
            "status": "candidate",
            "created_at": self._now().isoformat(),
        }
        self._append_candidate(candidate)
        return [candidate]

    def candidates(self) -> List[Dict[str, Any]]:
        return [entry for entry in self._read_candidates() if entry.get("status") == "candidate"]

    # ---------------------------------------------------------------- 回灌

    def promote(
        self,
        candidate_id: str,
        *,
        gate_summary: Dict[str, Any],
    ) -> Dict[str, Any]:
        self._require_all_gates(gate_summary)
        entries = self._read_candidates()
        target = next(
            (entry for entry in entries if entry.get("candidate_id") == candidate_id), None
        )
        _require(target is not None, f"候选规则 {candidate_id} 不存在")
        _require(
            target.get("status") == "candidate",
            f"候选规则 {candidate_id} 状态为 {target.get('status')}，不可重复回灌",
        )

        rule_id = self._next_rule_id()
        rule = {
            "rule_id": rule_id,
            "name": target.get("name"),
            "when": target.get("when"),
            "then": target.get("then"),
            "source_template": target.get("source_template"),
            "source_candidate": candidate_id,
            "evidence_refs": list(target.get("evidence_refs") or []),
            "promoted_at": self._now().isoformat(),
        }
        registry = self._read_registry()
        registry["rules"].append(rule)
        self._write_registry(registry)
        self._write_rules_yaml(registry)

        target["status"] = "promoted"
        target["rule_id"] = rule_id
        target["promoted_at"] = rule["promoted_at"]
        self._write_candidates(entries)
        return dict(rule)

    # ---------------------------------------------------------------- 校验

    @staticmethod
    def _require_all_gates(gate_summary: Dict[str, Any]) -> None:
        summary = gate_summary or {}
        gates = list(summary.get("gates") or [])
        _require(
            summary.get("overall") == "pass"
            and len(gates) >= 8
            and all(item.get("status") == "pass" for item in gates),
            "八门禁未全绿，候选规则不得回灌",
        )

    # ---------------------------------------------------------------- 存储

    def _candidates_path(self) -> Path:
        return self.root / "candidates" / "rules.jsonl"

    def _read_candidates(self) -> List[Dict[str, Any]]:
        path = self._candidates_path()
        if not path.is_file():
            return []
        entries: List[Dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                entries.append(item)
        return entries

    def _append_candidate(self, candidate: Dict[str, Any]) -> None:
        path = self._candidates_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(candidate, ensure_ascii=False, sort_keys=True) + "\n")

    def _write_candidates(self, entries: List[Dict[str, Any]]) -> None:
        path = self._candidates_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        body = "".join(
            json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n" for entry in entries
        )
        path.write_text(body, encoding="utf-8")

    def _next_candidate_id(self) -> str:
        numbers = [
            int(matched.group(1))
            for entry in self._read_candidates()
            if (matched := re.match(r"RULE-C-(\d+)$", str(entry.get("candidate_id") or "")))
        ]
        return f"RULE-C-{max(numbers, default=0) + 1:03d}"

    def _registry_path(self) -> Path:
        return self.root / "rules_registry.json"

    def _read_registry(self) -> Dict[str, Any]:
        path = self._registry_path()
        if not path.is_file():
            return {"version": 1, "rules": []}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "rules": []}
        if not isinstance(loaded, dict):
            return {"version": 1, "rules": []}
        loaded.setdefault("version", 1)
        loaded.setdefault("rules", [])
        return loaded

    def _write_registry(self, registry: Dict[str, Any]) -> None:
        self._registry_path().write_text(
            json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _next_rule_id(self) -> str:
        numbers = [
            int(matched.group(1))
            for rule in self._read_registry().get("rules") or []
            if (matched := _RULE_FILE.match(str(rule.get("rule_id") or "")))
        ]
        return f"RULE-{max(numbers, default=0) + 1:04d}"

    def _write_rules_yaml(self, registry: Dict[str, Any]) -> None:
        lines = ["version: 1", "rules:"]
        for rule in registry.get("rules") or []:
            lines.append(f"  - rule_id: {_yaml_scalar(rule.get('rule_id'))}")
            lines.append(f"    name: {_yaml_scalar(rule.get('name'))}")
            lines.append(f"    when: {_yaml_scalar(rule.get('when'))}")
            lines.append(f"    then: {_yaml_scalar(rule.get('then'))}")
            lines.append(f"    source_template: {_yaml_scalar(rule.get('source_template'))}")
            lines.append(f"    source_candidate: {_yaml_scalar(rule.get('source_candidate'))}")
            lines.append("    evidence_refs:")
            for ref in rule.get("evidence_refs") or []:
                lines.append(f"      - {_yaml_scalar(ref)}")
            lines.append(f"    promoted_at: {_yaml_scalar(rule.get('promoted_at'))}")
        (self.root / "rea_rules.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _now(self) -> datetime:
        return self.clock()
