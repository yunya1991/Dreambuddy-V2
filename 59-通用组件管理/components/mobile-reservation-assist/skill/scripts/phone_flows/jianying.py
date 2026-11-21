"""剪映：文案 → 热门工具「图文成片」→ 生成视频 → 导出 1080P 到相册。

红线：只做本地生成与导出；遇到会员/付费弹窗只关闭，不购买任何套餐。
"""

from __future__ import annotations

import time

from phone_driver.u2_driver import U2Error

PKG = "com.lemon.lv"
CLOSE_LABELS = ("暂不加入", "我知道了", "跳过", "以后再说", "关闭")
SAVED_HINTS = ("保存成功", "已保存", "导出成功", "已保存到相册")


def _record(steps: list[dict], action: str, ok: bool = True, note: str = "") -> None:
    steps.append({"action": action, "ok": ok, "note": note})


def _on_config_page(driver, text: str) -> bool:
    """剪映会恢复上次编辑：已在配置页且文案一致时直接复用，避免重复输入。"""
    page = driver.page_text(6000)
    if "生成视频" not in page:
        return False
    head = text.strip().splitlines()[0][:12] if text.strip() else ""
    return not head or head in page


def _open_text_to_video(driver, steps: list[dict]) -> None:
    if driver.wait("开始创作", 3) is None:
        driver.press("back")                        # 先退回首页，避免停在中间页
        time.sleep(2)
        if driver.tap_any(("剪辑",), timeout=3):
            time.sleep(2)
        driver.dismiss(CLOSE_LABELS, rounds=2)

    entry = driver.wait("图文成片", 5)
    if entry is None:
        driver.swipe_up()
        entry = driver.wait("图文成片", 4)
    if entry is None:
        raise U2Error(
            "jy_entry", "未找到热门工具「图文成片」",
            driver.page_text(), driver.screenshot("jy_no_entry"),
        )
    try:
        entry.click()
    except Exception:
        raise U2Error(
            "jy_entry", "点击「图文成片」失败",
            driver.page_text(), driver.screenshot("jy_entry_failed"),
        ) from None
    time.sleep(3)
    driver.dismiss(CLOSE_LABELS, rounds=2)
    _record(steps, "jy_entry", True, "图文成片")


def _fill_text(driver, text: str, steps: list[dict]) -> None:
    if driver.fill(text, hint="请输入创作想法"):
        _record(steps, "jy_input", True, "{} 字".format(len(text)))
        return
    raise U2Error(
        "jy_input", "图文成片页未找到可用的文案输入框",
        driver.page_text(), driver.screenshot("jy_no_input"),
    )


def make_video(driver, text: str, timeout: float = 900, share: bool = False) -> tuple[str, dict]:
    """返回 (state, detail)；share=True 时导出后点「分享到抖音」进入发布页。"""
    steps: list[dict] = []
    detail: dict = {"adapter": "jianying", "mode": "text_to_video", "steps": steps, "text_chars": len(text)}
    if not text.strip():
        return "error", dict(detail, error="empty_text", note="文案为空")

    driver.app_restart(PKG)
    detail["popups"] = driver.dismiss(CLOSE_LABELS, rounds=4)
    _record(steps, "jy_open", True, PKG)

    if not _on_config_page(driver, text):
        _open_text_to_video(driver, steps)
    # 入口点击后剪映可能直接恢复上次任务到配置页，需再判断一次
    if _on_config_page(driver, text):
        _record(steps, "jy_input", True, "沿用剪映已恢复的文案")
    else:
        _fill_text(driver, text, steps)
        if not driver.tap_any(("应用",), timeout=5):
            raise U2Error("jy_apply", "未找到「应用」按钮", driver.page_text(), driver.screenshot("jy_no_apply"))
        time.sleep(2)
        _record(steps, "jy_apply", True)

    # 配置页：比例面板会盖住「生成视频」，先展开比例项、选 9:16 并点右上 ✓ 收起
    page = driver.page_text(1200)
    if "视频比例" in page:
        if "9:16" not in page:
            driver.tap_any(("16:9", "视频比例"), timeout=3)
            time.sleep(1.5)
            page = driver.page_text(1200)
        if "9:16" in page:
            driver.tap_any(("9:16",), timeout=3)
            time.sleep(1)
            if not driver.tap_any(("确定", "完成"), timeout=2):
                driver.tap_xy(989, 1953)            # 面板右上确认 ✓
            time.sleep(2)
            _record(steps, "jy_ratio", True, "9:16")

    gen = driver.tap_any(("生成视频", "开始生成", "立即生成"), timeout=6)
    if not gen:
        driver.swipe_up()                           # 按钮可能在页面下方
        gen = driver.tap_any(("生成视频", "开始生成", "立即生成"), timeout=4)
    if not gen:
        raise U2Error("jy_generate", "未找到「生成视频」按钮", driver.page_text(), driver.screenshot("jy_no_generate"))
    _record(steps, "jy_generate", True, "已提交生成")

    # 生成 + 排队：等待编辑页出现「导出」，预算不超过总超时
    deadline = time.time() + max(120.0, min(timeout * 0.55, 300.0))
    edited = False
    while time.time() < deadline:
        time.sleep(5)
        driver.dismiss(CLOSE_LABELS, rounds=1)
        if driver.wait("导出", 1) is not None:
            edited = True
            break
    if not edited:
        raise U2Error(
            "jy_wait_edit", "等待生成超时（未出现「导出」）",
            driver.page_text(), driver.screenshot("jy_after_generate"),
        )
    _record(steps, "jy_wait_edit", True, "已进入编辑页")

    detail["screenshot"] = driver.screenshot("jy_after_generate")
    driver.tap_any(("导出",), timeout=5)
    time.sleep(3)
    driver.dismiss(CLOSE_LABELS, rounds=1)
    if driver.wait("1080P", 3) is not None:
        driver.tap_any(("1080P", "1080p"), timeout=3)
        time.sleep(1)
    driver.tap_any(("导出",), timeout=4)
    time.sleep(2)
    _record(steps, "jy_export", True, "已提交导出 1080P")

    # 等导出完成：以完成页提示为准（相册旧视频会导致误判）
    saved = False
    deadline = time.time() + 180
    while time.time() < deadline:
        time.sleep(4)
        page = driver.page_text(1500)
        if any(hint in page for hint in SAVED_HINTS) or "分享到抖音" in page:
            saved = True
            break
    detail["video"] = driver.latest_media(".mp4")
    detail["screenshot"] = driver.screenshot("jy_exported")
    _record(steps, "jy_wait_saved", saved, detail["video"] or "")
    if not saved:
        detail["note"] = "未捕获导出完成提示，请到相册确认最新视频"
        return "needs_human", detail
    detail["note"] = "视频已导出：{}".format(detail["video"] or "相册最新视频")

    if share:
        if not driver.tap_any(("分享到抖音",), timeout=8):
            raise U2Error(
                "jy_share", "导出完成页未找到「分享到抖音」按钮",
                driver.page_text(), driver.screenshot("jy_no_share"),
            )
        time.sleep(6)
        driver.dismiss(("允许", "同意", "始终允许", "仅在使用中允许"), rounds=2)
        time.sleep(3)
        detail["shared"] = True
        _record(steps, "jy_share", True, "已跳到抖音发布页")
    return "ok", detail
