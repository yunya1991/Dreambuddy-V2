"""P1.5 SQLite 持久化 — TDD 测试

Spec §4.1-4.3 三张核心表 + dotplot 缓存表：
  regime_state_daily       每行 = symbol × timestamp
  regime_trajectory_90d    快捷快照（每 symbol 单行 JSON）
  regime_model_weights     周度在线学习权重
  regime_dotplot_latest    最新点阵图缓存

覆盖：
  T1. test_init_creates_schema           — 初始化创建 4 张表
  T2. test_upsert_daily_single           — 单条写入 + 读取一致
  T3. test_upsert_daily_batch            — 批量写入 + 读取
  T4. test_upsert_replaces_existing      — 同 PK 重写（INSERT OR REPLACE）
  T5. test_get_trajectory_window_90      — 默认 90 日窗口
  T6. test_get_trajectory_custom_window  — 自定义窗口
  T7. test_get_snapshot_latest           — 最新一日
  T8. test_get_snapshot_empty            — 空表返回 None
  T9. test_get_indicators_evolution      — 12 指标历史序列
  T10. test_save_dotplot_roundtrip       — 点阵图保存 + 读取
  T11. test_get_latest_dotplot_empty     — 未保存返回 None
  T12. test_save_weekly_weights          — 周度权重写入 + 读取
  T13. test_get_latest_weights_empty     — 空表返回 None
  T14. test_list_weights_history         — 历史权重列表
  T15. test_context_manager              — with 语法 + 自动 close
  T16. test_trajectory_snapshot_refreshed — 写入后 90d 快照同步更新
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

# —— 路径处理
_THIS_DIR = Path(__file__).resolve().parent
_BCRM2_ROOT = _THIS_DIR.parent
assert _BCRM2_ROOT.name == "memory_l4", "tests 需放在 memory_l4/tests 下"
if str(_BCRM2_ROOT) not in sys.path:
    sys.path.insert(0, str(_BCRM2_ROOT))

from bcrm2.storage import EvolutionStorageSQLite, RegimeStateFrame  # noqa: E402


# ====================================================================
# 辅助：构造测试 frame
# ====================================================================
def _make_frame(t: str, price: float = 50000.0,
                level: float = 1.0, trend: float = 0.5) -> RegimeStateFrame:
    """构造一个简单的 RegimeStateFrame。"""
    return RegimeStateFrame(
        t=t,
        price=price,
        level_raw=level,
        trend_raw=trend,
        level_smooth=level * 0.9,
        trend_smooth=trend * 0.9,
        regime_probs={
            "TREND_UP_STRONG": 0.5, "TREND_UP_MILD": 0.2,
            "RANGE_BOUND": 0.1, "CONSOLIDATION": 0.05,
            "REVERSAL": 0.05, "VOLATILE_DROP": 0.03,
            "FOMO_RALLY": 0.04, "DISTRIBUTION": 0.03,
        },
        top3=[["TREND_UP_STRONG", 0.5], ["TREND_UP_MILD", 0.2], ["RANGE_BOUND", 0.1]],
        consensus=0.65,
        hmm_state=2,
        bocpd_cp_prob=0.0,
        indicators={
            "ma200_above_3d": 1.0, "ma50_above": 1.0, "ma20_vs_ma50_order": 1.0,
            "cycle_position_365d": 0.5, "ma_alignment_score": 0.6,
            "ma200_slope_signed": 0.5, "dow_hhhl_score": 1.33,
            "log_ret_90d": 1.0, "log_ret_30d": 0.5, "ma_slope_wavg": 0.4,
            "volume_trend_conf": 0.5, "vol_60d_pct": 0.6,
        },
    )


def _make_n_frames(n: int, start_date: str = "2026-01-01") -> list:
    """构造 n 个 frame，日期从 start_date 开始递增。"""
    from datetime import datetime, timedelta
    base = datetime.strptime(start_date, "%Y-%m-%d")
    frames = []
    for i in range(n):
        t = (base + timedelta(days=i)).strftime("%Y-%m-%d")
        frames.append(_make_frame(t, price=50000 + i * 100, level=1.0 + i * 0.05))
    return frames


# ====================================================================
# T1. 初始化创建 schema
# ====================================================================
def test_init_creates_schema(tmp_path):
    """初始化后 4 张表都存在。"""
    db_path = tmp_path / "evolution.db"
    storage = EvolutionStorageSQLite(db_path)
    cur = storage._conn.cursor()
    tables = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()]
    storage.close()
    assert "regime_state_daily" in tables
    assert "regime_trajectory_90d" in tables
    assert "regime_model_weights" in tables
    assert "regime_dotplot_latest" in tables


def test_init_idempotent(tmp_path):
    """重复初始化同一 db 不报错（CREATE TABLE IF NOT EXISTS）。"""
    db_path = tmp_path / "evolution.db"
    s1 = EvolutionStorageSQLite(db_path)
    s1.upsert_daily("BTCUSDT", _make_frame("2026-01-01"))
    s1.close()
    # 再次打开
    s2 = EvolutionStorageSQLite(db_path)
    snap = s2.get_snapshot("BTCUSDT")
    s2.close()
    assert snap is not None
    assert snap["t"] == "2026-01-01"


# ====================================================================
# T2/T3. 单条 / 批量写入 + 读取
# ====================================================================
def test_upsert_daily_single(tmp_path):
    storage = EvolutionStorageSQLite(tmp_path / "evo.db")
    frame = _make_frame("2026-08-19", price=60000.0, level=2.0, trend=1.5)
    storage.upsert_daily("BTCUSDT", frame)

    snap = storage.get_snapshot("BTCUSDT")
    storage.close()
    assert snap is not None
    assert snap["t"] == "2026-08-19"
    assert snap["price"] == pytest.approx(60000.0, abs=1e-6)
    assert snap["level_raw"] == pytest.approx(2.0, abs=1e-6)
    assert snap["trend_smooth"] == pytest.approx(1.5 * 0.9, abs=1e-6)
    assert snap["regime_probs"]["TREND_UP_STRONG"] == pytest.approx(0.5, abs=1e-6)
    assert snap["hmm_state"] == 2
    assert snap["indicators"]["dow_hhhl_score"] == pytest.approx(1.33, abs=1e-6)


def test_upsert_daily_batch(tmp_path):
    storage = EvolutionStorageSQLite(tmp_path / "evo.db")
    frames = _make_n_frames(30, "2026-01-01")
    n = storage.upsert_daily_batch("BTCUSDT", frames)
    assert n == 30

    traj = storage.get_trajectory("BTCUSDT", 30)
    storage.close()
    assert len(traj) == 30
    assert traj[0]["t"] == "2026-01-01"
    assert traj[-1]["t"] == "2026-01-30"


# ====================================================================
# T4. 同 PK 重写
# ====================================================================
def test_upsert_replaces_existing(tmp_path):
    storage = EvolutionStorageSQLite(tmp_path / "evo.db")
    f1 = _make_frame("2026-08-19", price=50000.0, level=1.0)
    storage.upsert_daily("BTCUSDT", f1)

    f2 = _make_frame("2026-08-19", price=60000.0, level=2.5)
    storage.upsert_daily("BTCUSDT", f2)

    snap = storage.get_snapshot("BTCUSDT")
    storage.close()
    assert snap["price"] == pytest.approx(60000.0, abs=1e-6)
    assert snap["level_raw"] == pytest.approx(2.5, abs=1e-6)


# ====================================================================
# T5/T6. trajectory 窗口
# ====================================================================
def test_get_trajectory_window_90(tmp_path):
    storage = EvolutionStorageSQLite(tmp_path / "evo.db")
    frames = _make_n_frames(120, "2026-01-01")
    storage.upsert_daily_batch("BTCUSDT", frames)

    traj = storage.get_trajectory("BTCUSDT", 90)
    storage.close()
    assert len(traj) == 90
    # 最近 90 日 = 第 31..120 日（2026-01-01 + 30 天 = 2026-01-31，+119 天 = 2026-04-30）
    assert traj[0]["t"] == "2026-01-31"
    assert traj[-1]["t"] == "2026-04-30"


def test_get_trajectory_custom_window(tmp_path):
    storage = EvolutionStorageSQLite(tmp_path / "evo.db")
    frames = _make_n_frames(50, "2026-01-01")
    storage.upsert_daily_batch("BTCUSDT", frames)

    traj = storage.get_trajectory("BTCUSDT", 10)
    storage.close()
    assert len(traj) == 10
    # 最近 10 日 = 第 41..50 日（2026-01-01 + 40 天 = 2026-02-10，+49 天 = 2026-02-19）
    assert traj[0]["t"] == "2026-02-10"
    assert traj[-1]["t"] == "2026-02-19"


def test_get_trajectory_empty(tmp_path):
    storage = EvolutionStorageSQLite(tmp_path / "evo.db")
    traj = storage.get_trajectory("BTCUSDT", 90)
    storage.close()
    assert traj == []


# ====================================================================
# T7/T8. snapshot
# ====================================================================
def test_get_snapshot_latest(tmp_path):
    storage = EvolutionStorageSQLite(tmp_path / "evo.db")
    frames = _make_n_frames(10, "2026-01-01")
    storage.upsert_daily_batch("BTCUSDT", frames)

    snap = storage.get_snapshot("BTCUSDT")
    storage.close()
    assert snap["t"] == "2026-01-10"
    assert snap["price"] == pytest.approx(50000 + 9 * 100, abs=1e-6)


def test_get_snapshot_empty(tmp_path):
    storage = EvolutionStorageSQLite(tmp_path / "evo.db")
    snap = storage.get_snapshot("BTCUSDT")
    storage.close()
    assert snap is None


# ====================================================================
# T9. indicators 历史序列
# ====================================================================
def test_get_indicators_evolution(tmp_path):
    storage = EvolutionStorageSQLite(tmp_path / "evo.db")
    frames = _make_n_frames(20, "2026-01-01")
    storage.upsert_daily_batch("BTCUSDT", frames)

    names = ["ma200_above_3d", "dow_hhhl_score", "vol_60d_pct"]
    evolution = storage.get_indicators_evolution("BTCUSDT", names, window=20)
    storage.close()
    assert set(evolution.keys()) == set(names)
    for name in names:
        assert len(evolution[name]) == 20
        # 第一日的值
        assert evolution[name][0] == pytest.approx(_make_frame("x").indicators[name], abs=1e-6)


def test_get_indicators_evolution_subset_window(tmp_path):
    """指定 window < 全量数据时返回最近 N 日。"""
    storage = EvolutionStorageSQLite(tmp_path / "evo.db")
    frames = _make_n_frames(50, "2026-01-01")
    storage.upsert_daily_batch("BTCUSDT", frames)

    evolution = storage.get_indicators_evolution("BTCUSDT", ["ma200_above_3d"], window=10)
    storage.close()
    assert len(evolution["ma200_above_3d"]) == 10


# ====================================================================
# T10/T11. dotplot 缓存
# ====================================================================
def test_save_dotplot_roundtrip(tmp_path):
    storage = EvolutionStorageSQLite(tmp_path / "evo.db")
    dotplot = {
        "rows": ["ma200_above_3d", "ma50_above"],
        "cols": ["TREND_UP_STRONG", "RANGE_BOUND"],
        "matrix": [[0.8, 0.3], [0.6, 0.5]],
        "marginal_probs": [0.6, 0.4],
        "target_index": 99,
        "sample_counts": {"TREND_UP_STRONG": 50, "RANGE_BOUND": 30},
    }
    storage.save_dotplot("BTCUSDT", dotplot)

    loaded = storage.get_latest_dotplot("BTCUSDT")
    storage.close()
    assert loaded is not None
    assert loaded["rows"] == ["ma200_above_3d", "ma50_above"]
    assert loaded["cols"] == ["TREND_UP_STRONG", "RANGE_BOUND"]
    assert loaded["matrix"] == [[0.8, 0.3], [0.6, 0.5]]
    assert loaded["marginal_probs"] == [0.6, 0.4]
    assert loaded["target_index"] == 99
    assert loaded["sample_counts"]["TREND_UP_STRONG"] == 50


def test_get_latest_dotplot_empty(tmp_path):
    storage = EvolutionStorageSQLite(tmp_path / "evo.db")
    loaded = storage.get_latest_dotplot("BTCUSDT")
    storage.close()
    assert loaded is None


def test_save_dotplot_replaces(tmp_path):
    storage = EvolutionStorageSQLite(tmp_path / "evo.db")
    storage.save_dotplot("BTCUSDT", {"matrix": [[0.5]], "target_index": 0})
    storage.save_dotplot("BTCUSDT", {"matrix": [[0.9]], "target_index": 1})

    loaded = storage.get_latest_dotplot("BTCUSDT")
    storage.close()
    assert loaded["matrix"] == [[0.9]]
    assert loaded["target_index"] == 1


# ====================================================================
# T12/T13/T14. 周度权重
# ====================================================================
def test_save_weekly_weights(tmp_path):
    storage = EvolutionStorageSQLite(tmp_path / "evo.db")
    weights_obj = {
        "level_weights": {"ma200_above_3d": 2.0, "ma50_above": 1.0},
        "trend_weights": {"dow_hhhl_score": 2.0, "log_ret_90d": 1.5},
        "regime_centers": {"TREND_UP_STRONG": [2.0, 3.0]},
        "max_daily_delta": 0.5,
    }
    storage.save_weekly_weights(date(2026, 8, 18), weights_obj, 0.657, "accepted")

    loaded = storage.get_latest_weights()
    storage.close()
    assert loaded is not None
    assert loaded["week_start"] == "2026-08-18"
    assert loaded["level_weights"]["ma200_above_3d"] == pytest.approx(2.0, abs=1e-6)
    assert loaded["trend_weights"]["dow_hhhl_score"] == pytest.approx(2.0, abs=1e-6)
    assert loaded["regime_centers"]["TREND_UP_STRONG"] == [2.0, 3.0]
    assert loaded["max_daily_delta"] == pytest.approx(0.5, abs=1e-6)
    assert loaded["objective"] == pytest.approx(0.657, abs=1e-6)
    assert loaded["comment"] == "accepted"


def test_get_latest_weights_empty(tmp_path):
    storage = EvolutionStorageSQLite(tmp_path / "evo.db")
    loaded = storage.get_latest_weights()
    storage.close()
    assert loaded is None


def test_list_weights_history(tmp_path):
    storage = EvolutionStorageSQLite(tmp_path / "evo.db")
    # 写入 3 周历史
    for i, ws in enumerate(["2026-08-04", "2026-08-11", "2026-08-18"]):
        storage.save_weekly_weights(
            ws,
            {"level_weights": {}, "trend_weights": {}, "regime_centers": {},
             "max_daily_delta": 0.5},
            objective=0.5 + i * 0.1,
            comment=f"week_{i}",
        )

    history = storage.list_weights_history(limit=10)
    storage.close()
    assert len(history) == 3
    # 最近的在前
    assert history[0]["week_start"] == "2026-08-18"
    assert history[0]["objective"] == pytest.approx(0.7, abs=1e-6)
    assert history[0]["comment"] == "week_2"


# ====================================================================
# T15. 上下文管理器
# ====================================================================
def test_context_manager(tmp_path):
    db_path = tmp_path / "evo.db"
    with EvolutionStorageSQLite(db_path) as storage:
        storage.upsert_daily("BTCUSDT", _make_frame("2026-08-19"))
        snap = storage.get_snapshot("BTCUSDT")
    assert snap is not None
    assert snap["t"] == "2026-08-19"
    # 退出后连接已关闭
    assert storage._conn is None


# ====================================================================
# T16. 写入后 90d 快照同步更新
# ====================================================================
def test_trajectory_snapshot_refreshed(tmp_path):
    """每次 upsert_daily 后，regime_trajectory_90d 同步覆盖更新。"""
    storage = EvolutionStorageSQLite(tmp_path / "evo.db")
    # 写入第 1 条
    storage.upsert_daily("BTCUSDT", _make_frame("2026-01-01"))
    # 直接查 regime_trajectory_90d 表
    cur = storage._conn.cursor()
    row = cur.execute(
        "SELECT trajectory FROM regime_trajectory_90d WHERE symbol='BTCUSDT'"
    ).fetchone()
    assert row is not None
    import json
    traj = json.loads(row["trajectory"])
    assert len(traj) == 1
    assert traj[0]["t"] == "2026-01-01"

    # 再写入 5 条
    for i in range(2, 7):
        storage.upsert_daily("BTCUSDT", _make_frame(f"2026-01-{i:02d}"))
    row = cur.execute(
        "SELECT trajectory FROM regime_trajectory_90d WHERE symbol='BTCUSDT'"
    ).fetchone()
    traj = json.loads(row["trajectory"])
    assert len(traj) == 6
    assert traj[0]["t"] == "2026-01-01"
    assert traj[-1]["t"] == "2026-01-06"
    storage.close()


# ====================================================================
# T17. 多 symbol 隔离
# ====================================================================
def test_multi_symbol_isolation(tmp_path):
    storage = EvolutionStorageSQLite(tmp_path / "evo.db")
    storage.upsert_daily("BTCUSDT", _make_frame("2026-08-19", price=60000.0))
    storage.upsert_daily("ETHUSDT", _make_frame("2026-08-19", price=3000.0))

    btc_snap = storage.get_snapshot("BTCUSDT")
    eth_snap = storage.get_snapshot("ETHUSDT")
    storage.close()
    assert btc_snap["price"] == pytest.approx(60000.0, abs=1e-6)
    assert eth_snap["price"] == pytest.approx(3000.0, abs=1e-6)
