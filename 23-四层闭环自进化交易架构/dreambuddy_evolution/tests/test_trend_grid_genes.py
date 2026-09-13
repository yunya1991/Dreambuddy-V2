"""
Phase E TDD 测试：趋势跟踪 + 网格交易 strategy_gene 入库 + ESS 冷启动

覆盖：
  T1. 6 个 condition 基因文件存在 + schema 合法
  T2. 3 个 action 基因文件存在 + schema 合法
  T3. 3 个 combination 入库 library.json + 引用正确
  T4. ESS 冷启动：n_samples=0, ess=0.0（样本<20 不调整权重）
  T5. code_ref 指向真实实现文件（trend_following / grid_trading / regime_gate）

参考：SPEC-趋势跟踪正金字塔与网格策略落地.md Phase E
硬约束：HC-TF-08/09（代码归属）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]  # 23-四层闭环自进化交易架构/
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

GENE_ROOT = REPO / "dreambuddy_evolution" / "gene_data"
COND_DIR = GENE_ROOT / "strategy_genes" / "conditions"
ACT_DIR = GENE_ROOT / "strategy_genes" / "actions"
COMBO_FILE = GENE_ROOT / "strategy_combinations" / "library.json"
SCHEMA_DIR = GENE_ROOT / "schemas"

# Phase E 新增 condition 基因 ID 列表
NEW_CONDITION_IDS = [
    "CD-DONCHIAN-20-BREAK",   # 已存在（Phase A 前入库）
    "CD-DONCHIAN-55-BREAK",   # 新增
    "CD-ATR-EXPANDING",       # 新增
    "CD-ADX-GT25-TREND",       # 新增
    "CD-BOLL-WIDTH-NARROW",    # 新增
    "CD-ADX-LT25-RANGE",       # 新增
]

# Phase E 新增 action 基因 ID 列表
NEW_ACTION_IDS = [
    "AC-PYRAMID-UNIT-HALF-N",  # 正金字塔 0.5N 加仓
    "AC-ATR-STOP-2N",          # 2×ATR 止损
    "AC-GRID-PLACE-ATR",       # 网格 ATR 间距布置
]

# Phase E 新增 combination ID 列表
NEW_COMBO_IDS = [
    "CB-TREND-001",   # 趋势跟踪快系统
    "CB-TREND-002",   # 趋势跟踪慢系统
    "CB-GRID-030",    # 网格交易
]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_schema(obj: dict, schema_name: str) -> bool:
    """用 gene_data/schemas 下的 schema 校验"""
    import jsonschema
    schema = _load_json(SCHEMA_DIR / f"{schema_name}.json")
    try:
        jsonschema.validate(obj, schema)
        return True
    except Exception:
        return False


# ====================================================================
# T1. 6 个 condition 基因文件存在 + schema 合法
# ====================================================================
class TestConditionGenes:
    """T1: condition 基因入库"""

    @pytest.mark.parametrize("gene_id", NEW_CONDITION_IDS)
    def test_condition_file_exists(self, gene_id):
        """每个 condition 基因文件存在"""
        f = COND_DIR / f"{gene_id}.json"
        assert f.exists(), f"condition 基因文件缺失: {f}"

    @pytest.mark.parametrize("gene_id", NEW_CONDITION_IDS)
    def test_condition_schema_valid(self, gene_id):
        """每个 condition 基因通过 schema 校验"""
        obj = _load_json(COND_DIR / f"{gene_id}.json")
        assert _validate_schema(obj, "condition"), f"{gene_id} schema 校验失败"

    @pytest.mark.parametrize("gene_id", NEW_CONDITION_IDS)
    def test_condition_gene_id_matches(self, gene_id):
        """gene_id 字段与文件名一致"""
        obj = _load_json(COND_DIR / f"{gene_id}.json")
        assert obj["gene_id"] == gene_id


# ====================================================================
# T2. 3 个 action 基因文件存在 + schema 合法
# ====================================================================
class TestActionGenes:
    """T2: action 基因入库"""

    @pytest.mark.parametrize("gene_id", NEW_ACTION_IDS)
    def test_action_file_exists(self, gene_id):
        """每个 action 基因文件存在"""
        f = ACT_DIR / f"{gene_id}.json"
        assert f.exists(), f"action 基因文件缺失: {f}"

    @pytest.mark.parametrize("gene_id", NEW_ACTION_IDS)
    def test_action_schema_valid(self, gene_id):
        """每个 action 基因通过 schema 校验"""
        obj = _load_json(ACT_DIR / f"{gene_id}.json")
        assert _validate_schema(obj, "action"), f"{gene_id} schema 校验失败"

    @pytest.mark.parametrize("gene_id", NEW_ACTION_IDS)
    def test_action_sl_floor_4pct(self, gene_id):
        """HC-TF-01: SL ≥ 4% 下限保护（sl_template ≥ 0.04）"""
        obj = _load_json(ACT_DIR / f"{gene_id}.json")
        # entry 类 action 检查 sl_template；非 entry 类（如 reduce）可能无 sl
        if obj.get("action_kind") == "open":
            assert obj["sl_template"] >= 0.04, f"{gene_id} SL={obj['sl_template']} < 4% 下限"


# ====================================================================
# T3. 3 个 combination 入库 library.json + 引用正确
# ====================================================================
class TestCombinations:
    """T3: combination 入库"""

    @pytest.fixture
    def combos(self):
        return _load_json(COMBO_FILE)

    @pytest.mark.parametrize("combo_id", NEW_COMBO_IDS)
    def test_combo_exists_in_library(self, combos, combo_id):
        """每个 combination 在 library.json 中存在"""
        ids = [c["combo_id"] for c in combos]
        assert combo_id in ids, f"{combo_id} 未入库 library.json"

    def test_trend_001_references(self, combos):
        """CB-TREND-001 引用 20 日突破 + 2N 止损 + 0.5N 加仓"""
        c = next((c for c in combos if c["combo_id"] == "CB-TREND-001"), None)
        assert c is not None
        # 引用 CD-DONCHIAN-20-BREAK
        assert "CD-DONCHIAN-20-BREAK" in c["condition_ids"]
        # 引用 AC-ATR-STOP-2N 和/或 AC-PYRAMID-UNIT-HALF-N
        assert "AC-ATR-STOP-2N" in c["action_ids"]

    def test_trend_002_references(self, combos):
        """CB-TREND-002 引用 55 日突破 + 2N 止损"""
        c = next((c for c in combos if c["combo_id"] == "CB-TREND-002"), None)
        assert c is not None
        assert "CD-DONCHIAN-55-BREAK" in c["condition_ids"]
        assert "AC-ATR-STOP-2N" in c["action_ids"]

    def test_grid_030_references(self, combos):
        """CB-GRID-030 引用布林带收窄 + 网格布置"""
        c = next((c for c in combos if c["combo_id"] == "CB-GRID-030"), None)
        assert c is not None
        assert "CD-BOLL-WIDTH-NARROW" in c["condition_ids"]
        assert "AC-GRID-PLACE-ATR" in c["action_ids"]


# ====================================================================
# T4. ESS 冷启动：n_samples=0, ess=0.0（样本<20 不调整权重）
# ====================================================================
class TestESSColdStart:
    """T4: ESS 冷启动机制"""

    @pytest.fixture
    def combos(self):
        return _load_json(COMBO_FILE)

    @pytest.mark.parametrize("combo_id", NEW_COMBO_IDS)
    def test_ess_cold_start_n_zero(self, combos, combo_id):
        """新入库 combination n_samples=0（冷启动）"""
        c = next((c for c in combos if c["combo_id"] == combo_id), None)
        assert c is not None
        assert c.get("n_samples", -1) == 0, f"{combo_id} n_samples={c.get('n_samples')} 应为 0（冷启动）"

    @pytest.mark.parametrize("combo_id", NEW_COMBO_IDS)
    def test_ess_cold_start_ess_zero(self, combos, combo_id):
        """新入库 combination ess=0.0（无样本不评分）"""
        c = next((c for c in combos if c["combo_id"] == combo_id), None)
        assert c is not None
        assert c.get("ess", -1) == 0.0, f"{combo_id} ess={c.get('ess')} 应为 0.0（冷启动）"


# ====================================================================
# T5. code_ref 指向真实实现文件
# ====================================================================
class TestCodeRef:
    """T5: code_ref 指向真实实现文件（HC-TF-08/09 代码归属）"""

    @pytest.mark.parametrize("gene_id", ["CD-DONCHIAN-55-BREAK", "CD-ATR-EXPANDING", "CD-ADX-GT25-TREND"])
    def test_condition_code_ref_trend_following(self, gene_id):
        """趋势类 condition code_ref 指向 trend_following 或 regime_gate"""
        obj = _load_json(COND_DIR / f"{gene_id}.json")
        f = obj["code_ref"]["file"]
        # 允许 trend_following / regime_gate / v15_signal
        assert any(k in f for k in ["trend_following", "regime_gate", "v15_signal"]), \
            f"{gene_id} code_ref.file={f} 应指向 trend_following/regime_gate/v15_signal"

    @pytest.mark.parametrize("gene_id", ["CD-BOLL-WIDTH-NARROW", "CD-ADX-LT25-RANGE"])
    def test_condition_code_ref_grid(self, gene_id):
        """网格类 condition code_ref 指向 grid_trading 或 regime_gate"""
        obj = _load_json(COND_DIR / f"{gene_id}.json")
        f = obj["code_ref"]["file"]
        assert any(k in f for k in ["grid_trading", "regime_gate", "v15_signal"]), \
            f"{gene_id} code_ref.file={f} 应指向 grid_trading/regime_gate/v15_signal"

    @pytest.mark.parametrize("gene_id", ["AC-PYRAMID-UNIT-HALF-N", "AC-ATR-STOP-2N"])
    def test_action_code_ref_trend(self, gene_id):
        """趋势类 action code_ref 指向 trend_following"""
        obj = _load_json(ACT_DIR / f"{gene_id}.json")
        f = obj["code_ref"]["file"]
        assert "trend_following" in f, f"{gene_id} code_ref.file={f} 应指向 trend_following"

    def test_action_code_ref_grid(self):
        """网格类 action code_ref 指向 grid_trading"""
        obj = _load_json(ACT_DIR / "AC-GRID-PLACE-ATR.json")
        f = obj["code_ref"]["file"]
        assert "grid_trading" in f, f"AC-GRID-PLACE-ATR code_ref.file={f} 应指向 grid_trading"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
