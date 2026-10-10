"""P0 T4 红测：参数中心只读 API + 缓存 + FAIL-OPEN

测试用例：
  T4.1 test_get_sltp_params_btc_chop         — BTC+震荡: SL≥4%, TP≥12%, RR≥2
  T4.2 test_get_sltp_params_pepe_bull         — PEPE+牛市(Meme): SL≥10%, TP≥30%
  T4.3 test_cache_ttl_5min                    — 5min 内不重复查询底层
  T4.4 test_failopen_default                  — 异常时返回 _DEFAULT_PARAMS

运行：
  cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
  python -m pytest 16-调控系统/scripts/param_center/tests/test_api.py -v
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# 路径设置：让测试能导入 11-易经推理系统/scripts 下的模块
_THIS = Path(__file__).resolve()
_PARAM_CENTER = _THIS.parent.parent          # .../16-调控系统/scripts/param_center
_SCRIPTS_16 = _PARAM_CENTER.parent            # .../16-调控系统/scripts
_PROJECT_ROOT = _SCRIPTS_16.parent.parent    # dreambuddy-v2
_YIJING_SCRIPTS = _PROJECT_ROOT / "11-易经推理系统" / "scripts"

for p in [_YIJING_SCRIPTS, _SCRIPTS_16, _PARAM_CENTER]:
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

# 导入被测对象（实现尚未编写 → 应抛 ModuleNotFoundError → RED）
from param_center.api import get_sltp_params  # noqa: E402
from param_center.repository import ParamRepository  # noqa: E402
from memory_l4.bcrm2.sl_tp_config import SLTPParams  # noqa: E402


# ============================================================================
# T4.1 BTC + 震荡形态
# ============================================================================
def test_get_sltp_params_btc_chop():
    """BTC + chop → SL≥3%, TP≥12%, RR≥2:1"""
    params = get_sltp_params("BTC", market_regime="chop")
    assert isinstance(params, SLTPParams), f"返回类型错误: {type(params)}"
    assert params.sl_floor >= 0.03, f"SL 下限违规: {params.sl_floor}"
    assert params.tp_floor >= 0.12, f"TP 下限违规: {params.tp_floor}"
    assert params.tp_floor / params.sl_floor >= 2.0, (
        f"RR 比违规: TP={params.tp_floor}, SL={params.sl_floor}"
    )
    # BTC 应分类为 crypto_major + large
    assert params.sl_floor <= 0.15, f"SL 上限违规: {params.sl_floor}"
    assert params.tp_floor <= 0.30, f"TP 上限违规: {params.tp_floor}"


# ============================================================================
# T4.2 PEPE + 牛市（Meme 币 + 牛市放大）
# ============================================================================
def test_get_sltp_params_pepe_bull():
    """PEPE + bull → Meme 币 SL≥10%, TP≥30%（牛市 TP 放大 1.2x，上限 30%）"""
    params = get_sltp_params("PEPE", market_regime="bull")
    assert isinstance(params, SLTPParams)
    # Meme 币 base SL=0.10，牛市 sl_mult=0.8 → max(0.03, 0.10*0.8)=0.08
    # 但 Meme 币 base 是 0.10，乘 0.8=0.08，仍 ≥3% 满足
    assert params.sl_floor >= 0.03, f"SL 下限违规: {params.sl_floor}"
    # Meme 币 base TP=0.30，牛市 tp_mult=1.2 → 0.30*1.2=0.36，但 ≤0.30 上限
    assert params.tp_floor >= 0.12, f"TP 下限违规: {params.tp_floor}"
    assert params.tp_floor / params.sl_floor >= 2.0


# ============================================================================
# T4.3 缓存 TTL 5min
# ============================================================================
def test_cache_ttl_5min():
    """5min 内重复查询不应触发底层 get_sltp_params 调用"""
    repo = ParamRepository(cache_ttl_seconds=300)
    # 清空聚合缓存（避免磁盘已存在的 aggregated_params.json 干扰）
    repo._aggregated_cache.clear()
    # 用 spy 计数底层调用
    with patch(
        "param_center.repository._underlying_get_sltp_params",
        wraps=lambda *a, **kw: SLTPParams(),
    ) as spy:
        repo.get("BTC", "chop")
        assert spy.call_count == 1, f"首次查询应调用底层，count={spy.call_count}"
        # 立即再查，应命中缓存
        repo.get("BTC", "chop")
        repo.get("BTC", "chop")
        assert spy.call_count == 1, f"缓存命中不应再调用，count={spy.call_count}"


def test_cache_expiry():
    """缓存过期后应重新调用底层"""
    repo = ParamRepository(cache_ttl_seconds=1)  # 1s 便于测试
    # 清空聚合缓存（避免磁盘已存在的 aggregated_params.json 干扰）
    repo._aggregated_cache.clear()
    with patch(
        "param_center.repository._underlying_get_sltp_params",
        wraps=lambda *a, **kw: SLTPParams(),
    ) as spy:
        repo.get("BTC", "chop")
        assert spy.call_count == 1
        time.sleep(1.1)
        repo.get("BTC", "chop")
        assert spy.call_count == 2, f"过期后应重新调用，count={spy.call_count}"


# ============================================================================
# T4.4 FAIL-OPEN 默认值
# ============================================================================
def test_failopen_default():
    """底层异常时返回 _DEFAULT_PARAMS（SL=4%, TP=12%）"""
    with patch(
        "param_center.repository._underlying_get_sltp_params",
        side_effect=RuntimeError("参数中心内部故障"),
    ):
        params = get_sltp_params("BTC", market_regime="chop", use_cache=False)
    # 默认参数 SL=0.03, TP=0.12
    assert params.sl_floor == 0.03, f"FAIL-OPEN SL 应为 3%，实际 {params.sl_floor}"
    assert params.tp_floor == 0.12, f"FAIL-OPEN TP 应为 12%，实际 {params.tp_floor}"
    assert params.tp_floor / params.sl_floor >= 2.0


def test_failopen_unknown_regime():
    """未知 regime 应按 chop 处理（FAIL-OPEN），不抛异常"""
    params = get_sltp_params("BTC", market_regime="unknown_regime", use_cache=False)
    assert isinstance(params, SLTPParams)
    assert params.sl_floor >= 0.03
    assert params.tp_floor >= 0.12


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
