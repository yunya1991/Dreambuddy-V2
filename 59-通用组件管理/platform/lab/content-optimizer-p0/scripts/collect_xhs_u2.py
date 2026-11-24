"""小红书只读采集器（P0-A 兜底通道，本地 u2 驱动）。

为什么存在：生产链路 `mra xhs scout` 只走「网关 + Auto.js」，本地 u2 无对应流程
（phone_driver/runner.py 的 LOCAL_DRIVERS 仅 jianying/douyin）。P0-A 需要先验证
「能否稳定产出结构化样本」，因此在 lab 内提供本脚本：

- 只读：只做搜索、点开笔记、读屏、返回；不点赞、不收藏、不关注、不评论、不发布
- 不改生产代码：仅 import 同目录 collect_p0a 的写盘/事件/解析工具
- 数据最小化：只存标题（≤100 字）+ 派生特征 + 互动计数，不存封面/正文全文
- 失败即停：任何一步找不到目标就抛 U2Stop，写事件后退出，不反复盲试

用法：
    python3 scripts/collect_xhs_u2.py --track 财经 --limit 3
    python3 scripts/collect_xhs_u2.py --track 财经,经济 --limit 3 --serial ddad4c46
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import collect_p0a as base  # noqa: E402

PLATFORM = "xiaohongshu"
PACKAGE = "com.xingin.xhs"
MAX_TITLE = 100
MAX_SCROLLS = 0  # 首屏采集：分层靠搜索排序位置，不滚动避免广告位与推荐位混杂

RESULT_TABS = ("综合", "最新", "爆款笔记")
POPUP_WORDS = ("我知道了", "暂不开启", "以后再说", "取消", "关闭", "跳过")
LOGIN_WORDS = ("登录", "注册")
AD_MARKS = ("¥", "广告", "赞助", "直播中")


class U2Stop(RuntimeError):
    """单步失败：带页面证据，交给调用方判定 error_code。"""

    def __init__(self, step: str, message: str, error_code: str = "LAYOUT_CHANGED"):
        super().__init__("{}：{}".format(step, message))
        self.step = step
        self.error_code = error_code


# ── 纯函数：可直接单测，不依赖真机 ──────────────────────────────────────────
def _bounds(value: str) -> tuple[int, int, int, int]:
    """'[13,1305][534,1409]' → (13,1305,534,1409)。"""
    nums = [int(n) for n in re.findall(r"-?\d+", value or "")]
    if len(nums) != 4:
        return (0, 0, 0, 0)
    return (nums[0], nums[1], nums[2], nums[3])


def _nodes(xml_text: str) -> list[dict]:
    """把 dump_hierarchy 拉平成 [{cls,text,desc,bounds}]。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out: list[dict] = []

    def walk(node: ET.Element) -> None:
        text = (node.attrib.get("text") or "").strip()
        desc = (node.attrib.get("content-desc") or "").strip()
        if text or desc:
            x1, y1, x2, y2 = _bounds(node.attrib.get("bounds", ""))
            out.append(
                {
                    "cls": (node.attrib.get("class") or "").split(".")[-1],
                    "text": text,
                    "desc": desc,
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                }
            )
        for child in node:
            walk(child)

    walk(root)
    return out


def _is_ad(text: str) -> bool:
    return any(mark in text for mark in AD_MARKS)


def _looks_like_title(node: dict) -> bool:
    """卡片标题：足够长、跨半屏宽、非时间/非作者。"""
    text = node["text"]
    if len(text) < 8 or _is_ad(text):
        return False
    if (node["x2"] - node["x1"]) < 380:
        return False
    return not re.fullmatch(r"\d+\s*(分钟|小时|天|周)前", text)


def _parse_cards(nodes: list[dict]) -> list[dict]:
    """从搜索结果页节点里还原卡片：标题 + 作者 + 点赞 + 相对时间。"""
    titles = [n for n in nodes if n["cls"] == "TextView" and _looks_like_title(n)]
    # 结果区之外（顶部时间、搜索词）按 y 下限过滤
    titles = [n for n in titles if n["y1"] > 380]
    titles.sort(key=lambda n: (n["y1"], n["x1"]))

    short = [
        n
        for n in nodes
        if n["cls"] == "TextView"
        and 1 <= len(n["text"]) <= 20
        and n["y1"] > 380
        and not _is_ad(n["text"])
        and not re.fullmatch(r"[\d.]+", n["text"])
        and n["text"] not in RESULT_TABS
    ]
    numbers = [
        n
        for n in nodes
        if n["cls"] == "TextView" and n["y1"] > 380 and re.fullmatch(r"[\d.]+[万wW]?", n["text"])
    ]
    times = [
        n
        for n in nodes
        if n["cls"] == "TextView" and n["y1"] > 380 and _relative_time(n["text"]) is not None
    ]

    cards: list[dict] = []
    ad_nodes = [n for n in nodes if n["text"] in ("广告", "赞助", "赞助内容")]
    for title in titles:
        column_left = title["x1"] < 540
        # 广告卡：标题上方 400px 内有「广告」标签，直接丢弃
        if any(
            _same_column(n, column_left) and 0 <= title["y1"] - n["y1"] <= 400 for n in ad_nodes
        ):
            continue
        below = [
            n
            for n in short + numbers + times
            if _same_column(n, column_left) and title["y2"] <= n["y1"] <= title["y2"] + 220
        ]
        author = next(
            (n["text"] for n in below if n in short and _relative_time(n["text"]) is None), ""
        )
        likes = next((n["text"] for n in below if n in numbers), "")
        rel = next((n["text"] for n in below if n in times), "")
        cards.append(
            {
                "title": title["text"][:MAX_TITLE],
                "author": author,
                "likes": likes,
                "relative_time": rel,
                "x": (title["x1"] + title["x2"]) // 2,
                "y": max(0, title["y1"] - 300),
                "title_y": title["y1"],
            }
        )
    # 同一标题重复（广告位与推荐位）去重
    seen: set[str] = set()
    unique: list[dict] = []
    for card in cards:
        if card["title"] in seen:
            continue
        seen.add(card["title"])
        unique.append(card)
    return unique


def _same_column(node: dict, column_left: bool) -> bool:
    return (node["x1"] < 540) == column_left


def _has_results(nodes: list[dict], keyword: str = "") -> bool:
    """结果页判定：能解析出卡片，且搜索词已回填到顶部输入框。"""
    if keyword and keyword not in [n["text"] for n in nodes]:
        return False
    return len(_parse_cards(nodes)) >= 1


def _relative_time(text: str) -> int | None:
    """'1天前' → 1（天）；'3小时前' → 0；'11-10' → 距今天数；无法解析 → None。"""
    value_text = (text or "").strip()
    match = re.fullmatch(r"(\d+)\s*(分钟|小时|天|周)前", value_text)
    if not match:
        if value_text == "刚刚":
            return 0
        if value_text == "昨天":
            return 1
        date_match = re.fullmatch(r"(\d{1,2})-(\d{1,2})", value_text)
        if not date_match:
            return None
        today = datetime.now().date()
        try:
            stamp = today.replace(month=int(date_match.group(1)), day=int(date_match.group(2)))
        except ValueError:
            return None
        if stamp > today:
            stamp = stamp.replace(year=today.year - 1)
        return (today - stamp).days
    value, unit = int(match.group(1)), match.group(2)
    if unit in ("分钟", "小时"):
        return 0
    if unit == "周":
        return value * 7
    return value


def _published_at(relative: str, collected_at: str) -> str | None:
    days = _relative_time(relative)
    if days is None:
        return None
    try:
        stamp = datetime.fromisoformat(collected_at)
    except ValueError:
        return None
    return (stamp - timedelta(days=days)).replace(microsecond=0).isoformat()


def _parse_detail(nodes: list[dict]) -> dict:
    """详情页：作者 + 点赞/收藏/评论（读 content-desc 按钮）+ 可见正文。"""
    detail: dict[str, Any] = {
        "author": "",
        "likes": "",
        "saves": "",
        "comments": "",
        "body": "",
        "title": "",
    }
    for node in nodes:
        desc = node["desc"]
        for label, key in (("点赞", "likes"), ("收藏", "saves"), ("评论", "comments")):
            if desc.startswith(label):
                match = re.search(r"(\d+(?:\.\d+)?[万wW]?)", desc)
                if match:
                    detail[key] = match.group(1)
    long_texts = [n for n in nodes if n["cls"] == "TextView" and len(n["text"]) >= 8]
    if long_texts:
        # 正文：屏幕上最长的一段；标题：正文之上最近的长文本
        body = max(long_texts, key=lambda n: len(n["text"]))
        detail["body"] = body["text"]
        upper = [n for n in long_texts if n["y2"] <= body["y1"] and n is not body]
        if upper:
            detail["title"] = sorted(upper, key=lambda n: n["y1"])[-1]["text"][:MAX_TITLE]
    author_nodes = [
        n
        for n in nodes
        if n["cls"] == "TextView"
        and 2 <= len(n["text"]) <= 20
        and n["y2"] < 320
        and not n["text"].isdigit()
    ]
    if author_nodes:
        detail["author"] = author_nodes[0]["text"]
    return detail


def _row(platform: str, item: dict, query: str, collected_at: str, rank: int) -> dict:
    row = base._normalize_item(platform, item, query, collected_at)
    bucket = "1-10" if rank <= 10 else ("11-30" if rank <= 30 else "31-50")
    title = str(row.get("title") or "")
    hashtags = len(re.findall(r"#\s*[^\s#]+", title))
    row.update(
        {
            "rank_bucket": bucket,
            "collector": "u2-xhs",
            "saves": base._parse_likes(item.get("saves")),
            "comments": base._parse_likes(item.get("comments")),
            "shares": None,
            "author_followers_bucket": "unknown",
            "published_at": item.get("published_at") or None,
            "media_type": "unknown",
            "cover_type": "unknown",
            "metrics_at": collected_at,
            "topic_count": hashtags,
            "hashtag_count": hashtags,
            # 不存原始 URL：用内容指纹前 16 位代替，仅用于去重与回溯
            "url_hash": row.get("sample_id", "")[:16] or None,
            "outlier_flags": "body_truncated" if item.get("body_truncated") else "",
        }
    )
    published = row.get("published_at")
    if published:
        try:
            stamp = datetime.fromisoformat(str(published))
            row["publish_hour"] = stamp.hour
            row["weekday"] = stamp.isoweekday()
        except ValueError:
            pass
    meta = {"missing_flags", "outlier_flags", "is_censored"}
    missing = [
        key
        for key, value in row.items()
        if key not in meta and (value is None or str(value).strip() in ("", "[]"))
    ]
    row["missing_flags"] = ";".join(missing)
    return row


# ── 真机操作 ────────────────────────────────────────────────────────────────
def _connect(serial: str = ""):
    import uiautomator2 as u2

    target = serial or _adb_serial()
    if not target:
        raise U2Stop("connect", "adb 无设备", "NO_DEVICE")
    return u2.connect(target)


def _adb_serial() -> str:
    try:
        done = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=8)
    except Exception:
        return ""
    for line in (done.stdout or "").splitlines()[1:]:
        if "\tdevice" in line:
            return line.split("\t")[0].strip()
    return ""


def _dump(d) -> list[dict]:
    return _nodes(d.dump_hierarchy())


def _dismiss_popups(d, nodes: list[dict]) -> bool:
    texts = {n["text"] for n in nodes}
    if texts & set(LOGIN_WORDS) and d(descriptionContains="关闭").exists:
        return False
    for word in POPUP_WORDS:
        if word in texts:
            element = d(text=word)
            try:
                if element.exists:
                    element.click()
                    time.sleep(1)
                    return True
            except Exception:
                continue
    return False


def _dismiss_system_dialogs(d, nodes: list[dict], rounds: int = 3) -> bool:
    """关掉系统权限/引导弹窗：相机/麦克风/位置/通讯录一律拒绝，其余允许。"""
    handled = False
    for _ in range(rounds):
        title = next((n["text"] for n in nodes if "？" in n["text"] and len(n["text"]) >= 6), "")
        if not title:
            return handled
        deny = any(
            word in title for word in ("拍摄", "录制", "麦克风", "相机", "位置", "通讯录", "照片")
        )
        target = "拒绝" if deny else "仅在使用中允许"
        if not d(text=target).exists:
            target = (
                "允许"
                if d(text="允许").exists
                else ("本次使用允许" if d(text="本次使用允许").exists else "")
            )
        if not target:
            return handled
        try:
            d(text=target).click()
        except Exception:
            return handled
        handled = True
        time.sleep(1)
        nodes = _dump(d)
    return handled


def _open_search(d, keyword: str) -> list[dict]:
    """回到搜索页并输入关键词，返回结果页节点。"""
    d.app_start(PACKAGE, wait=True)
    time.sleep(2)
    nodes = _dump(d)
    _dismiss_system_dialogs(d, nodes)
    # 已在搜索结果页
    if _has_results(nodes, keyword):
        return nodes
    # 先退到「发现」页：只有该页右上角按钮的 content-desc 恰好是「搜索」
    for _ in range(5):
        if d(className="android.widget.EditText").exists:
            break
        if d(description="搜索").exists:
            d(description="搜索").click()
            break
        d.press("back")
        time.sleep(1.5)
    time.sleep(2)
    nodes = _dump(d)
    _dismiss_system_dialogs(d, nodes)
    editor = d(className="android.widget.EditText")
    if not editor.exists:
        raise U2Stop("search.input", "找不到搜索输入框")
    editor.set_text(keyword)
    time.sleep(0.8)
    d.press("enter")
    deadline = time.time() + 15
    while time.time() < deadline:
        nodes = _dump(d)
        if _has_results(nodes, keyword):
            return nodes
        time.sleep(1)
    raise U2Stop("search.results", "搜索结果页未出现卡片（{}）".format(keyword))


def _open_card(d, card: dict) -> list[dict]:
    d.click(card["x"], card["y"])
    time.sleep(3)
    started = time.time()
    deadline = started + 14
    while time.time() < deadline:
        nodes = _dump(d)
        has_action = any(n["desc"].startswith(("点赞", "收藏")) for n in nodes)
        has_content = any(n["cls"] == "TextView" and len(n["text"]) >= 15 for n in nodes)
        if has_action and has_content:
            return nodes
        # 加载慢时先接受部分字段，避免整条样本丢失
        if has_content and time.time() - started >= 9:
            return nodes
        time.sleep(1)
    raise U2Stop("detail.open", "笔记详情未加载", "TIMEOUT")


def _back_to_results(d, keyword: str) -> list[dict]:
    d.press("back")
    time.sleep(2)
    deadline = time.time() + 8
    while time.time() < deadline:
        nodes = _dump(d)
        if _has_results(nodes, keyword):
            return nodes
        time.sleep(1)
    return _open_search(d, keyword)


def collect(track: str, limit: int = 3, serial: str = "") -> dict:
    run_id = "p0a-{}-xhs-u2".format(time.strftime("%Y%m%d-%H%M%S"))
    trace_id = "p0a:xhs-u2:{}".format(int(time.time() * 1000))
    check = base.channel_check(run_id, emit=True)
    base._event(
        "collect.request",
        "xhs.u2",
        trace_id=trace_id,
        run_id=run_id,
        status="requested",
        detail={"platform": PLATFORM, "track": track, "limit": limit, "driver": "u2"},
    )
    started = time.time()
    rows: list[dict] = []
    detail_log: dict[str, Any] = {"cards_seen": 0, "detail_ok": 0, "detail_failed": 0, "steps": []}
    status, error_code, error_note = "empty", "", ""
    try:
        d = _connect(serial)
        nodes = _open_search(d, track)
        _dismiss_popups(d, nodes)
        cards = _parse_cards(nodes)
        want = max(1, min(8, int(limit)))
        # 首屏不足时向下滚动补卡（仍按信息流先后顺序即排名）
        seen_titles = {card["title"] for card in cards}
        scrolls = 0
        while len(cards) < want and scrolls < 3:
            d.swipe(540, 1800, 540, 900, 0.25)
            time.sleep(1.5)
            for card in _parse_cards(_dump(d)):
                if card["title"] in seen_titles:
                    continue
                seen_titles.add(card["title"])
                cards.append(card)
            scrolls += 1
        cards = cards[:want]
        detail_log["cards_seen"] = len(cards)
        if not cards:
            status, error_code = "empty", "LAYOUT_CHANGED"
            error_note = "搜索结果页未解析出卡片"
        for rank, card in enumerate(cards, start=1):
            collected_at = datetime.now().astimezone().replace(microsecond=0).isoformat()
            item = {
                "title": card["title"],
                "author": card["author"],
                "likes": card["likes"],
                "published_at": _published_at(card["relative_time"], collected_at),
            }
            try:
                detail_nodes = _open_card(d, card)
                detail = _parse_detail(detail_nodes)
                item.update(
                    {
                        "title": detail.get("title") or item["title"],
                        "author": detail.get("author") or item["author"],
                        "likes": detail.get("likes") or item["likes"],
                        "saves": detail.get("saves"),
                        "comments": detail.get("comments"),
                        "body": detail.get("body"),
                        "body_truncated": bool(detail.get("body")),
                    }
                )
                detail_log["detail_ok"] += 1
                rows.append(_row(PLATFORM, item, track, collected_at, rank))
                nodes = _back_to_results(d, track)
            except U2Stop as exc:
                detail_log["detail_failed"] += 1
                detail_log["steps"].append({"rank": rank, "step": exc.step, "error": str(exc)})
                rows.append(_row(PLATFORM, item, track, collected_at, rank))
                nodes = _back_to_results(d, track)
            _dismiss_popups(d, nodes)
        if rows and status == "empty":
            status = "done"
    except U2Stop as exc:
        status, error_code = "error", exc.error_code
        error_note = str(exc)
    except Exception as exc:  # noqa: BLE001 - 设备/驱动异常统一落事件
        status, error_code = "error", "PARSE_ERROR"
        error_note = "{}: {}".format(type(exc).__name__, exc)

    duration_ms = int((time.time() - started) * 1000)
    columns = base._schema_columns()
    coverage = base._coverage(rows, columns)
    written, skipped = base._write_samples(rows) if rows else (0, 0)
    raw_path = base.RAW_DIR / "{}.json".format(run_id)
    try:
        base.RAW_DIR.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(
            __import__("json").dumps(
                {"detail": detail_log, "rows": rows}, ensure_ascii=False, indent=2
            ),
            encoding="utf-8",
        )
    except OSError:
        raw_path = None

    result = {
        "run_id": run_id,
        "trace_id": trace_id,
        "platform": PLATFORM,
        "status": status,
        "error_code": error_code,
        "note": error_note,
        "rows_written": written,
        "duplicates_skipped": skipped,
        "fields_present_min": coverage["fields_present_min"],
        "fields_present_mean": coverage["fields_present_mean"],
        "field_total": coverage["field_total"],
        "duration_ms": duration_ms,
        "samples_path": str(base.SAMPLES_PATH),
        "events_path": str(base.EVENTS_PATH),
        "raw_path": str(raw_path) if raw_path else "",
        "channel": check,
    }
    base._event(
        "collect.result",
        "xhs.u2",
        trace_id=trace_id,
        run_id=run_id,
        status=status,
        error_code=error_code,
        duration_ms=duration_ms,
        detail=result,
    )
    base._event(
        "collect.parse",
        "xhs.u2",
        trace_id=trace_id,
        run_id=run_id,
        status="done" if rows else "empty",
        error_code="" if rows else error_code,
        duration_ms=duration_ms,
        detail={
            "rows": len(rows),
            "fields_present_mean": coverage["fields_present_mean"],
            "fields_present_min": coverage["fields_present_min"],
            "field_total": coverage["field_total"],
            "cards_seen": detail_log["cards_seen"],
            "detail_ok": detail_log["detail_ok"],
            "detail_failed": detail_log["detail_failed"],
        },
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="小红书只读采集（P0-A 兜底通道）")
    parser.add_argument("--track", required=True, help="赛道关键词，逗号分隔")
    parser.add_argument("--limit", type=int, default=3, help="每个赛道读取的笔记数（1-8）")
    parser.add_argument("--serial", default="", help="adb 序列号；省略自动取第一台")
    args = parser.parse_args(argv)

    tracks = [item.strip() for item in args.track.split(",") if item.strip()]
    summary = []
    for track in tracks:
        summary.append(collect(track, limit=args.limit, serial=args.serial))
    print(__import__("json").dumps(summary, ensure_ascii=False, indent=2))
    return 0 if any(item["status"] == "done" for item in summary) else 1


if __name__ == "__main__":
    raise SystemExit(main())
