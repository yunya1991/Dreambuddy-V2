"""本地作业执行器：命中作业 → u2 流程 → 结构化回执。

并存策略：只有剪映 / 抖音走这里；其余适配器继续走 gateway + Auto.js。
开关：MRA_PHONE_DRIVER=auto（默认，u2 可用即本地）| gateway（全走旧通道）| u2（强制本地）。

铁律：任何一步失败立即停止并问千问要修正方案，不在本地反复盲试。
"""

from __future__ import annotations

import os

LOCAL_DRIVERS = ("jianying", "douyin")
MODES = ("auto", "gateway", "u2")

CONSULT_SYSTEM = (
    "你是安卓 UI 自动化排障助手。给出唯一一条最可能奏效的下一步操作建议，"
    "要求：一句话、20 字以内、只描述点哪里/输入什么，不要解释，不要给多个方案。"
)


def driver_mode() -> str:
    mode = (os.environ.get("MRA_PHONE_DRIVER") or "auto").strip().lower()
    return mode if mode in MODES else "auto"


def use_local_driver(adapter: str) -> bool:
    if adapter not in LOCAL_DRIVERS:
        return False
    mode = driver_mode()
    if mode == "gateway":
        return False
    if mode == "u2":
        return True
    from .u2_driver import available

    return available()


def make_driver():
    from .u2_driver import U2Driver

    return U2Driver()


def consult_qwen(adapter: str, exc) -> str:
    """失败后先问千问（brains 通道）；不重复尝试同一动作。"""
    try:
        import brain
    except ImportError:
        return ""
    if not brain.available():
        return ""
    prompt = "适配器：{}\n失败步骤：{}\n错误：{}\n当前页面文本：\n{}".format(
        adapter, getattr(exc, "step", ""), getattr(exc, "message", str(exc)),
        (getattr(exc, "page_text", "") or "")[:800],
    )
    try:
        answer = brain.chat(
            [{"role": "system", "content": CONSULT_SYSTEM}, {"role": "user", "content": prompt}],
            timeout=45,
            task="phone_debug",
        )
    except Exception:
        return ""
    return (answer or "").strip()[:500]


def _jianying_text(hit: dict) -> str:
    note = hit.get("note") or {}
    text = str(hit.get("text") or "").strip()
    if text:
        return text
    return (str(note.get("title") or "") + "\n" + str(note.get("body") or "")).strip()


def run_local_job(hit: dict, timeout: int = 300, driver=None) -> dict:
    """返回与网关回执同构的 {"state", "detail", "note"}。"""
    driver = driver or make_driver()
    try:
        return _run(hit, timeout, driver)
    finally:
        try:
            driver.restore_ime()                    # 无论成败都把输入法切回用户的
        except Exception:
            pass


def _run(hit: dict, timeout: int, driver) -> dict:
    adapter = str(hit.get("adapter") or "")
    try:
        if adapter == "jianying":
            from phone_flows.jianying import make_video

            share = bool(hit.get("share_douyin"))
            state, detail = make_video(driver, _jianying_text(hit), timeout=timeout, share=share)
            if share and state in ("ok", "done") and detail.get("shared"):
                from phone_flows.douyin import publish_current

                note = hit.get("note") or {}
                pub_state, pub_detail = publish_current(
                    driver,
                    str(note.get("title") or ""),
                    str(note.get("body") or ""),
                    list(note.get("topics") or []),
                    publish=True,
                )
                detail["publish"] = pub_detail
                detail["steps"] = list(detail.get("steps") or []) + list(pub_detail.get("steps") or [])
                if pub_state not in ("ok", "done"):
                    detail["note"] = pub_detail.get("note") or "抖音发布未确认"
                    state = pub_state
                else:
                    detail["note"] = "视频已生成并由剪映直接发布到抖音"
        elif adapter == "douyin":
            from phone_flows.douyin import post

            note = hit.get("note") or {}
            state, detail = post(
                driver,
                str(note.get("title") or ""),
                str(note.get("body") or ""),
                list(note.get("topics") or []),
                media=str(hit.get("media") or "image"),
                publish=bool(hit.get("publish_authorized")),
                timeout=timeout,
            )
        else:
            return {"state": "failed", "detail": {}, "note": "非本地驱动适配器：{}".format(adapter)}
    except Exception as exc:  # U2Error 及其他驱动异常：一步失败即停，先问千问
        detail = {
            "adapter": adapter,
            "steps": [],
            "step": getattr(exc, "step", ""),
            "error": getattr(exc, "message", str(exc)),
            "page_text": getattr(exc, "page_text", ""),
            "screenshot": getattr(exc, "screenshot", ""),
        }
        advice = consult_qwen(adapter, exc)
        detail["consult"] = advice
        detail["note"] = "执行失败，已按铁律询问千问"
        if advice:
            detail["note"] += "：{}".format(advice)
        return {"state": "needs_human", "detail": detail, "note": detail["note"]}

    detail.setdefault("adapter", adapter)
    state = "done" if state in ("ok", "done") else state
    return {"state": state, "detail": detail, "note": detail.get("note") or "", "driver": "u2"}
