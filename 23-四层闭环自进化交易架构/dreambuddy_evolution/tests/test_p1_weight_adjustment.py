"""
P1 TDD 测试：权重调整

基于 2026-07-15 顶部下跌案例分析：
  - 头肩顶（顶部反转）权重 ↑: 1.0 → 1.5
  - Donchian-20（顶部假突破）权重 ↓: 1.0 → 0.8
  - Donchian-55（慢系统滞后）权重 ↓: 1.0 → 0.6
  - ATR-EXPANDING（不区分方向）权重 ↓: 0.8 → 0.5
  - ADX-GT25-TREND（不区分方向）权重 ↓: 1.0 → 0.5
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

COND_DIR = REPO / "dreambuddy_evolution" / "gene_data" / "strategy_genes" / "conditions"
CAND_DIR = REPO / "dreambuddy_evolution" / "gene_data" / "candidates"


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ====================================================================
# P1 权重调整验证
# ====================================================================
def test_head_shoulders_weight_15():
    """头肩顶权重 1.5（顶部反转信号，当前案例价值高）"""
    gene = _load(CAND_DIR / "CD-KNOW-HEAD-SHOULDERS.json")
    assert gene.get("weight") == 1.5, f"头肩顶权重应为 1.5，实际 {gene.get('weight')}"


def test_donchian_20_weight_08():
    """Donchian-20 权重 0.8（顶部假突破率高）"""
    gene = _load(COND_DIR / "CD-DONCHIAN-20-BREAK.json")
    assert gene.get("weight") == 0.8, f"Donchian-20 权重应为 0.8，实际 {gene.get('weight')}"


def test_donchian_55_weight_06():
    """Donchian-55 权重 0.6（慢系统滞后更严重）"""
    gene = _load(COND_DIR / "CD-DONCHIAN-55-BREAK.json")
    assert gene.get("weight") == 0.6, f"Donchian-55 权重应为 0.6，实际 {gene.get('weight')}"


def test_atr_expanding_weight_05():
    """ATR-EXPANDING 权重 0.5（不区分方向，顶部亏损严重）"""
    gene = _load(COND_DIR / "CD-ATR-EXPANDING.json")
    assert gene.get("weight") == 0.5, f"ATR-EXPANDING 权重应为 0.5，实际 {gene.get('weight')}"


def test_adx_gt25_weight_05():
    """ADX-GT25-TREND 权重 0.5（不区分方向，需配合 DI 判断）"""
    gene = _load(COND_DIR / "CD-ADX-GT25-TREND.json")
    assert gene.get("weight") == 0.5, f"ADX-GT25-TREND 权重应为 0.5，实际 {gene.get('weight')}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
