"""tests/test_v15_budget_pool_dynamic.py — V15动态预算池TDD测试（spec §1/§2/§3）。

测试目标：
1. §1 预算分子公式：raw_pool=max(POOL, avail) × UTIL 钳制≤eq×CAP
2. §2 V15已用扣减：DEDUCT=true扣per_coin_budget；DEDUCT=false不扣
3. §3 MIN自适应：DYNAMIC=true → min=max(FLOOR, min(MIN, pool×10%))；DYNAMIC=false→固定$20
4. FAIL-OPEN：所有新配置读错/缺失→回退默认，不抛异常
5. 基线regression：今日case avail=$46 eq=$654 MU&LINK持2/3→BTC conf72 allowed=True（之前=False）
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

_HERE = Path(__file__).resolve().parent
_V15_ROOT = _HERE.parent
_LIB = _V15_ROOT / "lib"
if str(_V15_ROOT) not in sys.path:
    sys.path.insert(0, str(_V15_ROOT))
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))


# ---------------------------------------------------------------------------
# 工具：用临时env重新加载capital_manager模块（读取新配置需要重新import-level解析）
# ---------------------------------------------------------------------------
def _reload_cm(env: Optional[dict] = None):
    """在monkeypatch env后，重新加载capital_manager返回模块。"""
    # 先移除缓存以强制重新加载
    for mod in list(sys.modules.keys()):
        if mod in ("capital_manager", "config_loader", "okx_client",
                   "symbol_mapper", "token_pool_loader", "strategy_params"):
            del sys.modules[mod]
    # 如果外部环境变量强制设置，注入到os.environ
    backup = {}
    if env:
        for k, v in env.items():
            backup[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = str(v)
    try:
        import capital_manager  # type: ignore
        return capital_manager
    finally:
        for k, v in backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---------------------------------------------------------------------------
# 假cap数据（模仿今日实盘基线case）
# ---------------------------------------------------------------------------
def _baseline_cap(avail=46.0, eq=654.56, used=608.73):
    return {
        "mode": "dynamic",
        "budget_source": "okx_live_api",
        "fallback_used": False,
        "total_eq": eq,
        "avail_balance": avail,
        "used_margin": used,
        "balance_raw": {"ok": True, "total_eq": eq, "avail_balance": avail},
    }


# ==========================================================================
# RED 1 — §1 基线case：今日实盘 预算池=$200
# ==========================================================================
class TestS1BaselinePoolSize:
    def test_baseline_pool_gross_is_200_when_avail_46(self):
        """§1基线：POOL=200(default), avail=46, eq=654 → gross_pool=$200 (下限保障胜出)."""
        cm = _reload_cm()
        # 新函数应存在：_resolve_v15_budget_pool(cap, v15_used=0)
        assert hasattr(cm, "_resolve_v15_budget_pool"), "缺少函数 _resolve_v15_budget_pool"
        pool = cm._resolve_v15_budget_pool(_baseline_cap(), v15_used_usd=0.0, v15_state_positions=None)
        # §1 6个返回字段都应存在
        for f in ("pool_size_usdt", "budget_pool_gross", "v15_used_deducted",
                  "budget_pool_net", "effective_min_margin", "dynamic_min_applied"):
            assert f in pool, f"缺少返回字段 {f}: {list(pool.keys())}"
        assert abs(pool["budget_pool_gross"] - 200.0) < 0.01, (
            f"预期gross=$200(下限保障胜出), 实得${pool['budget_pool_gross']:.2f}")
        # DEDUCT=true默认, v15_used=0 → net应等于gross
        assert abs(pool["budget_pool_net"] - pool["budget_pool_gross"]) < 0.01

    def test_regression_btc_allowed_true_on_baseline(self):
        """§1基线regression：今日case(2/3名额,BTC conf72 STRONG_BULL)的alloc.allowed应为True。
        之前卡死于False(底仓$8.53<$20门禁)，是要修的根因。"""
        cm = _reload_cm()
        # 传override：当前V15 state持2仓位 → remaining_slots=1；已用v15_used_usd=80
        alloc = cm.calculate_per_coin_allocation(
            "BTC",
            confidence=72,
            elder_ray={"direction": "STRONG_BULL", "strength": 80, "ema_trend": "up"},
            pos_count_override=2,
            v15_used_usd=80.0,  # MU+LINK 每仓40 = $80 已占
        )
        assert alloc is not None and isinstance(alloc, dict)
        assert "allowed" in alloc
        assert alloc["allowed"] is True, (
            f"alloc.allowed应为True(今日根因修复), 实际False原因={alloc.get('reason')}, "
            f"base=${alloc.get('base_usd'):.2f}, avail_budget=${alloc.get('available_budget')}, "
            f"budget_pool_gross=${alloc.get('budget_pool_gross')}, net=${alloc.get('budget_pool_net')}")
        # 同响应附带6个新字段
        assert "budget_pool_gross" in alloc
        assert "budget_pool_net" in alloc
        assert "effective_min_margin" in alloc


# ==========================================================================
# §1 BIG avail：avail大场景（L4平仓，avail=$500 eq=$654 CAP=50%→$327上限）
# ==========================================================================
class TestS1AvailBigCapped:
    def test_avail_500_capped_327(self):
        """avail=$500 > POOL=$200且500 > eq×50%=$327 → gross被钳制到$327。"""
        cm = _reload_cm()
        pool = cm._resolve_v15_budget_pool(_baseline_cap(avail=500, eq=654.56))
        assert abs(pool["budget_pool_gross"] - 327.28) < 0.5, pool

    def test_util_120_still_in_cap(self):
        """UTIL=1.2放大时, (max(200,46)×1.2=240) ≤ 327 → gross=$240（未顶上限）。"""
        cm = _reload_cm({"V15_BUDGET_UTIL_PCT": "1.2"})
        pool = cm._resolve_v15_budget_pool(_baseline_cap(avail=46, eq=654.56))
        assert abs(pool["budget_pool_gross"] - 240.0) < 0.2, pool


# ==========================================================================
# §2 扣减项 DEDUCT开关
# ==========================================================================
class TestS2DeductUsed:
    def test_deduct_true_80_net_120(self):
        """DEDUCT=true(default), v15_used=$80, gross=$200 → net=$120; deducted=80."""
        cm = _reload_cm()
        pool = cm._resolve_v15_budget_pool(_baseline_cap(), v15_used_usd=80)
        assert abs(pool["v15_used_deducted"] - 80) < 0.01, pool
        assert abs(pool["budget_pool_net"] - 120) < 0.01, pool

    def test_deduct_false_keeps_gross(self):
        """DEDUCT=false, 即使v15_used=80 → deducted=0, net=200."""
        cm = _reload_cm({"V15_DEDUCT_V15_USED": "false"})
        pool = cm._resolve_v15_budget_pool(_baseline_cap(), v15_used_usd=80)
        assert pool["v15_used_deducted"] == 0, pool
        assert abs(pool["budget_pool_net"] - pool["budget_pool_gross"]) < 0.01, pool

    def test_deduct_via_state_positions(self):
        """v15_used_usd未传时，从v15_state_positions.values()的per_coin_budget累加=40+60=100。"""
        cm = _reload_cm()
        state_pos = {"MU": {"per_coin_budget": 40}, "LINK": {"per_coin_budget": 60}}
        pool = cm._resolve_v15_budget_pool(_baseline_cap(), v15_state_positions=state_pos)
        assert abs(pool["v15_used_deducted"] - 100) < 0.01, pool

    def test_deduct_exceeds_gross_keeps_half_pool_reserve(self):
        """v15_used=$500 >> gross=$200 (H4新语义) → 保留半池 net=\$100，不再扣到net=0。
        历史遗留大仓位（LINK单仓per_coin=\$202）不应永远锁死新开机会。"""
        cm = _reload_cm()
        pool = cm._resolve_v15_budget_pool(_baseline_cap(), v15_used_usd=500)
        # deducted上限=100 (gross - max(gross, POOL_SIZE)×50% = 200-100=100)
        assert abs(pool["v15_used_deducted"] - 100.0) < 0.01, pool
        assert abs(pool["budget_pool_net"] - 100.0) < 0.01, pool


# ==========================================================================
# §3 MIN自适应
# ==========================================================================
class TestS3DynamicMinMargin:
    def test_baseline_net_120_min_is_MIN(self):
        """net=$120, DYNAMIC=true → min(实际MIN_MARGIN_USD=$10, 120×10%=12) → max($5,10)=$10。"""
        cm = _reload_cm()
        pool = cm._resolve_v15_budget_pool(_baseline_cap(), v15_used_usd=80)
        EXPECTED = min(10.0, 12.0)  # 实际MIN_MARGIN_USD==10 (配置值), 比$12更小
        assert abs(pool["effective_min_margin"] - EXPECTED) < 0.05, pool
        assert pool["dynamic_min_applied"] is True

    def test_small_pool_net_30_min_is_floor_5(self):
        """net=$30, 10%=$3 < FLOOR=5 → min=$5。"""
        # 把gross压小：pool_size=30, avail=0, eq=100 → gross=30; used=0; net=$30
        cm = _reload_cm({"V15_POOL_SIZE_USDT": "30"})
        pool = cm._resolve_v15_budget_pool(_baseline_cap(avail=0, eq=100))
        assert abs(pool["budget_pool_net"] - 30) < 0.1, pool
        assert abs(pool["effective_min_margin"] - 5.0) < 0.05, pool

    def test_dynamic_false_stays_CONFIG_MIN(self):
        """DYNAMIC=false → 无论池大小, MIN=实际MIN_MARGIN_USD配置=$10（不是默认20）。"""
        cm = _reload_cm({"V15_DYNAMIC_MIN_MARGIN": "false", "V15_POOL_SIZE_USDT": "30"})
        pool = cm._resolve_v15_budget_pool(_baseline_cap(avail=0, eq=100))
        # 固定MIN跟随配置，应等于载入的MIN_MARGIN_USD=10（配置值）
        EXPECTED = cm.MIN_MARGIN_USD
        assert abs(pool["effective_min_margin"] - EXPECTED) < 0.01, (
            f"预期MIN={EXPECTED}, 实际={pool}, cm.MIN={cm.MIN_MARGIN_USD}")
        assert pool["dynamic_min_applied"] is False


# ==========================================================================
# §4 FAIL-OPEN：配置值非法/非数字→回退默认，不抛异常
# ==========================================================================
class TestS4FailOpenConfig:
    def test_garbage_pool_size_defaults_200(self):
        """V15_POOL_SIZE_USDT='not_a_number' → 回退200。"""
        cm = _reload_cm({"V15_POOL_SIZE_USDT": "not_a_number"})
        pool = cm._resolve_v15_budget_pool(_baseline_cap(avail=46, eq=654))
        assert abs(pool["pool_size_usdt"] - 200.0) < 0.01, pool
        assert abs(pool["budget_pool_gross"] - 200.0) < 0.01, pool

    def test_garbage_ratio_cap_defaults_0_5(self):
        """V15_MAX_RATIO_CAP='abc'或负数→回退→CAP=50%。avail大时被eq×0.5钳制。"""
        cm = _reload_cm({"V15_MAX_RATIO_CAP": "abc",
                         "V15_POOL_SIZE_USDT": "200"})
        pool = cm._resolve_v15_budget_pool(_baseline_cap(avail=9999, eq=400))
        # gross = min(max(200,9999)×1.0, 400×0.5=200) → 200
        assert abs(pool["budget_pool_gross"] - 200.0) < 0.01, pool

    def test_bool_typos_accepted(self):
        """V15_DEDUCT_V15_USED = '0', 'off', 'no' → False; 'yes','on','1' → True。"""
        for val in ("0", "off", "no", "false", "Disabled", "  No  "):
            cm = _reload_cm({"V15_DYNAMIC_MIN_MARGIN": val})
            pool = cm._resolve_v15_budget_pool(_baseline_cap(avail=46, eq=654))
            assert pool["dynamic_min_applied"] is False, f"val={val}应被解析为false"
        for val in ("1", "ON", "YES", "true", "Enabled"):
            cm = _reload_cm({"V15_DEDUCT_V15_USED": val})
            pool = cm._resolve_v15_budget_pool(_baseline_cap(avail=46, eq=654), v15_used_usd=10)
            assert abs(pool["v15_used_deducted"] - 10) < 0.01, f"val={val}应被解析为true"
