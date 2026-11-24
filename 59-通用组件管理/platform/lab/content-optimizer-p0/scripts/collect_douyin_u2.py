"""抖音只读滚动采集器（P0-A 兜底通道，本地 u2 驱动）。

为什么存在：生产 `mra douyin scout` 只读首屏卡片（约 5 张），覆盖不到
11-30 / 31-50 排名层。P0-A 需要验证「同一关键词下抖音卡片能否稳定分层」，
因此在 lab 内提供本脚本：

- 只读：只做搜索、上下滑动、读屏；不点赞、不评论、不关注、不发布
- 不改生产代码：仅复用同目录 collect_p0a 的写盘/事件工具与 collect_xhs_u2 的
  通用节点解析（_nodes/_dump/_connect/_dismiss_system_dialogs）
- 数据最小化：只存标题（≤100 字）+ 派生特征 + 点赞数，不打开视频详情
- 分层口径：按信息流可见顺序（首屏自上而下 + 逐屏下滚）依次编号，
  1-10 / 11-30 / 31-50 对应搜索排序前 50
- 失败即停：找不到搜索框/结果页就写事件退出，不反复盲试

用法：
    python3 scripts/collect_douyin_u2.py --track 财经 --limit 10
    python3 scripts/collect_douyin_u2.py --track 财经,经济,理财 --limit 10 --scrolls 2 --serial ddad4c46
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import collect_p0a as base  # noqa: E402
import collect_xhs_u2 as common  # noqa: E402

PLATFORM = "douyin"
PACKAGE = "com.ss.android.ugc.aweme"
MAX_TITLE = 100
DEFAULT_SCROLLS = 2

# 搜索结果页的非内容文本：导航/tab/操作按钮，不当作爆款标题
SCOUT_SKIP = frozenset(
    (
        "首页",
        "朋友",
        "消息",
        "我",
        "搜索",
        "综合",
        "视频",
        "用户",
        "商品",
        "直播",
        "音乐",
        "经验",
        "相关搜索",
        "猜你想搜",
        "筛选",
        "排序",
        "清空",
        "取消",
        "返回",
        "分享",
        "评论",
        "收藏",
        "点赞",
        "关注",
        "已关注",
        "展开",
        "收起",
        "全屏",
        "倍速",
    )
)
LIKES_RE = re.compile(r"^\d{1,6}(?:\.\d+)?\s*[万wWkK]?$")
# 点赞按钮的 content-desc 会被 u2 当正文读出来（「未点赞，喜欢1647，按钮」）；
# 「09.05 / 11-08」这类发布日期会命中 LIKES_RE，二者都要在卡片解析里排除。
PLACEHOLDER_TITLE_RE = re.compile(r"^(?:未点赞|已点赞|点赞|收藏|评论|分享|按钮|长按|双击)")
DATE_TEXT_RE = re.compile(r"^\d{1,2}[.\-]\d{1,2}$")
# 按钮 desc 里的点赞量：「未点赞，喜欢1647，按钮」→ 1647
LIKE_DESC_RE = re.compile(r"喜欢\s*(\d+(?:\.\d+)?\s*[万wWkK]?)")
POPUP_WORDS = ("我知道了", "暂不开启", "以后再说", "取消", "关闭", "跳过")

U2Stop = common.U2Stop


# ── 纯函数：可直接单测，不依赖真机 ──────────────────────────────────────────
def _is_placeholder_title(text: str) -> bool:
    """点赞/操作按钮的 content-desc 不是标题。"""
    raw = re.sub(r"\s+", "", str(text or ""))
    if not raw:
        return True
    if "按钮" in raw or "，喜欢" in raw or ",喜欢" in raw:
        return True
    return bool(PLACEHOLDER_TITLE_RE.match(raw))


def _is_like_count(text: str) -> bool:
    """「12.3w / 1.2万 / 3521」是点赞量；「09.05 / 11-08」是发布日期，不是。"""
    raw = re.sub(r"\s+", "", str(text or ""))
    if not raw or DATE_TEXT_RE.match(raw):
        return False
    return bool(LIKES_RE.match(raw))


def _like_label(node: dict) -> str:
    """卡片点赞文本：纯文本优先，其次从按钮 desc 的「喜欢N」提取。"""
    text = re.sub(r"\s+", "", node.get("text") or "")
    if _is_like_count(text):
        return text
    match = LIKE_DESC_RE.search(node.get("desc") or "")
    if match:
        return re.sub(r"\s+", "", match.group(1))
    return ""


def _is_date_like(text: str) -> bool:
    """「10.29 / 16小时前 / 昨天」这类时间文本不是作者昵称。"""
    raw = re.sub(r"\s+", "", str(text or ""))
    if DATE_TEXT_RE.match(raw):
        return True
    return bool(re.fullmatch(r"(?:\d+\s*(?:分钟|小时|天|周)前|刚刚|昨天|前天)", raw))


def _x_overlap(a: dict, b: dict) -> bool:
    return a["x1"] < b["x2"] and b["x1"] < a["x2"]


def _rank_bucket(rank: int) -> str:
    if rank <= 10:
        return "1-10"
    if rank <= 30:
        return "11-30"
    return "31-50"


def _parse_cards(
    nodes: list[dict],
    size: tuple[int, int] = (1080, 2400),
    keyword: str = "",
) -> list[dict]:
    """从搜索结果页节点还原卡片（标题 + 点赞 + 作者），按可见顺序（自上而下）。

    抖音搜索结果是双列瀑布流，同一张卡在 u2 里会被读成「按钮 desc + 文本」两份
    点赞，因此：① 点赞节点先按同标签、同 40px 纵向窗口折叠；② 标题与点赞按
    x 轴重叠 + 纵向最近距离一对一配对，避免串列复用或跨列误配。
    """
    height = (size or (1080, 2400))[1]
    low, high = int(height * 0.117), int(height * 0.875)
    near = int(height * 0.11)

    title_rows: list[tuple[str, dict, int]] = []
    seen: set[str] = set()
    for node in nodes:
        title = (node.get("text") or "").strip()
        if not (8 <= len(title) <= 80) or title in SCOUT_SKIP or _is_placeholder_title(title):
            continue
        center = (node["y1"] + node["y2"]) // 2
        if center < low or center > high:
            continue
        key = title[:24]
        if key in seen:
            continue
        seen.add(key)
        title_rows.append((title, node, center))
    title_rows.sort(key=lambda item: (item[2], item[1]["x1"]))

    like_rows: list[tuple[str, dict, int]] = []
    for node in sorted(nodes, key=lambda n: ((n["y1"] + n["y2"]) // 2, n["x1"])):
        label = _like_label(node)
        if not label:
            continue
        center = (node["y1"] + node["y2"]) // 2
        duplicated = any(
            prev_label == label
            and prev_node["x1"] < node["x2"]
            and node["x1"] < prev_node["x2"]
            and abs(prev_center - center) <= 40
            for prev_label, prev_node, prev_center in like_rows
        )
        if duplicated:
            continue
        like_rows.append((label, node, center))

    pairs = sorted(
        (abs(like_center - center), index, like_index)
        for index, (_, node, center) in enumerate(title_rows)
        for like_index, (_, like_node, like_center) in enumerate(like_rows)
        if _x_overlap(node, like_node) and 0 <= like_center - center <= near
    )
    matched: dict[int, str] = {}
    used_like: set[int] = set()
    for _, index, like_index in pairs:
        if index in matched or like_index in used_like:
            continue
        matched[index] = like_rows[like_index][0]
        used_like.add(like_index)

    short_rows = [
        node
        for node in nodes
        if 2 <= len((node.get("text") or "").strip()) <= 20
        and node["y1"] > low
        and (node.get("text") or "").strip() not in SCOUT_SKIP
        and not _is_like_count((node.get("text") or "").strip())
        and not _is_date_like((node.get("text") or "").strip())
        and not (node.get("text") or "").strip().isdigit()
    ]
    date_rows = [
        node
        for node in nodes
        if node["y1"] > low and _is_date_like((node.get("text") or "").strip())
    ]
    cards: list[dict] = []
    for index, (title, node, center) in enumerate(title_rows):
        # 相关搜索/猜你想搜 与博主卡：没有点赞，也没有作者下方的发布时间，剔除
        has_date = any(
            _x_overlap(node, date_node) and node["y2"] <= date_node["y1"] <= node["y2"] + 240
            for date_node in date_rows
        )
        if not matched.get(index) and not has_date:
            continue
        candidates = [
            (short["y1"], (short.get("text") or "").strip())
            for short in short_rows
            if _x_overlap(node, short) and node["y2"] <= short["y1"] <= node["y2"] + 240
        ]
        author = sorted(candidates, key=lambda item: item[0])[0][1] if candidates else ""
        cards.append(
            {
                "title": title[:MAX_TITLE],
                "likes": matched.get(index, ""),
                "author": author,
                "center": center,
                "keyword": keyword,
            }
        )
    return cards


def _has_results(nodes: list[dict], keyword: str = "") -> bool:
    """结果页判定：搜索框（EditText 或顶部区域）已回填关键词，且能解析出卡片。

    不能只看全页是否含关键词——卡片标题里的 #财经 话题会让旧关键词结果页
    误判为新关键词结果页。
    """
    if keyword:
        in_search_box = any(
            keyword in (node.get("text") or "") and (node["cls"] == "EditText" or node["y1"] < 300)
            for node in nodes
        )
        if not in_search_box:
            return False
    return len(_parse_cards(nodes)) >= 1


def _row(platform: str, item: dict, query: str, collected_at: str, rank: int) -> dict:
    row = base._normalize_item(platform, item, query, collected_at)
    title = str(row.get("title") or "")
    hashtags = len(re.findall(r"#[^\s#]+", title))
    row.update(
        {
            "rank_bucket": _rank_bucket(rank),
            "collector": "u2-douyin",
            "url_hash": (row.get("sample_id") or "")[:16] or None,
            "topic_count": hashtags,
            "hashtag_count": hashtags,
            "media_type": "video",
            "cover_type": "unknown",
            "metrics_at": collected_at,
        }
    )
    meta = {"missing_flags", "outlier_flags", "is_censored"}
    missing = [
        key
        for key, value in row.items()
        if key not in meta and (value is None or str(value).strip() in ("", "[]"))
    ]
    row["missing_flags"] = ";".join(missing)
    return row


# ── 真机操作 ────────────────────────────────────────────────────────────────
def _dismiss_popups(d, nodes: list[dict]) -> bool:
    texts = {n.get("text") or "" for n in nodes}
    for word in POPUP_WORDS:
        if word in texts:
            try:
                if d(text=word).exists:
                    d(text=word).click()
                    time.sleep(1)
                    return True
            except Exception:
                continue
    return False


def _open_search(d, keyword: str) -> list[dict]:
    """打开抖音搜索并输入关键词，返回结果页节点。"""
    d.app_start(PACKAGE, wait=True)
    time.sleep(2.5)
    nodes = common._dump(d)
    common._dismiss_system_dialogs(d, nodes)
    _dismiss_popups(d, nodes)
    nodes = common._dump(d)
    if _has_results(nodes, keyword):
        return nodes
    for _ in range(5):
        if d(className="android.widget.EditText").exists:
            break
        if d(description="搜索").exists:
            d(description="搜索").click()
            break
        if d(text="搜索").exists:
            d(text="搜索").click()
            break
        d.press("back")
        time.sleep(1.5)
    time.sleep(2)
    nodes = common._dump(d)
    common._dismiss_system_dialogs(d, nodes)
    editor = d(className="android.widget.EditText")
    if not editor.exists:
        raise U2Stop("search.input", "找不到搜索输入框")
    editor.set_text(keyword)
    time.sleep(0.8)
    d.press("enter")
    deadline = time.time() + 20
    while time.time() < deadline:
        nodes = common._dump(d)
        if _has_results(nodes, keyword):
            return nodes
        time.sleep(1)
    raise U2Stop("search.results", "搜索结果页未出现卡片（{}）".format(keyword))


def collect(
    track: str,
    limit: int = 10,
    scrolls: int = DEFAULT_SCROLLS,
    serial: str = "",
) -> dict:
    run_id = "p0a-{}-douyin-u2".format(time.strftime("%Y%m%d-%H%M%S"))
    trace_id = "p0a:douyin-u2:{}".format(int(time.time() * 1000))
    check = base.channel_check(run_id, emit=True)
    base._event(
        "collect.request",
        "douyin.u2",
        trace_id=trace_id,
        run_id=run_id,
        status="requested",
        detail={
            "platform": PLATFORM,
            "track": track,
            "limit": limit,
            "scrolls": scrolls,
            "driver": "u2",
        },
    )
    started = time.time()
    rows: list[dict] = []
    detail_log: dict[str, Any] = {"cards_seen": 0, "scrolls_done": 0, "steps": []}
    status, error_code, error_note = "empty", "", ""
    try:
        d = common._connect(serial)
        nodes = _open_search(d, track)
        _dismiss_popups(d, nodes)
        want = max(1, min(50, int(limit)))
        cards = _parse_cards(nodes, keyword=track)
        seen_titles = {card["title"] for card in cards}
        empty_scrolls = 0
        while (
            len(cards) < want
            and detail_log["scrolls_done"] < max(0, int(scrolls))
            and empty_scrolls < 2
        ):
            d.swipe(540, 1900, 540, 700, 0.3)
            time.sleep(1.8)
            _dismiss_popups(d, common._dump(d))
            new_cards = 0
            for card in _parse_cards(common._dump(d), keyword=track):
                if card["title"] in seen_titles:
                    continue
                seen_titles.add(card["title"])
                cards.append(card)
                new_cards += 1
            detail_log["scrolls_done"] += 1
            empty_scrolls = 0 if new_cards else empty_scrolls + 1
            if not new_cards:
                detail_log["steps"].append({"scroll": detail_log["scrolls_done"], "new_cards": 0})
        cards = cards[:want]
        detail_log["cards_seen"] = len(cards)
        if not cards:
            status, error_code = "empty", "LAYOUT_CHANGED"
            error_note = "搜索结果页未解析出卡片"
        for rank, card in enumerate(cards, start=1):
            collected_at = datetime.now().astimezone().replace(microsecond=0).isoformat()
            rows.append(
                _row(
                    PLATFORM,
                    {"title": card["title"], "author": card["author"], "likes": card["likes"]},
                    track,
                    collected_at,
                    rank,
                )
            )
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
        "douyin.u2",
        trace_id=trace_id,
        run_id=run_id,
        status=status,
        error_code=error_code,
        duration_ms=duration_ms,
        detail=result,
    )
    base._event(
        "collect.parse",
        "douyin.u2",
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
            "scrolls_done": detail_log["scrolls_done"],
        },
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="抖音只读滚动采集（P0-A 兜底通道）")
    parser.add_argument("--track", required=True, help="赛道关键词，逗号分隔")
    parser.add_argument("--limit", type=int, default=10, help="每个赛道读取的卡片数（1-30）")
    parser.add_argument("--scrolls", type=int, default=DEFAULT_SCROLLS, help="每个赛道的下滚屏数")
    parser.add_argument("--serial", default="", help="adb 序列号；省略自动取第一台")
    args = parser.parse_args(argv)

    tracks = [item.strip() for item in args.track.split(",") if item.strip()]
    summary = []
    for track in tracks:
        summary.append(collect(track, limit=args.limit, scrolls=args.scrolls, serial=args.serial))
    print(__import__("json").dumps(summary, ensure_ascii=False, indent=2))
    return 0 if any(item["status"] == "done" for item in summary) else 1


if __name__ == "__main__":
    raise SystemExit(main())
