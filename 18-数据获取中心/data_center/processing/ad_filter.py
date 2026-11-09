"""C1 广告/软文剔除 v0（规则版）— SPEC-D1-NARRATIVE-PRIMITIVES §2.1。

双判据：
  1. 推广特征：推广关键词 / 返佣外链 / 免责声明模板叠加推广
  2. 命题密度（启发式占位，P1 由 NPE 精化）：文本过短且无因果触发词
     → 标记 low_density（保留不剔除，下游自行降权）

硬约束：
  - 剔除决策可审计：filter_article 返回 {decision, hit_rules}；
    filter_batch 支持 audit_path JSONL 落盘
  - 边界样本保留并标 low_density
  - FAIL-OPEN：输入异常一律 keep + hit_rules=["error:..."]

v0 局限（P1 迭代方向）：
  - 关键词表靠人工维护，召回有限
  - 命题密度为启发式（长度+因果触发词），非真正命题计数
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger("data_center.processing.ad_filter")

# ── 推广关键词（命中即 drop）────────────────────────────────
_PROMO_KEYWORDS = [
    "注册即送",
    "注册立送",
    "新人礼包",
    "邀请码",
    "邀请好友",
    "返佣",
    "手续费返还",
    "瓜分",
    "体验金",
    "空投礼包",
    "点击链接领取",
    "下载.*领取",
    "专属链接",
    "推广链接",
]

# ── 返佣/推广外链特征（URL 路径含 ref/invite/promo 参数）───
_REF_LINK_RE = re.compile(
    r"https?://\S*(?:/ref/|[?&](?:ref|invite|referral|promo|utm_source)=)\S*",
    re.I,
)

# ── 免责声明模板（需与推广特征共现才 drop）──────────────────
_DISCLAIMER_TEMPLATES = [
    "不构成投资建议",
    "据此操作风险自担",
    "最终解释权归",
    "投资需谨慎",
    "非投资建议",
]

# ── 因果/条件触发词（命题密度启发式）────────────────────────
_CAUSAL_TRIGGERS = [
    "导致",
    "因此",
    "所以",
    "因为",
    "如果",
    "若",
    "当.*时",
    "意味着",
    "推动",
    "引发",
    "利好",
    "利空",
    "验证",
    "历史数据",
]

_MIN_CONTENT_LEN = 50  # 正文低于此长度视为密度不足候选


def _norm(x: Any) -> str:
    return str(x) if isinstance(x, (str, int, float)) else ""


def filter_article(title: Any = "", summary: Any = "", content: Any = "", **_: Any) -> dict:
    """单篇判定。返回 {"decision": "keep"|"drop", "hit_rules": [...]}。

    FAIL-OPEN：任何异常 → keep + error 标记。
    """
    try:
        title_s = _norm(title)
        summary_s = _norm(summary)
        content_s = _norm(content) or _norm(_.get("content_text", ""))
        all_text = f"{title_s}\n{summary_s}\n{content_s}"

        hit: list[str] = []

        # 判据 1a：推广关键词（标题/摘要/正文三路）
        for kw in _PROMO_KEYWORDS:
            if re.search(kw, all_text):
                hit.append(f"promo_kw:{kw}")

        # 判据 1b：返佣外链
        m = _REF_LINK_RE.search(all_text)
        if m:
            hit.append(f"ref_link:{m.group(0)[:60]}")

        # 判据 1c：免责声明模板（仅在已有其他推广特征时升级为 drop 依据）
        for tp in _DISCLAIMER_TEMPLATES:
            if tp in all_text:
                hit.append(f"disclaimer:{tp}")

        drop_rules = [r for r in hit if r.startswith(("promo_kw:", "ref_link:"))]
        if drop_rules:
            # 免责声明单独命中不 drop；但随推广特征一起记录
            return {"decision": "drop", "hit_rules": hit}

        # 判据 2：命题密度启发式（保留 + 标记，不剔除）
        has_disclaimer_only = any(r.startswith("disclaimer:") for r in hit)
        if has_disclaimer_only:
            hit = []  # 纯免责声明（正规研报也有）不算推广特征

        causal_hits = sum(1 for t in _CAUSAL_TRIGGERS if re.search(t, content_s))
        if len(content_s) < _MIN_CONTENT_LEN or causal_hits == 0:
            hit.append("low_density")

        return {"decision": "keep", "hit_rules": hit}
    except Exception as e:  # noqa: BLE003  FAIL-OPEN 硬约束
        logger.warning("[FAIL-OPEN] ad_filter 异常 %s: %s", type(e).__name__, str(e)[:120])
        return {"decision": "keep", "hit_rules": [f"error:{type(e).__name__}"]}


def filter_batch(articles: list[dict], audit_path: str | None = None) -> list[dict]:
    """批量判定 + 可选 JSONL 审计落盘。

    每条审计记录：{id, decision, hit_rules}。
    """
    decisions: list[dict] = []
    fp = open(audit_path, "a", encoding="utf-8") if audit_path else None
    try:
        for art in articles or []:
            if not isinstance(art, dict):
                d = {"decision": "keep", "hit_rules": ["error:bad_input"]}
            else:
                d = filter_article(
                    title=art.get("title", ""),
                    summary=art.get("summary", ""),
                    content=art.get("content_text", art.get("content", "")),
                )
            decisions.append(d)
            if fp:
                fp.write(
                    json.dumps(
                        {"id": art.get("id") if isinstance(art, dict) else None, **d},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    finally:
        if fp:
            fp.close()
    return decisions
