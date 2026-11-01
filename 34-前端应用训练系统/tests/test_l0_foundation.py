# -*- coding: utf-8 -*-
"""P1: L0 数据访问抽象层（L0Foundation / fetchContext）测试。

依据: `L0-接口规范-fetchContext.md` v0.1 + `PLAN-L0L1L2-implementation.md` P1。
RED 阶段：core/l0_foundation.py 不存在 → ModuleNotFoundError。
GREEN 阶段：实现 10 scope 注册表 + 统一信封 {ok,data,source,timestamp,degraded,meta}
+ FAIL-OPEN（任何数据源不可用只降级，绝不抛错）。

测试全部使用 tmp_path 构造假项目根，不依赖真实子系统数据、不发起真实网络请求。
"""

import json
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# 18 中心已迁移 PostgreSQL，测试需 mock 39 模块统一 PG 辅助模块
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "39-金融语义蒸馏系统", "scripts")
)


ENVELOPE_KEYS = {"ok", "data", "source", "timestamp", "degraded", "meta"}


def _make_l0(tmp_path):
    from core.l0_foundation import L0Foundation

    return L0Foundation(root=str(tmp_path))


def _write(tmp_path, *parts, content=""):
    p = tmp_path.joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ============================================================
# 1. 模块导入
# ============================================================


class TestModuleImport:
    def test_import_l0_foundation(self):
        from core.l0_foundation import L0Foundation

        assert callable(L0Foundation)

    def test_import_get_l0_singleton(self):
        from core.l0_foundation import get_l0

        l0_a = get_l0()
        l0_b = get_l0()
        assert l0_a is l0_b
        assert hasattr(l0_a, "fetch_context")
        assert hasattr(l0_a, "settle")

    def test_scope_registry_has_ten_scopes(self):
        from core.l0_foundation import L0Foundation

        l0 = L0Foundation(root="/nonexistent-root-for-test")
        for scope in (
            "datacenter.record",
            "evolution.contradiction",
            "evolution.snapshot",
            "yijing.bcrm2",
            "yijing.bdsm",
            "yijing.strategic",
            "event.state",
            "riskcontrol.trailing",
            "market.ticker",
            "cognitive.recall",
        ):
            assert scope in l0.list_scopes()


# ============================================================
# 2. 信封契约 + FAIL-OPEN
# ============================================================


class TestEnvelopeContract:
    def test_unknown_scope_degrades_not_raises(self, tmp_path):
        l0 = _make_l0(tmp_path)
        env = l0.fetch_context("not.a.scope")
        assert env.keys() == ENVELOPE_KEYS
        assert env["ok"] is False
        assert env["degraded"] is True
        assert env["data"] is None
        assert env["meta"].get("reason") == "unknown_scope"
        assert isinstance(env["timestamp"], str) and env["timestamp"]

    def test_fetcher_exception_is_caught(self, tmp_path, monkeypatch):
        l0 = _make_l0(tmp_path)

        def _boom(params):
            raise RuntimeError("disk on fire")

        monkeypatch.setattr(l0, "_fetch_datacenter_record", _boom)
        env = l0.fetch_context("datacenter.record", {"source": "fred"})
        assert env["degraded"] is True
        assert env["ok"] is False
        assert env["meta"].get("reason") == "fetch_error"
        assert "disk on fire" in env["meta"].get("error", "")

    def test_params_default_empty_dict(self, tmp_path):
        l0 = _make_l0(tmp_path)
        # cognitive.recall 缺参 → invalid_params 降级而非抛错
        env = l0.fetch_context("cognitive.recall")
        assert env["degraded"] is True


# ============================================================
# 3. datacenter.record（18 中心 PostgreSQL，经 dc_pg 查询）
# ============================================================


class TestDatacenterRecord:
    """mock dc_pg.fetch_latest_by_source，不依赖真实 PostgreSQL。"""

    def _patch_dc_pg(self, monkeypatch, fetch):
        """G0-3 后 dc_pg 按文件路径延迟加载，须替换 _load_dc_pg 而非 sys.modules 里的 dc_pg。"""
        import core.l0_foundation as l0_mod

        monkeypatch.setattr(
            l0_mod,
            "_load_dc_pg",
            lambda: types.SimpleNamespace(fetch_latest_by_source=fetch),
        )

    def _mock_rows(self, monkeypatch, rows):
        def _fake_fetch(source, sub_category=None):
            for r in rows:
                if r["source"] == source and (
                    sub_category is None or r.get("sub_category") == sub_category
                ):
                    return r
            return None

        self._patch_dc_pg(monkeypatch, _fake_fetch)

    def test_returns_latest_row_with_parsed_metrics(self, tmp_path, monkeypatch):
        self._mock_rows(
            monkeypatch,
            [
                {
                    "source": "fred",
                    "category": "macro",
                    "sub_category": "cpi",
                    "timestamp": "2026-10-16T00:00:00",
                    "metrics": {"cpi": 3.1},
                },
            ],
        )
        env = _make_l0(tmp_path).fetch_context("datacenter.record", {"source": "fred"})
        assert env["ok"] is True and env["degraded"] is False
        d = env["data"]
        assert d["source"] == "fred"
        assert d["timestamp"] == "2026-10-16T00:00:00"
        assert d["metrics"] == {"cpi": 3.1}

    def test_missing_param_source_degrades(self, tmp_path):
        env = _make_l0(tmp_path).fetch_context("datacenter.record", {})
        assert env["degraded"] is True
        assert env["meta"]["reason"] == "invalid_params"

    def test_pg_unreachable_returns_none_not_degraded(self, tmp_path, monkeypatch):
        # FAIL-OPEN：PostgreSQL 不可达 → dc_pg 返回 None → 空数据信封，不降级
        self._patch_dc_pg(monkeypatch, lambda s, sub_category=None: None)
        env = _make_l0(tmp_path).fetch_context("datacenter.record", {"source": "fred"})
        assert env["degraded"] is False
        assert env["data"] is None

    def test_no_matching_row_returns_none(self, tmp_path, monkeypatch):
        self._mock_rows(
            monkeypatch,
            [
                {
                    "source": "fred",
                    "category": "macro",
                    "sub_category": "cpi",
                    "timestamp": "2026-10-16",
                    "metrics": {"cpi": 3.1},
                },
            ],
        )
        env = _make_l0(tmp_path).fetch_context("datacenter.record", {"source": "coinglass"})
        assert env["degraded"] is False
        assert env["data"] is None

    def test_raw_string_metrics_passthrough(self, tmp_path, monkeypatch):
        # dc_pg 对无法解析的 metrics 字符串原样透传
        self._mock_rows(
            monkeypatch,
            [
                {
                    "source": "fred",
                    "category": "macro",
                    "sub_category": "cpi",
                    "timestamp": "2026-10-16",
                    "metrics": "not-json",
                },
            ],
        )
        env = _make_l0(tmp_path).fetch_context("datacenter.record", {"source": "fred"})
        assert env["data"]["metrics"] == "not-json"


# ============================================================
# 4. evolution.contradiction（23 系统矛盾日志）
# ============================================================


class TestEvolutionContradiction:
    LOG_REL = (
        "23-四层闭环自进化交易架构",
        "dreambuddy_evolution",
        "logs",
        "evolution_pipeline.log",
    )

    def test_parses_dimensions_last_occurrence_wins(self, tmp_path):
        _write(
            tmp_path,
            *self.LOG_REL,
            content=(
                "noise line\n"
                "2026-10-16 [Contradiction] dim=C1 dir=long strength=0.50 extra\n"
                "2026-10-16 [Contradiction] dim=C2 dir=short strength=0.80\n"
                "2026-10-16 [Contradiction] dim=C1 dir=neutral strength=0.72\n"
            ),
        )
        env = _make_l0(tmp_path).fetch_context("evolution.contradiction")
        assert env["degraded"] is False
        dims = env["data"]["dims"]
        assert dims["C1"] == {"direction": "neutral", "strength": 0.72}
        assert dims["C2"] == {"direction": "short", "strength": 0.80}

    def test_missing_log_degrades(self, tmp_path):
        env = _make_l0(tmp_path).fetch_context("evolution.contradiction")
        assert env["degraded"] is True
        assert env["meta"]["reason"] == "source_missing"

    def test_no_dimensions_returns_none(self, tmp_path):
        _write(tmp_path, *self.LOG_REL, content="pipeline started\nall good\n")
        env = _make_l0(tmp_path).fetch_context("evolution.contradiction")
        assert env["degraded"] is False
        assert env["data"] is None


# ============================================================
# 5. evolution.snapshot（23 系统快照 JSON）
# ============================================================


class TestEvolutionSnapshot:
    SNAP_REL = (
        "23-四层闭环自进化交易架构",
        "dreambuddy_evolution",
        "gene_data",
        "evolution_snapshots.json",
    )

    def test_returns_snapshot_dict(self, tmp_path):
        snap = {"BTC": {"dimension_predictions": {"C1": "long"}, "action": "long"}}
        _write(tmp_path, *self.SNAP_REL, content=json.dumps(snap))
        env = _make_l0(tmp_path).fetch_context("evolution.snapshot")
        assert env["degraded"] is False
        assert env["data"]["BTC"]["action"] == "long"

    def test_empty_snapshot_returns_none(self, tmp_path):
        _write(tmp_path, *self.SNAP_REL, content="{}")
        env = _make_l0(tmp_path).fetch_context("evolution.snapshot")
        assert env["degraded"] is False
        assert env["data"] is None

    def test_missing_file_degrades(self, tmp_path):
        env = _make_l0(tmp_path).fetch_context("evolution.snapshot")
        assert env["meta"]["reason"] == "source_missing"

    def test_broken_json_degrades(self, tmp_path):
        _write(tmp_path, *self.SNAP_REL, content="{broken")
        env = _make_l0(tmp_path).fetch_context("evolution.snapshot")
        assert env["degraded"] is True
        assert env["meta"]["reason"] == "read_error"


# ============================================================
# 6. yijing.bcrm2（11 系统 BCRM2 小时汇总）
# ============================================================


class TestBcrm2:
    PATH_REL = ("11-易经推理系统", "data", "bcrm2", "bcrm2_hourly_summary.json")

    def test_returns_results_map(self, tmp_path):
        d = {"results": {"BTC": {"direction": "UP", "confidence": 0.71, "hexagram": "乾为天"}}}
        _write(tmp_path, *self.PATH_REL, content=json.dumps(d))
        env = _make_l0(tmp_path).fetch_context("yijing.bcrm2")
        assert env["data"]["BTC"]["direction"] == "UP"

    def test_empty_results_returns_none(self, tmp_path):
        _write(tmp_path, *self.PATH_REL, content=json.dumps({"results": {}}))
        env = _make_l0(tmp_path).fetch_context("yijing.bcrm2")
        assert env["data"] is None
        assert env["degraded"] is False

    def test_missing_file_degrades(self, tmp_path):
        env = _make_l0(tmp_path).fetch_context("yijing.bcrm2")
        assert env["meta"]["reason"] == "source_missing"


# ============================================================
# 7. yijing.bdsm（11 系统 BDSM 快照，glob 最新）
# ============================================================


class TestBdsm:
    DIR_REL = ("11-易经推理系统", ".workbuddy", "bdsm")

    def test_returns_newest_snapshot(self, tmp_path):
        d = tmp_path.joinpath(*self.DIR_REL)
        d.mkdir(parents=True)
        (d / "bdsm_snapshot_20261015.json").write_text(
            json.dumps({"coins": {"BTC": {"available": False, "score": 0.1}}}), encoding="utf-8"
        )
        (d / "bdsm_snapshot_20261016.json").write_text(
            json.dumps(
                {
                    "coins": {
                        "ETH": {
                            "available": True,
                            "score": 0.83,
                            "rank": "A",
                            "phase": "growth",
                            "valuation_percentile": 65,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        env = _make_l0(tmp_path).fetch_context("yijing.bdsm")
        assert env["degraded"] is False
        assert "ETH" in env["data"]["coins"]
        assert "BTC" not in env["data"]["coins"]
        assert env["meta"]["snapshot_file"].endswith("bdsm_snapshot_20261016.json")

    def test_missing_dir_degrades(self, tmp_path):
        env = _make_l0(tmp_path).fetch_context("yijing.bdsm")
        assert env["degraded"] is True
        assert env["meta"]["reason"] == "source_missing"

    def test_no_snapshot_files_returns_none(self, tmp_path):
        tmp_path.joinpath(*self.DIR_REL).mkdir(parents=True)
        env = _make_l0(tmp_path).fetch_context("yijing.bdsm")
        assert env["degraded"] is False
        assert env["data"] is None


# ============================================================
# 8. yijing.strategic（11 系统 polling_trader 战略层影子日志）
# ============================================================


class TestStrategic:
    DIR_REL = ("11-易经推理系统", "data", "polling_trader")

    def test_parses_asset_veto_states(self, tmp_path):
        rec = {
            "msg": "2026 [战略层影子] dimension_veto | crypto_usdt=LONG|us_stock=NEUTRAL|precious_metal=SHORT"
        }
        noise = {"msg": "unrelated line"}
        f = tmp_path.joinpath(*self.DIR_REL, "trader_20261016.jsonl")
        f.parent.mkdir(parents=True)
        f.write_text(
            json.dumps(noise, ensure_ascii=False)
            + "\n"
            + "not-json-line\n"
            + json.dumps(rec, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        env = _make_l0(tmp_path).fetch_context("yijing.strategic")
        assets = env["data"]["assets"]
        assert assets == {"crypto_usdt": "LONG", "us_stock": "NEUTRAL", "precious_metal": "SHORT"}

    def test_missing_dir_degrades(self, tmp_path):
        env = _make_l0(tmp_path).fetch_context("yijing.strategic")
        assert env["meta"]["reason"] == "source_missing"

    def test_no_files_returns_none(self, tmp_path):
        tmp_path.joinpath(*self.DIR_REL).mkdir(parents=True)
        env = _make_l0(tmp_path).fetch_context("yijing.strategic")
        assert env["degraded"] is False
        assert env["data"] is None

    def test_no_veto_records_returns_none(self, tmp_path):
        f = tmp_path.joinpath(*self.DIR_REL, "trader_20261016.jsonl")
        f.parent.mkdir(parents=True)
        f.write_text(json.dumps({"msg": "[战略层影子] something else"}) + "\n", encoding="utf-8")
        env = _make_l0(tmp_path).fetch_context("yijing.strategic")
        assert env["data"] is None


# ============================================================
# 9. event.state（11 系统事件驱动状态）
# ============================================================


class TestEventState:
    PATH_REL = ("11-易经推理系统", "data", "event_driven_state.json")

    def test_returns_state_with_signal(self, tmp_path):
        state = {
            "updated_at": "2026-10-16T10:00:00",
            "signal": {
                "event_type": "fomc",
                "event_phase": "meeting",
                "signal": "neutral",
                "strength": 0.5,
                "confidence": 0.6,
            },
        }
        _write(tmp_path, *self.PATH_REL, content=json.dumps(state))
        env = _make_l0(tmp_path).fetch_context("event.state")
        assert env["data"]["signal"]["event_type"] == "fomc"
        assert env["data"]["updated_at"] == "2026-10-16T10:00:00"

    def test_missing_signal_returns_none(self, tmp_path):
        _write(tmp_path, *self.PATH_REL, content=json.dumps({"updated_at": "x"}))
        env = _make_l0(tmp_path).fetch_context("event.state")
        assert env["data"] is None
        assert env["degraded"] is False

    def test_missing_file_degrades(self, tmp_path):
        env = _make_l0(tmp_path).fetch_context("event.state")
        assert env["meta"]["reason"] == "source_missing"


# ============================================================
# 10. riskcontrol.trailing（16 系统 trailing runner 日志）
# ============================================================


class TestRiskControl:
    DIR_REL = ("16-调控系统", "logs")

    def test_parses_latest_evaluation(self, tmp_path):
        content = (
            "2026 评估完成: 总持仓=2 IDLE=1 ARMED=1 TRIGGERED=0 CLOSED=0 历史触发累计=5\n"
            "2026 评估完成: 总持仓=3 IDLE=0 ARMED=2 TRIGGERED=1 CLOSED=0 历史触发累计=6\n"
        )
        _write(tmp_path, *self.DIR_REL, "trailing_runner_20261016.log", content=content)
        env = _make_l0(tmp_path).fetch_context("riskcontrol.trailing")
        p = env["data"]["positions"]
        assert p == {
            "total": 3,
            "IDLE": 0,
            "ARMED": 2,
            "TRIGGERED": 1,
            "CLOSED": 0,
            "history_triggered": 6,
        }

    def test_missing_dir_degrades(self, tmp_path):
        env = _make_l0(tmp_path).fetch_context("riskcontrol.trailing")
        assert env["meta"]["reason"] == "source_missing"

    def test_no_log_files_returns_none(self, tmp_path):
        tmp_path.joinpath(*self.DIR_REL).mkdir(parents=True)
        env = _make_l0(tmp_path).fetch_context("riskcontrol.trailing")
        assert env["data"] is None
        assert env["degraded"] is False

    def test_no_evaluation_lines_returns_none(self, tmp_path):
        _write(tmp_path, *self.DIR_REL, "trailing_runner_x.log", content="startup\n")
        env = _make_l0(tmp_path).fetch_context("riskcontrol.trailing")
        assert env["data"] is None


# ============================================================
# 11. market.ticker（OKX 公开行情，主备双源）
# ============================================================


class TestMarketTicker:
    def _ticker(self, last="63000", open24h="62000"):
        return {
            "code": "0",
            "data": [{"last": last, "open24h": open24h, "high24h": "64000", "low24h": "61000"}],
        }

    def test_primary_source_success(self, tmp_path, monkeypatch):
        l0 = _make_l0(tmp_path)
        monkeypatch.setattr(l0, "_http_get_json", lambda url, timeout=5: self._ticker())
        env = l0.fetch_context("market.ticker", {"symbol": "BTC"})
        assert env["degraded"] is False
        assert env["data"]["last"] == "63000"
        assert "www.okx.com" in env["source"]
        assert env["meta"]["inst_id"] == "BTC-USDT"

    def test_falls_back_to_backup_source(self, tmp_path, monkeypatch):
        l0 = _make_l0(tmp_path)
        calls = []

        def _fake_http(url, timeout=5):
            calls.append(url)
            if "aws.okx.com" in url:
                return self._ticker()
            raise RuntimeError("primary blocked")

        monkeypatch.setattr(l0, "_http_get_json", _fake_http)
        env = l0.fetch_context("market.ticker", {"symbol": "ETH"})
        assert env["degraded"] is False
        assert env["data"]["last"] == "63000"
        assert "aws.okx.com" in env["source"]
        assert len(calls) == 2

    def test_both_sources_fail_degrades(self, tmp_path, monkeypatch):
        l0 = _make_l0(tmp_path)
        monkeypatch.setattr(
            l0,
            "_http_get_json",
            lambda url, timeout=5: (_ for _ in ()).throw(RuntimeError("net down")),
        )
        env = l0.fetch_context("market.ticker", {"symbol": "BTC"})
        assert env["degraded"] is True
        assert env["data"] is None
        assert env["meta"]["reason"] == "upstream_unavailable"

    def test_symbol_defaults_btc(self, tmp_path, monkeypatch):
        l0 = _make_l0(tmp_path)
        seen = {}

        def _fake_http(url, timeout=5):
            seen["url"] = url
            return self._ticker()

        monkeypatch.setattr(l0, "_http_get_json", _fake_http)
        env = l0.fetch_context("market.ticker")
        assert env["degraded"] is False
        assert "BTC-USDT" in seen["url"]


# ============================================================
# 12. cognitive.recall（4-MEMORY 认知系统，FAIL-OPEN）
# ============================================================


class TestCognitiveRecall:
    def test_returns_memories_from_cle(self, tmp_path, monkeypatch):
        l0 = _make_l0(tmp_path)

        class _FakeCle:
            def recall(self, context, top_k=5, min_quality="C"):
                return [{"score": 0.82, "content": "hit1"}, {"score": 0.5, "content": "hit2"}]

        monkeypatch.setattr(l0, "_load_cle", lambda: _FakeCle())
        env = l0.fetch_context(
            "cognitive.recall", {"context": "L0 测试", "top_k": 3, "min_quality": "C"}
        )
        assert env["degraded"] is False
        assert len(env["data"]) == 2
        assert env["data"][0]["score"] == 0.82

    def test_missing_context_degrades(self, tmp_path):
        env = _make_l0(tmp_path).fetch_context("cognitive.recall", {"top_k": 3})
        assert env["degraded"] is True
        assert env["meta"]["reason"] == "invalid_params"

    def test_cle_unavailable_fail_open(self, tmp_path, monkeypatch):
        l0 = _make_l0(tmp_path)

        def _boom():
            raise RuntimeError("cognitive db locked")

        monkeypatch.setattr(l0, "_load_cle", _boom)
        env = l0.fetch_context("cognitive.recall", {"context": "x"})
        assert env["degraded"] is True
        assert env["data"] == []
        assert env["meta"]["reason"] == "cognitive_unavailable"


# ============================================================
# 13. settle 分流（已落地能力挂到 L0，行为不变，FAIL-OPEN）
# ============================================================


class TestSettle:
    CASE_REL = ("34-前端应用训练系统", "l1_case_store.jsonl")

    def test_success_case_appended(self, tmp_path):
        l0 = _make_l0(tmp_path)
        # 阻断认知 record（不打真实认知库）
        l0._record_cognitive = lambda *a, **k: None
        result = {"success": True, "answer": "ans", "data": {"k": 1}}
        l0.settle(result, {"intent": "data_query", "message": "查 CPI"})
        lines = tmp_path.joinpath(*self.CASE_REL).read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["intent"] == "data_query"
        assert rec["message"] == "查 CPI"

    def test_degraded_case_not_appended(self, tmp_path):
        l0 = _make_l0(tmp_path)
        l0._record_cognitive = lambda *a, **k: None
        result = {"success": True, "degraded": True, "answer": "暂不可用", "data": None}
        l0.settle(result, {"intent": "risk_control", "message": "风控状态"})
        assert not tmp_path.joinpath(*self.CASE_REL).exists()

    def test_settle_never_raises(self, tmp_path, monkeypatch):
        l0 = _make_l0(tmp_path)
        monkeypatch.setattr(
            l0, "_append_case", lambda *a, **k: (_ for _ in ()).throw(OSError("ro fs"))
        )
        # 不抛错即通过
        l0.settle({"success": True, "answer": "a"}, {"intent": "x", "message": "y"})

    # -------- P3-3：45 门禁卡点（可选注入，默认不启用） --------

    def test_gate_allowed_settles(self, tmp_path):
        l0 = _make_l0(tmp_path)
        l0._record_cognitive = lambda *a, **k: None
        seen = []

        def _gate(context):
            seen.append(context)
            return True, {"decision": "PASS"}

        l0.settle({"success": True, "answer": "ans"}, {"intent": "data_query"}, gate=_gate)
        assert len(seen) == 1
        assert tmp_path.joinpath(*self.CASE_REL).exists()

    def test_gate_blocked_skips_settle(self, tmp_path):
        l0 = _make_l0(tmp_path)
        l0._record_cognitive = lambda *a, **k: None
        result = {"success": True, "answer": "ans"}
        l0.settle(result, {"intent": "data_query"}, gate=lambda _c: (False, {"decision": "BLOCK"}))
        assert not tmp_path.joinpath(*self.CASE_REL).exists()

    def test_gate_error_is_fail_closed(self, tmp_path):
        l0 = _make_l0(tmp_path)
        l0._record_cognitive = lambda *a, **k: None

        def _boom(_context):
            raise RuntimeError("gate down")

        l0.settle({"success": True, "answer": "ans"}, {"intent": "data_query"}, gate=_boom)
        assert not tmp_path.joinpath(*self.CASE_REL).exists()
