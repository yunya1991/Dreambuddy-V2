"""Odaily 星球日报快讯 collector 测试（TDD P0-2 T07 ~ T12）。

严格 TDD 循环：先红，后绿，再重构。
5 TC 覆盖:
  TC-1 正常 20 条 contract + 7 metrics 范围（Spec §4.3 数据契约）
  TC-2 增量 checkHasNew=0 返回空（Spec §4.5 增量去重第一道）
  TC-3 4 类 event_type 分布 + 关键词 Counter 命中（Spec §4.3 14 关键词 / 7 类 regex）
  TC-4 网络 Timeout 返回空不抛（Spec §4.6 FAIL-OPEN L1 Session）
  TC-5 ImportError sentiment_engine 缺失 → sentiment=0.5 中性全行（Spec §4.6 FAIL-OPEN L2）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ── 将 18-数据获取中心 加入 sys.path，让 pytest 能直接 import data_center ──
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_center.core.contract import DataRecord, validate_record  # noqa: E402

# 被测试模块目标路径（Collector 还没写，测试 import 失败即 RED Correct Reason）
COLLECTOR_MOD = "data_center.collectors.news.odaily_newsflash"
REQ_MOD = f"{COLLECTOR_MOD}.requests"
SENTIMENT_IMPORT_MOD = f"{COLLECTOR_MOD}.sys.modules"
# 真实 9基本面 sentiment_engine lazy import 路径
NINE_SENTIMENT_MOD = "nine_sentiment_engine_proxy"


# ============================================================
# T07 Fixtures（5 + 1 extra）
# ============================================================
@pytest.fixture
def fx_http_20():
    """Fixture 1 — 首屏 20 条 HTTP 正常响应（模拟 R3 探针 schema）。"""
    items = []
    titles = [
        # 货币政策类 monetary_policy
        "美联储主席暗示9月可能降息25个基点，市场定价概率升至82%",
        "欧央行管委：通胀下行趋势明确，9月不排除进一步降息",
        # 加密监管 crypto_regulation
        "美国SEC批准以太坊现货ETF上市，灰度等机构申请已全部生效",
        "香港金管局发布稳定币监管指引，7月1日起实施牌照制度",
        # 美国政策 us_policy
        "美国财政部发布国债季度再融资公告，长债发行规模低于预期",
        "白宫宣布对AI芯片出口管制新规，影响B100/H100系列",
        # 美国数据 us_data
        "美国7月非农就业新增18.7万人 失业率3.9% 低于预期",
        "美国7月CPI同比2.9% 核心CPI环比0.1% 均低于市场预期",
        # 地缘 geopolitics
        "中东局势升级，霍尔木兹海峡油轮遭袭，布油跳涨3%",
        "俄乌冲突：俄方宣布新一轮局部动员，欧盟考虑追加制裁",
        "朝鲜试射洲际弹道导弹，安理会召开紧急会议",
        # 安全事件 security_incident
        "币安热钱包转出1万枚ETH，PeckShield报警疑似私钥泄露",
        "Curve Finance攻击者归还80%被盗资金，剩余部分进入谈判",
        # 项目生态 project_ecosystem
        "V神发布ERC-7737标准，Layer2统一提款账户抽象方案",
        "Solana主网v1.18升级完成，TPS峰值实测提升42%",
        # 市场情绪 market_sentiment
        "比特币巨鲸地址3日累计增持1.2万枚BTC，创年内新高",
        "USDT溢价率达+0.45%，离岸资金入场信号显著",
        "灰度GBTC折价率收窄至-6.2%，机构资金开始回补",
        "恐惧贪婪指数突破75进入贪婪区，衍生品未平仓合约创3个月新高",
        # 再补一条 加密监管 做分布
        "韩国金融委员会将在9月公布虚拟资产会计处理标准终稿",
    ]
    for i, t in enumerate(titles):
        items.append({
            "id": 5_137_000 + i,
            "title": t,
            "description": f"<p>快讯内容摘要{i}。</p>",
            "isImportant": (i in {0, 2, 5, 8, 12, 16}),   # 官方打标重要
            "publishTimestamp": 1_760_000_000_000 + i * 60_000,
            "tags": [{"name": "政策"}, {"name": "快讯"}],
            "newsUrl": f"https://www.odaily.news/newsflash/post/5137{i:03d}",
            "images": [],
        })
    assert len(items) == 20

    class _Resp:
        status_code = 200
        def json(self):
            return {"code": 200, "data": {"list": items, "total": 371403, "totalPage": 18571}}
    return _Resp()


@pytest.fixture
def fx_lastid_zero():
    """Fixture 2 — checkHasNew N=0 增量空响应。"""
    class _Resp:
        status_code = 200
        def json(self):
            return {"code": 200, "data": 0}
    return _Resp()


@pytest.fixture
def fx_policy_batch():
    """Fixture 3 — 20条分类已知的「政策batch」，用于TC-3 Counter分布断言。"""
    # 与 fx_http_20 同步的预期分布（20 条 titles 手工编码）：
    #  monetary_policy=2 / crypto_regulation=3 / us_policy=2 / us_data=2 /
    #  geopolitics=3 / security_incident=2 / project_ecosystem=2 / market_sentiment=4
    return {
        "total": 20,
        "event_types": {
            "monetary_policy": 2,
            "crypto_regulation": 3,
            "us_policy": 2,
            "us_data": 2,
            "geopolitics": 3,
            "security_incident": 2,
            "project_ecosystem": 2,
            "market_sentiment": 4,
        },
        "important_count": 6,
    }


@pytest.fixture
def fx_session_timeout(monkeypatch):
    """Fixture 4 — Session monkeypatch，所有 GET 抛 Timeout。"""
    from requests.exceptions import Timeout  # noqa: F401

    class _TimeoutSession:
        def get(self, *a, **kw):
            from requests.exceptions import Timeout as _T
            raise _T("simulated timeout")
    return _TimeoutSession()


@pytest.fixture
def fx_import_error_sentiment(monkeypatch):
    """Fixture 5 — ImportError monkeypatch：sentiment_engine 缺失。"""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        # 拦截 9基本面 sentiment_engine 真实 import 路径
        if "sentiment_engine" in name:
            raise ImportError(f"No module named {name!r} (test stub)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    return fake_import


# ============================================================
# 辅助：动态 import collector（RED 阶段会抛 ImportError=正确的失败）
# ============================================================
def _get_collector_cls():
    import importlib
    mod = importlib.import_module(COLLECTOR_MOD)
    return mod.OdailyNewsflashCollector


# ============================================================
# T08 TC-1 正常 20 条 contract 验证 + 7 metrics 范围
# ============================================================
def test_tc1_normal_20_records_contract_and_metrics_ranges(mocker, fx_http_20):
    """TC-1 RED 验证目标：
    1. 返回 20 条 DataRecord；validate_record 全部通过
    2. source=odaily_newsflash category=news sub_category=newsflash_<id>
    3. 7 metrics 齐全，类型/范围符合 Spec §4.3：
       od_source_id(int) / od_policy_sentiment_0_1(float ∈[0,1]) /
       od_event_type(str 7枚举) / od_attention_type(str 5枚举) /
       od_is_important(str 'true'|'false') / od_decay_hl_hrs(int ∈{24,48,72,6}) /
       od_title_hash(str 8位 md5前缀)
    4. timestamp 合法 ISO8601（contract 强制）
    """
    # RED 阶段：collector 不存在 → import 失败 = "正确的红"
    # GREEN 阶段：mocker.patch requests.get 返回 fx_http_20
    mock_req = mocker.patch(REQ_MOD)
    mock_req.get.return_value = fx_http_20

    cls = _get_collector_cls()
    c = cls()
    recs = c.fetch({"route": "latest"})

    assert isinstance(recs, list), "fetch 必须返回 list"
    assert len(recs) == 20, f"首屏应=20条，实得 {len(recs)}"

    sent_values, event_types, decay_hrs, importance = [], [], [], []
    for rec in recs:
        assert isinstance(rec, DataRecord)
        validate_record(rec)  # 硬契约
        assert rec.source == "odaily_newsflash"
        assert rec.category == "news"
        assert rec.sub_category.startswith("newsflash_"), "sub_category = newsflash_<od_id>"
        m = rec.metrics
        # 7 字段齐全
        for k in ("od_source_id", "od_policy_sentiment_0_1", "od_event_type",
                  "od_attention_type", "od_is_important", "od_decay_hl_hrs", "od_title_hash"):
            assert k in m, f"metrics 缺失字段 {k!r}"
        # 类型/范围
        assert isinstance(m["od_source_id"], int), f"od_source_id 非 int: {type(m['od_source_id'])}"
        s = m["od_policy_sentiment_0_1"]
        assert isinstance(s, float) and 0.0 <= s <= 1.0, f"sentiment ∉[0,1]: {s!r}"
        assert m["od_event_type"] in {"monetary_policy", "crypto_regulation", "us_policy",
                                      "us_data", "geopolitics", "security_incident",
                                      "project_ecosystem", "market_sentiment"}
        assert m["od_attention_type"] in {"policy_easing", "policy_tightening",
                                          "market_risk_on", "market_risk_off", "neutral"}
        assert m["od_is_important"] in ("true", "false"), "bool 必须转 true/false 字符串"
        assert isinstance(m["od_decay_hl_hrs"], int) and m["od_decay_hl_hrs"] in {6, 24, 48, 72}
        assert isinstance(m["od_title_hash"], str) and len(m["od_title_hash"]) == 8

        sent_values.append(s)
        event_types.append(m["od_event_type"])
        decay_hrs.append(m["od_decay_hl_hrs"])
        importance.append(m["od_is_important"])

    # 7 metrics 统计范围合理（20条不全相等 → 算法在工作）
    assert len(set(event_types)) >= 5, f"事件类型覆盖应≥5，实际={len(set(event_types))}"
    assert sum(1 for v in sent_values if v != 0.5) >= 3, "sentiment 应有≥3条非中性（算法生效）"
    # decay 分布：政策类(monetary/crypto_reg)=72h, 安全/项目=24h, geo=48h, 市场数据=6h, us_data类偏6h
    # 至少应有≥1 条 72h 和 ≥1 条 24h
    assert 72 in decay_hrs, "政策类 decay=72h 至少应有 1 条"
    assert 24 in decay_hrs, "项目/安全 decay=24h 至少应有 1 条"
    assert "true" in importance, "重要标记 true 应有 1 条以上"


# ============================================================
# T09 TC-2 lastId=0 增量 checkHasNew → 空 list
# ============================================================
def test_tc2_incremental_lastid_zero_returns_empty(mocker, fx_lastid_zero):
    """TC-2: 采集器先请求 /newsflash/checkHasNew?lastId=<max_id>，若 N=0 直接返回 []。"""
    mock_req = mocker.patch(REQ_MOD)
    # 顺序调用：先 checkHasNew（返回0→不调page）
    mock_req.get.return_value = fx_lastid_zero
    cls = _get_collector_cls()
    c = cls()
    # 传入 last_id 非 None → 进入增量模式
    recs = c.fetch({"route": "latest", "last_id": 5_137_020})
    assert recs == [], "N=0 时必须空 list，不继续拉 page"
    # 断言只调了一次（只调了 checkHasNew 没调 page）
    assert mock_req.get.call_count == 1


# ============================================================
# T10 TC-3 event_type 分布 Counter 与关键词匹配数一致
# ============================================================
def test_tc3_event_type_distribution_counter_match(mocker, fx_http_20, fx_policy_batch):
    """TC-3: 14 关键词 + 7 类 regex → Counter 与 fixture 编码吻合。"""
    mock_req = mocker.patch(REQ_MOD)
    mock_req.get.return_value = fx_http_20
    cls = _get_collector_cls()
    c = cls()
    recs = c.fetch({"route": "latest"})
    from collections import Counter
    actual = Counter(r.metrics["od_event_type"] for r in recs)
    expected = fx_policy_batch["event_types"]
    # 7 大类逐项匹配；允许 ±1 的容忍（关键词边界）
    for k, exp in expected.items():
        got = actual.get(k, 0)
        assert abs(got - exp) <= 1, (
            f"event_type[{k}] mismatch: expected≈{exp} actual={got}\n"
            f"全量 Counter: {dict(actual)}"
        )


# ============================================================
# T11 TC-4 网络 Timeout → [] 不抛
# ============================================================
def test_tc4_network_timeout_returns_empty_no_raise(mocker, fx_session_timeout):
    """TC-4: 网络层 Timeout 必须静默回退 []，不抛到上层。"""
    mock_req = mocker.patch(REQ_MOD)
    from requests.exceptions import Timeout as _T
    mock_req.get.side_effect = _T("connect timeout")
    cls = _get_collector_cls()
    c = cls()
    try:
        recs = c.fetch({"route": "latest"})
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"FAIL-OPEN L1 违规：Timeout 抛到上层: {type(e).__name__}: {e}")
    assert recs == []


# ============================================================
# T12 TC-5 ImportError sentiment_engine 缺失 → sentiment=0.5 中性全行
# ============================================================
def test_tc5_import_error_sentiment_neutral_half(mocker, fx_http_20, fx_import_error_sentiment):
    """TC-5: lazy import sentiment_engine 失败时，所有 od_policy_sentiment_0_1=0.5。"""
    mock_req = mocker.patch(REQ_MOD)
    mock_req.get.return_value = fx_http_20
    cls = _get_collector_cls()
    c = cls()
    recs = c.fetch({"route": "latest"})
    assert len(recs) == 20, "sentiment 缺失不应影响采集条数"
    for r in recs:
        s = r.metrics["od_policy_sentiment_0_1"]
        assert s == 0.5, f"FAIL-OPEN L2 违规：sentiment={s!r} 非中性 0.5"
