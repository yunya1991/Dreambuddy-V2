"""探索录制 → 适配器草案：把手机端页面快照序列压缩成 L3 工具序列。

定位：
- 输入：人工在手机上操作一遍目标流程，Agent 持续上传页面快照（节点树 + 文本 + 截图）。
- 输出：`explore.draft.v1` JSON 草案（可直接渲染为 L4 适配器源码草案）。

纪律：
- 草案只允许编排 `phone_tools` 已登记的 UI 工具；
- 任何支付/提交/锁座节点都不进入步骤，只记 warning；
- 页面签名（package + activity + 文本）同时供后续回放兼容门禁使用。
"""

from __future__ import annotations

import hashlib
import re

from phone_tools import TOOLS, CommandError, build_step

SCHEMA = "explore.draft.v1"
BASELINE_SCHEMA = "explore.baseline.v1"
CHECK_SCHEMA = "explore.check.v1"
MAX_ASSERTION_TEXTS = 3
MAX_WARNINGS = 10
MATCH_RATIO = 0.67
DEFAULT_THRESHOLD = 0.8

PAYMENT_MARKERS = ("支付", "提交订单", "确认支付", "去支付", "锁座", "占座", "代付")
SESSION_RE = re.compile(r"\d{4}[-/年]\d{1,2}|\d{1,2}月\d{1,2}日|\d{1,2}:\d{2}")
TIER_RE = re.compile(r"\d+\s*元|内场|看台|VIP|档位|票档", re.I)
ORDER_MARKERS = ("确认订单", "订单确认", "填写订单", "提交订单")


def page_signature(package: str, activity: str, nodes: list[dict]) -> str:
    """页面签名：包名 + Activity + 可见文本（顺序敏感）。"""
    texts = []
    for node in nodes or []:
        for key in ("text", "desc"):
            value = str((node or {}).get(key) or "").strip()
            if value:
                texts.append(value)
    raw = "\u0001".join([str(package or ""), str(activity or ""), "|".join(texts)])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _dedupe(snapshots: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for item in snapshots or []:
        nodes = item.get("nodes") or []
        signature = item.get("signature") or page_signature(
            item.get("package", ""), item.get("activity", ""), nodes
        )
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(dict(item, signature=signature))
    return unique


def _find_edit(nodes: list[dict]) -> dict | None:
    for node in nodes:
        if str(node.get("cls") or "").lower() == "edittext" and str(node.get("text") or "").strip():
            return node
    return None


def _find_by_regex(nodes: list[dict], pattern: re.Pattern, used: set[tuple], seq) -> dict | None:
    for index, node in enumerate(nodes):
        if (seq, index) in used:
            continue
        text = str(node.get("text") or "").strip()
        if text and pattern.search(text) and node.get("clickable", True):
            used.add((seq, index))
            return node
    return None


def _selector(node: dict) -> dict:
    text = str(node.get("text") or "").strip()
    if text:
        return {"type": "text", "value": text}
    desc = str(node.get("desc") or "").strip()
    if desc:
        return {"type": "desc", "value": desc}
    return {"type": "bounds", "value": node.get("bounds") or []}


def build_draft(exploration: dict, snapshots: list[dict]) -> dict:
    """按快照序列推断工具链，返回 `explore.draft.v1`。"""
    unique = _dedupe(snapshots)
    warnings: list[str] = []
    steps: list[dict] = []
    assertions: list[dict] = []

    if not unique:
        return {
            "schema": SCHEMA,
            "exploration_id": exploration.get("_id"),
            "app": exploration.get("app", ""),
            "goal": exploration.get("goal", ""),
            "package": "",
            "snapshot_count": 0,
            "steps": [],
            "assertions": [],
            "warnings": ["没有可用快照：请确认录制期间手机端已上传页面"],
            "ready": False,
        }

    package = str(unique[0].get("package") or "")
    app = str(exploration.get("app") or "")
    app_id = package or app

    for item in unique:
        nodes = item.get("nodes") or []
        texts = [str(n.get("text") or "").strip() for n in nodes if str(n.get("text") or "").strip()]
        assertions.append(
            {
                "seq": item.get("seq"),
                "signature": item.get("signature"),
                "package": item.get("package", ""),
                "activity": item.get("activity", ""),
                "expect": texts[:MAX_ASSERTION_TEXTS],
            }
        )

    def add(action: str, params: dict, item: dict, node: dict | None = None) -> None:
        try:
            build_step(action, **params)
        except CommandError as exc:
            warnings.append("跳过步骤 {}：{}".format(action, exc))
            return
        evidence = {"snapshot_seq": item.get("seq")}
        if node:
            evidence["selector"] = _selector(node)
            evidence["bounds"] = node.get("bounds")
        steps.append({"action": action, "params": params, "evidence": evidence})

    if app_id:
        add("open_app", {"app": app_id}, unique[0])

    search_field = ""
    for item in unique:
        edit = _find_edit(item.get("nodes") or [])
        if edit:
            search_field = "搜索"
            add(
                "search",
                {"field": search_field, "value": str(edit.get("text") or "").strip()},
                item,
                edit,
            )
            break

    used: set[tuple] = set()
    for item in unique:
        node = _find_by_regex(item.get("nodes") or [], SESSION_RE, used, item.get("seq"))
        if node:
            add("select_session", {"value": str(node["text"]).strip()}, item, node)
            break
    for item in unique:
        node = _find_by_regex(item.get("nodes") or [], TIER_RE, used, item.get("seq"))
        if node:
            add("select_tier", {"value": str(node["text"]).strip()}, item, node)
            break

    observed_order = any(
        any(marker in str(item.get("page_text") or "") for marker in ORDER_MARKERS) for item in unique
    )
    if not observed_order:
        warnings.append("未观察到官方下单页，goto_order_page 为推断步骤")
    add("goto_order_page", {}, unique[-1])
    add("stop", {"reason": "await_human_confirm"}, unique[-1])

    payment_seen = any(
        any(marker in (str(n.get("text") or "") + str(n.get("desc") or "")) for marker in PAYMENT_MARKERS)
        for item in unique
        for n in (item.get("nodes") or [])
    )
    if payment_seen:
        warnings.append("快照含支付/提交节点，已忽略：草案不含支付步骤")

    for action in ("select_session", "select_tier"):
        if not any(s["action"] == action for s in steps):
            warnings.append("未识别到 {} 步骤，启用前请人工补齐".format(action))

    return {
        "schema": SCHEMA,
        "exploration_id": exploration.get("_id"),
        "app": app,
        "goal": exploration.get("goal", ""),
        "package": package,
        "snapshot_count": len(unique),
        "steps": steps,
        "assertions": assertions,
        "warnings": warnings[:MAX_WARNINGS],
        "ready": bool(steps) and bool(assertions) and all(s["action"] in TOOLS for s in steps),
    }


def build_baseline(exploration: dict, snapshots: list[dict], name: str) -> dict:
    """把一次录制固化为适配器基线（步骤 + 逐帧断言），供后续改版比对。"""
    draft = build_draft(exploration, snapshots)
    return {
        "schema": BASELINE_SCHEMA,
        "name": name,
        "app": exploration.get("app", ""),
        "exploration_id": exploration.get("_id"),
        "steps": draft["steps"],
        "assertions": draft["assertions"],
    }


def _snapshot_blob(snapshot: dict) -> str:
    parts = [str(snapshot.get("page_text") or "")]
    for node in snapshot.get("nodes") or []:
        for key in ("text", "desc"):
            value = str((node or {}).get(key) or "").strip()
            if value:
                parts.append(value)
    return " | ".join(parts)


def check_compatibility(
    baseline: dict, snapshots: list[dict], threshold: float = DEFAULT_THRESHOLD
) -> dict:
    """回放兼容门禁：基线断言在新录制中命中率 + 关键步骤取值仍在页面出现。"""
    unique = _dedupe(snapshots)
    assertions = baseline.get("assertions") or []
    blobs = [_snapshot_blob(item) for item in unique]
    matched: list[dict] = []
    missing: list[dict] = []

    for assertion in assertions:
        hit = None
        for snapshot, blob in zip(unique, blobs):
            if assertion.get("signature") and assertion["signature"] == snapshot.get("signature"):
                hit = snapshot
                break
            expect = [item for item in (assertion.get("expect") or []) if item]
            if expect:
                overlap = sum(1 for item in expect if item in blob)
                if overlap / len(expect) >= MATCH_RATIO:
                    hit = snapshot
                    break
        if hit:
            matched.append({"seq": assertion.get("seq"), "matched_seq": hit.get("seq")})
        else:
            missing.append(
                {"seq": assertion.get("seq"), "signature": assertion.get("signature"), "expect": assertion.get("expect")}
            )

    coverage = round(len(matched) / len(assertions), 2) if assertions else 0.0
    all_text = " | ".join(blobs)
    step_misses = []
    for step in baseline.get("steps") or []:
        value = (step.get("params") or {}).get("value")
        if value and value not in all_text:
            step_misses.append({"action": step.get("action"), "value": value})

    return {
        "schema": CHECK_SCHEMA,
        "compatible": bool(assertions) and coverage >= threshold and not step_misses,
        "coverage": coverage,
        "threshold": threshold,
        "snapshot_count": len(unique),
        "matched": matched,
        "missing": missing,
        "step_misses": step_misses,
    }


def render_adapter(draft: dict) -> str:
    """把草案渲染为 L4 适配器源码草案（默认不落盘，需人工复核后启用）。"""
    app = re.sub(r"[^0-9a-zA-Z]+", " ", str(draft.get("app") or "explore")).strip()
    class_name = "".join(word.title() for word in app.split()) or "Explore"

    lines = [
        '"""由 mra explore 生成的适配器草案：请人工复核选择器与断言后再启用。"""',
        "",
        "from .base import BasePhoneAdapter, build_step, validate_steps",
        "",
        "",
        "class {}Draft(BasePhoneAdapter):".format(class_name),
        '    """目标：{}"""'.format(str(draft.get("goal") or "").replace('"', "'")),
        "",
        '    NAME = "{}_draft"'.format(class_name.lower()),
        '    APP = "{}"'.format(str(draft.get("package") or "")),
        '    ROUTE_HINT = ""',
        '    SEARCH_FIELD = "{}"'.format(
            next(
                (s["params"].get("field", "") for s in draft.get("steps", []) if s["action"] == "search"),
                "",
            )
        ),
        '    IDENT_FIELD = ""',
        "",
        "    def _steps(self, target):",
        "        return validate_steps([",
    ]
    for step in draft.get("steps", []):
        if step["action"] in ("goto_order_page", "stop"):
            continue  # 基类固定追加，避免重复
        params = ", ".join("{}={!r}".format(k, v) for k, v in step.get("params", {}).items())
        suffix = ", " + params if params else ""
        lines.append('            build_step("{}{}"),'.format(step["action"], suffix))
    lines.extend(["        ])", ""])
    return "\n".join(lines)
