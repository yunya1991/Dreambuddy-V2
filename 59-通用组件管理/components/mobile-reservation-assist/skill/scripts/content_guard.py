"""内容合规护栏：发布前扫描高风险表达，命中即拦截或交千问整改。

定位：只做「金融内容」的确定性规则扫描，不依赖模型判断。
- 高风险（block）：个股代码/名称+交易动作、荐股、买卖点、收益承诺、代客理财
- 中风险（warn）：交易动作词、夸张标题党、引流话术
- 策略：block 命中必须改写或放弃发布；warn 只提示，允许人工确认

风控背景：平台对「具体标的 + 买卖建议」判定最严，其次是收益承诺与焦虑营销。
本模块只认「可证实的文字风险」，不评价内容质量。
"""

from __future__ import annotations

import re

# 高风险：直接拒绝发布
BLOCK_PATTERNS = (
    ("个股代码", re.compile(r"(?<!\d)\d{6}(?!\d)")),
    ("荐股用语", re.compile(r"荐股|推荐股票|推荐个股|牛股|黑马股|翻倍股|必涨|必跌")),
    ("买卖指令", re.compile(r"(买入|卖出|加仓|减仓|满仓|空仓|抄底|逃顶|梭哈|建仓|清仓)")),
    ("收益承诺", re.compile(r"稳赚|保本|保收益|零风险|躺赚|保证收益|年化\s*\d+%|翻倍|收益率\s*\d+%")),
    ("代客理财", re.compile(r"代客理财|带你赚钱|跟单|喊单|带单|内幕消息")),
    ("点位预测", re.compile(r"目标价|止盈位|止损位|看到\s*\d+\s*元|必到\s*\d+")),
)

# 中风险：提示但可继续（发布前需人工确认）
WARN_PATTERNS = (
    ("标题党", re.compile(r"震惊|重磅|必看|速看|炸裂|天塌了|再不.{0,4}就晚了|彻底疯了")),
    ("焦虑营销", re.compile(r"最后机会|错过就|来不及了|血亏|亏麻了")),
    ("引流话术", re.compile(r"加微信|加V|私信我|评论区扣|扣1|领取资料|进群")),
    ("涨跌描述", re.compile(r"暴涨|暴跌|狂飙|崩盘|起飞|跳水")),
)

# 改写后仍可能触发的平台敏感词（仅提示，不阻断）
SOFT_WORDS = ("投资建议", "仅供参考", "不构成")


def scan(text: str) -> dict:
    """扫描文本：返回 {block: [...], warn: [...], clean: bool}。"""
    blob = str(text or "")
    blocks: list[dict] = []
    warns: list[dict] = []
    for name, pattern in BLOCK_PATTERNS:
        for match in pattern.finditer(blob):
            blocks.append({"type": name, "hit": match.group(0)})
    for name, pattern in WARN_PATTERNS:
        for match in pattern.finditer(blob):
            warns.append({"type": name, "hit": match.group(0)})
    # 去重（同类型同命中只留一条）
    blocks = _dedupe(blocks)
    warns = _dedupe(warns)
    return {"block": blocks, "warn": warns, "clean": not blocks}


def _dedupe(items: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for item in items:
        key = (item["type"], item["hit"])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def scan_note(note: dict) -> dict:
    """扫描整篇内容：标题 + 正文 + 话题 + 图文分页文案。"""
    parts = [str(note.get("title") or ""), str(note.get("body") or "")]
    parts.extend(str(item) for item in (note.get("topics") or []))
    for page in note.get("pages") or []:
        if isinstance(page, dict):
            parts.append(str(page.get("heading") or ""))
            parts.extend(str(item) for item in (page.get("points") or []))
        else:
            parts.append(str(page))
    return scan("\n".join(parts))


def describe(findings: dict) -> str:
    """把扫描结果压成一行，便于 CLI 输出与回执。"""
    blocks = findings.get("block") or []
    warns = findings.get("warn") or []
    if not blocks and not warns:
        return "通过"
    parts = []
    if blocks:
        parts.append("阻断：" + "、".join("{}（{}）".format(item["type"], item["hit"]) for item in blocks[:5]))
    if warns:
        parts.append("提示：" + "、".join("{}（{}）".format(item["type"], item["hit"]) for item in warns[:5]))
    return "；".join(parts)
