"""
DreamOS capability 层 — 运行时工具集唯一副本 (tool_set v1.0)

对齐 56-L2架构能力聚合层/contracts/tool_set.schema.json:
    - 输入: 47-MCP管理系统/registry/mcp_capabilities.yaml（唯一事实源）
    - 输出: 冻结的工具面快照（可见性 / 审批 / 生效语义随快照固化）
    - 3.1 / 52 / DreamOS 只读消费，禁止各自推导工具面

映射规则（可机器判定）:
    name        l{层}.{domain 连字符转下划线}.{tool.name}
    layer       取自 shell.layer
    exposure    control → control；readonly-observe / in-process-only → read；
                not-exposed → 整个壳不进入快照
    effect      trade-exec 域的写工具 → trade；其余 read → read、write/read-write → write
    requires_mandate  write/trade 强制 true；read 继承注册表声明
    visibility  read → both（模型与 App 均可见）；write/trade → model（仅模型经 Mandate 通道）
    approval    trade → human；write → requires_mandate ? human : auto；read → auto
    denied_tools  deprecated 壳的工具 + 调用方显式屏蔽项

D3 配额交叉校验见 quota_report()：分层配额 / max_total_tools / 单壳上限 / 口径一致性。
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

TOOL_SET_SCHEMA_VERSION = "1.0"

POLICY_ORDER = ["deny", "mode", "allow", "human"]

POLICY_MODES = ("default", "plan", "accept_edits", "bypass")

# 与 47 registry 校验器一致：available + degraded 计入 active
ACTIVE_STATUSES = ("available", "degraded")

LAYER_PREFIX = {"L0": "l0", "L1": "l1", "L2": "l2"}

NAME_PATTERN = re.compile(r"^l[0-2]\.[a-z0-9_]+\.[a-z0-9_]+$")

SHELL_PATTERN = re.compile(r"^l[0-2]\.[a-z0-9_]+\.mcp$")

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{3,64}$")

_TRADE_DOMAIN = "trade-exec"

_EXPOSURE_MAP = {
    "control": "control",
    "readonly-observe": "read",
    "in-process-only": "read",
}

DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[4] / "47-MCP管理系统" / "registry" / "mcp_capabilities.yaml"
)

# H2 影子阶段：v1.0 快照不动，旁路写 tool_set.hcp.json（SPEC-56-H v0.3 §4.2）
HCP_SIDECAR_SCHEMA_VERSION = "hcp-1.0"
HCP_TOOL_LIMIT = 15


class ToolSetError(ValueError):
    """注册表无法映射为合法 tool_set（漂移需立即暴露，不静默跳过）"""


# ============================================================
# 映射规则
# ============================================================


def _slug(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _normalize_shell_id(value: Any) -> str:
    """注册表壳 ID 含连字符（l0.trade-exec.mcp），契约要求下划线，此处规范化"""
    raw = str(value or "")
    parts = raw.split(".")
    if len(parts) != 3 or parts[2] != "mcp":
        raise ToolSetError(f"壳 ID 格式非法: {raw!r}")
    normalized = f"{parts[0]}.{_slug(parts[1])}.mcp"
    if not SHELL_PATTERN.match(normalized):
        raise ToolSetError(f"壳 ID 不符合契约 pattern: {raw!r} → {normalized!r}")
    return normalized


def _tool_entry(shell: Dict[str, Any], tool: Dict[str, Any]) -> Dict[str, Any]:
    layer = str(shell.get("layer") or "")
    if layer not in LAYER_PREFIX:
        raise ToolSetError(f"壳 {shell.get('shell_id')} 缺少合法 layer: {layer!r}")

    domain = _slug(shell.get("capability_domain") or tool.get("domain"))
    name = f"{LAYER_PREFIX[layer]}.{domain}.{_slug(tool.get('name'))}"

    shell_id = _normalize_shell_id(shell.get("shell_id"))
    if not NAME_PATTERN.match(name):
        raise ToolSetError(f"工具名不符合契约 pattern: {name!r}（壳 {shell_id}）")

    exposure = _EXPOSURE_MAP.get(str(shell.get("exposure") or ""))
    if exposure is None:
        raise ToolSetError(f"壳 {shell_id} 的 exposure 不可映射: {shell.get('exposure')!r}")

    read_write = str(tool.get("read_write") or "read")
    if read_write == "read":
        effect = "read"
    elif tool.get("domain") == _TRADE_DOMAIN:
        effect = "trade"
    else:
        effect = "write"

    requires_mandate = bool(tool.get("requires_mandate")) or effect in ("write", "trade")

    if effect == "trade":
        approval = "human"
    elif effect == "write":
        approval = "human" if requires_mandate else "auto"
    else:
        approval = "auto"

    visibility = "both" if effect == "read" else "model"

    return {
        "name": name,
        "shell": shell_id,
        "layer": layer,
        "exposure": exposure,
        "effect": effect,
        "requires_mandate": requires_mandate,
        "visibility": visibility,
        "approval": approval,
    }


# ============================================================
# 快照生成
# ============================================================


def build_tool_set_from_registry(
    registry: Dict[str, Any],
    run_id: Optional[str] = None,
    mode: str = "default",
    generated_at: Optional[datetime] = None,
    extra_denied: Iterable[str] = (),
) -> Dict[str, Any]:
    """由注册表文档生成 tool_set 快照（纯函数，便于测试与回放）"""
    if mode not in POLICY_MODES:
        raise ToolSetError(f"policy.mode 非法: {mode!r}，允许 {POLICY_MODES}")

    normalized_run_id = (
        run_id if run_id and RUN_ID_PATTERN.match(run_id) else f"run-{uuid.uuid4().hex[:12]}"
    )
    stamp = generated_at or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)

    tools: List[Dict[str, Any]] = []
    denied: List[str] = []

    for shell in registry.get("shells") or []:
        status = str(shell.get("status") or "")
        if str(shell.get("exposure") or "") == "not-exposed":
            continue
        if status in ACTIVE_STATUSES:
            tools.extend(_tool_entry(shell, tool) for tool in shell.get("tools") or [])
            continue
        if status == "deprecated":
            layer = str(shell.get("layer") or "")
            domain = _slug(shell.get("capability_domain"))
            for tool in shell.get("tools") or []:
                name = f"{LAYER_PREFIX.get(layer, 'l0')}.{domain}.{_slug(tool.get('name'))}"
                if NAME_PATTERN.match(name):
                    denied.append(name)

    names = [t["name"] for t in tools]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ToolSetError(f"工具名重复（同一能力域内不可重名）: {duplicates}")

    extras = set(extra_denied)
    malformed = sorted(d for d in extras if not NAME_PATTERN.match(d))
    if malformed:
        raise ToolSetError(f"extra_denied 含非法工具名: {malformed}")
    conflict = sorted(extras & set(names))
    if conflict:
        raise ToolSetError(f"denied_tools 与 tools 冲突: {conflict}")

    # 退役壳与活跃壳同域重名时以活跃为准（如 agent.debate 与 l2.debate 双壳期）
    denied = sorted({d for d in denied if d not in names} | extras)

    snapshot: Dict[str, Any] = {
        "schema_version": TOOL_SET_SCHEMA_VERSION,
        "run_id": normalized_run_id,
        "generated_at": stamp.isoformat(),
        "source": "47-registry",
        "policy": {"order": list(POLICY_ORDER), "mode": mode},
        "tools": tools,
    }
    if denied:
        snapshot["denied_tools"] = denied
    return snapshot


def build_tool_set(
    registry_path: Optional[Path] = None,
    run_id: Optional[str] = None,
    mode: str = "default",
    generated_at: Optional[datetime] = None,
    extra_denied: Iterable[str] = (),
) -> Dict[str, Any]:
    """读取 47 registry YAML 并生成 tool_set 快照"""
    path = Path(registry_path) if registry_path else DEFAULT_REGISTRY_PATH
    if not path.exists():
        raise ToolSetError(f"注册表不存在: {path}")

    try:
        import yaml  # 延迟导入：仅生成快照时需要
    except ImportError as exc:  # pragma: no cover - 环境缺依赖时给出明确指引
        raise ToolSetError("缺少 PyYAML，无法读取 47 registry") from exc

    with path.open("r", encoding="utf-8") as fh:
        registry = yaml.safe_load(fh) or {}
    return build_tool_set_from_registry(
        registry,
        run_id=run_id,
        mode=mode,
        generated_at=generated_at,
        extra_denied=extra_denied,
    )


# ============================================================
# H2：tool_set 影子 sidecar（hash / version / diff / 审批绑定）
# ============================================================


def _canonical_tools_json(tools: Iterable[Dict[str, Any]]) -> str:
    normalized = sorted(
        (dict(item) for item in tools or [] if isinstance(item, dict)),
        key=lambda item: str(item.get("name") or ""),
    )
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compute_tool_set_hash(tools: Iterable[Dict[str, Any]]) -> str:
    """对排序后的 tools canonical JSON 做 sha256；同会话同 mode 且工具未变时稳定"""
    digest = hashlib.sha256(_canonical_tools_json(tools).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def diff_tools(
    previous: Iterable[Dict[str, Any]],
    current: Iterable[Dict[str, Any]],
) -> Dict[str, List[str]]:
    """按 name 对比两次工具面；changed 仅记录内容变化的同名工具"""
    prev = {str(t.get("name")): t for t in previous or [] if isinstance(t, dict)}
    curr = {str(t.get("name")): t for t in current or [] if isinstance(t, dict)}
    return {
        "added": sorted(curr.keys() - prev.keys()),
        "removed": sorted(prev.keys() - curr.keys()),
        "changed": sorted(name for name in prev.keys() & curr.keys() if prev[name] != curr[name]),
    }


def _parse_rfc3339(value: Any) -> datetime:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ToolSetError(f"时间字段不是合法 RFC3339: {value!r}") from exc
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def build_hcp_sidecar(
    snapshot: Dict[str, Any],
    *,
    session_id: str,
    tool_set_id: Optional[str] = None,
    previous: Optional[Dict[str, Any]] = None,
    approval_ref: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """生成 hcp-1.0 影子快照（不改写 v1.0 快照本体）。

    previous: {"version": int, "snapshot": <上一次 v1.0 快照>}
    规则: 工具面未变 → 沿用 version 且 diff 为空；变更 → version+1 并输出 diff。
    """
    if not isinstance(snapshot, dict):
        raise ToolSetError("snapshot 必须是 dict")

    tools = snapshot.get("tools") or []
    if not isinstance(tools, list):
        raise ToolSetError("snapshot.tools 必须是数组")
    if len(tools) > HCP_TOOL_LIMIT:
        raise ToolSetError(
            f"工具面 {len(tools)} 个超过上限 {HCP_TOOL_LIMIT}（G-L2-13：len(tools) ≤ max_tools_per_shell）"
        )
    if not isinstance(session_id, str) or not session_id.strip():
        raise ToolSetError("H2 sidecar 必须绑定非空 session_id")

    current_hash = compute_tool_set_hash(tools)
    prev = previous or {}
    prev_tools = (prev.get("snapshot") or {}).get("tools") or []
    prev_version = int(prev.get("version") or 0)
    unchanged = bool(prev) and compute_tool_set_hash(prev_tools) == current_hash

    if not prev or unchanged:
        diff = {"added": [], "removed": [], "changed": []}
    else:
        diff = diff_tools(prev_tools, tools)

    version = prev_version if unchanged else prev_version + 1

    return {
        "schema_version": HCP_SIDECAR_SCHEMA_VERSION,
        "tool_set_id": tool_set_id or f"ts-{uuid.uuid4().hex[:12]}",
        "run_id": snapshot.get("run_id"),
        "session_id": session_id,
        "mode": (snapshot.get("policy") or {}).get("mode") or "default",
        "version": max(1, version),
        "hash": current_hash,
        "diff": diff,
        "approval_ref": approval_ref,
    }


def validate_tool_set_approval(
    sidecar: Dict[str, Any],
    mandate: Dict[str, Any],
    *,
    generated_at: Any,
) -> None:
    """G-L2-13：审批必须引用同一 hash，且签发时间晚于快照生成时间（先快照后审批）"""
    if not isinstance(sidecar, dict) or not isinstance(mandate, dict):
        raise ToolSetError("sidecar / mandate 必须是 dict")

    mandate_id = mandate.get("mandate_id")
    if not mandate_id:
        raise ToolSetError("mandate 缺少 mandate_id")
    if mandate.get("tool_set_hash") != sidecar.get("hash"):
        raise ToolSetError("mandate.tool_set_hash 与 tool_set 快照 hash 不一致（G-L2-13）")

    approval_ref = sidecar.get("approval_ref") or {}
    if approval_ref:
        if approval_ref.get("tool_set_hash") != sidecar.get("hash"):
            raise ToolSetError("approval_ref.tool_set_hash 与快照 hash 不一致")
        if approval_ref.get("mandate_id") != mandate_id:
            raise ToolSetError("approval_ref.mandate_id 与 mandate 不一致")

    if _parse_rfc3339(mandate.get("issued_at")) <= _parse_rfc3339(generated_at):
        raise ToolSetError("审批签发时间必须晚于快照 generated_at（先快照后审批）")


def write_hcp_sidecar(sidecar: Dict[str, Any], path: Path) -> Path:
    """旁路落盘 tool_set.hcp.json（v1.0 原文件不动）"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(sidecar, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


# ============================================================
# D3 配额交叉校验
# ============================================================


def _active_shells(registry: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        s
        for s in registry.get("shells") or []
        if str(s.get("status") or "") in ACTIVE_STATUSES
        and str(s.get("exposure") or "") != "not-exposed"
    ]


def quota_report(registry: Dict[str, Any]) -> Dict[str, Any]:
    """D3：注册表配额与工具面交叉校验（不依赖快照，直接对注册表复算）

    校验:
        E-LAYER-EXCEEDED       分层工具数 > layer_quota[层]
        E-TOTAL-EXCEEDED       活跃工具总数 > layer_quota.total
        E-MAX-TOTAL-EXCEEDED   活跃工具总数 > max_total_tools
        E-SHELL-EXCEEDED       单壳工具数 > max_tools_per_shell
        E-ROLE-EXCEEDED        角色工具数 > max_tools_per_role
    口径:
        E-TOTAL-CAP-MISMATCH   max_total_tools 与 layer_quota.total 不一致（GAP-18，记 warning）
    """
    limits = registry.get("enums") or {}
    layer_quota = limits.get("layer_quota") or {}
    max_total_tools = int(limits.get("max_total_tools") or 0)
    max_per_shell = int(limits.get("max_tools_per_shell") or 0)
    max_per_role = int(limits.get("max_tools_per_role") or 0)

    per_layer = {"L0": 0, "L1": 0, "L2": 0}
    per_shell: Dict[str, int] = {}
    for shell in _active_shells(registry):
        layer = str(shell.get("layer") or "")
        count = len(shell.get("tools") or [])
        if layer in per_layer:
            per_layer[layer] += count
        per_shell[str(shell.get("shell_id"))] = count

    total = sum(per_layer.values())
    violations: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    for layer, count in per_layer.items():
        cap = int(layer_quota.get(layer) or 0)
        if cap and count > cap:
            violations.append(
                {"code": "E-LAYER-EXCEEDED", "layer": layer, "count": count, "cap": cap}
            )

    quota_total = int(layer_quota.get("total") or 0)
    if quota_total and total > quota_total:
        violations.append({"code": "E-TOTAL-EXCEEDED", "count": total, "cap": quota_total})
    if max_total_tools and total > max_total_tools:
        violations.append({"code": "E-MAX-TOTAL-EXCEEDED", "count": total, "cap": max_total_tools})
    if quota_total and max_total_tools and quota_total != max_total_tools:
        warnings.append(
            {
                "code": "E-TOTAL-CAP-MISMATCH",
                "max_total_tools": max_total_tools,
                "layer_quota_total": quota_total,
            }
        )

    if max_per_shell:
        for shell_id, count in sorted(per_shell.items()):
            if count > max_per_shell:
                violations.append(
                    {
                        "code": "E-SHELL-EXCEEDED",
                        "shell": shell_id,
                        "count": count,
                        "cap": max_per_shell,
                    }
                )

    if max_per_role:
        for role, spec in (registry.get("worker_roles") or {}).items():
            tools = (spec or {}).get("tools") or []
            if len(tools) > max_per_role:
                violations.append(
                    {
                        "code": "E-ROLE-EXCEEDED",
                        "role": role,
                        "count": len(tools),
                        "cap": max_per_role,
                    }
                )

    return {
        "ok": not violations,
        "active_total": total,
        "active_by_layer": per_layer,
        "active_by_shell": per_shell,
        "layer_quota": dict(layer_quota),
        "max_total_tools": max_total_tools,
        "max_tools_per_shell": max_per_shell,
        "max_tools_per_role": max_per_role,
        "violations": violations,
        "warnings": warnings,
    }
