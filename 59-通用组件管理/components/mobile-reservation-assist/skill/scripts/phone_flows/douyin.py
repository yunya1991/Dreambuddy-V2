"""抖音：相册选素材 → 编辑页 → 发布页填标题/描述 → 停在「发作品」前。

红线：默认只填充内容并停下；仅当上游显式 publish_authorized 才点「发作品」。
"""

from __future__ import annotations

import time

from phone_driver.u2_driver import U2Error

PKG = "com.ss.android.ugc.aweme"
MAX_TITLE = 55
POPUP_LABELS = (
    "始终允许", "仅在使用中允许", "本次使用允许", "允许访问全部",
    "同意并继续", "同意", "我知道了", "以后再说", "允许",
)
ALBUM_HINTS = ("全部", "所有照片", "图片", "最近项目", "相机胶卷")
PUBLISH_BUTTONS = ("发作品", "发布", "发布作品")
TITLE_HINTS = ("添加作品标题", "添加标题", "填写标题")
DESC_HINTS = ("添加作品描述", "添加描述", "说点什么")


def _published(driver) -> bool:
    """发布成功：出现成功提示，或已回到带底部导航的抖音首页。"""
    page = driver.page_text(1500)
    if any(hint in page for hint in PUBLISH_HINTS):
        return True
    return all(hint in page for hint in ("首页", "朋友", "消息"))
PUBLISH_HINTS = ("发布成功", "作品已发布", "已发布")


def _record(steps: list[dict], action: str, ok: bool = True, note: str = "") -> None:
    steps.append({"action": action, "ok": ok, "note": note})


def _ensure_home(driver) -> None:
    for _ in range(6):
        if _discard_editor(driver):                 # 编辑页返回确认：放弃残留草稿
            time.sleep(1.5)
            continue
        driver.dismiss(POPUP_LABELS, rounds=2)
        _dismiss_resume_draft(driver)
        if driver.wait("首页", 2) is not None:
            return
        driver.press("back")
        time.sleep(1.5)
    driver.app_restart(PKG)
    driver.dismiss(POPUP_LABELS, rounds=2)
    _dismiss_resume_draft(driver)
    _discard_editor(driver)
    if driver.wait("首页", 3) is None:
        raise U2Error("douyin_home", "未能回到抖音首页", driver.page_text(), driver.screenshot("douyin_no_home"))


def _discard_editor(driver) -> bool:
    page = driver.page_text(1000)
    if "放弃" not in page:
        return False
    return bool(driver.tap_any(("放弃",), timeout=2))


def _is_editor(driver) -> bool:
    """编辑页特征：右侧贴纸/特效 + 底部下一步。"""
    page = driver.page_text(1200)
    return "下一步" in page and any(hint in page for hint in ("贴纸", "特效", "文字"))


def _dismiss_resume_draft(driver) -> None:
    """上次停在编辑页会弹「继续编辑作品吗？」：点右上关闭，不进入草稿箱。"""
    page = driver.page_text(1000)
    if "继续编辑" not in page and "草稿" not in page:
        return
    if driver.tap_any(("关闭",), timeout=2):
        time.sleep(1)
        return
    driver.tap_xy(810, 769)                         # 弹窗右上 X
    time.sleep(1)


def _open_album(driver, steps: list[dict]) -> None:
    entry = driver.d(descriptionContains="拍摄")
    tapped = False
    try:
        tapped = entry.exists and bool(entry.click())
    except Exception:
        tapped = False
    if not tapped:
        tapped = driver.tap_any(("发布", "拍摄"), timeout=4)
    if not tapped:
        tapped = driver.tap_xy(540, 2330)          # 底部中间「+」
    time.sleep(2)
    driver.dismiss(POPUP_LABELS, rounds=2)          # 相机/麦克风权限
    _record(steps, "douyin_capture", True)

    for _ in range(3):
        if driver.tap_any(("相册",), timeout=2):
            time.sleep(2)
            break
        time.sleep(1)
    else:
        driver.tap_xy(840, 1980)                    # 拍摄页右下角相册入口
        time.sleep(2)
    driver.dismiss(POPUP_LABELS, rounds=2)          # 照片权限：允许访问全部
    _record(steps, "douyin_album_open", True)


def _album_ready(driver) -> bool:
    page = driver.page_text(800)
    return any(hint in page for hint in ALBUM_HINTS)


def _pick_first(driver, media: str, steps: list[dict]) -> None:
    if media == "video":
        driver.tap_any(("视频",), timeout=3)
        time.sleep(2)
    driver.tap_xy(167, 680)                         # 相册时间倒序，左上角最新素材
    time.sleep(3)
    _record(steps, "douyin_pick", True, "已选相册最新{}".format("视频" if media == "video" else "首图"))


def _next(driver) -> bool:
    if driver.tap_any(("下一步",), timeout=5):
        time.sleep(2)
        return True
    driver.tap_xy(790, 2300)
    time.sleep(2)
    return True


def post(driver, title: str, body: str, topics: list[str], media: str = "image",
         publish: bool = False, timeout: float = 300) -> tuple[str, dict]:
    """返回 (state, detail)；state ∈ ok / needs_human / error。"""
    steps: list[dict] = []
    detail: dict = {"adapter": "douyin", "steps": steps, "media": media}
    title = (title or "").strip()[:MAX_TITLE]
    body = (body or "").strip()
    if topics:
        body = (body + "\n" + " ".join("#" + str(t).lstrip("#") for t in topics)).strip()
    if not title and not body:
        return "error", dict(detail, error="empty_note", note="标题与正文均为空")
    detail.update({"title": title, "body_chars": len(body)})

    driver.app_start(PKG)
    driver.dismiss(POPUP_LABELS, rounds=3)
    _record(steps, "douyin_open", True, PKG)
    _ensure_home(driver)
    _open_album(driver, steps)

    if not _album_ready(driver):
        driver.dismiss(POPUP_LABELS, rounds=1)
        if driver.tap_any(("相册",), timeout=3):    # 只补点一次，避免二次误点打乱页面
            time.sleep(2)
    in_editor = _is_editor(driver)
    if not _album_ready(driver) and not in_editor:
        raise U2Error(
            "douyin_album", "相册未就绪（可能未授予照片权限）",
            driver.page_text(), driver.screenshot("douyin_no_album"),
        )

    if in_editor:
        _record(steps, "douyin_pick", True, "沿用已选素材（编辑页）")
    else:
        _pick_first(driver, "video" if media == "video" else "image", steps)
        if not _next(driver):
            raise U2Error("douyin_preview", "预览页未找到「下一步」", driver.page_text(), driver.screenshot("douyin_no_next"))
        _record(steps, "douyin_preview", True)

    # 编辑页 → 发布页（已在编辑页时只点一次，避免误触"立即日常"等按钮）
    if not driver.tap_any(("下一步",), timeout=8):
        raise U2Error("douyin_editor", "编辑页未找到「下一步」", driver.page_text(), driver.screenshot("douyin_no_next2"))
    time.sleep(2)
    _record(steps, "douyin_editor", True)

    page = driver.page_text(1200)
    if not any(hint in page for hint in ("添加标题", "添加作品描述", "发作品")):
        raise U2Error(
            "douyin_publish_page", "未进入发布页（标题/描述输入框缺失）",
            page, driver.screenshot("douyin_no_publish_page"),
        )

    filled = driver.fill_fields([(TITLE_HINTS, title), (DESC_HINTS, body)])
    detail["filled"] = {"title": bool(filled and filled[0]), "body": bool(len(filled) > 1 and filled[1])}
    driver._dismiss_ime_picker()
    driver.hide_keyboard()                          # 键盘会挡住右下「发布」
    time.sleep(1)
    detail["screenshot"] = driver.screenshot("douyin_draft")
    _record(steps, "douyin_compose", detail["filled"]["title"], "标题/描述已填")

    if not publish:
        detail["note"] = "已选素材并填好标题描述，停在「发作品」前；确认后手动点发作品（或显式授权）"
        return "needs_human", detail

    if not driver.tap_any(PUBLISH_BUTTONS, timeout=6):
        raise U2Error(
            "douyin_publish", "已授权发布，但未找到「发布」按钮",
            driver.page_text(), driver.screenshot("douyin_no_publish_btn"),
        )
    time.sleep(4)
    if any(hint in driver.page_text(800) for hint in ("添加标题", "添加作品描述", "作品描述")):
        driver.tap_any(PUBLISH_BUTTONS, timeout=4)  # 键盘收起后首次点击可能未触发
        time.sleep(4)
    detail["screenshot"] = driver.screenshot("douyin_published")
    ok = _published(driver)
    detail["note"] = "发布成功" if ok else "已点击发作品，未捕获成功提示，请人工确认"
    _record(steps, "douyin_publish", ok, detail["note"])
    return ("ok" if ok else "needs_human"), detail


def publish_current(driver, title: str, body: str, topics: list[str],
                    publish: bool = True) -> tuple[str, dict]:
    """剪映「分享到抖音」已打开抖音发布页：只填描述并发布，不再走相册。"""
    steps: list[dict] = []
    detail: dict = {"adapter": "douyin", "steps": steps, "entry": "jianying_share"}
    page = driver.page_text(1500)
    if "下一步" in page:                            # 分享后先落在编辑页，需点下一步到发布页
        driver.tap_any(("下一步",), timeout=6)
        time.sleep(3)
        page = driver.page_text(1500)
    if not any(hint in page for hint in ("添加合适的话题和描述", "添加作品描述", "添加标题", "发布")):
        raise U2Error(
            "douyin_publish_page", "未进入抖音发布页",
            page, driver.screenshot("douyin_no_publish_page"),
        )

    desc = (title or "").strip()[:MAX_TITLE]
    if body.strip():
        desc = (desc + "\n" + body.strip()).strip()
    if topics:
        desc = (desc + "\n" + " ".join("#" + str(t).lstrip("#") for t in topics)).strip()

    results = driver.fill_fields([(TITLE_HINTS, (title or "").strip()[:20]), (DESC_HINTS, desc)])
    detail["filled"] = {"title": bool(results and results[0]), "desc": bool(len(results) > 1 and results[1])}
    driver._dismiss_ime_picker()
    driver.hide_keyboard()
    time.sleep(1.5)
    detail["screenshot"] = driver.screenshot("douyin_draft")
    _record(steps, "douyin_compose", detail["filled"]["desc"], "标题/描述已填")

    if not publish:
        detail["note"] = "已填好描述，停在「发布」前"
        return "needs_human", detail

    driver._dismiss_ime_picker()                    # 选择器会挡住「发布」
    if not driver.tap_any(PUBLISH_BUTTONS, timeout=6):
        raise U2Error(
            "douyin_publish", "未找到「发布」按钮",
            driver.page_text(), driver.screenshot("douyin_no_publish_btn"),
        )
    time.sleep(5)
    detail["screenshot"] = driver.screenshot("douyin_published")
    ok = _published(driver)
    detail["note"] = "发布成功" if ok else "已点击发布，未捕获成功提示，请人工确认"
    _record(steps, "douyin_publish", ok, detail["note"])
    return ("ok" if ok else "needs_human"), detail
