"""链路埋点与监控：每个手机动作落一条事件，规则发现异常，交由千问接管。

职责边界：
- 本模块只负责「记录 + 发现问题」，不做任何手机操作、不调用大模型。
- 接管动作由 `mra watch --heal` 调用宪法闭环（问千问 → 大模型验证 → 再问）。

事件形状（JSONL，按天分文件）：
{"ts": 1763..., "trace_id": "...", "stage": "...", "action": "...", "adapter": "...",
 "ok": true, "state": "done", "duration": 12.3, "page_text": "...", "screenshot": "...",
 "error": "", "detail": {...}}
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

TERMINAL_ACTIONS = ("xhs_publish", "douyin_publish", "jy_export", "jy_share")
OK_STATES = ("ok", "done", "pending_human")
# 这些动作本就不产出页面文本，不参与「白屏」判定，避免误报
PAGE_TEXT_EXEMPT = {"pkg", "apps", "adapters", "tools", "open_app", "key", "swipe", "type", "tap", "shot"}


def trace_dir() -> Path:
    root = Path(os.environ.get("MRA_STATE_DIR") or (Path.home() / ".mobile-reservation-assist"))
    path = root / "traces"
    path.mkdir(parents=True, exist_ok=True)
    return path


def record(
    stage: str,
    action: str,
    ok: bool,
    *,
    trace_id: str = "",
    adapter: str = "",
    state: str = "",
    duration: float = 0.0,
    page_text: str = "",
    screenshot: str = "",
    error: str = "",
    detail: dict | None = None,
) -> dict:
    """追加一条埋点；写失败不影响主链路。"""
    event = {
        "ts": int(time.time()),
        "trace_id": trace_id or stage,
        "stage": stage,
        "action": action,
        "adapter": adapter,
        "ok": bool(ok),
        "state": state,
        "duration": round(float(duration), 2),
        "page_text": (page_text or "")[:1000],
        "screenshot": screenshot or "",
        "error": (error or "")[:400],
        "detail": detail or {},
    }
    try:
        path = trace_dir() / "{}.jsonl".format(time.strftime("%Y%m%d"))
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return event


def tail(limit: int = 50, trace_id: str = "") -> list[dict]:
    """读取最近事件（按时间正序），可按 trace_id 过滤。"""
    directory = trace_dir()
    files = sorted(directory.glob("*.jsonl"))[-2:]
    events: list[dict] = []
    for path in files:
        try:
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
        except OSError:
            continue
    if trace_id:
        events = [event for event in events if event.get("trace_id") == trace_id]
    return events[-limit:]


def detect(events: list[dict]) -> list[dict]:
    """确定性规则发现异常；只报「可被证据支撑」的问题。"""
    anomalies: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(rule: str, trace: str, message: str, evidence: list[dict]) -> None:
        key = (rule, trace)
        if key in seen:
            return
        seen.add(key)
        anomalies.append({"rule": rule, "trace_id": trace, "message": message, "evidence": evidence[-5:]})

    groups: dict[str, list[dict]] = {}
    for event in events:
        groups.setdefault(str(event.get("trace_id") or "default"), []).append(event)

    for trace, items in groups.items():
        streak: list[dict] = []
        for event in items:
            if event.get("ok"):
                streak = []
                continue
            streak.append(event)
            if len(streak) >= 2:
                add(
                    "repeat_failure",
                    trace,
                    "同一链路连续 {} 次动作失败：{}".format(len(streak), event.get("action", "")),
                    list(streak),
                )
                break

        for event in items:
            if not event.get("ok") and event.get("action") in TERMINAL_ACTIONS:
                add(
                    "terminal_failure",
                    trace,
                    "终态动作失败：{}（{}）".format(event.get("action"), event.get("error", "")),
                    [event],
                )
            if str(event.get("state") or "") == "timeout":
                add("timeout", trace, "手机回执超时：{}".format(event.get("action", "")), [event])

        # 页面停滞：连续 3 条相同页面文本，且期间有失败
        texts = [str(event.get("page_text") or "") for event in items]
        if len(items) >= 3:
            for index in range(2, len(items)):
                window = texts[index - 2:index + 1]
                if window[0] and len(set(window)) == 1 and any(not items[i].get("ok") for i in range(index - 2, index + 1)):
                    add("page_stuck", trace, "页面连续 3 次无变化且存在失败", items[index - 2:index + 1])
                    break

        # 白屏：动作成功但页面文本为空（只针对应产出页面文本的动作）
        if (
            items
            and all(not str(event.get("page_text") or "").strip() for event in items[-2:])
            and items[-1].get("ok")
            and all(event.get("action") not in PAGE_TEXT_EXEMPT for event in items[-2:])
        ):
            add("page_empty", trace, "连续动作页面文本为空（疑似白屏/无权限）", items[-2:])

    return anomalies


def summary(events: list[dict]) -> dict:
    total = len(events)
    failed = sum(1 for event in events if not event.get("ok"))
    return {
        "events": total,
        "failed": failed,
        "traces": len({event.get("trace_id") for event in events}),
        "latest": events[-1] if events else {},
    }
