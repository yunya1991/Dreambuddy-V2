"""C1 广告/软文剔除 v0.1（规则版）— SPEC-D1-NARRATIVE-PRIMITIVES §2.1。

双判据：
  1. 推广特征：推广关键词 + 推广意图证据 / 返佣外链 / 免责声明模板叠加推广
  2. 命题密度（启发式占位，P1 由 NPE 精化）：文本过短且无因果触发词
     → 标记 low_density（保留不剔除，下游自行降权）

v0.1 变更（P0 试爬实测：29 drop 中 18 误判，剔除精度仅 ~34%）：
  - 根因：返佣/瓜分/邀请码 在商业模式分析文中是正常词汇
    （返佣机制拆解、瓜分蛋糕比喻、邀请码产品事实），单关键词命中即剔过杀
  - 新口径（预注册）：推广词命中需叠加推广意图证据才 drop：
      a) 标题命中推广词；或
      b) 正文命中位置 ±80 字窗口内含动作词（注册/点击/链接/http/领取/
         奖励/奖金/福利/活动/任务/积分/STEP/签到/促销/空投）
  - 仅关键词无意图 → keep + promo_kw_weak:<kw> 审计标记（下游可降权）
  - 注：动作词不含"获得"——实测其为分析文高频词（"获得优势/获得收入"），
    是 v0.1 首轮误判主因

硬约束：
  - 剔除决策可审计：filter_article 返回 {decision, hit_rules}；
    filter_batch 支持 audit_path JSONL 落盘
  - 边界样本保留并标 low_density
  - FAIL-OPEN：输入异常一律 keep + hit_rules=["error:..."]
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger("data_center.processing.ad_filter")

# ── 推广关键词（需叠加意图证据才 drop）──────────────────────
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

# ── 推广意图动作词（±80 字窗口共现 = 推广意图证据）──────────
_PROMO_ACTION_WORDS = [
    "注册",
    "点击",
    "链接",
    "http",
    "领取",
    "奖励",
    "奖金",
    "福利",
    "活动",
    "任务",
    "积分",
    "STEP",
    "签到",
    "促销",
    "空投",
]
_ACTION_WINDOW = 80

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

        # 判据 1a（v0.1）：推广关键词需叠加意图证据
        #   - 标题命中 → drop 级
        #   - 正文/摘要命中 ±80 字窗口含动作词 → drop 级
        #   - 仅关键词无意图 → promo_kw_weak（保留，审计可降权）
        body_text = f"{summary_s}\n{content_s}"
        for kw in _PROMO_KEYWORDS:
            if re.search(kw, title_s):
                hit.append(f"promo_kw:{kw}")
                continue
            strong = False
            for m in re.finditer(kw, body_text):
                lo = max(0, m.start() - _ACTION_WINDOW)
                hi = m.end() + _ACTION_WINDOW
                window = body_text[lo:hi]
                if any(a in window for a in _PROMO_ACTION_WORDS):
                    strong = True
                    break
            if strong:
                hit.append(f"promo_kw:{kw}")
            elif re.search(kw, body_text):
                hit.append(f"promo_kw_weak:{kw}")

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
