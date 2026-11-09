"""Odaily 星球日报深度文章 collector 测试（TDD）。

被测模块：data_center.collectors.news.odaily_post
上游 API：GET https://web-api.odaily.news/post/page?page=N&limit=M

7 TC 覆盖:
  TC-1 正常 N 条 contract + 12 metrics 范围校验（数据契约硬约束）
  TC-2 增量 last_id 过滤：仅保留 id > last_id 的记录
  TC-3 depth_only=True 仅保留 depthPlateId 非空且 >0 的深度文章
  TC-4 网络 Timeout 返回空不抛（FAIL-OPEN L1）
  TC-5 sentiment_engine ImportError → sentiment=0.5 中性兜底（FAIL-OPEN L2）
  TC-6 翻页参数透传：page=2 时 requests 收到 page=2
  TC-7 事件/ticker/tags 字段：events[0].published_ms 正确 + tickers_hit_csl 提取 + tags_csl 拼接
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_center.core.contract import validate_record  # noqa: E402

COLLECTOR_MOD = "data_center.collectors.news.odaily_post"
REQ_MOD = f"{COLLECTOR_MOD}.requests"


# ============================================================
# Fixtures
# ============================================================
@pytest.fixture
def fx_http_3():
    """3 条深度文章 HTTP 响应（对齐真实 API schema）。"""
    items = [
        {
            "id": 5213834,
            "title": "美联储货币政策深度报告：降息路径全解析",
            "cover": "https://oss.odaily.top/image/x1.jpg",
            "summary": "本文深入分析美联储降息与扩表路径。",
            "isTop": True,
            "isHot": False,
            "publishTimestamp": 1_794_224_283_000,
            "tags": [{"id": 24, "name": "投资"}, {"id": 100, "name": "美联储"}],
            "depthPlateId": 7,
            "viewpoint": None,
            "isCollection": False,
            "isLike": False,
        },
        {
            "id": 5213833,
            "title": "SOL 主网升级深度解读：TPS 提升 42% 的技术原理",
            "cover": "https://oss.odaily.top/image/x2.jpg",
            "summary": "Solana 主网 v1.18 升级技术细节全披露。",
            "isTop": False,
            "isHot": True,
            "publishTimestamp": 1_794_224_000_000,
            "tags": [{"id": 105, "name": "Solana"}],
            "depthPlateId": 1,
            "viewpoint": None,
            "isCollection": False,
            "isLike": False,
        },
        {
            "id": 5213832,
            "title": "今日快讯改写：不构成深度文章",
            "cover": "",
            "summary": "短稿。",
            "isTop": False,
            "isHot": False,
            "publishTimestamp": 1_794_223_000_000,
            "tags": [],
            "depthPlateId": None,  # ← 非深度
            "viewpoint": None,
            "isCollection": False,
            "isLike": False,
        },
    ]
    return {
        "code": 200,
        "msg": "操作成功",
        "data": {
            "total": 63750,
            "pageSize": 20,
            "pageNum": 1,
            "list": items,
            "empty": False,
            "hasMore": True,
            "totalPage": 3188,
        },
        "success": True,
    }


def _mk_resp(payload: dict) -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = payload
    return r


# ============================================================
# TC-1 契约 + 12 metrics 范围
# ============================================================
def test_tc1_contract_and_metrics(fx_http_3):
    from data_center.collectors.news.odaily_post import OdailyPostCollector

    with patch(REQ_MOD) as mock_req:
        mock_req.get.return_value = _mk_resp(fx_http_3)
        recs = OdailyPostCollector().fetch({})

    assert len(recs) == 3
    for rec in recs:
        validate_record(rec)
        assert rec.source == "odaily_post"
        assert rec.category == "news"
        assert rec.sub_category.startswith("post_")
        m = rec.metrics
        # 12 个扁平 metrics 硬约束
        expected_keys = {
            "odp_source_id",
            "odp_policy_sentiment_0_1",
            "odp_event_type",
            "odp_attention_type",
            "odp_is_important",
            "odp_is_depth",
            "odp_decay_hl_hrs",
            "odp_title_hash",
            "odp_tickers_hit_csl",
            "odp_depth_plate_id",
            "odp_tags_csl",
            "odp_summary_hash",
        }
        assert expected_keys.issubset(
            set(m.keys())
        ), f"missing keys: {expected_keys - set(m.keys())}"
        # 类型/范围断言
        assert isinstance(m["odp_source_id"], int)
        assert 0.0 <= m["odp_policy_sentiment_0_1"] <= 1.0
        assert m["odp_is_important"] in ("true", "false")
        assert m["odp_is_depth"] in ("true", "false")
        assert isinstance(m["odp_decay_hl_hrs"], int) and m["odp_decay_hl_hrs"] > 0
        assert isinstance(m["odp_depth_plate_id"], int)


# ============================================================
# TC-2 增量 last_id 过滤
# ============================================================
def test_tc2_incremental_last_id(fx_http_3):
    from data_center.collectors.news.odaily_post import OdailyPostCollector

    with patch(REQ_MOD) as mock_req:
        mock_req.get.return_value = _mk_resp(fx_http_3)
        recs = OdailyPostCollector().fetch({"last_id": 5213833})

    # 仅保留 id > 5213833 的 → 只剩 5213834
    assert len(recs) == 1
    assert recs[0].metrics["odp_source_id"] == 5213834


# ============================================================
# TC-3 depth_only 过滤
# ============================================================
def test_tc3_depth_only(fx_http_3):
    from data_center.collectors.news.odaily_post import OdailyPostCollector

    with patch(REQ_MOD) as mock_req:
        mock_req.get.return_value = _mk_resp(fx_http_3)
        recs = OdailyPostCollector().fetch({"depth_only": True})

    # depthPlateId: 7 / 1 / None → 仅前两条为深度
    assert len(recs) == 2
    assert all(r.metrics["odp_is_depth"] == "true" for r in recs)
    assert {r.metrics["odp_depth_plate_id"] for r in recs} == {7, 1}


# ============================================================
# TC-4 网络 Timeout FAIL-OPEN L1
# ============================================================
def test_tc4_timeout_fail_open():
    import requests as _rq
    from data_center.collectors.news.odaily_post import OdailyPostCollector

    with patch(REQ_MOD) as mock_req:
        mock_req.get.side_effect = _rq.exceptions.Timeout("boom")
        mock_req.exceptions = _rq.exceptions
        recs = OdailyPostCollector().fetch({})
    assert recs == []


# ============================================================
# TC-5 sentiment_engine 缺失 → 0.5 兜底
# ============================================================
def test_tc5_sentiment_import_error(fx_http_3, monkeypatch):
    from data_center.collectors.news import odaily_post as mod
    from data_center.collectors.news.odaily_post import OdailyPostCollector

    # 模拟 9基本面 不可导入
    monkeypatch.setattr(mod, "_sentiment_lazy", lambda t, d: (0.5, False))

    with patch(REQ_MOD) as mock_req:
        mock_req.get.return_value = _mk_resp(fx_http_3)
        recs = OdailyPostCollector().fetch({})

    assert all(r.metrics["odp_policy_sentiment_0_1"] == 0.5 for r in recs)


# ============================================================
# TC-6 翻页参数透传
# ============================================================
def test_tc6_page_param_passthrough(fx_http_3):
    from data_center.collectors.news.odaily_post import OdailyPostCollector

    with patch(REQ_MOD) as mock_req:
        mock_req.get.return_value = _mk_resp(fx_http_3)
        OdailyPostCollector().fetch({"page": 2, "limit": 50})

    # 验证 requests.get 被调用时 params 含 page=2 limit=50
    assert mock_req.get.called
    _, kwargs = mock_req.get.call_args
    assert kwargs["params"]["page"] == 2
    assert kwargs["params"]["limit"] == 50


# ============================================================
# TC-7 events / tickers / tags
# ============================================================
def test_tc7_events_tickers_tags(fx_http_3):
    from data_center.collectors.news.odaily_post import OdailyPostCollector

    with patch(REQ_MOD) as mock_req:
        mock_req.get.return_value = _mk_resp(fx_http_3)
        recs = OdailyPostCollector().fetch({})

    # 第 2 条（SOL 主网升级）应命中 SOL ticker + token_milestone 分类
    sol_rec = next(r for r in recs if "SOL" in r.metrics["odp_tickers_hit_csl"])
    assert sol_rec.metrics["odp_event_type"] == "token_milestone"
    assert "Solana" in sol_rec.metrics["odp_tags_csl"]
    # events[0] 契约
    ev = sol_rec.events[0]
    assert ev["event_type"] == "token_milestone"
    assert ev["published_ms"] == 1_794_224_000_000
    assert ev["importance"] == 2  # isHot=True → importance=2
    # raw 保留原始字段
    assert sol_rec.raw["depthPlateId"] == 1
    assert "SOL" in sol_rec.raw["tickers_hit"]
