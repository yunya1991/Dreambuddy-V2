"""Odaily 深度文章正文爬取器 collector 测试（TDD）。

被测模块：data_center.collectors.news.odaily_post_content
上游页面：GET https://www.odaily.news/post/{id} （HTML，正文在 div#post-content）

背景：odaily_post 列表端点无 content 字段（实测 2026-11-09），正文需二次爬详情页。
页面结构（实测）：正文容器 <div id="post-content">，内部 <p>/<img> 标签；
页面另有 application/ld+json（NewsArticle schema，含 datePublished，无 articleBody）。

7 TC 覆盖：
  TC-1 正常解析：div#post-content → 纯文本，metrics 契约 + 范围校验
  TC-2 无 #post-content 容器 → fetch_ok="false" 记录（可审计），content_len=0
  TC-3 网络 Timeout → 该 id 记 fetch_ok="false"，不抛异常（FAIL-OPEN L1）
  TC-4 多 id 批量：单条失败不阻塞其他（L2 隔离）
  TC-5 文本规范化：去标签、段落间保留换行、HTML 实体反转义、无多余空白
  TC-6 HTTP 404 → fetch_ok="false"
  TC-7 raw 保留 content_text 与 datePublished（来自 ld+json），sha1 与文本一致
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_center.core.contract import validate_record  # noqa: E402

COLLECTOR_MOD = "data_center.collectors.news.odaily_post_content"
REQ_MOD = f"{COLLECTOR_MOD}.requests"


# ============================================================
# Fixtures（对齐实测页面结构 2026-11-09 /post/5213824）
# ============================================================
FX_HTML_OK = """<!DOCTYPE html>
<html><head><title>币圈 RUG 史 - Odaily</title>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"NewsArticle",
 "headline":"币圈 RUG 史","datePublished":"2026-11-09T07:49:33.000Z"}
</script></head>
<body><main>
<div id="post-content" class="w-full whitespace-pre-line DetailContent_detail__pRaS_">
<p><em>原创 | Odaily 星球日报&#xff08;<u>@OdailyChina</u>&#xff09;</em></p>
<p>这是社区对 DePIN 项目 Puffpaw 的真实评价。</p>
<p><img src="https://oss.odaily.top/image/x.png" /></p>
<p>降息 50bp 将推动风险资产上涨，历史验证概率较高。</p>
</div>
<div id="other">无关内容</div>
</main></body></html>"""

FX_HTML_NO_CONTENT = """<!DOCTYPE html>
<html><head><title>无正文页</title></head>
<body><main><div id="list">只有列表</div></main></body></html>"""


def _mk_resp(html: str, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.text = html
    r.content = html.encode("utf-8")
    return r


# ============================================================
# TC-1 正常解析 + 契约
# ============================================================
def test_tc1_parse_ok_contract():
    from data_center.collectors.news.odaily_post_content import OdailyPostContentCollector

    with patch(REQ_MOD) as mock_req:
        mock_req.get.return_value = _mk_resp(FX_HTML_OK)
        recs = OdailyPostContentCollector().fetch({"ids": [5213824]})

    assert len(recs) == 1
    rec = recs[0]
    validate_record(rec)
    assert rec.source == "odaily_post_content"
    assert rec.category == "news"
    assert rec.sub_category == "post_content_5213824"
    m = rec.metrics
    expected_keys = {
        "odpc_source_id",
        "odpc_fetch_ok",
        "odpc_content_len",
        "odpc_para_count",
        "odpc_content_sha1",
        "odpc_date_published",
    }
    assert expected_keys.issubset(set(m.keys())), f"missing: {expected_keys - set(m.keys())}"
    assert m["odpc_source_id"] == 5213824
    assert m["odpc_fetch_ok"] == "true"
    assert m["odpc_content_len"] > 0
    assert m["odpc_para_count"] >= 3  # 3 个文本段落（img 段不计）
    assert m["odpc_date_published"] == "2026-11-09T07:49:33.000Z"


# ============================================================
# TC-2 无 #post-content → fetch_ok="false" 可审计记录
# ============================================================
def test_tc2_no_content_container():
    from data_center.collectors.news.odaily_post_content import OdailyPostContentCollector

    with patch(REQ_MOD) as mock_req:
        mock_req.get.return_value = _mk_resp(FX_HTML_NO_CONTENT)
        recs = OdailyPostContentCollector().fetch({"ids": [999]})

    assert len(recs) == 1
    m = recs[0].metrics
    assert m["odpc_fetch_ok"] == "false"
    assert m["odpc_content_len"] == 0
    validate_record(recs[0])


# ============================================================
# TC-3 网络 Timeout FAIL-OPEN L1
# ============================================================
def test_tc3_timeout_fail_open():
    import requests as _rq
    from data_center.collectors.news.odaily_post_content import OdailyPostContentCollector

    with patch(REQ_MOD) as mock_req:
        mock_req.get.side_effect = _rq.exceptions.Timeout("boom")
        mock_req.exceptions = _rq.exceptions
        recs = OdailyPostContentCollector().fetch({"ids": [123]})

    assert len(recs) == 1
    assert recs[0].metrics["odpc_fetch_ok"] == "false"


# ============================================================
# TC-4 多 id 批量隔离
# ============================================================
def test_tc4_batch_isolation():
    import requests as _rq
    from data_center.collectors.news.odaily_post_content import OdailyPostContentCollector

    def _side_effect(url, **kwargs):
        if "5213824" in url:
            return _mk_resp(FX_HTML_OK)
        raise _rq.exceptions.ConnectionError("down")

    with patch(REQ_MOD) as mock_req:
        mock_req.get.side_effect = _side_effect
        mock_req.exceptions = _rq.exceptions
        recs = OdailyPostContentCollector().fetch({"ids": [5213824, 888, 999]})

    assert len(recs) == 3
    ok = [r for r in recs if r.metrics["odpc_fetch_ok"] == "true"]
    bad = [r for r in recs if r.metrics["odpc_fetch_ok"] == "false"]
    assert len(ok) == 1 and ok[0].metrics["odpc_source_id"] == 5213824
    assert {r.metrics["odpc_source_id"] for r in bad} == {888, 999}


# ============================================================
# TC-5 文本规范化
# ============================================================
def test_tc5_text_normalization():
    from data_center.collectors.news.odaily_post_content import OdailyPostContentCollector

    with patch(REQ_MOD) as mock_req:
        mock_req.get.return_value = _mk_resp(FX_HTML_OK)
        recs = OdailyPostContentCollector().fetch({"ids": [5213824]})

    text = recs[0].raw["content_text"]
    assert "<p>" not in text and "<em>" not in text  # 标签已去除
    assert "&#xff08;" not in text and "（" in text  # 实体已反转义
    assert "无关内容" not in text  # 容器外内容不混入
    assert "Puffpaw 的真实评价" in text
    # 段落间换行保留
    lines = [ln for ln in text.split("\n") if ln.strip()]
    assert len(lines) >= 3


# ============================================================
# TC-6 HTTP 404 → fetch_ok="false"
# ============================================================
def test_tc6_http_404():
    from data_center.collectors.news.odaily_post_content import OdailyPostContentCollector

    with patch(REQ_MOD) as mock_req:
        mock_req.get.return_value = _mk_resp("not found", status=404)
        recs = OdailyPostContentCollector().fetch({"ids": [404000]})

    assert len(recs) == 1
    assert recs[0].metrics["odpc_fetch_ok"] == "false"
    assert recs[0].metrics["odpc_content_len"] == 0


# ============================================================
# TC-7 raw 与 sha1 一致性
# ============================================================
def test_tc7_raw_and_sha1():
    import hashlib

    from data_center.collectors.news.odaily_post_content import OdailyPostContentCollector

    with patch(REQ_MOD) as mock_req:
        mock_req.get.return_value = _mk_resp(FX_HTML_OK)
        recs = OdailyPostContentCollector().fetch({"ids": [5213824]})

    rec = recs[0]
    text = rec.raw["content_text"]
    assert rec.metrics["odpc_content_sha1"] == hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    assert rec.metrics["odpc_content_len"] == len(text)
    assert rec.raw["id"] == 5213824
    assert rec.raw["datePublished"] == "2026-11-09T07:49:33.000Z"
