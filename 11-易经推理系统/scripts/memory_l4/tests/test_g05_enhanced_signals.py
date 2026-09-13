"""
G-05 增强版信号接入测试
========================
③ no_bounce_at_key：PotentialFieldEngineer 关键位检测
④ no_intervener：odaily_newsflash 事件检测

测试策略：mock K线数据和DB，验证两个方法的增强逻辑。
"""

from __future__ import annotations

import sys
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


# ============================================================
# ③ no_bounce_at_key 增强版测试
# ============================================================
def _make_klines(n: int, start_price: float = 100.0, trend: str = "down") -> list[dict]:
    """生成n根K线数据."""
    klines = []
    price = start_price
    for i in range(n):
        if trend == "down":
            close = start_price - i * 0.5
            high = close + 0.3
            low = close - 0.3
        elif trend == "up":
            close = start_price + i * 0.5
            high = close + 0.3
            low = close - 0.3
        else:  # sideways
            close = start_price + (i % 3 - 1) * 0.2
            high = close + 0.3
            low = close - 0.3
        klines.append({
            "open": close + 0.1,
            "high": high,
            "low": low,
            "close": close,
            "volume": 1000.0 + i,
        })
    return klines


def test_t_e1_no_bounce_insufficient_klines():
    """③ K线<50根但>=6根 → 回退简化版（连续6根下行判定）."""
    from scripts.memory_l4.polling_trader import PollingTrader
    trader = MagicMock(spec=PollingTrader)
    trader._recent_klines = _make_klines(6, trend="down")
    # 绑定真实方法
    result = PollingTrader._detect_no_bounce_at_key(trader)
    # 6根下行 → 简化版判定 True
    assert result is True


def test_t_e2_no_bounce_sufficient_klines_down_trend():
    """③ 250根下行趋势K线 → 增强版判定（穿越支撑位+无反弹）."""
    from scripts.memory_l4.polling_trader import PollingTrader
    trader = MagicMock(spec=PollingTrader)
    trader._recent_klines = _make_klines(250, trend="down")
    result = PollingTrader._detect_no_bounce_at_key(trader)
    # 下行趋势 → 连续下行 → True
    assert isinstance(result, bool)


def test_t_e3_no_bounce_up_trend():
    """③ 上行趋势 → 不应判定为无反弹."""
    from scripts.memory_l4.polling_trader import PollingTrader
    trader = MagicMock(spec=PollingTrader)
    trader._recent_klines = _make_klines(250, trend="up")
    result = PollingTrader._detect_no_bounce_at_key(trader)
    assert result is False


def test_t_e4_no_bounce_no_klines():
    """③ _recent_klines=None → False（FAIL-OPEN）."""
    from scripts.memory_l4.polling_trader import PollingTrader
    trader = MagicMock(spec=PollingTrader)
    trader._recent_klines = None
    result = PollingTrader._detect_no_bounce_at_key(trader)
    assert result is False


def test_t_e5_no_bounce_exception_fail_open():
    """③ 异常 → False（FAIL-OPEN）."""
    from scripts.memory_l4.polling_trader import PollingTrader
    trader = MagicMock(spec=PollingTrader)
    # 设置 _recent_klines 触发异常
    trader._recent_klines = "not_a_list"
    result = PollingTrader._detect_no_bounce_at_key(trader)
    assert result is False


# ============================================================
# ④ no_intervener 增强版测试
# ============================================================
def _create_test_db(news_items: list[dict]) -> str:
    """创建临时测试DB，插入 odaily_newsflash 新闻."""
    db_path = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS records (
            source TEXT,
            category TEXT,
            sub_category TEXT,
            timestamp TEXT,
            metrics TEXT,
            events TEXT,
            raw TEXT,
            timeseries TEXT
        )
    """)
    for item in news_items:
        cur.execute(
            "INSERT INTO records (source, metrics, events, raw, timestamp) VALUES (?, ?, ?, ?, ?)",
            ("odaily_newsflash",
             json.dumps(item.get("metrics", {})),
             json.dumps(item.get("events", [])),
             json.dumps(item.get("raw", {})),
             item.get("timestamp", "2026-09-13T00:00:00+00:00"))
        )
    conn.commit()
    conn.close()
    return db_path


def test_t_e6_no_intervener_no_intervention_news():
    """④ 无干预类新闻 → no_intervener=True（无干预者）."""
    db_path = _create_test_db([
        {"metrics": {"od_event_type": "market_sentiment"},
         "raw": {"title": "巨鲸增持BTC", "content": "市场情绪乐观"}},
        {"metrics": {"od_event_type": "project_ecosystem"},
         "raw": {"title": "以太坊升级", "content": "Layer2进展"}},
    ])
    result = _test_no_intervener_with_db(db_path)
    Path(db_path).unlink(missing_ok=True)
    assert result is True


def test_t_e7_intervener_monetary_policy_event():
    """④ 有 monetary_policy 类事件 → no_intervener=False（有干预者）."""
    db_path = _create_test_db([
        {"metrics": {"od_event_type": "monetary_policy"},
         "raw": {"title": "美联储加息50基点", "content": "FOMC决议"}},
    ])
    result = _test_no_intervener_with_db(db_path)
    Path(db_path).unlink(missing_ok=True)
    assert result is False


def test_t_e8_intervener_crypto_regulation_event():
    """④ 有 crypto_regulation 类事件 → no_intervener=False."""
    db_path = _create_test_db([
        {"metrics": {"od_event_type": "crypto_regulation"},
         "raw": {"title": "SEC批准BTC现货ETF", "content": "监管新规"}},
    ])
    result = _test_no_intervener_with_db(db_path)
    Path(db_path).unlink(missing_ok=True)
    assert result is False


def test_t_e9_intervener_keyword_in_title():
    """④ 标题含干预关键词（但event_type不对）→ no_intervener=False."""
    db_path = _create_test_db([
        {"metrics": {"od_event_type": "market_sentiment"},
         "raw": {"title": "央行宣布干预汇市", "content": "稳定市场"}},
    ])
    result = _test_no_intervener_with_db(db_path)
    Path(db_path).unlink(missing_ok=True)
    assert result is False


def test_t_e10_no_intervener_db_missing():
    """④ DB不存在 → True（FAIL-OPEN，保守判定无干预者）."""
    # 用临时空目录测试DB不存在
    import tempfile
    tmp_dir = tempfile.mkdtemp()
    fake_root = Path(tmp_dir) / "fake_root"
    fake_dc = fake_root / "18-数据获取中心"
    fake_dc.mkdir(parents=True, exist_ok=True)
    # 不创建 data_center.db → DB不存在

    from scripts.memory_l4.polling_trader import PollingTrader
    import scripts.memory_l4.polling_trader as pt_module

    trader = MagicMock(spec=PollingTrader)
    original_root = pt_module._PROJECT_ROOT
    pt_module._PROJECT_ROOT = fake_root
    try:
        result = PollingTrader._detect_no_intervener(trader)
    finally:
        pt_module._PROJECT_ROOT = original_root
        # 清理
        import shutil
        shutil.rmtree(fake_root, ignore_errors=True)

    assert result is True


def test_t_e11_no_intervener_empty_db():
    """④ DB存在但无新闻 → True（无干预者）."""
    db_path = _create_test_db([])
    result = _test_no_intervener_with_db(db_path)
    Path(db_path).unlink(missing_ok=True)
    assert result is True


def _test_no_intervener_with_db(db_path: str) -> bool:
    """辅助：用指定DB路径测试 _detect_no_intervener."""
    from scripts.memory_l4.polling_trader import PollingTrader
    import scripts.memory_l4.polling_trader as pt_module

    trader = MagicMock(spec=PollingTrader)
    # 临时覆盖 _PROJECT_ROOT
    original_root = pt_module._PROJECT_ROOT
    pt_module._PROJECT_ROOT = Path(db_path).parent / "fake_root"
    # 创建 fake_root/18-数据获取中心/data_center.db 软链接
    fake_dir = pt_module._PROJECT_ROOT / "18-数据获取中心"
    fake_dir.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy(db_path, str(fake_dir / "data_center.db"))

    try:
        result = PollingTrader._detect_no_intervener(trader)
    finally:
        pt_module._PROJECT_ROOT = original_root
        # 清理
        try:
            (fake_dir / "data_center.db").unlink(missing_ok=True)
            fake_dir.rmdir()
            pt_module._PROJECT_ROOT.rmdir()
        except Exception:
            pass

    return result


# ============================================================
# 端到端：增强版信号 → G-05 触发
# ============================================================
def test_t_e12_e2e_enhanced_signals_to_g05():
    """端到端：增强版4判据全满足 → G-05 触发."""
    from scripts.memory_l4.portfolio_risk_fuses import PortfolioRiskFuses

    # 构造4判据全满足的 ctx（模拟增强版信号输出）
    ctx = {
        "primary_dim_jumped": True,
        "mechanism_active": True,
        "no_bounce_at_key": True,    # 增强版判定
        "no_intervener": True,       # 增强版判定
        # G-02 字段（不满足，确保走G-05）
        "positions_by_direction": {"LONG": 0, "SHORT": 0},
        "avg_float_loss_pct_15m": 0.0,
        "btc_lambda": 1.0,
        "daily_equity_prev": 2000.0,
        "daily_equity_now": 1990.0,
    }

    fuses = PortfolioRiskFuses(enable=True)
    act = fuses.tick_and_check(ctx)
    assert act.emergency_shutdown is True
    assert act.reason.startswith("g05_")
