"""Gap1 Impl-11 TDD：_fetch_news_72h_limit200() 新闻 72h × 200 条 SQLite 真实通路。

Spec: 2026-08-29-gap1-fd7-news-72h-200-design.md
- 函数签名（向后兼容扩展）：_fetch_news_72h_limit200(self, db_path: Optional[str] = None) -> List[Dict]
- news_list[dict] 8 字段：6 必填（source/sub_category/title/content/timestamp_ms/category）+ 2 可选 topic/url
- 三层 FAIL-OPEN：外套 try/except（已存在）/ 中套 SQLite 异常 / 内套单条解析 continue
- 顺序：SQL WHERE category='news' ORDER BY id DESC LIMIT 400 → Python 72h 过滤 → 按 timestamp_ms DESC → [0:200]
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

THIS_DIR = Path(__file__).resolve().parent
_REPO = THIS_DIR.parent                                    # 11-易经推理系统/
_COMPUTER_ROOT = _REPO / "scripts" / "memory_l4"
_FUND_ROOT = Path(__file__).resolve().parents[1].parent / "9-基本面分析"
_FUND_ENGINES = _FUND_ROOT / "engines"

if str(_COMPUTER_ROOT) not in sys.path:
    sys.path.insert(0, str(_COMPUTER_ROOT))
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
if str(_FUND_ENGINES) not in sys.path:
    sys.path.insert(0, str(_FUND_ENGINES))


# ============================================================
# Helpers
# ============================================================
def _get_computer_cls():
    from five_domain_feature_computer import FiveDomainFeatureComputer
    return FiveDomainFeatureComputer


RECORDS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    category TEXT NOT NULL,
    sub_category TEXT,
    timestamp TEXT,
    metrics TEXT,
    events TEXT,
    timeseries TEXT,
    raw TEXT,
    schema_version TEXT DEFAULT '1.0'
);
"""


def _tmp_records_db(tmp_path: Path, seed_rows: List[Dict[str, Any]]) -> Path:
    """Helper：在 tmp_path 下创建临时 SQLite，写入 records 表 seed_rows（按字段对齐）。返回 db 路径。"""
    db_path = tmp_path / "dc_seed.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(RECORDS_SCHEMA_SQL)
        # seed_rows: 每一项含 source/category/sub_category/timestamp(int秒或ISO字符串)/metrics(dict|str)/events(dict|str)/timeseries(dict|str)/raw(dict|str)
        fields = ["source", "category", "sub_category", "timestamp", "metrics", "events", "timeseries", "raw", "schema_version"]
        defaults = {"events": "{}", "timeseries": "{}", "raw": "{}", "schema_version": "1.0"}
        sql = f"INSERT INTO records ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})"
        for i, row in enumerate(seed_rows, start=1):
            vals = []
            for f in fields:
                v = row.get(f, defaults.get(f, ""))
                if isinstance(v, dict):
                    vals.append(json.dumps(v, ensure_ascii=False))
                else:
                    vals.append(str(v) if v is not None else "")
            conn.execute(sql, vals)
        conn.commit()
    finally:
        conn.close()
    return db_path


# ============================================================
# TC-3（第一个能真正 RED FAIL 的最小用例）：主路径 1 条 72h 内 odaily 有效新闻 → len=1 + 字段校验
# ============================================================
class TestTC3MainPathOneValidOdaily:
    def test_tc3_len_1_6_fields_nonempty_ts_mapping(self, tmp_path):
        """主路径：插入1条 odaily_newsflash → 断言 6 字段非空 + topic/url 映射 + timestamp_ms 差<1000ms。"""
        now_s = int(time.time())
        metrics = {"title": "BTC突破10万美元", "topic": "BTC行情", "url": "https://odaily.news/btc-100k"}
        raw = {"publishTimestamp": now_s * 1000, "content": "比特币价格突破100000美元整数关口，市场情绪高涨。",
               "topic": metrics["topic"], "url": metrics["url"]}
        db_path = _tmp_records_db(tmp_path, [
            {"id": 1, "source": "odaily_newsflash", "category": "news", "sub_category": "spot",
             "timestamp": now_s, "metrics": metrics, "raw": raw}
        ])
        Cls = _get_computer_cls()
        c = Cls()
        res = c._fetch_news_72h_limit200(db_path=str(db_path))
        assert isinstance(res, list), "返回值必须是 list"
        assert len(res) == 1, f"预期1条，实际{len(res)}条（空壳返回len=0则说明SQL未实现）"
        one = res[0]
        # 6 必填字段非空
        for f in ["source", "sub_category", "title", "content", "timestamp_ms", "category"]:
            v = one.get(f)
            assert v is not None and (isinstance(v, str) and len(v) > 0 or isinstance(v, (int, float))), \
                f"必填字段 {f} 为空或缺失：{repr(v)}"
        # timestamp_ms 与 expected 差 < 1000ms
        assert abs(one["timestamp_ms"] - now_s * 1000) < 1000, \
            f"timestamp_ms 解析偏差：预期{now_s*1000} 实际{one['timestamp_ms']}"
        # 字段映射：title=metrics.title，topic/url 从 raw（或 metrics）带入
        assert one["title"] == metrics["title"], f"title 映射错：{one['title']} vs {metrics['title']}"
        # topic/url 可选字段
        assert one.get("topic") == raw["topic"], f"topic 映射错"
        assert one.get("url") == raw["url"], f"url 映射错"


# ============================================================
# TC-1：DB 不存在 → 返回 len=0（FAIL-OPEN 外套 2 层）
# ============================================================
class TestTC1DbNotExistReturnEmpty:
    def test_tc1_not_exist_len_0(self):
        """不存在路径 → 返回空 list（外套中隔离生效）。"""
        Cls = _get_computer_cls()
        c = Cls()
        res = c._fetch_news_72h_limit200(db_path="/tmp/__gap1_not_exist_xyz_999.db")
        assert isinstance(res, list) and len(res) == 0


# ============================================================
# TC-2：category 过滤（3 条 chain/market/regime 全非 news → len=0）
# ============================================================
class TestTC2CategoryFilter:
    def test_tc2_chain_category_returns_zero(self, tmp_path):
        """WHERE category='news' 应过滤掉 chain/market/regime 三类。"""
        now_s = int(time.time())
        rows = []
        for i, cat in enumerate(["chain", "market", "regime"]):
            rows.append({"source": f"s{i}", "category": cat, "sub_category": "x",
                         "timestamp": now_s - i, "metrics": {"title": f"t{i}"},
                         "raw": {"publishTimestamp": (now_s - i) * 1000, "content": f"c{i}"}})
        db_path = _tmp_records_db(tmp_path, rows)
        Cls = _get_computer_cls()
        c = Cls()
        res = c._fetch_news_72h_limit200(db_path=str(db_path))
        assert len(res) == 0, f"3条非news category应过滤为0，实际{len(res)}条: {res}"


# ============================================================
# TC-4：2 条（now-1h / now-80h）→ len=1（now-80h 超72h 过滤掉）
# ============================================================
class TestTC472hBoundaryFilter:
    def test_tc4_out_of_range_filtered(self, tmp_path):
        now_s = int(time.time())
        good_s = now_s - 3600          # now-1h 有效
        bad_s = now_s - 80 * 3600      # now-80h 超期
        rows = [
            {"source": "odaily", "category": "news", "sub_category": "1h",
             "timestamp": good_s, "metrics": {"title": "good"},
             "raw": {"publishTimestamp": good_s * 1000, "content": "good1h"}},
            {"source": "odaily", "category": "news", "sub_category": "80h",
             "timestamp": bad_s, "metrics": {"title": "bad"},
             "raw": {"publishTimestamp": bad_s * 1000, "content": "bad80h"}},
        ]
        db_path = _tmp_records_db(tmp_path, rows)
        Cls = _get_computer_cls()
        c = Cls()
        res = c._fetch_news_72h_limit200(db_path=str(db_path))
        assert len(res) == 1, f"1条有效1条超期 → len=1，实际{len(res)}条: {res}"
        assert res[0]["sub_category"] == "1h", f"应保留1h那条，实际sub_category={res[0].get('sub_category')}"


# ============================================================
# TC-5：timestamp 解析失败 + publishTimestamp 缺失 → 保留 timestamp_ms=0 不丢
# ============================================================
class TestTC5TimestampParseFailOpen:
    def test_tc5_ts_bad_and_pub_missing_kept_ts0(self, tmp_path):
        rows = [{
            "source": "odaily", "category": "news", "sub_category": "ts_bad",
            "timestamp": "@@不是ISO_@@坏字符串",
            "metrics": {"title": "有标题保留", "topic": "X"},
            "raw": {"content": "有内容保留，publishTimestamp 缺失"},
        }]
        db_path = _tmp_records_db(tmp_path, rows)
        Cls = _get_computer_cls()
        c = Cls()
        res = c._fetch_news_72h_limit200(db_path=str(db_path))
        assert len(res) == 1, f"解析失败应保留=0，实际丢弃为len=0/多条"
        assert res[0]["timestamp_ms"] == 0, f"解析失败 timestamp_ms 应为 0，实际{res[0]['timestamp_ms']}"
        # title/content 仍正常非空
        assert len(res[0]["title"]) > 0 and len(res[0]["content"]) > 0


# ============================================================
# TC-6：250 条全 72h 内 → 截断 200 + 排序 DESC（id=250 最新在第 0 位）
# ============================================================
class TestTC6Limit200OrderDesc:
    def test_tc6_250news_truncated_to_200_latest_id_first(self, tmp_path):
        now_s = int(time.time())
        rows = []
        for i in range(1, 251):                         # id=1(oldest) → id=250(newest)
            ts = now_s - 10 * (250 - i)                  # 跨度仅 2490 秒 = 41 分钟（全在 72h 内）
            rows.append({"source": "s", "category": "news", "sub_category": str(i),
                         "timestamp": ts, "metrics": {"title": f"t{i}"},
                         "raw": {"publishTimestamp": ts * 1000, "content": f"c{i}"}})
        db_path = _tmp_records_db(tmp_path, rows)
        Cls = _get_computer_cls()
        c = Cls()
        res = c._fetch_news_72h_limit200(db_path=str(db_path))
        assert len(res) == 200, f"250条72h内应截断到200，实际{len(res)}"
        assert res[0]["timestamp_ms"] > res[-1]["timestamp_ms"], f"必须按timestamp DESC排序"
        assert res[0]["sub_category"] == "250", f"id=250 最新应在第0位，实际sub_category={res[0].get('sub_category')}"


# ============================================================
# TC-7：400 条（200 条 now-1h + 200 条 now-100h 超期）→ 正好 200 条有效 + 每条≥cutoff_ms
# ============================================================
class TestTC7BigBatch72hFilter:
    def test_tc7_400rows_200outdated_truncated_to_200_valid(self, tmp_path):
        now_s = int(time.time())
        rows = []
        good_base = now_s - 3600
        bad_base = now_s - 100 * 3600
        for i in range(200):
            ts_g = good_base - i
            rows.append({"source": "g", "category": "news", "sub_category": f"g{i}",
                         "timestamp": ts_g, "metrics": {"title": f"g{i}"},
                         "raw": {"publishTimestamp": ts_g * 1000, "content": f"gc{i}"}})
        for i in range(200):
            ts_b = bad_base - i
            rows.append({"source": "b", "category": "news", "sub_category": f"b{i}",
                         "timestamp": ts_b, "metrics": {"title": f"b{i}"},
                         "raw": {"publishTimestamp": ts_b * 1000, "content": f"bc{i}"}})
        db_path = _tmp_records_db(tmp_path, rows)
        Cls = _get_computer_cls()
        c = Cls()
        res = c._fetch_news_72h_limit200(db_path=str(db_path))
        assert len(res) == 200, f"200条有效200条超期 → len=200，实际{len(res)}"
        cutoff_ms = (int(time.time()) - 72 * 3600) * 1000
        for item in res:
            assert item["timestamp_ms"] >= cutoff_ms, f"超期未过滤: ts={item['timestamp_ms']} < cutoff={cutoff_ms}"
            assert item["sub_category"].startswith("g"), f"混入超期b条: {item['sub_category']}"


# ============================================================
# TC-8：2 条（1 正常 + 1 条 metrics 纯坏 JSON 字符串）→ len=1（内套跳过坏的，好的保留）
# ============================================================
class TestTC8BadJsonSingleSkip:
    def test_tc8_bad_metrics_json_skipped_good_kept(self, tmp_path):
        now_s = int(time.time())
        db_path = tmp_path / "tc8_bad.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(RECORDS_SCHEMA_SQL)
        # 正常一条
        conn.execute(
            "INSERT INTO records (source,category,sub_category,timestamp,metrics,events,timeseries,raw,schema_version) VALUES (?,?,?,?,?,?,?,?,?)",
            ("good_src", "news", "good", str(now_s), json.dumps({"title": "goodt"}),
             "{}", "{}", json.dumps({"publishTimestamp": now_s*1000, "content": "goodc"}), "1.0")
        )
        # 坏 metrics 一条（直接写入纯坏 JSON 字符串到 metrics 列）
        conn.execute(
            "INSERT INTO records (source,category,sub_category,timestamp,metrics,events,timeseries,raw,schema_version) VALUES (?,?,?,?,?,?,?,?,?)",
            ("bad_src", "news", "bad", str(now_s), "}{bad{{json{{{",
             "{}", "{}", json.dumps({"publishTimestamp": now_s*1000, "content": "badc"}), "1.0")
        )
        conn.commit(); conn.close()
        Cls = _get_computer_cls()
        c = Cls()
        res = c._fetch_news_72h_limit200(db_path=str(db_path))
        assert len(res) == 1, f"坏JSON1条被跳过 → len=1，实际{len(res)}: {res}"
        assert res[0]["sub_category"] == "good", f"保留应是good那条，实际sub_category={res[0].get('sub_category')}"


# ============================================================
# TC-9（集成打通验收）：monkeypatch news_list=5条正负 → _fd_S_dao_boost != 0 且 abs ≤ 0.10
# ============================================================
class TestTC9IntegrationSDaoBoostNonZero:
    def test_tc9_s_dao_boost_nonzero_and_clamp_le_010(self, monkeypatch):
        """S级 5 delta 中至少 S1 Sentiment 消费 news_list title/content 聚合出非 0 sent_mean。"""
        ts_ms = int(time.time() * 1000)
        fake_news = [
            {"source":"odaily","category":"news","sub_category":"s","title":"美联储官宣降息25bp",
             "content":"美联储FOMC会议宣布降息25个基点，市场风险偏好上行。","timestamp_ms":ts_ms},
            {"source":"odaily","category":"news","sub_category":"s","title":"贝莱德现货ETF获通过",
             "content":"美国SEC正式批准贝莱德比特币现货ETF上市，机构资金加速入场。","timestamp_ms":ts_ms-1000},
            {"source":"odaily","category":"news","sub_category":"s","title":"各国央行增持黄金和BTC储备",
             "content":"多国央行宣布将BTC纳入储备资产，长期叙事偏多。","timestamp_ms":ts_ms-2000},
            {"source":"odaily","category":"news","sub_category":"s","title":"SEC起诉Binance内幕交易",
             "content":"SEC对Binance发起内幕交易诉讼，Binance US业务或暂停。","timestamp_ms":ts_ms-3000},
            {"source":"odaily","category":"news","sub_category":"s","title":"FTX清算抛售5亿BTC",
             "content":"FTX破产受托人出售5亿美元BTC和ETH，短期抛压显著。","timestamp_ms":ts_ms-4000},
        ]
        def _stub(*a, **kw):
            return list(fake_news)
        Cls = _get_computer_cls()
        c = Cls()
        monkeypatch.setattr(c, "_fetch_news_72h_limit200", _stub)
        v = c._fd_S_dao_boost(coin_data={})
        assert isinstance(v, float), f"S_dao_boost 应是 float，实际{type(v)}"
        assert v != 0.0, (
            f"新闻通路未打通！S_dao_boost=0 说明 S级 5 delta 全部返回0，"
            f"检查 S1 Sentiment 聚合是否消费 news_list title/content。"
        )
        assert abs(v) <= 0.10, f"S级 clamp ±0.10 越界: v={v}"
