# -*- coding: utf-8 -*-
"""T1–T3 图规格制品落盘（SPEC-54-统计图表化能力 ADR-V12 / V-AC12 / L1S-04）。

路径固定为 `54-L1架构能力聚合层/artifacts/visual/<capability>/<as_of>.json`。

硬约束：
  - **幂等**：同 `capability + as_of + payload` 重跑字节一致；内容已相同则不重写文件；
  - **原子**：先写同目录临时文件再 `os.replace`，读侧永不见半截文件；
  - **确定性**：规范 JSON（`sort_keys`、固定分隔符、UTF-8、末尾 LF），不写时钟字段；
  - **FAIL-OPEN**：`L1_ARTIFACTS_ENABLED=0/false/no/off` 时整体不落盘；
  - **路径安全**：`capability` / `as_of` 仅允许 `[A-Za-z0-9._-]`，且不得为 `.` / `..`。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from typing import Any, Dict, Iterable, List, Mapping, Optional

MODULE_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
ARTIFACT_SUBDIR = os.path.join("artifacts", "visual")
# 可落盘的图种（T1 表格 / T2 曲线 / T3 矩阵·图·树）
ARTIFACT_KINDS = frozenset({"table", "series", "matrix", "graph", "tree"})
_TOKEN = re.compile(r"^[A-Za-z0-9._-]+$")


def enabled() -> bool:
    """`L1_ARTIFACTS_ENABLED=0/false/no/off` 时全量不落盘。"""
    raw = os.environ.get("L1_ARTIFACTS_ENABLED", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def artifacts_root(root: Optional[str] = None) -> str:
    return os.path.abspath(root) if root else os.path.join(MODULE_ROOT, ARTIFACT_SUBDIR)


def _safe_token(value: Any, field: str) -> str:
    token = str(value or "").strip()
    if not token or token in {".", ".."} or not _TOKEN.match(token):
        raise ValueError(f"invalid {field}: {value!r}")
    return token


def dumps(payload: Any) -> bytes:
    """规范 JSON：键排序 + 固定分隔符 + 2 空格缩进 + 末尾 LF（同输入字节一致）。"""
    text = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        separators=(",", ": "),
        default=str,
    )
    return (text + "\n").encode("utf-8")


def artifact_path(capability: str, as_of: str, *, root: Optional[str] = None) -> str:
    return os.path.join(
        artifacts_root(root),
        _safe_token(capability, "capability"),
        f"{_safe_token(as_of, 'as_of')}.json",
    )


def write_artifact(
    capability: str, as_of: str, payload: Any, *, root: Optional[str] = None
) -> Dict[str, Any]:
    """写单份制品；内容未变返回 `written=False` 且不触碰文件（V-AC12）。"""
    target = artifact_path(capability, as_of, root=root)
    data = dumps(payload)
    digest = hashlib.sha256(data).hexdigest()
    if os.path.isfile(target):
        with open(target, "rb") as fh:
            if fh.read() == data:
                return {"path": target, "written": False, "sha256": digest, "bytes": len(data)}
    directory = os.path.dirname(target)
    os.makedirs(directory, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        dir=directory, prefix=".tmp-", suffix=".json", delete=False
    )
    temp_name = handle.name
    try:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(temp_name, target)
        temp_name = ""
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
    return {"path": target, "written": True, "sha256": digest, "bytes": len(data)}


def read_artifact(
    capability: str, as_of: Optional[str] = None, *, root: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """读制品；`as_of=None` 取字典序最新一份，缺失返回 None（不伪造）。"""
    if as_of is None:
        versions = list_artifacts(root=root).get(str(capability), [])
        if not versions:
            return None
        as_of = versions[-1]
    target = artifact_path(capability, as_of, root=root)
    if not os.path.isfile(target):
        return None
    with open(target, "r", encoding="utf-8") as fh:
        return json.load(fh)


def list_artifacts(*, root: Optional[str] = None) -> Dict[str, List[str]]:
    """`{capability: [as_of, ...]}`（升序）；目录不存在返回空字典。"""
    base = artifacts_root(root)
    if not os.path.isdir(base):
        return {}
    out: Dict[str, List[str]] = {}
    for capability in sorted(os.listdir(base)):
        folder = os.path.join(base, capability)
        if not os.path.isdir(folder) or capability.startswith("."):
            continue
        versions = sorted(
            name[: -len(".json")]
            for name in os.listdir(folder)
            if name.endswith(".json") and not name.startswith(".")
        )
        if versions:
            out[capability] = versions
    return out


def consume_latest(
    *, root: Optional[str] = None, capability: Optional[str] = None
) -> Dict[str, Any]:
    """T4 反思消费入口（L1S-05）：回显各能力**最新**制品摘要，只读 + FAIL-OPEN。

    返回 `{"ok", "as_of", "capabilities", "items"}`；无制品属正常空态（`ok=True`），
    目录不可读才返回 `ok=False`（调用方降级，不伪造 capability 列表）。
    """
    try:
        listing = list_artifacts(root=root)
    except OSError as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "as_of": None,
            "capabilities": [],
            "items": [],
        }
    names = sorted(listing) if capability is None else [str(capability)]
    items: List[Dict[str, Any]] = []
    for name in names:
        versions = listing.get(name) or []
        if not versions:
            continue
        latest = versions[-1]
        payload = read_artifact(name, latest, root=root) or {}
        items.append(
            {
                "capability": name,
                "as_of": latest,
                "n_visuals": payload.get("n_visuals"),
                "spec_version": payload.get("spec_version"),
            }
        )
    return {
        "ok": True,
        "as_of": max((item["as_of"] for item in items), default=None),
        "capabilities": [item["capability"] for item in items],
        "items": items,
    }


def persist_visuals(
    visuals: Iterable[Mapping[str, Any]],
    as_of: Optional[str],
    *,
    root: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """按 `source_capability` 分组落盘 `visuals`（T1–T3），返回逐能力写盘结果。

    - 无 `as_of` → 不落盘（制品按 `as_of` 版本化，缺版本不猜）；
    - 图种不在 `ARTIFACT_KINDS` 或缺 `source_capability` → 跳过；
    - 组内按 `id` 排序，保证同输入字节一致；
    - 任一能力写盘异常不影响其他能力（FAIL-OPEN，异常聚合到 `errors`）。
    """
    if not enabled():
        return {"enabled": False, "reason": "artifacts_disabled"}
    if not as_of:
        return {"enabled": True, "reason": "as_of_missing", "written": [], "unchanged": []}

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for visual in visuals or ():
        if not isinstance(visual, Mapping):
            continue
        capability = str(visual.get("source_capability") or "")
        if not capability or str(visual.get("kind") or "") not in ARTIFACT_KINDS:
            continue
        grouped.setdefault(capability, []).append(dict(visual))

    written: List[str] = []
    unchanged: List[str] = []
    errors: Dict[str, str] = {}
    for capability in sorted(grouped):
        rows = sorted(grouped[capability], key=lambda row: str(row.get("id") or ""))
        payload: Dict[str, Any] = {
            "capability": capability,
            "as_of": as_of,
            "spec_version": rows[0].get("spec_version"),
            "n_visuals": len(rows),
            "visuals": rows,
        }
        if extra:
            payload["context"] = dict(extra)
        try:
            result = write_artifact(capability, as_of, payload, root=root)
        except (OSError, ValueError) as exc:
            errors[capability] = f"{type(exc).__name__}: {exc}"
            continue
        (written if result["written"] else unchanged).append(capability)
    return {
        "enabled": True,
        "root": artifacts_root(root),
        "as_of": as_of,
        "written": written,
        "unchanged": unchanged,
        "errors": errors,
    }
