"""
TDD 测试: P2 CBR 系统扩展 — 形态案例接入

扩展现有 CBR 系统（11-易经推理系统/scripts/memory_l4/cbr_engine.py），
支持形态案例（头肩顶、颈线跌破等）的存储和检索。

验证点：
  T1. CBRCase 新增 pattern + case_type 字段
  T2. CBRQuery 新增 pattern 字段（查询形态特征）
  T3. CaseBase 能添加形态案例
  T4. CBREngine 能检索形态案例（按 pattern 过滤）
  T5. 头肩顶案例能被结构化入 CaseBase
  T6. FAIL-OPEN: 空库检索返回空列表
  T7. to_feature_dict 包含 pattern 字段
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]  # dreambuddy-v2/
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# 导入现有 CBR 系统
# cbr_engine.py 内部用 `from scripts.memory_l4.cbr_similarity import ...`
# 需要将 11-易经推理系统/ 放在 path 最前面，避免被 dreambuddy_evolution/scripts 冲突
_YJ = REPO / "11-易经推理系统"
if str(_YJ) in sys.path:
    sys.path.remove(str(_YJ))
sys.path.insert(0, str(_YJ))

# 确保 11-易经推理系统 在最前，让 `scripts.memory_l4` 解析到正确包
import importlib
import importlib.util

def _load_cbr_module():
    """直接按文件路径加载 CBR 模块，避免包名冲突"""
    cbr_path = _YJ / "scripts" / "memory_l4" / "cbr_engine.py"
    spec = importlib.util.spec_from_file_location("cbr_engine", str(cbr_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_cbr = _load_cbr_module()
CBRCase = _cbr.CBRCase
CBRQuery = _cbr.CBRQuery
CaseBase = _cbr.CaseBase
CBREngine = _cbr.CBREngine


# ====================================================================
# T1. CBRCase 新增 pattern + case_type 字段
# ====================================================================
def test_cbr_case_has_pattern_field():
    """T1: CBRCase 新增 pattern 和 case_type 字段"""
    case = CBRCase(
        case_id="test-001",
        inst_id="BTC-USDT-SWAP",
        regime="TOP_DROP",
        decision="short",
        confidence=0.75,
        pattern="head_shoulders_top",
        case_type="pattern",
    )
    assert case.pattern == "head_shoulders_top"
    assert case.case_type == "pattern"


# ====================================================================
# T2. CBRQuery 新增 pattern 字段
# ====================================================================
def test_cbr_query_has_pattern_field():
    """T2: CBRQuery 新增 pattern 字段"""
    query = CBRQuery(
        inst_id="BTC-USDT-SWAP",
        regime="TOP_DROP",
        decision="short",
        confidence=0.75,
        pattern="head_shoulders_top",
    )
    assert query.pattern == "head_shoulders_top"


# ====================================================================
# T3. CaseBase 能添加形态案例
# ====================================================================
def test_case_base_add_pattern_case():
    """T3: CaseBase 能添加形态案例"""
    cb = CaseBase()
    case = CBRCase(
        case_id="pattern-001",
        inst_id="BTC-USDT-SWAP",
        regime="TOP_DROP",
        decision="short",
        confidence=0.82,
        pattern="head_shoulders_top",
        case_type="pattern",
        pnl_pct=-3.2,
        is_profit=False,
    )
    cb.cases.append(case)
    assert len(cb.cases) == 1
    assert cb.cases[0].pattern == "head_shoulders_top"
    assert cb.cases[0].case_type == "pattern"


# ====================================================================
# T4. CBREngine 能检索形态案例
# ====================================================================
def test_cbr_engine_retrieve_pattern_cases():
    """T4: CBREngine 能检索形态案例（按 pattern 过滤）"""
    cb = CaseBase()
    # 添加 3 个形态案例 + 1 个普通交易案例
    for i, (pattern, pnl) in enumerate([
        ("head_shoulders_top", -2.5),
        ("head_shoulders_top", -3.0),
        ("neckline_break", -1.8),
        ("donchian_breakout", 0.5),  # 普通交易案例
    ]):
        cb.cases.append(CBRCase(
            case_id=f"case-{i}",
            inst_id="BTC-USDT-SWAP",
            regime="TOP_DROP" if pattern != "donchian_breakout" else "TREND",
            decision="short" if pattern != "donchian_breakout" else "long",
            confidence=0.7 + i * 0.02,
            pattern=pattern,
            case_type="pattern" if pattern != "donchian_breakout" else "trade",
            pnl_pct=pnl,
            is_profit=pnl > 0,
        ))

    engine = CBREngine(case_base=cb, top_k=5, similarity_threshold=0.0)
    query = CBRQuery(
        inst_id="BTC-USDT-SWAP",
        regime="TOP_DROP",
        decision="short",
        confidence=0.75,
        pattern="head_shoulders_top",
    )
    results = engine.retrieve(query)
    # pattern 案例应优先匹配
    pattern_results = [r for r in results if r.case.pattern == "head_shoulders_top"]
    assert len(pattern_results) >= 2, f"应检索到 ≥2 个头肩顶案例，实际 {len(pattern_results)}"


# ====================================================================
# T5. 头肩顶案例能被结构化入 CaseBase
# ====================================================================
def test_head_shoulders_case_import():
    """T5: 头肩顶案例能被结构化入 CaseBase"""
    cb = CaseBase()
    # 模拟 2026-07-15 BTC 头肩顶案例
    case = CBRCase(
        case_id="BTC-HS-20260715",
        inst_id="BTC-USDT-SWAP",
        regime="TOP_DROP",
        decision="short",
        confidence=0.82,
        volatility=1.5,
        entry_price=65600.0,
        exit_price=62536.0,
        pnl_pct=-3.2,
        drawdown=0.03,
        leverage=2.0,
        pattern="head_shoulders_top",
        case_type="pattern",
        system_source="shadow_backtest",
        timestamp="2026-07-15",
        tags=["head_shoulders_top", "top_drop", "btc"],
    )
    cb.cases.append(case)
    assert len(cb.cases) == 1
    assert cb.cases[0].case_id == "BTC-HS-20260715"
    assert cb.cases[0].pattern == "head_shoulders_top"
    assert cb.cases[0].case_type == "pattern"
    assert cb.cases[0].system_source == "shadow_backtest"


# ====================================================================
# T6. FAIL-OPEN: 空库检索返回空列表
# ====================================================================
def test_empty_case_base_retrieve():
    """T6: 空库检索返回空列表"""
    cb = CaseBase()
    engine = CBREngine(case_base=cb, top_k=3)
    query = CBRQuery(
        inst_id="BTC-USDT-SWAP",
        regime="TOP_DROP",
        pattern="head_shoulders_top",
    )
    results = engine.retrieve(query)
    assert results == []


# ====================================================================
# T7. to_feature_dict 包含 pattern 字段
# ====================================================================
def test_to_feature_dict_includes_pattern():
    """T7: CBRCase.to_feature_dict 和 CBRQuery.to_feature_dict 包含 pattern"""
    case = CBRCase(
        case_id="test-002",
        pattern="neckline_break",
        case_type="pattern",
    )
    fd = case.to_feature_dict()
    assert "pattern" in fd, f"case feature_dict 应包含 pattern，实际 {list(fd.keys())}"

    query = CBRQuery(pattern="neckline_break")
    qfd = query.to_feature_dict()
    assert "pattern" in qfd, f"query feature_dict 应包含 pattern，实际 {list(qfd.keys())}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
