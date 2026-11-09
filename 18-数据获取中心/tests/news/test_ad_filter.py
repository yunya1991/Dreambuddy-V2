"""C1 广告剔除 v0（规则版）测试 — SPEC-D1-NARRATIVE-PRIMITIVES §2.1。

被测模块：data_center.processing.ad_filter

双判据（v0 规则版）：
  1. 推广特征：推广关键词 / 外链域名 / 免责声明模板
  2. 命题密度（启发式占位）：文本过短且无因果触发词 → 标记 low_density（保留不剔除）

硬约束：
  - 剔除决策必须可审计：返回 decision + hit_rules + 可落盘 JSONL
  - 边界样本（密度低但无推广特征）保留并标 low_density
  - FAIL-OPEN：输入异常一律 keep + hit_rules=["error:..."]

8 TC 覆盖：
  TC-1 正常深度文章 → keep，无命中规则
  TC-2 推广关键词（注册/返佣/邀请码）→ drop + 命中关键词规则
  TC-3 外链推广域名（交易所返佣链接）→ drop
  TC-4 免责声明模板（"不构成投资建议"叠加推广）→ drop
  TC-5 低命题密度但无推广特征 → keep + low_density 标记
  TC-6 批量接口 + JSONL 审计落盘
  TC-7 空/异常输入 FAIL-OPEN → keep
  TC-8 推广词在标题命中也算（title+summary+content 三路检查）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MOD = "data_center.processing.ad_filter"


def _art(title="", summary="", content=""):
    return {"id": 1, "title": title, "summary": summary, "content_text": content}


# 正常深度文章（含因果论证，无推广特征）
FX_OK = _art(
    title="美联储降息路径全解析",
    summary="本文分析降息对风险资产的传导机制。",
    content="美联储降息 50bp 将导致美元走弱，因此风险资产上涨。历史数据显示，"
    "2019 年降息周期中 BTC 上涨 230%。如果通胀回落，那么降息空间打开。",
)

# 交易所推广软文
FX_AD = _art(
    title="新用户注册即送 500 USDT",
    summary="点击链接领取返佣，邀请好友再得 20% 手续费返佣。",
    content="立即注册 BitXXX 交易所，输入邀请码 ABC123，永久返佣 30%。"
    "点击 https://bitxxx.com/ref/abc123 领取新人礼包。",
)


# TC-1 正常文章 keep
def test_tc1_normal_keep():
    from data_center.processing.ad_filter import filter_article

    d = filter_article(**FX_OK)
    assert d["decision"] == "keep"
    assert d["hit_rules"] == []


# TC-2 推广关键词 → drop
def test_tc2_promo_keywords_drop():
    from data_center.processing.ad_filter import filter_article

    d = filter_article(**FX_AD)
    assert d["decision"] == "drop"
    assert any(r.startswith("promo_kw:") for r in d["hit_rules"])


# TC-3 外链返佣域名 → drop
def test_tc3_ref_link_drop():
    from data_center.processing.ad_filter import filter_article

    d = filter_article(**FX_AD)
    assert d["decision"] == "drop"
    assert any(r.startswith("ref_link:") for r in d["hit_rules"])


# TC-4 免责声明模板 + 推广 → drop
def test_tc4_disclaimer_template():
    from data_center.processing.ad_filter import filter_article

    art = _art(
        title="XX 平台新币上线",
        summary="",
        content="XX 交易所上线新币，注册交易瓜分 10000 USDT 奖池。"
        "本文不构成投资建议，据此操作风险自担。活动最终解释权归平台所有。",
    )
    d = filter_article(**art)
    assert d["decision"] == "drop"
    assert any(r.startswith("disclaimer:") for r in d["hit_rules"])


# TC-5 低密度无推广 → keep + low_density
def test_tc5_low_density_keep():
    from data_center.processing.ad_filter import filter_article

    art = _art(title="短讯", summary="", content="BTC 涨了。")
    d = filter_article(**art)
    assert d["decision"] == "keep"
    assert "low_density" in d["hit_rules"]


# TC-6 批量 + JSONL 审计
def test_tc6_batch_audit_jsonl(tmp_path):
    from data_center.processing.ad_filter import filter_batch

    out = tmp_path / "audit.jsonl"
    decisions = filter_batch([FX_OK, FX_AD], audit_path=str(out))
    assert len(decisions) == 2
    assert decisions[0]["decision"] == "keep"
    assert decisions[1]["decision"] == "drop"
    lines = out.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    rec = json.loads(lines[1])
    assert rec["decision"] == "drop"
    assert rec["hit_rules"]


# TC-7 异常输入 FAIL-OPEN（None 输入不抛异常、不剔除）
def test_tc7_fail_open():
    from data_center.processing.ad_filter import filter_article

    d = filter_article(title=None, summary=None, content=None)
    assert d["decision"] == "keep"


# TC-8 标题命中推广词也剔除
def test_tc8_title_hit():
    from data_center.processing.ad_filter import filter_article

    art = _art(
        title="注册即送 100 USDT 体验金",
        summary="",
        content="正常正文内容，包含因果：降息导致上涨。",
    )
    d = filter_article(**art)
    assert d["decision"] == "drop"
    assert any(r.startswith("promo_kw:") for r in d["hit_rules"])
