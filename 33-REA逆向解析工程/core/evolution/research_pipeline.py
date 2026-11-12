"""Research Pipeline — T-G14 三层分级器 + 五段研发流水线

SPEC-33-G §2.11.1 / §2.11.2 / §2.11.4 / §2.11.5：
  ① 分级：确定性 classify（LLM 不得自定级），无法判定默认 L3（保守）
  ② 流水线：路由(DreamOS) → 脑暴(双链) → 研发(DSH 子 Agent) → 取证(L0) → 门禁
  ③ 产物契约：research_artifact.json + dev_artifact.json + evidence_refs 三者缺一不得进门禁
  ④ 层约束：L2 新增依赖→L3；stateful 禁止自动（L2-9）；自动合入关闭（L2-7）
            L3 只出 ADR + SPEC，禁止代码变更

工程约束：纯标准库；适配器（路由/脑暴/研发/取证/门禁）由调用方注入，
便于与 DreamOS / LobeHub / DSH / L0 解耦并可单测。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

LEVELS = ("L1", "L2", "L3")
LEVEL_RANK = {"L1": 1, "L2": 2, "L3": 3}

CODE_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".m",
    ".swift",
    ".rb",
    ".php",
    ".cs",
}

_NUMBERED_DIR = re.compile(r"^(\d+)[-_]")


class PipelineError(ValueError):
    """分级 / 流水线契约违约（硬拒绝）。"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PipelineError(message)


def _module_of(path: str) -> Optional[str]:
    """取路径首个编号目录（如 33-REA逆向解析工程 / 4-MEMORY）。"""
    normalized = str(path or "").strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized:
        return None
    head = normalized.split("/", 1)[0]
    return head if _NUMBERED_DIR.match(head) else None


def _is_code_file(path: str) -> bool:
    suffix = Path(str(path or "")).suffix.lower()
    return suffix in CODE_SUFFIXES


class ChangeClassifier:
    """§2.11.1 分级规则：确定性判定，保守优先。"""

    def __init__(self, *, max_files: int = 3, max_lines: int = 200):
        self.max_files = int(max_files)
        self.max_lines = int(max_lines)

    def classify(
        self,
        *,
        files: Iterable[str] = (),
        lines_changed: int = 0,
        changes_contract: bool = False,
        changes_schema: bool = False,
        changes_dependency_direction: bool = False,
        adds_dependency: bool = False,
        stateful: bool = False,
        rule_only: bool = False,
    ) -> Dict[str, Any]:
        paths = [str(item).strip() for item in files if str(item).strip()]
        modules = sorted({module for module in (_module_of(p) for p in paths) if module})
        lines = max(0, int(lines_changed or 0))
        reasons: List[str] = []
        level = "L2"

        if changes_contract:
            reasons.append("改公共契约 → L3")
        if changes_schema:
            reasons.append("改 schema → L3")
        if changes_dependency_direction:
            reasons.append("改依赖方向 → L3")
        if adds_dependency:
            reasons.append("新增外部依赖 → L3（L2-3）")
        if len(modules) >= 2:
            reasons.append(f"触及 {len(modules)} 个编号目录 → L3")
        if len(paths) > self.max_files:
            reasons.append(f"改动文件 {len(paths)} 个 > {self.max_files} → L3")
        if lines > self.max_lines:
            reasons.append(f"改动 {lines} 行 > {self.max_lines} → L3")

        if level == "L2" and not reasons:
            if rule_only:
                code_files = [p for p in paths if _is_code_file(p)]
                if code_files:
                    reasons.append(
                        f"规则级变更包含代码文件 {code_files[:3]}，无法判定，保守降级 L3"
                    )
                else:
                    level = "L1"
                    reasons.append("只改规则/权重/SKILL → L1")
            elif not modules:
                reasons.append("无法判定编号模块，保守默认 L3")
            elif not paths:
                reasons.append("变更清单为空，无法判定，保守默认 L3")

        if reasons:
            level = "L3" if any("L3" in reason for reason in reasons) else level
        if level == "L2" and reasons:
            level = "L3"
        if level not in LEVELS:
            level = "L3"

        return {
            "level": level,
            "reasons": reasons,
            "module": modules[0] if len(modules) == 1 else None,
            "modules": modules,
            "files": paths,
            "lines_changed": lines,
            "stateful": bool(stateful),
        }


def classify_change(**kwargs: Any) -> Dict[str, Any]:
    """函数式入口：与 classify_change.py 的确定性判定等价。"""
    return ChangeClassifier().classify(**kwargs)


class ResearchPipeline:
    """五段研发流水线（路由 → 脑暴 → 研发 → 取证 → 门禁）。"""

    def __init__(
        self,
        root: str | Path,
        *,
        clock: Optional[Callable[[], datetime]] = None,
        classifier: Optional[ChangeClassifier] = None,
        max_explorations_per_week: int = 2,
        max_l2_changes_per_week: int = 2,
    ):
        self.root = Path(root)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.classifier = classifier or ChangeClassifier()
        self.max_explorations_per_week = int(max_explorations_per_week)
        self.max_l2_changes_per_week = int(max_l2_changes_per_week)

    # ---------------------------------------------------------------- 主流程

    def run(
        self,
        proposal: Dict[str, Any],
        *,
        route: Callable[[Dict[str, Any]], Dict[str, Any]],
        brainstorm: Callable[[Dict[str, Any]], Dict[str, Any]],
        develop: Callable[[Dict[str, Any], Dict[str, Any]], Any],
        collect_evidence: Callable[[Dict[str, Any], Any], Iterable[str]],
        gate: Optional[Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        prop = dict(proposal or {})
        proposal_id = str(prop.get("proposal_id") or "").strip()
        _require(bool(proposal_id), "proposal_id is required")
        _require(bool(str(prop.get("claim") or "").strip()), "claim is required")
        _require(
            bool(str(prop.get("falsifier") or "").strip()), "falsifier is required（缺则 hold）"
        )

        change = prop.get("change") or {}
        classified = self.classifier.classify(
            files=change.get("files") or (),
            lines_changed=change.get("lines_changed") or 0,
            changes_contract=bool(change.get("changes_contract")),
            changes_schema=bool(change.get("changes_schema")),
            changes_dependency_direction=bool(change.get("changes_dependency_direction")),
            adds_dependency=bool(change.get("adds_dependency")),
            stateful=bool(change.get("stateful")),
            rule_only=bool(change.get("rule_only")),
        )
        level = classified["level"]
        declared_level = str(prop.get("level") or "").strip() or None

        self._check_budget(level)

        # ① 路由（DreamOS）
        route_result = dict(route(prop) or {})
        route_name = str(route_result.get("route") or "").strip()
        _require(bool(route_name), "DreamOS 路由失败：route 为空")
        _require(
            route_name in {"workers", "debate"},
            f"研发流水线不接受路由 {route_name}：交易/风控请求永不进入研发",
        )

        # ② 脑暴（双链，铁律⑤：model 与 evidence_path 必须不同）
        research = dict(brainstorm(prop) or {})
        self._validate_brainstorm(research)

        # ③ 研发（DSH 子 Agent，统一 SubagentOutput 契约）
        outputs = develop(prop, route_result)
        if isinstance(outputs, dict):
            outputs = [outputs]
        outputs = list(outputs or [])
        _require(bool(outputs), "DSH 研发无产物，流水线终止")
        for item in outputs:
            _require(isinstance(item, dict), "SubagentOutput 必须为 dict")
            _require(bool(str(item.get("module") or "").strip()), "SubagentOutput 缺 module")
            _require(bool(str(item.get("summary") or "").strip()), "SubagentOutput 缺 summary")
        self._validate_dev_outputs(level, outputs)

        # ④ 取证（L0 能力矩阵）
        evidence_refs = [
            str(ref).strip() for ref in (collect_evidence(prop, outputs) or []) if str(ref).strip()
        ]
        _require(bool(evidence_refs), "无 Evidence 的改动直接打回（L0 取证为空）")

        # 产物落盘（三者缺一不得进入门禁）
        artifacts = self._write_artifacts(
            proposal_id=proposal_id,
            prop=prop,
            classified=classified,
            declared_level=declared_level,
            route_result=route_result,
            research=research,
            outputs=outputs,
            evidence_refs=evidence_refs,
        )

        # ⑤ 门禁
        if gate is None:
            state = "dev_done"
        else:
            gate_result = dict(gate(prop, artifacts) or {})
            state = "qualified" if gate_result.get("overall") == "pass" else "gates_failed"

        result = {
            "proposal_id": proposal_id,
            "level": level,
            "declared_level": declared_level,
            "level_source": "classifier",
            "level_reasons": classified["reasons"],
            "state": state,
            "route": route_result,
            "artifacts": artifacts,
            "evidence_refs": evidence_refs,
            "auto_merge": self._auto_merge_policy(level, classified),
            "run_at": self._now().isoformat(),
        }
        self._append_run(result)
        return result

    # ---------------------------------------------------------------- 校验

    @staticmethod
    def _validate_brainstorm(research: Dict[str, Any]) -> None:
        cards = list(research.get("plan_cards") or [])
        _require(len(cards) >= 2, "双链脑暴至少需要 2 张 PlanCard（side A/B 各一）")
        sides = {
            str(side.get("side") or "").upper(): side for side in (research.get("sides") or [])
        }
        _require({"A", "B"} <= set(sides), "双链脑暴必须同时包含 side A 与 side B")
        side_a, side_b = sides["A"], sides["B"]
        model_a = str(side_a.get("model") or "").strip()
        model_b = str(side_b.get("model") or "").strip()
        path_a = str(side_a.get("evidence_path") or "").strip()
        path_b = str(side_b.get("evidence_path") or "").strip()
        _require(bool(model_a and model_b), "双链脑暴缺 model，fail-closed")
        _require(bool(path_a and path_b), "双链脑暴缺 evidence_path，fail-closed")
        _require(
            model_a != model_b,
            f"两链 model 必须不同（均为 {model_a}），fail-closed（铁律⑤）",
        )
        _require(
            path_a != path_b,
            f"两链 evidence_path 必须不同（均为 {path_a}），fail-closed（铁律⑤）",
        )

    @staticmethod
    def _validate_dev_outputs(level: str, outputs: List[Dict[str, Any]]) -> None:
        if level == "L3":
            for item in outputs:
                kind = str(item.get("kind") or "").strip().lower()
                _require(
                    kind in {"adr", "spec"},
                    f"L3 只出 ADR + SPEC 草案，禁止代码变更（当前 kind={kind or '<empty>'}）",
                )
                _require(
                    not item.get("code_changes") and not item.get("diff"),
                    "L3 产物不得包含代码变更（只出 ADR/SPEC）",
                )
            return
        if level == "L2":
            for item in outputs:
                has_code = bool(item.get("code_changes") or item.get("diff"))
                _require(
                    has_code or str(item.get("kind") or "").strip().lower() in {"patch", "code"},
                    "L2 研发必须产出代码 diff（L2-2）",
                )

    # ---------------------------------------------------------------- 预算

    def _check_budget(self, level: str) -> None:
        runs = self._read_runs()
        week = self._iso_week(self._now())
        same_week = [run for run in runs if self._iso_week(self._parse(run.get("run_at"))) == week]
        _require(
            len(same_week) < self.max_explorations_per_week,
            f"本周研发探索配额已用尽（{len(same_week)}/{self.max_explorations_per_week}）",
        )
        if level == "L2":
            l2_used = sum(1 for run in same_week if run.get("level") == "L2")
            _require(
                l2_used < self.max_l2_changes_per_week,
                f"本周 L2 变更配额已用尽（{l2_used}/{self.max_l2_changes_per_week}）",
            )

    @staticmethod
    def _auto_merge_policy(level: str, classified: Dict[str, Any]) -> Dict[str, Any]:
        if level == "L3":
            return {"allowed": False, "reason": "L3 只出 ADR/SPEC，不写代码，不进入合入通道"}
        if level == "L1":
            return {"allowed": False, "reason": "L1 走 Policy 八门禁，不经代码合入"}
        if classified.get("stateful"):
            return {
                "allowed": False,
                "reason": "stateful 变更禁止自动（L2-9），须人工 + 状态恢复演练",
            }
        return {"allowed": False, "reason": "L2 自动合入未开启（SPEC §8 L2-7 未开始）"}

    # ---------------------------------------------------------------- 产物

    def _write_artifacts(
        self,
        *,
        proposal_id: str,
        prop: Dict[str, Any],
        classified: Dict[str, Any],
        declared_level: Optional[str],
        route_result: Dict[str, Any],
        research: Dict[str, Any],
        outputs: List[Dict[str, Any]],
        evidence_refs: List[str],
    ) -> Dict[str, str]:
        artifact_dir = self.root / proposal_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        now = self._now().isoformat()

        research_artifact = {
            "proposal_id": proposal_id,
            "trigger": prop.get("trigger"),
            "claim": prop.get("claim"),
            "falsifier": prop.get("falsifier"),
            "level": classified["level"],
            "declared_level": declared_level,
            "level_source": "classifier",
            "level_reasons": classified["reasons"],
            "route": route_result,
            "brainstorm": research,
            "created_at": now,
        }
        dev_artifact = {
            "proposal_id": proposal_id,
            "level": classified["level"],
            "outputs": outputs,
            "rollback_point": prop.get("rollback_point") or f"evo/{proposal_id}",
            "created_at": now,
        }

        paths = {
            "research_artifact": artifact_dir / "research_artifact.json",
            "dev_artifact": artifact_dir / "dev_artifact.json",
            "evidence_refs": artifact_dir / "evidence_refs.json",
        }
        self._write_json(paths["research_artifact"], research_artifact)
        self._write_json(paths["dev_artifact"], dev_artifact)
        self._write_json(
            paths["evidence_refs"], {"proposal_id": proposal_id, "evidence_refs": evidence_refs}
        )
        return {name: str(path) for name, path in paths.items()}

    def completion_rate(self, *, window_days: int = 28) -> Dict[str, Any]:
        """G-G14：窗口内进入研发队列的 proposal 中产出可验收产物的比例。"""
        now = self._now()
        start = now - timedelta(days=int(window_days))
        runs = [
            run
            for run in self._read_runs()
            if (parsed := self._parse(run.get("run_at"))) is not None and start <= parsed <= now
        ]
        deliverables = [run for run in runs if run.get("state") == "qualified"]
        total = len(runs)
        return {
            "window_days": int(window_days),
            "total": total,
            "deliverable": len(deliverables),
            "rate": (len(deliverables) / total) if total else 0.0,
        }

    # ---------------------------------------------------------------- 存储

    def _runs_path(self) -> Path:
        return self.root / "pipeline_runs.jsonl"

    def _append_run(self, result: Dict[str, Any]) -> None:
        path = self._runs_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "proposal_id": result["proposal_id"],
            "level": result["level"],
            "declared_level": result["declared_level"],
            "state": result["state"],
            "artifacts": result["artifacts"],
            "evidence_refs": result["evidence_refs"],
            "run_at": result["run_at"],
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def _read_runs(self) -> List[Dict[str, Any]]:
        path = self._runs_path()
        if not path.is_file():
            return []
        runs: List[Dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                runs.append(item)
        return runs

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _parse(value: Any) -> Optional[datetime]:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    @staticmethod
    def _iso_week(moment: Optional[datetime]) -> Optional[tuple]:
        if moment is None:
            return None
        iso = moment.isocalendar()
        return (iso[0], iso[1])

    def _now(self) -> datetime:
        return self.clock()
