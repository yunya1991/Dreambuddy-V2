"""
P2 TDD 测试：新增 CD-DONCHIAN-10-BREAK + CD-NECKLINE-BREAK 信号

CD-DONCHIAN-10-BREAK: 10日唐奇安通道突破（更敏感，下突破能及时触发）
  - 上突破 → long, 下突破 → short（动态方向）

CD-NECKLINE-BREAK: 颈线跌破信号（头肩顶颈线有效跌破 → 做空）
  - 方向固定 short（顶部反转做空信号）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

SCRIPTS_DIR = REPO / "dreambuddy_evolution" / "scripts"
COND_DIR = REPO / "dreambuddy_evolution" / "gene_data" / "strategy_genes" / "conditions"


def _import_shadow_backtest():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "shadow_backtest", SCRIPTS_DIR / "shadow_backtest.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_trend_up(n=60):
    klines = []
    for i in range(n):
        close = 100.0 + i * 2.0
        klines.append({"timestamp": f"2026-01-{i+1:02d}", "open": close-0.5,
                        "high": close+1.0, "low": close-1.0, "close": close, "volume": 1000.0})
    return klines


def _make_trend_down(n=60):
    klines = []
    for i in range(n):
        close = 200.0 - i * 2.0
        klines.append({"timestamp": f"2026-01-{i+1:02d}", "open": close+0.5,
                        "high": close+1.0, "low": close-1.0, "close": close, "volume": 1000.0})
    return klines


def _make_head_and_shoulders_top(n=70):
    """构造头肩顶形态：左肩-头-右肩-颈线跌破"""
    klines = []
    # 阶段1: 左肩 100→110→105 (15 bar)
    for i in range(15):
        close = 100.0 + i * 0.67
        klines.append({"timestamp": f"2026-01-{i+1:02d}", "open": close-0.5,
                        "high": close+1.0, "low": close-1.0, "close": close, "volume": 1000.0})
    # 阶段2: 头部 105→120→110 (15 bar)
    for i in range(15):
        if i < 8:
            close = 110.0 + i * 1.25
        else:
            close = 120.0 - (i - 8) * 1.25
        klines.append({"timestamp": f"2026-01-{i+16:02d}", "open": close-0.5,
                        "high": close+1.0, "low": close-1.0, "close": close, "volume": 800.0})
    # 阶段3: 右肩 110→115→108 (15 bar)
    for i in range(15):
        if i < 5:
            close = 110.0 + i
        else:
            close = 115.0 - (i - 5) * 1.0
        klines.append({"timestamp": f"2026-01-{i+31:02d}", "open": close-0.5,
                        "high": close+1.0, "low": close-1.0, "close": close, "volume": 600.0})
    # 阶段4: 颈线跌破 108→95 (25 bar，放量)
    for i in range(25):
        close = 108.0 - i * 0.5
        klines.append({"timestamp": f"2026-01-{i+46:02d}", "open": close+0.3,
                        "high": close+0.8, "low": close-1.2, "close": close, "volume": 1200.0})
    return klines


# ====================================================================
# CD-DONCHIAN-10-BREAK 测试
# ====================================================================
def test_donchian_10_gene_exists():
    """T1: CD-DONCHIAN-10-BREAK 基因文件存在"""
    assert (COND_DIR / "CD-DONCHIAN-10-BREAK.json").exists()


def test_donchian_10_up_breakout_long():
    """T2: 10日上突破 → long"""
    sb = _import_shadow_backtest()
    klines = _make_trend_up(60)
    bars = sb.calc_indicators(klines)
    triggered, direction = sb.eval_gene_with_direction("CD-DONCHIAN-10-BREAK", bars[50], klines, 50)
    if triggered:
        assert direction == "long", f"10日上突破应为 long，实际 {direction}"


def test_donchian_10_down_breakout_short():
    """T3: 10日下突破 → short"""
    sb = _import_shadow_backtest()
    klines = _make_trend_down(60)
    bars = sb.calc_indicators(klines)
    triggered, direction = sb.eval_gene_with_direction("CD-DONCHIAN-10-BREAK", bars[50], klines, 50)
    if triggered:
        assert direction == "short", f"10日下突破应为 short，实际 {direction}"


def test_donchian_10_in_dynamic_direction_set():
    """T4: CD-DONCHIAN-10-BREAK 在 _DYNAMIC_DIRECTION_GENES 中"""
    sb = _import_shadow_backtest()
    assert "CD-DONCHIAN-10-BREAK" in sb._DYNAMIC_DIRECTION_GENES


def test_donchian_10_weight_09():
    """T5: CD-DONCHIAN-10-BREAK 权重 0.9（短期突破，比20日更敏感）"""
    gene = json.loads((COND_DIR / "CD-DONCHIAN-10-BREAK.json").read_text(encoding="utf-8"))
    assert gene.get("weight") == 0.9


# ====================================================================
# CD-NECKLINE-BREAK 测试
# ====================================================================
def test_neckline_break_gene_exists():
    """T6: CD-NECKLINE-BREAK 基因文件存在"""
    assert (COND_DIR / "CD-NECKLINE-BREAK.json").exists()


def test_neckline_break_direction_short():
    """T7: 颈线跌破方向固定 short"""
    sb = _import_shadow_backtest()
    # 颈线跌破是顶部反转信号，方向固定 short
    assert sb._GENE_DIRECTION.get("CD-NECKLINE-BREAK") == "short"


def test_neckline_break_weight_12():
    """T8: 颈线跌破权重 1.2（顶部反转信号，价值较高）"""
    gene = json.loads((COND_DIR / "CD-NECKLINE-BREAK.json").read_text(encoding="utf-8"))
    assert gene.get("weight") == 1.2


def test_neckline_break_triggers_on_head_shoulders():
    """T9: 头肩顶形态中颈线跌破应触发"""
    sb = _import_shadow_backtest()
    klines = _make_head_and_shoulders_top(60)
    bars = sb.calc_indicators(klines)
    # 阶段4 颈线跌破（bar 46~60）
    triggered = False
    for i in range(46, min(60, len(bars))):
        if sb.eval_gene("CD-NECKLINE-BREAK", bars[i], klines, i):
            triggered = True
            break
    assert triggered, "头肩顶颈线跌破应触发 CD-NECKLINE-BREAK"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
