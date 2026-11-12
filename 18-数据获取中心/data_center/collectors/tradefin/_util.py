"""中文财经采集器共用的文本 / 时间工具（P1-A）。

纪律：
  - 中文门户时间戳多为北京时间且不带时区 → 一律按 Asia/Shanghai 解释后转 UTC，
    禁止让 `datetime.fromisoformat` 把裸时间当本地/UTC 造成 8 小时前视偏差。
  - HTML 只做"去标签 + 反转义 + 段落保留"，不引入额外清洗规则（正文原样入库）。
"""

from __future__ import annotations

import html as html_lib
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

CN_TZ = ZoneInfo("Asia/Shanghai")

_TAG_RE = re.compile(r"<[^>]+>")
_PARA_RE = re.compile(r"</p\s*>", re.I)
_BR_RE = re.compile(r"<br\s*/?>", re.I)
_BRACKET_RE = re.compile(r"^[【\[]([^】\]]{2,80})[】\]]\s*")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_cn_time(value: str) -> datetime:
    """'2026-11-11 23:42:05'（北京时间）→ aware UTC datetime。"""
    text = str(value).strip().replace("T", " ")
    dt = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=CN_TZ)
    return dt.astimezone(timezone.utc)


def cn_time_iso(value: str) -> str:
    return to_iso(parse_cn_time(value))


def unix_to_iso(value: int | str | None) -> str:
    ts = int(value or 0)
    return to_iso(datetime.fromtimestamp(ts, tz=timezone.utc))


def html_to_text(raw: str) -> str:
    """保留段落的 HTML → 纯文本。"""
    text = _PARA_RE.sub("\n", raw or "")
    text = _BR_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = html_lib.unescape(text).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def split_title_body(text: str) -> tuple[str, str]:
    """快讯文本 → (标题, 正文)。

    优先取 `【标题】正文` 的括号标题；否则取第一句（≤60 字）作标题。
    """
    body = html_to_text(text)
    flat = body.replace("\n", " ").strip()
    m = _BRACKET_RE.match(flat)
    if m:
        title = m.group(1).strip()
        rest = flat[m.end() :].strip()
        return title or flat[:60], rest or flat
    if not flat:
        return "", ""
    head = re.split(r"[。！？；!?;]", flat, maxsplit=1)[0]
    return (head[:60] or flat[:60]), flat
