#!/usr/bin/env python3
"""
test_polling_mode_switch.py — Phase A TDD 测试集
对应 Spec §5.1: BCRM2 满仓算力重分配（开关 S1 = enable_mode_switch）

RED 失败原因：对应工具函数/分支/属性尚未实现。
GREEN 最小实现：严格按 Spec §3.1~§3.3 写最小可通过代码，不扩展。
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[3]  # 11-易经推理系统
sys.path.insert(0, str(ROOT))

from scripts.memory_l4.polling_trader import PollingTrader  # noqa: E402


# ──────────────────────────────────────────────────────────
# 辅助：构造最小 PollingTrader 实例（完全 patch 掉 __init__，避免真实加载模型/网络调用）
# ──────────────────────────────────────────────────────────
def _make_trader(coins=None, max_positions=3, enable_mode_switch=True):
    """使用 unittest.mock patch 掉 __init__，手动挂载最小必要属性，避免真实初始化开销。"""
    with patch.object(PollingTrader, "__init__", lambda self, *a, **kw: None):
        t = PollingTrader.__new__(PollingTrader)

    # ── 核心配置 ──
    default_coins = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"]
    t.coins = list(coins or default_coins)
    t.max_positions = max_positions

    # ── 4 个 Feature Flag（Phase A 先只挂 S1，其他 Flag Phase B/C 再加时补 None）──
    t.enable_mode_switch = enable_mode_switch
    # Phase B/C 的开关占位（None 未启用，确保开关关闭时分支走旧路径语义）
    t.enable_ev_radar = None       # Phase B 再设
    t.enable_multi_horizon = None  # Phase C
    t.enable_ranked_tp = None      # Phase C

    # ── 持仓跟踪 + OKX（默认返回空，让 monkeypatch 覆盖更方便）──
    t.position_tracker = MagicMock(spec=["all_open_positions", "all_closed_positions"])
    t.position_tracker.all_open_positions.return_value = []
    t.position_tracker.all_closed_positions.return_value = []
    t.okx_client = MagicMock(spec=["get_positions", "cfg"])
    t.okx_client.get_positions.return_value = {"ok": True, "positions": []}

    # ── 黑名单 & 辅助方法默认桩（monkeypatch 可覆盖）──
    t.blacklist_coins = set()
    t.dynamic_blacklist = {}
    t.DYNAMIC_BLACKLIST_CONSECUTIVE_LOSSES = 2
    t.DYNAMIC_BLACKLIST_DURATION_SEC = 3 * 86400
    t._check_dynamic_blacklist = MagicMock(return_value=False)

    # ── MODE 阈值常量（对齐 Spec §3.2）──
    t.MODE_OCCUPANCY_MODE3 = 1.00
    t.MODE_OCCUPANCY_MODE2 = 2 / 3    # 2/3 ≈ 0.6667，保证 2of3 场景严格命中 MODE2
    t.MODE3_COARSE_CANDIDATE_TOPN = 3

    # ── 缓存 TTL 常量（对齐 Spec §3.3）──
    t.MODE_CACHE_TTL_ANOMALY = 2
    t.MODE_CACHE_TTL_INFER_COARSE = 1
    t.MODE_CACHE_TTL_KLINE_SHORT = 1
    t.MODE_CACHE_TTL_HORIZON_PREDS = 2
    t.MODE_CACHE_TTL_POSITION_EV = 2
    t._cycle_idx = 0
    t._mode_cache = {}

    # ── 日志 & 计数（默认桩，可 monkeypatch 覆盖收集）──
    t._log = MagicMock()
    t._count_total_positions = MagicMock(return_value=0)

    return t


class TestSwitchOffMode(unittest.TestCase):
    """Spec 5.1 测试 1: 开关关闭 → MODE-OFF 且所有集合为全量"""

    def test_switch_off_mode_tag_is_MODE_OFF_and_full_sets_all_coins(self):
        """RED 失败原因: _decide_mode_coins 方法不存在"""
        t = _make_trader(coins=["A", "B", "C", "D", "E", "F"], max_positions=3,
                         enable_mode_switch=False)

        mode, anom, infer_full, infer_coarse = t._decide_mode_coins()

        self.assertEqual(mode, "MODE-OFF")
        self.assertListEqual(sorted(anom), sorted(t.coins))
        self.assertListEqual(sorted(infer_full), sorted(t.coins))
        self.assertListEqual(infer_coarse, [])


class TestMODE1Light(unittest.TestCase):
    """Spec 5.1 测试 2: 开关开 + occupancy=0 → MODE1_LIGHT 全量 full"""

    def test_switch_on_0_positions_is_MODE1_and_full_all_coins(self):
        """RED 失败原因: occupancy=0 判定分支没写"""
        t = _make_trader(coins=["A", "B", "C", "D", "E", "F"], max_positions=3)

        # monkeypatch 持仓计数为 0，且 OKX 也返回空
        t._count_total_positions.return_value = 0
        t.position_tracker.all_open_positions.return_value = []
        t.okx_client.get_positions.return_value = {"ok": True, "positions": []}
        t._check_dynamic_blacklist.return_value = False

        mode, anom, infer_full, infer_coarse = t._decide_mode_coins()

        self.assertEqual(mode, "MODE1_LIGHT")
        self.assertEqual(len(infer_coarse), 0)
        # MODE1_LIGHT: 所有候选池应在 infer_full 里
        for c in t.coins:
            self.assertIn(c, infer_full)


class TestMODE2Half(unittest.TestCase):
    """Spec 5.1 测试 3: 开关开 + occupancy=2/3 → MODE2_HALF"""

    def test_switch_on_2_of_3_positions_is_MODE2_half_sets(self):
        """RED 失败原因: occupancy>=0.67 分支未写"""
        t = _make_trader(
            coins=["BTC", "SOL", "XAU", "A", "B", "C", "D", "E", "F", "G", "H", "I"],
            max_positions=3,
        )

        # 持仓 2 个：BTC + SOL
        held = ["BTC", "SOL"]
        pos_records = [MagicMock(coin="BTC"), MagicMock(coin="SOL")]
        t._count_total_positions.return_value = 2
        t.position_tracker.all_open_positions.return_value = pos_records
        t.okx_client.get_positions.return_value = {
            "ok": True,
            "positions": [
                {"instId": "BTC-USDT-SWAP"},
                {"instId": "SOL-USDT-SWAP"},
            ],
        }
        t._check_dynamic_blacklist.return_value = False

        mode, anom, infer_full, infer_coarse = t._decide_mode_coins()

        self.assertEqual(mode, "MODE2_HALF")
        # 持仓币必须全部出现在 anom / infer_full 里
        for c in held:
            self.assertIn(c, anom, f"held {c} should be in anom_coins")
            self.assertIn(c, infer_full, f"held {c} should be in infer_full_coins")
        # MODE2_HALF: infer_coarse_candidate_n = 0
        self.assertEqual(len(infer_coarse), 0)
        # 候选 anom Top4、infer_full Top5
        candidate_pool = [c for c in t.coins if c not in held]
        # anom 候选 = Top4
        expected_anom_cand_n = 4
        actual_anom_cand = [c for c in anom if c not in held]
        self.assertEqual(len(actual_anom_cand), expected_anom_cand_n,
                         "MODE2 anom_coins should include Top4 candidates")
        # infer_full 候选 = Top5
        expected_full_cand_n = 5
        actual_full_cand = [c for c in infer_full if c not in held]
        self.assertEqual(len(actual_full_cand), expected_full_cand_n,
                         "MODE2 infer_full should include Top5 candidates")
        # 保证 held ∩ infer_full = 2 全部存在
        self.assertEqual(sum(1 for c in held if c in infer_full), 2)


class TestMODE3Full(unittest.TestCase):
    """Spec 5.1 测试 4: 开关开 + occupancy=3/3 → MODE3_FULL，Top1 补全推理钩子"""

    def test_switch_on_3_of_3_positions_is_MODE3_full_top3_coarse_top1_toppedup(self):
        """RED 失败原因: MODE3 分支 + coarse 分支 + 补全推理钩子未写"""
        # 12 个币种：3 持仓 + 9 候选
        coins = ["BTC", "SOL", "XAU"] + [f"CAND{i}" for i in range(1, 10)]
        t = _make_trader(coins=coins, max_positions=3)

        held = ["BTC", "SOL", "XAU"]
        pos_records = [MagicMock(coin=c) for c in held]
        t._count_total_positions.return_value = 3
        t.position_tracker.all_open_positions.return_value = pos_records
        t.okx_client.get_positions.return_value = {
            "ok": True,
            "positions": [{"instId": f"{c}-USDT-SWAP"} for c in held],
        }
        t._check_dynamic_blacklist.return_value = False

        mode, anom, infer_full, infer_coarse = t._decide_mode_coins()

        self.assertEqual(mode, "MODE3_FULL")
        # anom = held3 + Top3 candidates = 6
        self.assertEqual(len(anom), 6, "MODE3 anom_coins should be held3+Top3 cand")
        for c in held:
            self.assertIn(c, anom)
            self.assertIn(c, infer_full)
        # infer_full 中候选 = 0（只含 held）
        infer_full_candidates = [c for c in infer_full if c not in held]
        self.assertEqual(len(infer_full_candidates), 0,
                         "MODE3 infer_full should not include candidate coins (0 full)")
        # infer_coarse = Top3 candidates
        self.assertEqual(len(infer_coarse), 3, "MODE3 infer_coarse should be Top3 cand")

        # --- coarse Top1 → topup_full_coins 补全推理钩子 ---
        # 模拟推理阶段粗推理返回的 confidence 降序：粗 Top1 应被加入 topup_full
        coarse_inferences = {}
        # 给 infer_coarse 的 3 个币打标 + 置信度（第 1 个 = 最高 0.9）
        confidences = [0.90, 0.80, 0.70]
        for i, coin in enumerate(infer_coarse):
            coarse_inferences[coin] = {
                "direction": 1,
                "confidence": confidences[i],
                "next_state": {"direction": 1, "confidence": confidences[i], "derivation": "test"},
                "hexagram": {"name": "乾为天"},
                "_coarse": True,
            }
        # 如果 Phase A-3 的补全函数存在就调用，否则 RED 阶段该方法会抛 AttributeError
        sorted_coarse = sorted(
            infer_coarse,
            key=lambda c: coarse_inferences.get(c, {}).get("confidence", 0.0),
            reverse=True,
        )
        expected_topup_top1 = sorted_coarse[0]

        # 运行 _pick_topup_from_coarse（如果 RED 阶段不存在则 AttributeError = 正确失败）
        topup_list = t._pick_topup_from_coarse(infer_coarse, coarse_inferences)
        self.assertEqual(len(topup_list), 1)
        self.assertEqual(topup_list[0], expected_topup_top1,
                         f"Top1 补全推理应是粗置信度最高的 {expected_topup_top1}")


class TestCycleCacheTTL(unittest.TestCase):
    """Spec 5.1 测试 5: 缓存 TTL 用 self._cycle_idx（非 wall-clock）"""

    def test_cycle_cache_ttl_expires_after_2_cycles_anomaly_and_1_cycle_kline(self):
        """RED 失败原因: _cache_get/_cache_set 不存在"""
        t = _make_trader(coins=["BTC"], max_positions=3)

        key_anom = ("anom", "BTC")
        key_kline = ("kline_s", "BTC")

        # cycle=0 写入
        t._cycle_idx = 0
        t._cache_set(key_anom, "anom_payload")
        t._cache_set(key_kline, "kline_payload")

        # cycle=1 读取：两者都命中
        t._cycle_idx = 1
        ok1, v1 = t._cache_get(key_anom, t.MODE_CACHE_TTL_ANOMALY)
        ok2, v2 = t._cache_get(key_kline, t.MODE_CACHE_TTL_KLINE_SHORT)
        self.assertTrue(ok1 and v1 == "anom_payload", "anom cache should hit at cycle=1")
        self.assertTrue(ok2 and v2 == "kline_payload", "kline cache should hit at cycle=1")

        # cycle=2 读取：anomaly 命中（TTL=2），kline 过期（TTL=1）
        t._cycle_idx = 2
        ok1, v1 = t._cache_get(key_anom, t.MODE_CACHE_TTL_ANOMALY)
        ok2, _ = t._cache_get(key_kline, t.MODE_CACHE_TTL_KLINE_SHORT)
        self.assertTrue(ok1 and v1 == "anom_payload", "anom cache should hit at cycle=2 (TTL=2)")
        self.assertFalse(ok2, "kline cache should expire at cycle=2 (TTL=1)")

        # cycle=3 读取：两者都过期
        t._cycle_idx = 3
        ok1, _ = t._cache_get(key_anom, t.MODE_CACHE_TTL_ANOMALY)
        ok2, _ = t._cache_get(key_kline, t.MODE_CACHE_TTL_KLINE_SHORT)
        self.assertFalse(ok1, "anom cache should expire at cycle=3 (> TTL=2)")
        self.assertFalse(ok2, "kline cache should expire at cycle=3")


class TestMODE3CoarseMarkAndTopup(unittest.TestCase):
    """Spec 5.1 测试 6: coarse 推理必须打 _coarse=True 标，补全后清除标并打日志"""

    def test_MODE3_coarse_result_must_have_coarse_flag_and_then_toppedup_overwrite(self):
        """RED 失败原因: coarse 分支未打标 / topup_full 覆盖分支未写"""
        t = _make_trader(coins=["BTC", "SOL", "XAU", "C1", "C2", "C3"], max_positions=3)

        held = ["BTC", "SOL", "XAU"]
        pos_records = [MagicMock(coin=c) for c in held]
        t._count_total_positions.return_value = 3
        t.position_tracker.all_open_positions.return_value = pos_records
        t.okx_client.get_positions.return_value = {
            "ok": True,
            "positions": [{"instId": f"{c}-USDT-SWAP"} for c in held],
        }
        t._check_dynamic_blacklist.return_value = False

        log_calls = []

        def _fake_log(msg, level="INFO"):
            log_calls.append((level, msg))

        t._log.side_effect = _fake_log

        # 构造 3 个粗推理结果（_coarse=True 标记）
        all_inferences = {}
        coarse_coins = ["C1", "C2", "C3"]
        for i, c in enumerate(coarse_coins):
            # 调用工具函数 _mark_coarse_inference（RED 阶段不存在 → AttributeError）
            inf = {"confidence": 0.75 + 0.05 * i, "direction": 1,
                   "next_state": {"confidence": 0.75 + 0.05 * i}}
            t._mark_coarse_inference(inf)
            all_inferences[c] = inf

        # 断言粗结果全部有 _coarse=True
        for c in coarse_coins:
            self.assertTrue(all_inferences[c].get("_coarse") is True,
                            f"粗推理结果 {c} 必须标记 _coarse=True")

        # --- 模拟 Top1 补全推理覆盖 ---
        # 粗 Top1 = C3 (置信度最高 0.85)
        topup_coin = "C3"
        # 调用工具函数 _apply_topup_full（RED 阶段不存在 → AttributeError）
        full_inf = {"confidence": 0.88, "direction": 1,
                    "next_state": {"confidence": 0.88}}
        t._apply_topup_full(all_inferences, topup_coin, full_inf, coarse_confidence=0.85)

        # 补全后 _coarse 标记必须被清除
        self.assertNotIn("_coarse", all_inferences[topup_coin],
                         "补全推理后，_coarse 标记必须被覆盖/清除")
        # 必须存在 "[MODE3][补全推理]" 日志
        self.assertTrue(
            any("[补全推理]" in msg for _, msg in log_calls),
            "补全推理必须打日志包含 '[补全推理]' 字样\n实际日志: " + str(log_calls),
        )


class TestMODE3CoarseOpenGate(unittest.TestCase):
    """Spec 5.1 测试 7: 粗结果未补全 → 新开仓门禁必须跳过，绝不调用 _open_position"""

    def test_MODE3_new_open_without_toppedup_must_raise_guard_error(self):
        """RED 失败原因: Phase3 开仓门禁分支未写"""
        t = _make_trader(coins=["BTC", "SOL", "XAU", "C1", "C2"], max_positions=3)

        held = ["BTC", "SOL", "XAU"]
        pos_records = [MagicMock(coin=c) for c in held]
        t._count_total_positions.return_value = 3
        t.position_tracker.all_open_positions.return_value = pos_records
        t.okx_client.get_positions.return_value = {
            "ok": True,
            "positions": [{"instId": f"{c}-USDT-SWAP"} for c in held],
        }
        t._check_dynamic_blacklist.return_value = False

        warn_logs = []
        info_logs = []

        def _fake_log(msg, level="INFO"):
            if level in ("WARN", "ERROR"):
                warn_logs.append(msg)
            else:
                info_logs.append(msg)

        t._log.side_effect = _fake_log

        # 伪造 C1 的粗推理结果（_coarse=True），但 C1 未在补全列表里
        open_position_calls = []

        def _fake_open_position(*a, **kw):
            open_position_calls.append(True)
            raise AssertionError("门禁未通过却调用了 _open_position！")

        t._open_position = _fake_open_position

        # 调用门禁工具函数 _guard_coarse_not_toppedup（RED 阶段不存在 → AttributeError）
        toppedup_history = set()  # C1 从未补全
        coarse_inf = {
            "confidence": 0.86, "direction": 1, "_coarse": True,
            "next_state": {"confidence": 0.86, "direction": 1, "derivation": "x"},
            "hexagram": {"name": "乾为天"},
        }
        passed = t._guard_coarse_not_toppedup("C1", coarse_inf, toppedup_history)

        # 门禁必须返回 False（不能过）
        self.assertFalse(passed, "粗推理 + 未补全 → 门禁必须返回 False 阻止开仓")
        # 必须有告警日志（warn 或 info 中含 未补全/门禁）
        all_logs = warn_logs + info_logs
        self.assertTrue(
            any("未补全" in m or "门禁" in m or "coarse" in m.lower() for m in all_logs),
            "门禁未通过时必须打 WARN 日志\n实际 logs: " + str(all_logs),
        )
        # _open_position 从未被调用
        self.assertEqual(len(open_position_calls), 0,
                         "_open_position 绝对不能在门禁未通过时被调用")


# =====================================================================
# Phase A 补充: 边界场景 TDD（缓存 purge / 黑名单过滤 / cycle 集成 / occupancy 边界）
# =====================================================================
class TestCachePurgeMechanism(unittest.TestCase):
    """Spec §3.3: _cache_set 每 30 轮 purge 超 TTL×4 的条目防 OOM。"""

    def test_purge_at_cycle_30_removes_stale_entries(self):
        """cycle=30 时触发 purge，written_cycle < 30 - max_ttl*4 的条目被清理。"""
        t = _make_trader(coins=["BTC"], max_positions=3)
        # max_ttl = max(2,1,1,2,2) = 2 → cutoff = 30 - 8 = 22
        # 写入三条：cycle=10（过期）、cycle=20（过期）、cycle=25（保留）
        t._cycle_idx = 10
        t._cache_set(("old",), "old_payload")
        t._cycle_idx = 20
        t._cache_set(("mid",), "mid_payload")
        t._cycle_idx = 25
        t._cache_set(("fresh",), "fresh_payload")
        self.assertEqual(len(t._mode_cache), 3)

        # cycle=30 触发 purge → cutoff=22 → old(10) 和 mid(20) 被清
        t._cycle_idx = 30
        t._cache_set(("trigger",), "trigger_payload")
        self.assertNotIn(("old",), t._mode_cache, "cycle=10 的条目应被 purge")
        self.assertNotIn(("mid",), t._mode_cache, "cycle=20 的条目应被 purge")
        self.assertIn(("fresh",), t._mode_cache, "cycle=25 的条目应保留")
        self.assertIn(("trigger",), t._mode_cache, "新写入的条目应存在")

    def test_no_purge_when_cycle_not_multiple_of_30(self):
        """cycle 非 30 倍数时不触发 purge。"""
        t = _make_trader(coins=["BTC"], max_positions=3)
        t._cycle_idx = 10
        t._cache_set(("stale",), "stale_payload")
        # cycle=29 不触发 purge
        t._cycle_idx = 29
        t._cache_set(("new",), "new_payload")
        self.assertIn(("stale",), t._mode_cache, "非 30 倍数不应 purge")


class TestDynamicBlacklistFiltering(unittest.TestCase):
    """Spec §3.2: 动态黑名单中的币种应从候选池中排除。"""

    def test_blacklisted_coin_excluded_from_candidate_pool(self):
        """_decide_mode_coins 中动态黑名单币不出现在 anom/infer_full/infer_coarse。"""
        t = _make_trader(
            coins=["BTC", "SOL", "XAU", "BAD", "C1", "C2"],
            max_positions=3,
        )
        # 空仓 → MODE1_LIGHT → 全量候选
        t._count_total_positions.return_value = 0
        t.position_tracker.all_open_positions.return_value = []
        t.okx_client.get_positions.return_value = {"ok": True, "positions": []}

        # BAD 币被动态黑名单拦截
        def _fake_blacklist(coin):
            if coin == "BAD":
                return True
            return False
        t._check_dynamic_blacklist = MagicMock(side_effect=_fake_blacklist)

        mode, anom, infer_full, infer_coarse = t._decide_mode_coins()

        self.assertEqual(mode, "MODE1_LIGHT")
        self.assertNotIn("BAD", anom, "黑名单币不应出现在 anom_coins")
        self.assertNotIn("BAD", infer_full, "黑名单币不应出现在 infer_full_coins")
        # 其余 5 个币正常
        for c in ["BTC", "SOL", "XAU", "C1", "C2"]:
            self.assertIn(c, anom)

    def test_static_blacklist_also_excluded(self):
        """静态黑名单（blacklist_coins set）同样排除。"""
        t = _make_trader(coins=["A", "B", "C", "D"], max_positions=3)
        t._count_total_positions.return_value = 0
        t.position_tracker.all_open_positions.return_value = []
        t.okx_client.get_positions.return_value = {"ok": True, "positions": []}
        t._check_dynamic_blacklist.return_value = False
        t.blacklist_coins = {"B"}

        mode, anom, infer_full, _ = t._decide_mode_coins()
        self.assertNotIn("B", anom)
        self.assertNotIn("B", infer_full)
        for c in ["A", "C", "D"]:
            self.assertIn(c, anom)


class TestAdvanceCycleIdxIntegration(unittest.TestCase):
    """_advance_cycle_idx 在 Phase A run_once 入口的集成行为。"""

    def test_normal_advance_monotonic(self):
        """连续调用 _advance_cycle_idx 时 cycle_idx 单调递增。"""
        t = _make_trader(coins=["BTC"], max_positions=3)
        idx1 = t._advance_cycle_idx()
        idx2 = t._advance_cycle_idx()
        idx3 = t._advance_cycle_idx()
        self.assertEqual(idx1, 1)
        self.assertEqual(idx2, 2)
        self.assertEqual(idx3, 3)

    def test_advance_preserves_cache_on_normal_progression(self):
        """正常推进时缓存不被清空。"""
        t = _make_trader(coins=["BTC"], max_positions=3)
        t._advance_cycle_idx()  # cycle=1
        t._cache_set(("key1",), "v1")
        t._advance_cycle_idx()  # cycle=2
        self.assertIn(("key1",), t._mode_cache)

    def test_rollback_clears_cache(self):
        """cycle_idx 被外部回退后，_advance_cycle_idx 检测到并清缓存。"""
        t = _make_trader(coins=["BTC"], max_positions=3)
        t._advance_cycle_idx()  # cycle=1
        t._advance_cycle_idx()  # cycle=2
        t._cache_set(("key1",), "v1")
        self.assertEqual(len(t._mode_cache), 1)

        # 模拟外部回退（日期 rollover / 状态恢复错误）
        t._cycle_idx = 0
        t._advance_cycle_idx()  # 检测到 0 < last_seen=2 → 清缓存
        self.assertEqual(len(t._mode_cache), 0,
                         "回退后缓存应被清空")


class TestOccupancyBoundaryValues(unittest.TestCase):
    """occupancy 边界值：1/3（MODE1/MODE2 之间）、恰好 2/3（MODE2 阈值）。"""

    def test_1_of_3_positions_is_MODE1_light(self):
        """occupancy = 1/3 ≈ 0.333 < 2/3 → MODE1_LIGHT（全量候选）。"""
        t = _make_trader(
            coins=["BTC", "SOL", "XAU", "A", "B", "C"],
            max_positions=3,
        )
        held = ["BTC"]
        t._count_total_positions.return_value = 1
        t.position_tracker.all_open_positions.return_value = [MagicMock(coin="BTC")]
        t.okx_client.get_positions.return_value = {
            "ok": True, "positions": [{"instId": "BTC-USDT-SWAP"}],
        }
        t._check_dynamic_blacklist.return_value = False

        mode, anom, infer_full, infer_coarse = t._decide_mode_coins()
        self.assertEqual(mode, "MODE1_LIGHT")
        self.assertEqual(len(infer_coarse), 0)
        # 全量候选都应在 infer_full 中
        for c in ["SOL", "XAU", "A", "B", "C"]:
            self.assertIn(c, infer_full)

    def test_exactly_2_of_3_is_MODE2_half(self):
        """occupancy = 2/3 = 0.6667 ≥ MODE_OCCUPANCY_MODE2 → MODE2_HALF。"""
        t = _make_trader(
            coins=["BTC", "SOL", "XAU", "A", "B", "C", "D", "E", "F", "G"],
            max_positions=3,
        )
        held = ["BTC", "SOL"]
        t._count_total_positions.return_value = 2
        t.position_tracker.all_open_positions.return_value = [MagicMock(coin=c) for c in held]
        t.okx_client.get_positions.return_value = {
            "ok": True, "positions": [{"instId": f"{c}-USDT-SWAP"} for c in held],
        }
        t._check_dynamic_blacklist.return_value = False

        mode, _, _, infer_coarse = t._decide_mode_coins()
        self.assertEqual(mode, "MODE2_HALF")
        self.assertEqual(len(infer_coarse), 0)


class TestMODE3CandidateShortfall(unittest.TestCase):
    """MODE3 候选不足 TopN 时的降级行为。"""

    def test_MODE3_with_only_2_candidates_coarse_gets_2(self):
        """满仓但候选只有 2 个（< TopN=3）→ infer_coarse 取 min(2, 3) = 2。"""
        t = _make_trader(
            coins=["BTC", "SOL", "XAU", "C1", "C2"],  # 3 held + 2 candidates
            max_positions=3,
        )
        held = ["BTC", "SOL", "XAU"]
        t._count_total_positions.return_value = 3
        t.position_tracker.all_open_positions.return_value = [MagicMock(coin=c) for c in held]
        t.okx_client.get_positions.return_value = {
            "ok": True, "positions": [{"instId": f"{c}-USDT-SWAP"} for c in held],
        }
        t._check_dynamic_blacklist.return_value = False

        mode, anom, infer_full, infer_coarse = t._decide_mode_coins()
        self.assertEqual(mode, "MODE3_FULL")
        # anom = held3 + Top3 candidates，但只有 2 个 → anom = 5
        self.assertEqual(len(anom), 5)
        # infer_full = held3 only (0 candidates)
        self.assertEqual(len(infer_full), 3)
        # infer_coarse = 2 (不是 3，因为只有 2 个可用)
        self.assertEqual(len(infer_coarse), 2,
                         "候选不足 TopN 时应取实际可用数量")

    def test_MODE3_with_zero_candidates(self):
        """满仓且无候选（所有币都在持仓中）→ infer_coarse 为空。"""
        t = _make_trader(coins=["BTC", "SOL", "XAU"], max_positions=3)
        held = ["BTC", "SOL", "XAU"]
        t._count_total_positions.return_value = 3
        t.position_tracker.all_open_positions.return_value = [MagicMock(coin=c) for c in held]
        t.okx_client.get_positions.return_value = {
            "ok": True, "positions": [{"instId": f"{c}-USDT-SWAP"} for c in held],
        }
        t._check_dynamic_blacklist.return_value = False

        mode, anom, infer_full, infer_coarse = t._decide_mode_coins()
        self.assertEqual(mode, "MODE3_FULL")
        self.assertEqual(len(infer_coarse), 0, "无候选时 infer_coarse 应为空")
        self.assertEqual(len(anom), 3, "anom 仅含持仓")


if __name__ == "__main__":
    unittest.main(verbosity=2)
