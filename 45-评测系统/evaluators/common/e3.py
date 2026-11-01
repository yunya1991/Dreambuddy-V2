# -*- coding: utf-8 -*-
"""
e3.py — 通用准入验证器（P2-1，抽象自 33-REA E3）
==================================================
SPEC §5.4：L1 全类型执行，零致命项；≤60s。

三层：
1. 网络层 N：object_ref 可达（file/local 本地校验 / 注入 fetcher）、端点健康（注入 prober）、
   依赖资源可解析（URI 合法 + 可选 resolver）
2. 内容层 C：eval_request.v1.json schema、category↔object_type 配对、声明哈希与实际哈希一致
3. 交叉层 X：commit 声明 ↔ 制品/object_ref 实际；泛化声明 ↔ 实际；未验证声明只告警

出分：每层一个 hard item（E3-network / E3-content / E3-cross）：
- 该层有 fatal → BLOCK；有预算超时 → INCONCLUSIVE；否则 PASS

边界：
- 探针/fetcher/resolver 全部可注入；默认不联网（无 fetcher 时非本地引用记「未验证」告警）
- 评测器注册与版本锁定属 P2-9
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from core.gateway import CategoriesConfig, CategoriesConfigError
from jsonschema import Draft202012Validator
from storage.repo import EvalItemRecord

MODULE_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = MODULE_ROOT / "contracts" / "schemas" / "eval_request.v1.json"

LAYERS = ("network", "content", "cross")

FATAL = "fatal"
WARN = "warn"
TIMEOUT = "timeout"


@dataclass(frozen=True)
class ValidationIssue:
    """单条准入问题：code 形如 `N1_object_unreachable:<subject>`，便于观测与断言。"""

    layer: str
    code: str
    severity: str  # fatal / warn / timeout
    message: str
    subject: str | None = None


@dataclass(frozen=True)
class E3Context:
    """交叉层与内容层需要的「声明 vs 实际」数据（由评测器/取证侧提供）。"""

    declared_commit: str | None = None
    artifact_commit: str | None = None
    declared_sha256: str | None = None
    actual_sha256: str | None = None
    declared_claims: dict[str, str] = field(default_factory=dict)
    actual_claims: dict[str, str] = field(default_factory=dict)


class E3Validator:
    """三层准入验证器：validate 产出 issues，build_items 产出 EvalItem（hard）。"""

    def __init__(
        self,
        categories: CategoriesConfig | None = None,
        fetcher: Callable[[str], bool | None] | None = None,
        prober: Callable[[str], bool] | None = None,
        resolver: Callable[[str], bool] | None = None,
        clock: Callable[[], datetime] | None = None,
        budget_ms: int = 60_000,
        schema_path: str | Path = SCHEMA_PATH,
    ) -> None:
        self._categories = categories or CategoriesConfig.load()
        self._fetcher = fetcher
        self._prober = prober
        self._resolver = resolver
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._budget_ms = budget_ms
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        self._schema = Draft202012Validator(schema)

    # ---------- 校验 ----------

    def validate(self, request: Any, context: E3Context | None = None) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        started = self._clock()
        evaluated = 0
        for layer in LAYERS:
            if evaluated and self._budget_exceeded(started):
                remaining = LAYERS[evaluated:]
                issues.extend(
                    ValidationIssue(
                        layer=item,
                        code="BUDGET_EXCEEDED",
                        severity=TIMEOUT,
                        message=f"L1 预算 {self._budget_ms}ms 超时，后续层未执行",
                    )
                    for item in remaining
                )
                break
            checker = getattr(self, f"_check_{layer}")
            issues.extend(checker(request, context))
            evaluated += 1
        return issues

    def build_items(self, run_id: str, issues: list[ValidationIssue]) -> list[EvalItemRecord]:
        """每层一个 hard item；detail 保留全部 issue code（证据可追）。"""
        items: list[EvalItemRecord] = []
        for layer in LAYERS:
            layer_issues = [i for i in issues if i.layer == layer]
            if any(i.severity == TIMEOUT for i in layer_issues):
                status = "INCONCLUSIVE"
            elif any(i.severity == FATAL for i in layer_issues):
                status = "BLOCK"
            else:
                status = "PASS"
            items.append(
                EvalItemRecord(
                    item_id=f"{run_id}-{layer.upper()}",
                    run_id=run_id,
                    name=f"E3-{layer}",
                    kind="hard",
                    score=None,
                    n=None,
                    ci_lower=None,
                    ci_upper=None,
                    weight=None,
                    status=status,
                    evidence_id=None,
                    detail="; ".join(i.code for i in layer_issues) or None,
                )
            )
        return items

    # ---------- 网络层 ----------

    def _check_network(self, request: Any, _context: E3Context | None) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        ref = request.get("object_ref") if isinstance(request, dict) else None
        if not isinstance(ref, str) or not ref:
            issues.append(
                _issue("network", f"N1_object_unreachable:{ref}", FATAL, "object_ref 缺失")
            )
        else:
            reachable = self._object_reachable(ref)
            if reachable is False:
                issues.append(
                    _issue("network", f"N1_object_unreachable:{ref}", FATAL, "object_ref 不可达")
                )
            elif reachable is None:
                issues.append(
                    _issue(
                        "network",
                        f"N1_object_unverified:{ref}",
                        WARN,
                        "object_ref 未配置可达性校验",
                    )
                )

        manifest = request.get("env_manifest") if isinstance(request, dict) else None
        if not isinstance(manifest, dict):
            return issues

        endpoints = manifest.get("endpoints") or []
        if endpoints and self._prober is None:
            issues.append(
                _issue("network", "N2_probe_unconfigured", WARN, "端点探针未配置，端点健康未验证")
            )
        elif self._prober is not None:
            for endpoint in endpoints:
                if not self._safe_probe(endpoint):
                    issues.append(
                        _issue(
                            "network",
                            f"N2_endpoint_unhealthy:{endpoint}",
                            FATAL,
                            "端点不可达",
                        )
                    )

        for resource in manifest.get("resources") or []:
            if not _is_resource_uri(resource):
                issues.append(
                    _issue(
                        "network",
                        f"N3_resource_unresolvable:{resource}",
                        FATAL,
                        "依赖资源引用非法",
                    )
                )
            elif self._resolver is not None and not self._safe_resolve(resource):
                issues.append(
                    _issue(
                        "network",
                        f"N3_resource_unreachable:{resource}",
                        FATAL,
                        "依赖资源不可解析",
                    )
                )
        return issues

    def _object_reachable(self, ref: str) -> bool | None:
        if self._fetcher is not None:
            try:
                return self._fetcher(ref)
            except Exception:  # noqa: BLE001 — 拉取异常按不可达处理（fail-closed）
                return False
        parsed = urlparse(ref)
        if parsed.scheme in ("file", "local"):
            path = Path(parsed.path or ref.split("://", 1)[-1])
            return path.exists()
        return None  # 其他 scheme 默认不联网，交由评测器注入 fetcher

    def _safe_probe(self, endpoint: str) -> bool:
        try:
            return bool(self._prober(endpoint))  # type: ignore[misc]
        except Exception:  # noqa: BLE001
            return False

    def _safe_resolve(self, resource: str) -> bool:
        try:
            return bool(self._resolver(resource))  # type: ignore[misc]
        except Exception:  # noqa: BLE001
            return False

    # ---------- 内容层 ----------

    def _check_content(self, request: Any, context: E3Context | None) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        errors = sorted(
            self._schema.iter_errors(request),
            key=lambda e: list(e.absolute_path),
        )
        for error in errors:
            path = ".".join(str(part) for part in error.absolute_path) or "<root>"
            issues.append(_issue("content", f"C1_schema_invalid:{path}", FATAL, error.message))

        if isinstance(request, dict):
            category, object_type = request.get("category"), request.get("object_type")
            if (
                isinstance(category, str)
                and isinstance(object_type, str)
                and category in self._categories.mapping
            ):
                try:
                    allowed = self._categories.allows(category, object_type)
                except CategoriesConfigError:
                    allowed = False
                if not allowed:
                    issues.append(
                        _issue(
                            "content",
                            f"C2_category_mismatch:{category}/{object_type}",
                            FATAL,
                            "category 与 object_type 不匹配（§12 categories 映射）",
                        )
                    )

        if context is not None and context.declared_sha256 and context.actual_sha256:
            if context.declared_sha256 != context.actual_sha256:
                issues.append(
                    _issue("content", "C3_hash_mismatch", FATAL, "声明哈希与制品实际哈希不一致")
                )
        return issues

    # ---------- 交叉层 ----------

    def _check_cross(self, request: Any, context: E3Context | None) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if context is None:
            return issues

        declared = context.declared_commit
        if declared:
            candidates = [context.artifact_commit, _ref_commit(request)]
            if any(candidate and candidate != declared for candidate in candidates):
                issues.append(
                    _issue("cross", "X1_commit_mismatch", FATAL, "commit 声明与实际不一致")
                )

        for key, declared_value in context.declared_claims.items():
            actual_value = context.actual_claims.get(key)
            if actual_value is None:
                issues.append(
                    _issue("cross", f"X3_claim_unverified:{key}", WARN, "声明缺少实际值佐证")
                )
            elif actual_value != declared_value:
                issues.append(
                    _issue(
                        "cross",
                        f"X2_claim_mismatch:{key}",
                        FATAL,
                        f"声明 {declared_value} ≠ 实际 {actual_value}",
                    )
                )
        return issues

    # ---------- 预算 ----------

    def _budget_exceeded(self, started: datetime) -> bool:
        elapsed_ms = (self._clock() - started).total_seconds() * 1000
        return elapsed_ms > self._budget_ms


def _issue(layer: str, code: str, severity: str, message: str) -> ValidationIssue:
    subject = code.split(":", 1)[1] if ":" in code else None
    return ValidationIssue(
        layer=layer, code=code, severity=severity, message=message, subject=subject
    )


def _is_resource_uri(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlparse(value)
    return bool(parsed.scheme) and bool(parsed.netloc or parsed.path)


def _ref_commit(request: Any) -> str | None:
    """从 object_ref 尾段 `@<sha>` 解析 commit（无则 None）。"""
    if not isinstance(request, dict):
        return None
    ref = request.get("object_ref")
    if not isinstance(ref, str) or "@" not in ref:
        return None
    return ref.rsplit("@", 1)[-1] or None
