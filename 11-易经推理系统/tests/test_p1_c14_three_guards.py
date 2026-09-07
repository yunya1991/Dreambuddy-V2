"""P1 · C1④ 三条信息截止护栏 TDD（RED → GREEN）
SPEC: docs/superpowers/specs/2026-09-01-p1-c14-three-guards-design.md
护栏：
G1 卦×0.70+0.85地板（生产已生效·不动，用原test覆盖）
G2 EV门槛boost>0.05夹（≤0.05→boost清零回baseline）
G3 Vintage≤168h一周内 + 未来函数120s冷却（WHERE+dt断言双保险）
"""
from __future__ import annotations

import math
import os
import sys
import time
from typing import Any, Dict, List

import pytest

# 目录兼容：tests/ 目录下直接运行（sys.path 需要 root/11-易经推理系统）
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
MOD_DIR = os.path.join(ROOT, "scripts", "memory_l4")
if MOD_DIR not in sys.path:
    sys.path.insert(0, MOD_DIR)

from polling_trader import (  # noqa: E402  模块路径注入后导入
    compute_score_b_with_event_boost,
    _polling_get_coin_event_positive_strength,
)

# ---- 导入 DC 侧 compute_coin_event_positive_strength（用于G3-B）----
DC_ROOT = os.path.abspath(os.path.join(ROOT, os.pardir, "18-数据获取中心"))
if DC_ROOT not in sys.path:
    sys.path.insert(0, DC_ROOT)
from data_center.collectors.news.odaily_newsflash import (  # noqa: E402
    compute_coin_event_positive_strength,
)


# =========================================================================
# G2：EV门槛boost>0.05夹（7条 parametrize）
# =========================================================================
class TestG2EVThresholdGuard:
    # (strength, cont, conf_norm, exp_boost_range_or_zero, delta_from_baseline)
    @pytest.mark.parametrize(
        "strength,cont,conf_norm,exp_boost_eq0",
        [
            # （1）Fail-Open baseline：strength=None→boost=0=原v3.0公式（不进G2夹分支，原P0断言仍成立）
            (None, 0.70, 0.80, True),
            # （2）strength≤0.35不进boost计算→boost=0（不进G2夹）
            (0.34, 0.70, 0.80, True),
            # （3）典型吹票黑嘴：strength=0.40→raw_boost≈0.008→≤0.05→必须清零
            (0.40, 0.70, 0.80, True),
            # （4）中等正面：strength=0.50→raw≈0.023→≤0.05→必须清零
            (0.50, 0.70, 0.80, True),
            # （5）一条ARC主网单条：strength=0.60→raw≈0.038→≤0.05→必须清零（保守一条不抬）
            (0.60, 0.70, 0.80, True),
            # （6）边界0.050：strength=0.675→raw=0.10*(0.325)/0.65=0.050→必须清零（<=0.050）
            (0.675, 0.70, 0.80, True),
        ],
    )
    def test_g2_low_boost_cleared_to_zero(self, strength, cont, conf_norm, exp_boost_eq0):
        score_b, boost = compute_score_b_with_event_boost(cont, conf_norm, strength)
        baseline = 0.60 * cont + 0.40 * conf_norm
        if exp_boost_eq0:
            assert boost == pytest.approx(0.0, abs=1e-5), f"strength={strength}应boost=0但得{boost}"
            assert score_b == pytest.approx(baseline, abs=1e-5), f"strength={strength}应回baseline={baseline:.4f}但得{score_b:.4f}"
        else:
            assert boost > 0.05

    @pytest.mark.parametrize(
        "strength,cont,conf_norm,min_expected_boost",
        [
            # （7）刚过门槛：strength=0.676→boost≈0.05015→应>0.05放行
            (0.676, 0.70, 0.80, 0.050),
            # （8）强叠加：strength=0.85→boost=0.0769→>0.05放行
            (0.85, 0.70, 0.80, 0.070),
            # （9）上限：strength=1.00→boost=0.10（硬上限clamp）
            (1.00, 0.70, 0.80, 0.099),
        ],
    )
    def test_g2_high_boost_passes_above_05(self, strength, cont, conf_norm, min_expected_boost):
        score_b, boost = compute_score_b_with_event_boost(cont, conf_norm, strength)
        baseline = 0.60 * cont + 0.40 * conf_norm
        assert boost >= min_expected_boost, f"strength={strength}应boost≥{min_expected_boost}但得{boost}"
        assert boost <= 0.100, f"boost硬上限0.10但得{boost}"
        assert score_b > baseline, f"放行场景应score_b>{baseline:.4f}但得{score_b:.4f}"


# =========================================================================
# G3-B：DC侧 dt 断言（dt>168h/dt<0→weight=0，不参与strength）3条
# =========================================================================
class TestG3DCSideWeightAssert:
    def _rec(self, dt_hrs: float, sentiment=0.9, important=True, event_type="token_milestone"):
        now_fixed_ms = 1_760_000_000_000
        published_ms = int(now_fixed_ms - dt_hrs * 3_600_000) if dt_hrs >= 0 else int(now_fixed_ms + (-dt_hrs) * 3_600_000)
        imp = 2 if important else 1
        decay_hl = {"token_milestone": 24, "market_sentiment": 12}.get(event_type, 36)
        return {
            "metrics": {
                "od_event_type": event_type,
                "od_policy_sentiment_0_1": sentiment,
                "od_is_important": "true" if important else "false",
                "od_decay_hl_hrs": decay_hl,
            },
            "events": [{"event_type": event_type, "importance": imp, "published_ms": published_ms}],
            "tickers_hit": ["CRCL"],
        }

    def test_g3b_outdated_170h_is_weighted_zero(self):
        now_ms = 1_760_000_000_000
        # 混2条：一条dt=3h(有效正面) + 一条dt=170h(超龄应weight=0)
        recs = [self._rec(3.0, 0.95, True), self._rec(170.0, 0.95, True)]
        strength, dbg = compute_coin_event_positive_strength("CRCL", recs, now_ms=now_ms)
        # 仅按单条dt=3h算：sentiment=0.95 * decay=0.5^(3/24)=0.917 * evt_weight=1.2 * importance=2.0
        # 单项= 0.95*0.917*1.2*2.0=2.09 → clip 1.6。mean≈max≈1.6。0.6*1.6+0.4*1.6=1.6→clip到1.0。
        # 如果170h的也参与（权重非0）→ strength会明显高于只一条参与的：所以strength≤1.0且dbg['hit']=1
        assert dbg["hit"] == 1, f"超龄170h应被丢弃，只1条命中但dbg={dbg}"
        assert 0.90 <= strength <= 1.0, f"单条dt=3h有效正面应≥0.9但strength={strength:.3f}"

    def test_g3b_negative_dt_future_leak_weighted_zero(self):
        now_ms = 1_760_000_000_000
        # dt=-6h = 未来6小时=未来泄漏 → weight=0；另配一条dt=5h有效
        recs = [self._rec(-6.0, 0.95, True), self._rec(5.0, 0.90, True)]
        strength, dbg = compute_coin_event_positive_strength("CRCL", recs, now_ms=now_ms)
        assert dbg["hit"] == 1, f"未来dt=-6h应被丢弃；dbg={dbg}"
        assert 0.85 <= strength <= 1.0

    def test_g3b_valid_range_0_to_168_all_counted(self):
        now_ms = 1_760_000_000_000
        # dt=0h, 84h, 168h 共3条（均在[0,168]范围）
        recs = [self._rec(0.0, 0.9, True), self._rec(84.0, 0.88, False), self._rec(168.0, 0.85, True)]
        strength, dbg = compute_coin_event_positive_strength("CRCL", recs, now_ms=now_ms)
        assert dbg["hit"] == 3, f"3条有效应全命中；dbg={dbg}"
        assert strength > 0.70, f"3条有效正面应strength>0.7，但strength={strength:.3f}"


# =========================================================================
# G3-A：DB桥 Vintage/未来过滤（6条·使用临时SQLite模拟data_center.db）
# =========================================================================
class TestG3AVintageAndFutureOnDBBridge:
    DB_PATH = "/tmp/_ut_p1_c14_odaily.db"

    @pytest.fixture(autouse=True)
    def _setup_db(self):
        # 清理
        if os.path.isfile(self.DB_PATH):
            os.remove(self.DB_PATH)
        import sqlite3
        conn = sqlite3.connect(self.DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                category TEXT DEFAULT 'news',
                sub_category TEXT DEFAULT 'flash',
                timestamp TEXT,
                metrics TEXT DEFAULT '{}',
                events TEXT DEFAULT '[]',
                timeseries TEXT DEFAULT '{}',
                raw TEXT DEFAULT '{}'
            )"""
        )
        # 插入7条 mock odaily_newsflash（不同dt_ms+CRCL ticker命中）
        now_ms = int(time.time() * 1000)
        rows = []
        cases = [
            ("future_60s", now_ms + 60_000, 0.95, True),          # 未来60s（120s冷却内→应丢弃）
            ("cooling_60s_ago", now_ms - 60_000, 0.95, True),     # 60s前 <120s→冷却内→丢弃
            ("cooling_121s_ago", now_ms - 121_000, 0.95, True),   # 121s前 >冷却→保留
            ("dt_5d_ago", now_ms - 5*24*3600_000, 0.92, False),  # 5天=120h ≤168h→保留
            ("dt_168h_boundary", now_ms - 168*3600_000, 0.90, True),  # 整整168h→按设计"≤168含"→保留
            ("dt_169h_over", now_ms - 169*3600_000, 0.95, True),  # 169h→超龄→丢弃
            ("dt_200h_over", now_ms - 200*3600_000, 0.95, True),  # 200h→超龄→丢弃
        ]
        for name, ts, sentiment, important in cases:
            metrics_json = (
                '{"od_event_type":"token_milestone","od_policy_sentiment_0_1":' + str(sentiment) +
                ',"od_is_important":"' + ("true" if important else "false") +
                '","od_decay_hl_hrs":24,"od_tickers_hit_csl":"CRCL","od_title_hash":"' + name[:8] + '"}'
            )
            events_json = (
                '[{"event_type":"token_milestone","importance":' + ("2" if important else "1") +
                ',"published_ms":' + str(ts) + '}]'
            )
            raw_json = '{"tickers_hit":["CRCL"],"title":"CRCL mock ' + name + '"}'
            # timestamp列：传 int ms级（polling_trader.py L279-284 → tv>1e12 → pub_ms=int(tv) 直接命中正确分支）
            rows.append(("odaily_newsflash", "news", "flash", int(ts), metrics_json, events_json, '{}', raw_json))
        cur.executemany(
            "INSERT INTO records(source,category,sub_category,timestamp,metrics,events,timeseries,raw) "
            "VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
        conn.close()

        # monkey-patch：临时改 _polling_get_coin_event_positive_strength 用到的 DB 路径
        import polling_trader as pt_mod
        orig_func = pt_mod._polling_get_coin_event_positive_strength.__globals__.get("os")
        self._orig_env = os.environ.get("DATA_CENTER_DB_PATH")
        # DATA_CENTER_DB_PATH 不是环境变量直接用？实际是用相对路径拼 → 改为直接把 DATA_CENTER_DB 路径传进：重写模块级_ODAILY_DB_PATH
        self._orig_db_path = getattr(pt_mod, "_P1_UT_DB_PATH_OVERRIDE", None)
        # 直接注入 override：给 _polling_get_coin_event_positive_strength 函数所在模块注入测试DB路径
        pt_mod._P1_C14_TEST_DB_OVERRIDE = self.DB_PATH
        yield
        # teardown
        if hasattr(pt_mod, "_P1_C14_TEST_DB_OVERRIDE"):
            delattr(pt_mod, "_P1_C14_TEST_DB_OVERRIDE")
        if os.path.isfile(self.DB_PATH):
            os.remove(self.DB_PATH)

    @pytest.mark.parametrize(
        "_name,expected_hit_min,expected_hit_max",
        [
            ("只保留 121s前+5d+168h边界 共3条", 3, 3),
        ],
    )
    def test_g3a_only_recent_week_and_post_cooling_counted(self, _name, expected_hit_min, expected_hit_max):
        # 注意：_polling_get_coin_event_positive_strength 内部是硬编码 data_center.db路径 → 需要先改它：
        # 用 monkeypatch 包一层：实际调用时模块级 _P1_C14_TEST_DB_OVERRIDE 存在→用它
        strength, dbg = _polling_get_coin_event_positive_strength("CRCL")
        assert dbg["records_in_db"] >= 7, f"mock应写入7条；dbg={dbg}"
        assert expected_hit_min <= dbg["hit"] <= expected_hit_max, (
            f"仅 121s前/5d/整168h 3条应命中但 dbg_hit={dbg['hit']}；dbg={dbg}"
        )


# =========================================================================
# 向后兼容：原P0 test_p0_score_b_event_boost.py 9条T的核心断言不改
# =========================================================================
class TestThreeGuardsBackwardCompat:
    def test_p0_high_strength_still_boosted(self):
        """原P0断言：strength=0.85（强事件）应Score_B抬升"""
        score_b, boost = compute_score_b_with_event_boost(0.75, 0.80, 0.85)
        baseline = 0.60 * 0.75 + 0.40 * 0.80
        assert score_b > baseline + 0.06, f"strength=0.85应至少抬+0.06，Δ={score_b-baseline:.4f}"
        assert boost >= 0.07

    def test_p0_none_strength_exact_baseline(self):
        """Fail-Open基线字节等价原v3.0"""
        score_b, boost = compute_score_b_with_event_boost(0.62, 0.63, None)
        baseline = 0.60 * 0.62 + 0.40 * 0.63
        assert boost == pytest.approx(0.0, abs=1e-6)
        assert score_b == pytest.approx(baseline, abs=1e-6)

    def test_p0_clamp_10_percent_cap(self):
        """原P0断言：boost硬上限≤0.10"""
        _s, boost = compute_score_b_with_event_boost(0.99, 0.99, 1.00)
        assert boost <= 0.100001
        assert boost >= 0.099  # strength=1.00 顶格
