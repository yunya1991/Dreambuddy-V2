# -*- coding: utf-8 -*-
"""BDSM Phase 0 单元测试 — 常量定义 + 快照生成 + FAIL-OPEN.

TDD RED → GREEN 循环：
  1. 测试失败（常量不存在/快照未实现）
  2. 写最小代码让其通过
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
# tests/ → 11-易经推理系统/ → scripts/memory_l4/force_vector
_FORCE_VEC_DIR = os.path.normpath(os.path.join(_THIS_DIR, "..", "scripts", "memory_l4", "force_vector"))
if _FORCE_VEC_DIR not in sys.path:
    sys.path.insert(0, _FORCE_VEC_DIR)


class TestBDSMCoins(unittest.TestCase):
    """S2: BDSM_COINS 常量定义（R4 落地）。

    权威池 = {UNI, PUMP, HYPE, AAVE, SOL, CRCL, ETH, BTC} — 8 币
    SKY 暂移除（见 Spec §12）。
    """

    def test_bdsm_coins_exists_and_contains_exact_10_coins(self) -> None:
        """RED: 先跑这个，import 失败证明常量没定义。BTC 于 L1 代理信号就绪后纳入；2026-09-06 新增 ZEC/ARB。"""
        from coin_fundamental_ranker import BDSM_COINS  # noqa: WPS433
        expected = {"UNI", "PUMP", "HYPE", "AAVE", "SOL", "CRCL", "ETH", "BTC", "ZEC", "ARB"}
        self.assertEqual(BDSM_COINS, expected,
                         f"BDSM_COINS 应为 {expected}，实际 {BDSM_COINS}")
        # 附加约束：SKY 不在权威池
        self.assertNotIn("SKY", BDSM_COINS, "SKY 已从 BDSM 权威池移除，不应再包含")

    def test_bdsm_coins_is_frozenset(self) -> None:
        """外部不应能直接修改常量。"""
        from coin_fundamental_ranker import BDSM_COINS  # noqa: WPS433
        self.assertIsInstance(BDSM_COINS, frozenset)


class TestBDSMSnapshotWriter(unittest.TestCase):
    """S3: bdsm_snapshot_writer Phase 0 每日快照生成（R3 FAIL-OPEN + 正常写入）。

    两个关键用例：
      1. neutral_snapshot() FAIL-OPEN 兜底字节等价「BDSM 不存在」
      2. build_snapshot() 能生成 7 币快照 JSON 并写盘（即使 coin 数据有缺失也要填 available=false）
    """

    def test_import_bdsm_snapshot_writer(self) -> None:
        """RED: 模块与 write_snapshot 函数未定义时，直接 ImportError/AttrError。"""
        try:
            from bdsm_snapshot_writer import neutral_snapshot  # noqa: WPS433
        except (ModuleNotFoundError, ImportError) as exc:
            self.fail(f"bdsm_snapshot_writer.neutral_snapshot 未实现: {exc}")
        from bdsm_snapshot_writer import neutral_snapshot  # noqa: WPS433 F811
        snap = neutral_snapshot(reason="unittest")
        # 顶层字段
        self.assertEqual(snap["version"], "1.0")
        self.assertEqual(snap["snapshot_date"], date.today().isoformat())
        self.assertEqual(snap["neutral_fallback_reason"], "unittest")
        # 7 币均需有 entry，字段全部为中性值
        from coin_fundamental_ranker import BDSM_COINS  # noqa: WPS433
        for coin in BDSM_COINS:
            self.assertIn(coin, snap["coins"], f"{coin} 缺失中性条目")
            entry = snap["coins"][coin]
            self.assertFalse(entry["available"])
            self.assertEqual(entry["data_quality"], "insufficient")
            self.assertEqual(entry["score"], 0.0)
            self.assertEqual(entry["rank"], "B")
            # R3: 约束全是 PASS
            self.assertEqual(entry["direction_constraint"], "NEUTRAL")
            self.assertEqual(entry["cap_multiplier"], 1.0)
            self.assertEqual(entry["exit_action"], "NONE")

    def test_write_snapshot_creates_json_file_with_7_coins(self) -> None:
        """RED: write_snapshot 写入 bdsm_snapshot_{YYYYMMDD}.json 并可读取。

        即使 compute_all 有真实/失败的差异，只要 8 币 entry 齐全 + 结构完整
       （available / score / rank / direction_constraint / cap_multiplier / exit_action
        六个字段存在）即视为通过 — FAIL-OPEN 会兜底为中性。
        """
        import json

        from bdsm_snapshot_writer import write_snapshot  # noqa: WPS433
        from coin_fundamental_ranker import BDSM_COINS  # noqa: WPS433

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = write_snapshot(out_dir=tmpdir, dry_run_read_coin_data_from_db=False)
            self.assertTrue(os.path.exists(output_path), f"快照文件 {output_path} 未创建")
            with open(output_path) as f:
                data = json.load(f)
            self.assertEqual(data["version"], "1.0")
            # 快照应含所有 8 币
            for coin in BDSM_COINS:
                self.assertIn(coin, data["coins"], f"{coin} 缺 entry")
                entry = data["coins"][coin]
                for required_key in (
                    "available", "data_quality", "score", "rank",
                    "direction_constraint", "cap_multiplier", "exit_action",
                ):
                    self.assertIn(required_key, entry,
                                  f"{coin} 缺失必需字段 {required_key}")

    def test_cap_multiplier_formula(self) -> None:
        """RED: _compute_cap 实现三段乘法，夹到 [0,1]。

        A 级 + score=0.4 + sufficient = 0.8*0.8*1.0 = 0.64
        """
        from bdsm_snapshot_writer import _compute_cap_multiplier  # noqa: WPS433
        self.assertAlmostEqual(_compute_cap_multiplier(rank="A", score=0.4, data_quality="sufficient"), 0.64)
        self.assertEqual(_compute_cap_multiplier(rank="C", score=-0.5, data_quality="insufficient"), 0.0)

    def test_direction_constraint_formula(self) -> None:
        """RED: _compute_direction — score>0.3 → LONG_ONLY，score<-0.3 → SHORT_ONLY。"""
        from bdsm_snapshot_writer import _compute_direction  # noqa: WPS433
        self.assertEqual(_compute_direction(score=0.5, data_quality="sufficient"), "LONG_ONLY")
        self.assertEqual(_compute_direction(score=-0.5, data_quality="sufficient"), "SHORT_ONLY")
        self.assertEqual(_compute_direction(score=0.0, data_quality="sufficient"), "NEUTRAL")
        # data_quality=insufficient 即使 score 极端也强制 NEUTRAL
        self.assertEqual(_compute_direction(score=0.9, data_quality="insufficient"), "NEUTRAL")


class BDSMPoolIsolationTests(unittest.TestCase):
    """S5 子池隔离 — source_tag 分类 + 计数 + 子池上限（不真实构造 PollingTrader）。"""

    def setUp(self) -> None:
        # 路径顺序严格：必须让 11-易经推理系统/ 最优先解析 scripts.*（与 trading_utils 的绝对包 import 匹配）；
        #   · scripts.memory_l4.paths → 需要 base_11 前缀最优先
        #   · force_vector.* / trading_utils → 走 memory_l4 前缀
        # 模块级 test 会预先插入 _FORCE_VEC_DIR，这里要把 base_11 强制置顶避免 scripts 被其他目录包遮蔽
        _THIS_DIR = Path(__file__).resolve().parent
        _BASE_11 = str(_THIS_DIR.parent)        # .../11-易经推理系统
        _MEM_L4 = os.path.join(_BASE_11, "scripts", "memory_l4")
        for p in (_MEM_L4, _BASE_11):
            if p in sys.path:
                sys.path.remove(p)
        sys.path.insert(0, _MEM_L4)
        sys.path.insert(0, _BASE_11)

    def test_bdsm10_coins_exact_without_sky(self) -> None:
        """BDSM_COINS = 10 币精确集合（BTC+ZEC+ARB 纳入，无 SKY，SKY 走纯 BCRM）。"""
        from force_vector.coin_fundamental_ranker import BDSM_COINS  # noqa: WPS433
        expected = {"UNI", "PUMP", "HYPE", "AAVE", "SOL", "CRCL", "ETH", "BTC", "ZEC", "ARB"}
        self.assertEqual(BDSM_COINS, expected)
        self.assertNotIn("SKY", BDSM_COINS)

    def test_count_subpool_mock_bcrm5_vs_bdsm3(self) -> None:
        """构造 8 个 TradeRecord（5×bcrm 3×bdsm）→ 各自子池计数，边界正确。"""
        from trading_utils import TradeRecord  # noqa: WPS433
        bcrm_coins = ["BTC", "NVDA", "XAU", "GOOGL", "COIN"]
        bdsm_coins = ["UNI", "PUMP", "SOL"]
        recs = [
            TradeRecord(
                trade_id=f"t{i}", coin=c, inst_id=f"{c}-SWAP",
                direction="long", entry_price=1.0, confidence=0.7,
                hexagram="x", source_tag=("bcrm" if c in bcrm_coins else "bdsm"),
            )
            for i, c in enumerate(bcrm_coins + bdsm_coins)
        ]
        self.assertEqual(sum(1 for r in recs if r.source_tag == "bdsm"), 3)
        self.assertEqual(sum(1 for r in recs if r.source_tag == "bcrm"), 5)
        for r in recs:
            self.assertIn(r.source_tag, {"bdsm", "bcrm"})

    def test_legacy_positions_without_tag_fallback_by_coin(self) -> None:
        """老仓位 source_tag 空 → 按币回溯分类（BDSM_COINS → bdsm）。"""
        from force_vector.coin_fundamental_ranker import BDSM_COINS  # noqa: WPS433
        from trading_utils import TradeRecord  # noqa: WPS433
        uni_legacy = TradeRecord(trade_id="old", coin="UNI", inst_id="UNI-SWAP",
                                 direction="long", entry_price=10.0,
                                 confidence=0.5, hexagram="乾为天")
        self.assertEqual(uni_legacy.source_tag, "")  # 兼容默认
        tag = "bdsm" if uni_legacy.coin in BDSM_COINS else "bcrm"
        self.assertEqual(tag, "bdsm")


class BDSMDataQuality7SignalTests(unittest.TestCase):
    """S3 data_quality 本地重算：7 信号覆盖 ≥3/7 且 conf≥0.35 → partial。"""

    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1] / "scripts" / "memory_l4"
        sys.path.insert(0, str(root))

    def _recompute_dq(self, sub_signals: dict, confidence: float) -> str:
        """复刻 bdsm_snapshot_writer._build_coin_entry 里的 data_quality 7 信号规则。"""
        total_signals = (
            "revenue_stability", "mc_fees_mean_reversion", "tvl_growth_momentum",
            "revenue_quality", "supply_shrinkage_intensity",
            "value_capture_delta", "revenue_sustainability",
        )
        covered = sum(1 for k in total_signals
                      if sub_signals.get(k) is not None and abs(float(sub_signals.get(k, 0))) > 1e-9)
        ratio = covered / len(total_signals)
        if ratio >= 5 / 7 and confidence >= 0.70:
            return "sufficient"
        elif ratio >= 3 / 7 and confidence >= 0.35:
            return "partial"
        elif ratio >= 1 / 7:
            return "partial"
        return "insufficient"

    def test_bdsm_three_signals_only_partial(self) -> None:
        """Artemis 四信号全 0，仅 E5+E6+E7 非零 (3/7=0.428≥3/7) + conf=0.43 → partial。"""
        sub = {"supply_shrinkage_intensity": 0.56,
               "value_capture_delta": 0.69,
               "revenue_sustainability": -0.08}  # 3/7
        dq = self._recompute_dq(sub, confidence=0.43)
        self.assertEqual(dq, "partial")  # 真实快照 PUMP 预期（冒烟测试已验证）

    def test_all_zero_insufficient(self) -> None:
        """7 信号全 0（ETH 原生数据缺）→ insufficient。"""
        sub: dict = {k: 0.0 for k in
                     ("revenue_stability", "mc_fees_mean_reversion", "tvl_growth_momentum",
                      "revenue_quality", "supply_shrinkage_intensity",
                      "value_capture_delta", "revenue_sustainability")}
        self.assertEqual(self._recompute_dq(sub, confidence=0.0), "insufficient")

    def test_6_signals_sufficient(self) -> None:
        """6/7 覆盖 + conf≥0.70 → sufficient。"""
        sub = {k: 0.5 for k in
               ("revenue_stability", "mc_fees_mean_reversion", "tvl_growth_momentum",
                "supply_shrinkage_intensity", "value_capture_delta", "revenue_sustainability")}
        self.assertEqual(self._recompute_dq(sub, confidence=0.72), "sufficient")


class BDSMExitTriggerTests(unittest.TestCase):
    """B1~B5 出场触发：制造历史快照对比，验证 _detect_exit_action 优先级和返回。"""

    def setUp(self) -> None:
        _THIS_DIR = Path(__file__).resolve().parent
        _BASE_11 = _THIS_DIR.parent  # = .../11-易经推理系统
        _MEM_L4 = _BASE_11 / "scripts" / "memory_l4"
        for p in (str(_BASE_11), str(_MEM_L4)):
            if p not in sys.path:
                sys.path.insert(0, p)

    def _make_entry(self, phase: str, score: float, rank: str,
                    phase_conf: float = 0.8, dq: str = "partial") -> dict:
        from force_vector.bdsm_snapshot_writer import (  # noqa: WPS433
            _compute_cap_multiplier,
            _compute_direction,
        )
        return {
            "available": True, "phase": phase, "score": score, "rank": rank,
            "phase_confidence": phase_conf, "data_quality": dq,
            "direction_constraint": _compute_direction(score, dq),
            "cap_multiplier": _compute_cap_multiplier(rank, score, dq),
            "e5": 0.0, "e6": 0.0, "e7": 0.0,
            "valuation_percentile": 50.0,
            "bds_score": 0.0,
        }

    def test_b4_e7_collapse_reduces_80(self) -> None:
        """B4：昨日 E7>0 → 今日 E7≤0（营收可持续性塌方）→ REDUCE_80。"""
        from force_vector.bdsm_snapshot_writer import (  # noqa: WPS433
            _detect_exit_action,
            neutral_snapshot,
        )
        today = self._make_entry("P2_REVENUE_EXPANSION", score=0.45, rank="A")
        today["e7"] = 0.0  # E7 今日归零
        yesterday = neutral_snapshot("yesterday")
        y_entry = self._make_entry("P2_REVENUE_EXPANSION", score=0.55, rank="A")
        y_entry["e7"] = 0.3  # 昨日 E7>0
        yesterday["coins"]["UNI"] = y_entry
        action, triggers = _detect_exit_action("UNI", today, {"D-1": yesterday})
        self.assertEqual(action, "REDUCE_80")
        self.assertTrue(any("B4" in t for t in triggers), triggers)

    def test_b1_phase_upgrade_p2_p3_reduces_50(self) -> None:
        """B1：P2→P3 且 估值分位>80 且 BDS≥0 → REDUCE_50。"""
        from force_vector.bdsm_snapshot_writer import (  # noqa: WPS433
            _detect_exit_action,
            neutral_snapshot,
        )
        today = self._make_entry("P3_VALUATION_RECOVERY", score=0.55, rank="A")
        today["valuation_percentile"] = 87.0
        today["bds_score"] = 0.4
        hist = neutral_snapshot("d-1")
        y_entry = self._make_entry("P2_REVENUE_EXPANSION", score=0.25, rank="B")
        y_entry["valuation_percentile"] = 60.0
        y_entry["bds_score"] = 0.3
        hist["coins"]["UNI"] = y_entry
        action, triggers = _detect_exit_action("UNI", today, {"D-1": hist})
        self.assertEqual(action, "REDUCE_50")
        self.assertTrue(any("B1" in t for t in triggers), triggers)

    def test_b2_phase_degraded_p2_to_p1_bds_negative_close_all(self) -> None:
        """B2：P2 → P1 且今日 bds<0 → CLOSE_ALL。"""
        from force_vector.bdsm_snapshot_writer import (  # noqa: WPS433
            _detect_exit_action,
            neutral_snapshot,
        )
        today = self._make_entry("P1_EXPECTATION", score=0.1, rank="B")
        today["bds_score"] = -0.2
        hist = neutral_snapshot("hist")
        hist["coins"]["UNI"] = self._make_entry("P2_REVENUE_EXPANSION", score=0.4, rank="A")
        action, triggers = _detect_exit_action("UNI", today, {"D-1": hist})
        self.assertEqual(action, "CLOSE_ALL")
        self.assertIn("B2_phase_reverted_to_p1", triggers)

    def test_b5_rank_tumbling_a_to_c_two_day_close_all(self) -> None:
        """B5：A→C（≥2 级 两日）→ CLOSE_ALL。"""
        from force_vector.bdsm_snapshot_writer import (  # noqa: WPS433
            _detect_exit_action,
            neutral_snapshot,
        )
        today = self._make_entry("P2_REVENUE_EXPANSION", score=0.2, rank="C")
        d1 = neutral_snapshot("d1")
        d1["coins"]["UNI"] = self._make_entry("P2_REVENUE_EXPANSION", score=0.5, rank="A")
        d2 = neutral_snapshot("d2")
        d2["coins"]["UNI"] = self._make_entry("P2_REVENUE_EXPANSION", score=0.45, rank="A")
        history = {"D-2": d2, "D-1": d1}  # sorted keys: D-1 = y, D-2 = by → tby empty, len(rank_series)=2
        # 凑足 3 条让 _rank_tumbling len ≥ 3: tby, y, today — 再加 D-3
        d3 = neutral_snapshot("d3")
        d3["coins"]["UNI"] = self._make_entry("P2_REVENUE_EXPANSION", score=0.6, rank="A")
        history["D-3"] = d3
        # sorted: D-1, D-2, D-3 → 但 keys 升序为 D-1<D-2<D-3，[-1]=D-3? 错！实际 key 应是时间戳或可排序
        # 真实 writer 使用 YYYY-MM-DD 字符串，所以按 lex 升序 = 旧到新。改 key 格式：
        history = {"2026-08-30": d3, "2026-08-31": d1, "2026-09-01": {"coins": {"UNI": today}}}
        action, triggers = _detect_exit_action("UNI", today, history)
        self.assertEqual(action, "CLOSE_ALL")
        self.assertIn("B5_rank_tumbling", triggers)


class BDSMSnapshotFailOpenTests(unittest.TestCase):
    """§S6 load_today_snapshot FAIL-OPEN：缺文件 / schema 异常 → 中性快照兜底."""

    def setUp(self) -> None:
        _THIS_DIR = Path(__file__).resolve().parent
        _BASE_11 = _THIS_DIR.parent
        _MEM_L4 = os.path.join(str(_BASE_11), "scripts", "memory_l4")
        for p in (_MEM_L4, str(_BASE_11)):
            if p in sys.path:
                sys.path.remove(p)
        sys.path.insert(0, _MEM_L4)
        sys.path.insert(0, str(_BASE_11))
        self._tmpdir = tempfile.TemporaryDirectory()  # noqa: SIM115

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_load_today_snapshot_missing_file_returns_neutral_7_coins(self) -> None:
        """快照不存在 → neutral_snapshot(reason) 7 币六字段齐全."""
        from force_vector.bdsm_snapshot_writer import (  # noqa: WPS433
            BDSM_COINS,
            load_today_snapshot,
        )
        snap = load_today_snapshot(out_dir=self._tmpdir.name)
        self.assertEqual(snap["version"], "1.0")
        self.assertTrue(snap["neutral_fallback_reason"])  # 非空说明兜底
        self.assertEqual(set(snap["coins"].keys()), BDSM_COINS)
        for coin, entry in snap["coins"].items():
            self.assertIs(entry["available"], False, f"{coin} available 应为 False")
            self.assertEqual(entry["data_quality"], "insufficient", coin)
            self.assertEqual(entry["score"], 0.0, coin)
            self.assertEqual(entry["rank"], "B", coin)
            self.assertEqual(entry["direction_constraint"], "NEUTRAL", coin)
            self.assertEqual(entry["cap_multiplier"], 1.0, coin)
            self.assertEqual(entry.get("exit_action", "NONE"), "NONE", coin)

    def test_load_today_snapshot_bad_schema_missing_coins_fallback(self) -> None:
        """快照 JSON schema 错（缺 coins 字段）→ 中性兜底."""
        from force_vector.bdsm_snapshot_writer import (  # noqa: WPS433
            BDSM_COINS,
            load_today_snapshot,
        )
        bad_file = Path(self._tmpdir.name) / f"bdsm_snapshot_{date.today().strftime('%Y%m%d')}.json"
        bad_file.write_text('{"schema_version":"1.0","generated_at":"2026-09-02T00:00:00"}', encoding="utf-8")
        snap = load_today_snapshot(out_dir=self._tmpdir.name)
        self.assertTrue(snap["neutral_fallback_reason"])
        self.assertEqual(set(snap["coins"].keys()), BDSM_COINS)
        self.assertTrue(all(e["data_quality"] == "insufficient" for e in snap["coins"].values()))



class BDSPPhase2CouplingTests(unittest.TestCase):
    """Phase 2 缺口 1/2/3：BDSM 快照强耦合进 PollingTrader 三条路径。

    TDD 要求：先看失败 → 写最小代码 → 回归通过。
    每条缺口至少 2 条 UT（命中 + FAIL-OPEN/非 BDSM 不拦截）。
    """

    def setUp(self) -> None:
        _THIS_DIR = Path(__file__).resolve().parent
        _BASE_11 = str(_THIS_DIR.parent)        # .../11-易经推理系统
        _MEM_L4 = os.path.join(_BASE_11, "scripts", "memory_l4")
        for p in (_MEM_L4, _BASE_11):
            if p in sys.path:
                sys.path.remove(p)
        sys.path.insert(0, _MEM_L4)
        sys.path.insert(0, _BASE_11)

    # ── 缺口 1：方向约束 ──
    def test_gap1_long_only_drops_short_open_and_returns_none(self) -> None:
        """BDSM 方向= LONG_ONLY + bcrm 开 short → DROP，返回 (False, drop_reason)."""
        from unittest.mock import MagicMock, patch
        from scripts.memory_l4.polling_trader import PollingTrader
        with patch.object(PollingTrader, "__init__", lambda self, *a, **kw: None):
            t = PollingTrader.__new__(PollingTrader)
        t._log = MagicMock()
        t.BDSM_COINS = frozenset({"UNI", "PUMP", "HYPE", "AAVE", "SOL", "CRCL", "ETH"})
        # 覆盖今日快照：UNI LONG_ONLY
        snap = {
            "version": "1.0",
            "coins": {
                "UNI": {"available": True, "direction_constraint": "LONG_ONLY",
                        "cap_multiplier": 1.0, "exit_action": "NONE"},
            },
        }
        t._bdsm_snapshot_cache = {"ts": float("inf"), "snapshot": snap}  # TTL 不失效

        is_pass, drop_reason = t._apply_bdsm_direction_constraint("UNI", "DOWN")
        self.assertFalse(is_pass, f"LONG_ONLY 下的 DOWN 应该被拦截: {drop_reason}")
        self.assertIn("bdsm_long_only_dropped", drop_reason)

    def test_gap1_neutral_or_non_bdsm_not_dropped(self) -> None:
        """FAIL-OPEN: NEUTRAL 快照 或 非 BDSM 币 BTC → 不拦截。"""
        from unittest.mock import MagicMock, patch
        from scripts.memory_l4.polling_trader import PollingTrader
        with patch.object(PollingTrader, "__init__", lambda self, *a, **kw: None):
            t = PollingTrader.__new__(PollingTrader)
        t._log = MagicMock()
        t.BDSM_COINS = frozenset({"UNI", "PUMP", "HYPE", "AAVE", "SOL", "CRCL", "ETH"})
        # NEUTRAL 快照
        snap_neutral = {"version": "1.0", "coins": {"UNI": {
            "available": False, "direction_constraint": "NEUTRAL", "cap_multiplier": 1.0, "exit_action": "NONE"}}}
        t._bdsm_snapshot_cache = {"ts": float("inf"), "snapshot": snap_neutral}

        # BTC 非 BDSM → 无方向约束
        is_pass_btc, reason_btc = t._apply_bdsm_direction_constraint("BTC", "DOWN")
        self.assertTrue(is_pass_btc, f"非 BDSM 币 BTC 应放行: {reason_btc}")
        self.assertEqual(reason_btc, "not_bdsm_coin")

        # UNI NEUTRAL(dq insufficient) → 不拦截（FAIL-OPEN 中性等价 BDSM 不存在）
        is_pass_uni, reason_uni = t._apply_bdsm_direction_constraint("UNI", "DOWN")
        self.assertTrue(is_pass_uni, f"NEUTRAL 约束等价不存在: {reason_uni}")
        self.assertEqual(reason_uni, "neutral_pass")

    # ── 缺口 2：仓位 MIN(crm, crm×cap) — 纯函数 helper ──
    def test_gap2_cap_multiplier_0175_scales_position_usdt(self) -> None:
        """UNI cap=0.175 → 原 1000 U → 175 U，cap_applied=True 用于日志。"""
        from unittest.mock import MagicMock, patch
        from scripts.memory_l4.polling_trader import PollingTrader
        with patch.object(PollingTrader, "__init__", lambda self, *a, **kw: None):
            t = PollingTrader.__new__(PollingTrader)
        t._log = MagicMock()
        t.BDSM_COINS = frozenset({"UNI"})
        t._bdsm_snapshot_cache = {"ts": float("inf"), "snapshot": {
            "version": "1.0", "coins": {
                "UNI": {"available": True, "data_quality": "partial",
                        "direction_constraint": "NEUTRAL", "cap_multiplier": 0.175,
                        "exit_action": "NONE"}}}}
        actual, cap_used, info_tag = t._apply_bdsm_cap_multiplier("UNI", 1000.0)
        self.assertAlmostEqual(actual, 175.0, delta=1e-6)
        self.assertAlmostEqual(cap_used, 0.175, delta=1e-6)
        self.assertEqual(info_tag, "bdsm_cap_applied")

    def test_gap2_non_bdsm_or_missing_cap_defaults_1(self) -> None:
        """FAIL-OPEN: 非 BDSM 或 cap 缺失 → 返回原仓位，cap=1.0 不生效。"""
        from unittest.mock import MagicMock, patch
        from scripts.memory_l4.polling_trader import PollingTrader
        with patch.object(PollingTrader, "__init__", lambda self, *a, **kw: None):
            t = PollingTrader.__new__(PollingTrader)
        t.BDSM_COINS = frozenset({"UNI"})
        # 空快照 coins 表 → UNI 不存在
        t._bdsm_snapshot_cache = {"ts": float("inf"), "snapshot": {"version": "1.0", "coins": {}}}
        actual1, cap1, tag1 = t._apply_bdsm_cap_multiplier("UNI", 2000.0)
        self.assertAlmostEqual(actual1, 2000.0, delta=1e-6)
        self.assertAlmostEqual(cap1, 1.0, delta=1e-6)
        self.assertEqual(tag1, "fail_open_cap_default_1.0")
        # BTC 非 BDSM
        actual2, cap2, tag2 = t._apply_bdsm_cap_multiplier("BTC", 5000.0)
        self.assertAlmostEqual(actual2, 5000.0, delta=1e-6)
        self.assertEqual(tag2, "not_bdsm_coin")

    def test_gap2_cap_zero_blocks_open(self) -> None:
        """cap=0 → 返回 (0.0, 0.0, blocked)。上层据此拦截不开仓。"""
        from unittest.mock import MagicMock, patch
        from scripts.memory_l4.polling_trader import PollingTrader
        with patch.object(PollingTrader, "__init__", lambda self, *a, **kw: None):
            t = PollingTrader.__new__(PollingTrader)
        t.BDSM_COINS = frozenset({"ETH"})
        t._bdsm_snapshot_cache = {"ts": float("inf"), "snapshot": {"version": "1.0", "coins": {
            "ETH": {"available": False, "data_quality": "insufficient",
                    "direction_constraint": "NEUTRAL", "cap_multiplier": 0.0,
                    "exit_action": "NONE"}}}}
        actual, cap, tag = t._apply_bdsm_cap_multiplier("ETH", 3000.0)
        self.assertAlmostEqual(actual, 0.0, delta=1e-6)
        self.assertAlmostEqual(cap, 0.0, delta=1e-6)
        self.assertEqual(tag, "bdsm_cap_zero_blocked")

    # ── 缺口 3：出场 OR 逻辑 ──
    def test_gap3_close_all_calls_okx_full_close_and_handle_close(self) -> None:
        """BDSM CLOSE_ALL → 走 market_close_long/short 全平 + handle_close_position 落盘。"""
        from unittest.mock import MagicMock, patch
        from scripts.memory_l4.polling_trader import PollingTrader
        with patch.object(PollingTrader, "__init__", lambda self, *a, **kw: None):
            t = PollingTrader.__new__(PollingTrader)
        t._log = MagicMock()
        t.BDSM_COINS = frozenset({"UNI"})
        t._bdsm_snapshot_cache = {"ts": float("inf"), "snapshot": {"version": "1.0", "coins": {
            "UNI": {"available": True, "exit_action": "CLOSE_ALL", "exit_triggers": ["B5_rank_tumbling"],
                    "direction_constraint": "NEUTRAL", "cap_multiplier": 1.0}}}}
        t.position_tracker = MagicMock()
        t.position_tracker.all_open_positions = MagicMock(return_value=[])  # yijing exit 的持仓不用它
        # 模拟 _bdsm_check_exit_actions 作用到 UNI 持仓 → OKX client close_long 调用
        pos_info = {"inst_id": "UNI-USDT-SWAP", "coin": "UNI", "pos_side": "long", "pos": 10,
                    "avg_px": 10.0, "mark_px": 11.0, "upl": 10.0, "upl_ratio": 0.10,
                    "open_time_sec": 0}

        t.okx_client = MagicMock()
        t.okx_client.market_close_long = MagicMock(return_value={"ok": True, "dry_run": False})
        t._handle_close_position = MagicMock()
        t._get_coin_position_info = MagicMock(return_value={"has_position": True, **pos_info})

        t._bdsm_check_exit_actions()  # 缺口 3 新增方法
        t.okx_client.market_close_long.assert_called_once_with(
            "UNI-USDT-SWAP", reason="bdsm_exit:CLOSE_ALL(B5_rank_tumbling,exit)")
        t._handle_close_position.assert_called_once()
        self.assertEqual(t._handle_close_position.call_args.kwargs.get("exit_reason", ""),
                         "bdsm_exit:CLOSE_ALL(B5_rank_tumbling,exit)")

    def test_gap3_no_bdsm_coin_or_none_no_action(self) -> None:
        """FAIL-OPEN：非 BDSM 币 / exit=NONE → 不调用 OKX 任何平仓/减仓接口。"""
        from unittest.mock import MagicMock, patch
        from scripts.memory_l4.polling_trader import PollingTrader
        with patch.object(PollingTrader, "__init__", lambda self, *a, **kw: None):
            t = PollingTrader.__new__(PollingTrader)
        t._log = MagicMock()
        t.BDSM_COINS = frozenset({"UNI"})
        # NONE 快照
        t._bdsm_snapshot_cache = {"ts": float("inf"), "snapshot": {"version": "1.0", "coins": {
            "UNI": {"available": True, "exit_action": "NONE", "exit_triggers": [],
                    "direction_constraint": "NEUTRAL", "cap_multiplier": 1.0},
        }}}
        t.okx_client = MagicMock()
        t.position_tracker = MagicMock(all_open_positions=MagicMock(return_value=[]))
        t._get_coin_position_info = MagicMock()
        # 加一个 BTC 持仓（非 BDSM，有 open_position）但 exit 不处理 BTC
        t.position_tracker.all_open_positions.return_value = [
            MagicMock(coin="BTC", inst_id="BTC-USDT-SWAP")
        ]
        t._bdsm_check_exit_actions()
        t.okx_client.market_close_long.assert_not_called()
        t.okx_client.market_close_short.assert_not_called()


# ============================================================================
# Bug (C)(D) 修复回归：兄弟子包 scripts.memory_l4.force_vector 环境 下 不抛
#   ModuleNotFound(from force_vector.models/...)，且 快照 读取 对齐 今日数值
# ============================================================================
class BDSMBrotherPackageEnvTests(unittest.TestCase):
    """BUG-C/D 根因修复：scripts/memory_l4/force_vector/__init__.py 和
    bdsm_snapshot_writer.py 在 顶层 force_vector 包不存在 时 (即 daemon
    `-m scripts.memory_l4.polling_trader` 兄弟子包模式) 不崩溃。
    """

    _SIBLING_CWD = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统"
    _BROKEN = None  # 懒缓存 import 结果，避免多轮 subprocess 开销

    def _run_as_sibling_module(self, module_stmt: str):
        """用 `python3 -m scripts.memory_l4...` 兄弟子包环境跑一段代码，返回 stdout。"""
        import subprocess, tempfile, os, textwrap
        script = os.path.join(
            self._SIBLING_CWD, "scripts", "memory_l4",
            "_ut_bug_cd_probe.py",
        )
        # 临时脚本（与真实 daemon sys.path/__package__ 等价）
        with open(script, "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(module_stmt))
        try:
            r = subprocess.run(
                ["/opt/anaconda3/bin/python3",
                 "-u", "-m", "scripts.memory_l4._ut_bug_cd_probe"],
                cwd=self._SIBLING_CWD,
                capture_output=True, text=True, timeout=60,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            return r.returncode, r.stdout, r.stderr
        finally:
            try: os.remove(script)
            except FileNotFoundError: pass

    # ------------------------------------------------------------------ RED1
    def test_brother_subpkg_does_not_error_models_missing(self):
        """兄弟子包模式直接 import coin_fundamental_ranker 不得抛
        ModuleNotFound: No module named 'force_vector'。BUG-C 回归。"""
        stmt = """\
        import json, sys
        try:
            mod = __import__("scripts.memory_l4.force_vector.coin_fundamental_ranker",
                             fromlist=["BDSM_COINS"])
            coins = sorted(list(getattr(mod, "BDSM_COINS") or []))
            print(json.dumps({"ok": True, "coins": coins, "len": len(coins)}))
        except Exception as e:
            import traceback; traceback.print_exc()
            print(json.dumps({"ok": False, "err": type(e).__name__ + ": " + str(e)}))
        """
        rc, out, err = self._run_as_sibling_module(stmt)
        self.assertEqual(rc, 0, f"subprocess rc={rc} stderr={err[-500:]}")
        last = [l for l in out.splitlines() if l.strip()][-1]
        import json
        data = json.loads(last)
        self.assertTrue(data.get("ok"), f"兄弟子包 BDSM_COINS 失败: {data}")
        self.assertEqual(data.get("len"), 10, f"10币 预期，实际={data.get('coins')}")

    # ------------------------------------------------------------------ RED2
    def test_brother_subpkg_load_today_snapshot_correct_caps(self):
        """兄弟子包模式 load_today_snapshot 必须读到 真实快照（非 FAIL-OPEN 中性），
        8 BDSM 币 cap_mult 与 今日快照 硬编码 对齐。BUG-D 回归。"""
        stmt = """\
        import json, sys
        try:
            mod = __import__("scripts.memory_l4.force_vector.bdsm_snapshot_writer",
                             fromlist=["load_today_snapshot", "DEFAULT_BDSM_DIR"])
            DEFAULT_DIR = getattr(mod, "DEFAULT_BDSM_DIR", None)
            snap = getattr(mod, "load_today_snapshot")()
            coins = {}
            for c, info in (snap or {}).get("coins", {}).items():
                coins[c] = round(info.get("cap_multiplier", -1), 4)
            print(json.dumps({
                "ok": snap is not None, "default_dir": DEFAULT_DIR,
                "date": (snap or {}).get("snapshot_date"), "coins": coins,
                "ncoins": len((snap or {}).get("coins", {})),
            }, ensure_ascii=False))
        except Exception as e:
            import traceback; traceback.print_exc()
            print(json.dumps({"ok": False, "err": type(e).__name__ + ": " + str(e)}))
        """
        rc, out, err = self._run_as_sibling_module(stmt)
        self.assertEqual(rc, 0, f"subprocess rc={rc} stderr={err[-500:]}")
        last = [l for l in out.splitlines() if l.strip()][-1]
        import json
        data = json.loads(last)
        self.assertTrue(data.get("ok"), f"兄弟子包 快照读 失败: {data}")
        self.assertIsNotNone(data.get("default_dir"), "DEFAULT_BDSM_DIR 导出别名丢失")
        self.assertGreaterEqual(data.get("ncoins", 0), 8, "快照 8 BDSM 币 必须存在")
        # BUG-D 回归核心意图：cap_mult 非 1.0 中性兜底（随市场动态变化，不硬编码具体值）
        for c in ("UNI", "PUMP", "HYPE", "AAVE", "SOL", "CRCL", "ETH"):
            got = data.get("coins", {}).get(c)
            self.assertIsNotNone(
                got, f"快照缺 币={c} (兄弟子包 读到中性/None)")
            self.assertNotEqual(
                got, 1.0,
                f"币={c} cap_mult=1.0 → BUG-D 回归：中性兜底未修复（实际={got}）")


# ============================================================================
# set_leverage 硬约束：OKX 端下单前 必须 同步 设置 杠杆（默认 5x）
#   T1: OKXSimulatedClient.set_leverage(inst_id, lever, mgn_mode) 调用 正确 REST
#   T2: PollingTrader._open_position 内 在 market_open_long 前 调 set_leverage
# ============================================================================
class OKXSetLeverageTests(unittest.TestCase):
    """set_leverage 方法 + _open_position 前置调用 TDD（Session 2 决策硬约束）。"""

    def setUp(self) -> None:
        _THIS_DIR = Path(__file__).resolve().parent
        _BASE_11 = str(_THIS_DIR.parent)        # .../11-易经推理系统
        _MEM_L4 = os.path.join(_BASE_11, "scripts", "memory_l4")
        for p in (_MEM_L4, _BASE_11):
            if p in sys.path:
                sys.path.remove(p)
        sys.path.insert(0, _MEM_L4)
        sys.path.insert(0, _BASE_11)

    def test_set_leverage_calls_okx_rest_endpoint(self):
        """T1 RED: set_leverage 必须 POST /api/v5/account/set-leverage
        body 包含 instId / lever / mgnMode 三键，认证签名；dry_run=True 也 必须 打。"""
        from unittest.mock import MagicMock, patch, PropertyMock
        sys.path.insert(0, os.path.normpath(os.path.join(_THIS_DIR, "..")))
        from scripts.memory_l4.okx_simulated import OKXSimulatedClient
        cfg = {
            "api_key": "tdd_key", "secret_key": "tdd_secret", "passphrase": "tdd_pp",
            "base_url": "https://www.okx.com",
            "default_leverage": 5, "td_mode": "isolated",
            "default_inst_id": "UNI-USDT-SWAP", "simulated": False, "dry_run": True,
        }
        # 用 patch.object 绕过 _proxy_setup（不打网络）
        with patch.object(OKXSimulatedClient, "_proxy_setup", lambda self: None):
            cli = OKXSimulatedClient(config=cfg)
        captured = {}
        def fake_post(path, body, auth=True):
            captured["path"] = path
            captured["body"] = body
            captured["auth"] = auth
            return {"code": "0", "msg": "", "data": [{"lever": "5"}]}
        cli._post = fake_post
        # RED 断言：方法存在；参数正确；返回 ok
        self.assertTrue(hasattr(cli, "set_leverage"),
                        "FAIL-RED: OKXSimulatedClient 无 set_leverage 方法")
        res = cli.set_leverage("UNI-USDT-SWAP", lever=5.0, mgn_mode="isolated")
        self.assertEqual(captured.get("path"), "/api/v5/account/set-leverage",
                         f"FAIL-RED: 未走 /api/v5/account/set-leverage 端点，实际={captured.get('path')}")
        self.assertEqual(captured.get("auth"), True, "FAIL-RED: set_leverage 必须 auth=True 签名")
        body = captured.get("body", {})
        self.assertEqual(body.get("instId"), "UNI-USDT-SWAP")
        self.assertEqual(str(body.get("lever")), "5")
        self.assertEqual(body.get("mgnMode"), "isolated")
        self.assertTrue(res.get("ok"), f"FAIL-RED: 返回 ok!=True，res={res}")

    def test_open_position_calls_set_leverage_before_place_order(self):
        """T2 RED: _open_position 在调用 market_open_long/short 前 必须 先调
        self.okx_client.set_leverage(inst_id, lever, td_mode)。用 MagicMock 追踪 call_args 顺序。"""
        sys.path.insert(0, os.path.normpath(os.path.join(_THIS_DIR, "..")))
        import types
        from unittest.mock import MagicMock
        # 轻量 trader：只 填 _open_position 用到 的 必备 attrs + 让 _execute_trade 不 参与
        from scripts.memory_l4.polling_trader import PollingTrader
        t = object.__new__(PollingTrader)
        t._log = MagicMock()
        t.shadow_mode = False
        # _capital_ctrl 家族（_fetch_capital_advice / _apply_capital_control_to_position 读）
        t._capital_ctrl = None
        t._capital_ctrl_last_result = None
        t._capital_ctrl_last_ts = 0.0
        t._CAPITAL_CTRL_MIN_INTERVAL = 300.0
        # 把会读的复杂 helper 全 替换 成 安全 lambda，避免 链式 缺 attrs
        def _fetch_capital_advice(self, force=False): return None
        def _apply_capital_control_to_position(self, coin, position_usdt, available_equity, *a, **kw):
            return (float(position_usdt), "chain_probe noop")
        t._fetch_capital_advice = types.MethodType(_fetch_capital_advice, t)
        t._apply_capital_control_to_position = types.MethodType(_apply_capital_control_to_position, t)
        # perf_tracker：get_balance 失败（我的 mock 没配置）时，走 perf_tracker.current_equity
        t.perf_tracker = MagicMock()
        t.perf_tracker.current_equity = 2070.0
        # 让 get_balance 返回 False ok，避免 td_mode == isolated 分支 覆盖 available_equity
        t.okx_client = MagicMock()
        t.okx_client.cfg = {"default_leverage": 5.0, "td_mode": "cross", "default_inst_id": "UNI-USDT-SWAP"}
        t.okx_client.get_balance.return_value = {"ok": False}
        t.okx_client.get_available_balance.return_value = {"ok": True, "total_eq": 2070.0, "assets": {"USDT": {"avail": 1800.0, "eq": 2070.0}}}
        t.okx_client.get_positions.return_value = {"ok": True, "positions": []}
        t.okx_client._usdt_to_sz.return_value = 12.31
        t.risk_manager = MagicMock()
        t.risk_manager.calc_position_size = MagicMock(return_value={
            "position_usdt": 100.0, "margin_usdt": 20.0, "position_pct": 0.01,
            "confidence_factor": 1.13, "volatility_factor": 1.0,
            "kelly_factor": 1.0, "consecutive_loss_factor": 1.0,
            "hexagram_factor": 1.0, "vol_regime_factor": 1.0,
            "p2_base_multiplier": 1.0, "leverage": 5, "reason": "tdd_set_lev",
        })
        t.position_tracker = MagicMock(); t.position_tracker.all_open_positions.return_value = []
        def _apply_bdsm_cap(self, coin, position_usdt, *a, **kw):
            return (float(position_usdt), 1.0, "noop_cap")
        t._apply_bdsm_cap_multiplier = types.MethodType(_apply_bdsm_cap, t)
        def _apply_fuses(self, coin, position_usdt, direction, inf, *a, **kw):
            return (float(position_usdt), [], False, None)
        t._apply_portfolio_risk_fuses = types.MethodType(_apply_fuses, t)
        t._compute_p2_dynamic_sizing_factors = lambda hex, lookback=30, min_samples=5: {
            "kelly_factor": 1.0, "consecutive_loss_factor": 1.0, "hexagram_factor": 1.0,
            "vol_regime_factor": 1.0, "vol_regime_class": "NORMAL",
            "vol_adaptive_sl_mult": 1.0, "vol_adaptive_tp_mult": 1.0,
            "win_rate": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            "win_streak": 0, "loss_streak": 0, "p2_base_multiplier": 1.0,
            "hexagram_class": "neutral",
        }
        t._get_regime_pred_multipliers = lambda *a, **kw: {"position_mult":1,"tp_mult":1,"sl_mult":1,"threshold_mult":1}
        t._get_current_price = lambda coin, *a, **kw: 8.1234
        t._get_base_sl_roi = lambda *a, **kw: 0.0644
        t._get_base_tp_roi = lambda *a, **kw: 0.1079
        t._enforce_sl_price_floor = lambda new_sl, entry, side, **kw: (new_sl, False, 0.0644, {})
        t._enforce_tp_price_floor = lambda new_tp, entry, side, **kw: (new_tp, False, 0.1079, {})
        t._parse_bearish_score_from_reason = lambda r: "NONE"
        t._parse_regime_from_reason = lambda r: "TRENDING_UP"
        t._check_hexagram_consistency = lambda *a, **kw: {"confidence_multiplier":1.0,"reason":"tdd","raise_a_floor_to":0.0}
        t._compute_long_position_multiplier = lambda self, s: 1.0
        t._compute_short_position_multiplier = lambda self, s: 1.0
        t._reload_enable_inject_if_stale = lambda self: None
        t._load_symbol_registry = lambda self: None
        t._save_exit_strategy_decision = lambda self, **kw: None
        t._cache_set = lambda self, *a, **kw: None
        t.initial_equity = 2000.0
        t.BDSM_COINS = frozenset(["UNI"])
        # 核心：okx_client 已在上面 定义。这里 补 call_order + set_leverage/market_open_long side_effect
        call_order = []
        # 重 设 覆盖 掉 上面 的 MagicMock()（保留 get_balance/get_available_balance/get_positions/_usdt_to_sz 预设）
        def _set_lev_side_effect(*a, **kw):
            call_order.append("set_leverage"); return {"ok": True}
        def _mol_side_effect(*a, **kw):
            call_order.append("market_open_long"); return {"ok": True, "ordId": "tdd-123", "clOrdId": "x", "avgPx": 8.12, "sz": 12.31}
        t.okx_client.set_leverage.side_effect = _set_lev_side_effect
        t.okx_client.market_open_long.side_effect = _mol_side_effect
        t.okx_client.set_take_profit = MagicMock(return_value={"ok": True})
        t.okx_client.set_stop_loss = MagicMock(return_value={"ok": True})
        t.infer_kline_from_price = lambda self, price, coin, volatility: []
        # mock 出必要的 instance attrs（_open_position 读 state.position_size_pct/min/max）
        t.state = MagicMock()
        t.state.position_size_pct = 0.20
        t.state.min_position_size_pct = 0.01
        t.state.max_position_size_pct = 0.20
        t.state.min_position_usdt = 10.0
        t.EXIT_CONFIRM_REQUIRED = False
        # 构造 最简 inference dict（覆盖 _open_position 关键字段）
        inference = {
            "coin": "UNI", "inst_id": "UNI-USDT-SWAP",
            "confidence": 0.88, "direction": "UP", "fail_closed": False,
            "is_ranging": False, "trend_strength": 0.8,
            "kline_data": [], "price": 8.1234, "volatility": 0.02,
            "stop_loss_px": 7.60, "take_profit_px": 9.00,
            "hexagram": "风雷益", "score_consensus": 0.8, "gate_base_threshold": 0.4,
            "regime_pred": "TRENDING_UP", "asset_class": "crypto_usdt",
            "snapshot": {"price":8.1234,"volatility":0.02,"is_ranging":False,"regime":"TRENDING_UP"},
            "market_snapshot": {"price":8.1234,"volatility":0.02,"is_ranging":False,"regime":"TRENDING_UP"},
            "_regime_pred": "TRENDING_UP",
            "consensus_breakdown": {"s_p":0.8,"s_e":0.8,"s_b":0.8},
        }
        # 调用 _open_position
        t._open_position(inference, is_reverse=False, is_trial=False)
        # RED 断言 A：set_leverage 被 调 1 次，参数 (inst_id, lever=5, mgn_mode=isolated)
        self.assertEqual(t.okx_client.set_leverage.call_count, 1,
                         f"FAIL-RED: set_leverage 调用次数={t.okx_client.set_leverage.call_count} 不是 1")
        lev_args = t.okx_client.set_leverage.call_args
        self.assertEqual(lev_args.kwargs.get("inst_id") or lev_args.args[0] if lev_args.args else lev_args.kwargs.get("inst_id"),
                         "UNI-USDT-SWAP", f"FAIL-RED: set_leverage inst_id 不对 args={lev_args}")
        # RED 断言 B：顺序必须 set_leverage 先 于 market_open_long
        self.assertEqual(call_order, ["set_leverage", "market_open_long"],
                         f"FAIL-RED: 调用 顺序 错。预期 set_leverage → market_open_long，实际={call_order}")
        # RED 断言 C：market_open_long 调 1 次
        self.assertEqual(t.okx_client.market_open_long.call_count, 1,
                         f"FAIL-RED: market_open_long 调用 次数={t.okx_client.market_open_long.call_count}")


# ═══════════════════════════════════════════════════════════════════════
# P0-A1 Phase 0 有效字段写入（cvs/trend_stop/value_exit 非 neutral）
# ═══════════════════════════════════════════════════════════════════════

class TestPhase0RealFieldWriteback(unittest.TestCase):
    """P0-A1: _build_coin_entry / write_snapshot 必须写回 Phase 0 真实值（非 neutral 默认）。

    旧快照问题：7 币 cvs=0、trend_stop=全零、value_exit.pf_pct=50（neutral 默认），
    导致实盘 polling_trader 读取时永远 FAIL-OPEN 回退 cap。
    """

    def test_build_coin_entry_contains_nonzero_phase0_fields(self) -> None:
        """对合成的真实K线构造 entry → ts_score/cvs/trend_stop/value_exit 必须非 neutral 默认。"""
        import json
        from bdsm_snapshot_writer import _build_coin_entry, _neutral_coin_entry
        from bdsm_snapshot_writer import _compute_cvs, _compute_value_exit, _compute_trend_stop

        # 用合成K线验证 Phase 0 写回逻辑在真实 snapshot 里会触发
        # 先造一条 neutral，再用合成 downtrend 数据跑 4 个 Phase 0 函数
        entry = _neutral_coin_entry("test_neutral")
        self.assertEqual(entry["technical_assessment"]["ts_score"], 0.0)
        self.assertEqual(entry["cvs"], 0.0)
        self.assertEqual(entry["trend_stop"]["action"], "none")
        self.assertEqual(entry["value_exit"]["pf_percentile"], 50.0)
        # 还需要顶层 alias（实盘 _apply_bdsm_scaling 读 coin_entry.get("ts_score")）
        self.assertIn("ts_score", entry,
                      f"实盘 _apply_bdsm_scaling 直接读 ts_score 顶层字段，当前缺失；keys={sorted(entry.keys())}")

        # 模拟 downtrend 超卖场景：TS(0.6) + BDS(0.4) → CVS>0 → 非零
        ts, _ = 0.6, 0.0
        cvs, ratio = _compute_cvs(bds_score=0.4, ts_score=ts)
        self.assertGreater(cvs, 0.0)
        self.assertGreaterEqual(ratio, 0.0)
        # 模拟高估场景：valuation_percentile=82（>80高估区）→ reduce30（BDS>0未泡沫线）
        ve = _compute_value_exit(bds_score=0.35, valuation_percentile=82)
        self.assertEqual(ve["action"], "reduce30")
        self.assertEqual(ve["pf_overvalued"], True)
        self.assertEqual(ve["pf_bubble"], False)
        # 极端泡沫=92 → full_exit
        ve92 = _compute_value_exit(bds_score=0.35, valuation_percentile=92)
        self.assertEqual(ve92["action"], "full_exit")
        self.assertEqual(ve92["pf_bubble"], True)

    def test_write_snapshot_fill_phase0_fields_if_klines(self) -> None:
        """write_snapshot 生成的 entry 含 technical_assessment/cvs/trend_stop/value_exit 四个 v1.3 字段结构完整。"""
        import json
        from bdsm_snapshot_writer import write_snapshot
        with __import__("tempfile").TemporaryDirectory() as tmpdir:
            path = write_snapshot(out_dir=tmpdir, dry_run_read_coin_data_from_db=False)
            with open(path) as f:
                data = json.load(f)
            for coin, entry in data["coins"].items():
                # 结构完整性（即使 FAIL-OPEN 中性也要有字段）
                for required in ("technical_assessment", "cvs", "cvs_ratio",
                                 "scaling_plan", "trend_stop", "value_exit"):
                    self.assertIn(required, entry, f"{coin} 缺 {required}")
                self.assertIsInstance(entry["cvs"], (int, float))
                self.assertIn("action", entry["trend_stop"])
                self.assertIn("action", entry["value_exit"])


if __name__ == "__main__":
    unittest.main(verbosity=2)