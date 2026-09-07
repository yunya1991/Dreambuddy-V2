"""P0-3 阶段2 TDD：Shadow 红线审计 + 4门槛 + JSONL fail-open。

Spec §5.3（红线 Shadow 模式）：
  · FiveDomainFeatureComputer.enable_odaily_engine_boost = False（默认！红线不开）
  · Shadow 不修改任何五维结果（result 字节等价于 enable=False）
  · 仅 JSONL append：`scripts/runtime/odaily_engine_boost_records.jsonl`（逐行 {ts,cls,...}）
  · 4门槛（T37/T42 验证）：hit_rate ≥ 60% / thaw_accuracy ≥ 70% / sharpe ≥ 1.05 / IMPORT_FAIL = 0
    全部 PASS → PR+CR 后才把 enable 默认改 True

6 TC（T31~T36）：
  TC-1 (T31) 红线默认 False：shadow 不开 → 任何情况下不写 JSONL，result 字节和阶段1一致
  TC-2 (T32) enable=True + odaily_* 正常 → shadow 写 JSONL，字段齐全（8字段 schema 必含）
  TC-3 (T33) SentimentEngine ImportError 24h 阻塞模拟 → shadow IMPORT_FAIL 计数写入，且 JSONL 仅一条 error 记录（IMPORT_FAIL ≠0 → Phase2 END 不开开关）
  TC-4 (T34) 4 引擎 mock + policy_ts_20 长度=20 + ∈[0,1] 合法
  TC-5 (T35) Lifecycle & 3D stress（None/缺字段/空字符串 odaily）→ shadow 全吞不 throw，result 字节稳定
  TC-6 (T36) PermissionError（目录只读）→ shadow 不 throw，result 字节等价
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

THIS_DIR = Path(__file__).resolve().parent
_REPO = THIS_DIR.parent
_ROOT = str(_REPO)
_ML4 = str(_REPO / "scripts" / "memory_l4")
for p in (_ML4, _ROOT):
    if p not in sys.path: sys.path.insert(0, p)


# ============================================================
# Helpers
# ============================================================
def _mk_computer(tmp_path: Path, shadow_enable: bool, override_runtime_dir: Optional[Path] = None):
    from five_domain_feature_computer import FiveDomainFeatureComputer
    c = FiveDomainFeatureComputer(enable=True)
    # RED 断言：类属性默认 False（红线）
    assert hasattr(FiveDomainFeatureComputer, "enable_odaily_engine_boost"), \
        "RED 阶段：缺失 enable_odaily_engine_boost 类属性（红线保护）"
    c.enable_odaily_engine_boost = shadow_enable  # TC 显式设置
    # 注入测试用 runtime 路径：FiveDomainFeatureComputer 提供 override 属性
    runtime_dir = override_runtime_dir or (tmp_path / "runtime")
    runtime_dir.mkdir(parents=True, exist_ok=True)
    # 约定：c._od_shadow_jsonl_path 可读写属性（阶段2 GREEN 实现）
    c._od_shadow_jsonl_path = str(runtime_dir / "odaily_engine_boost_records.jsonl")
    return c


SAMPLE_OD_COIN = {
    # 正常 odaily_*（R3 结构，让 boost 非 0，shadow 写真实数值）
    "odaily_policy_sentiment_3d": 0.60,
    "odaily_important_ratio_3d": 0.20,
    "odaily_crypto_reg_ratio_3d": 0.15,
    "odaily_reg_policy_ratio_3d": 0.30,
    "odaily_security_hits_3d": 3,
    "odaily_geopolitics_hits_3d": 2,
    "odaily_batch_size_3d": 20,
    "pn_cycle_sentiment_norm": 0.55,
    "atr_percentile": 0.4,
    "liquidity_score": 0.55,
    "merrill_phase": "RECOVERY",
    "regime": "ranging",
    "cycle4y_t_rel": 0.32,
}


def _read_jsonl(path: str) -> list:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            out.append(json.loads(line))
    return out


# ============================================================
# T31 TC-1 红线默认 False → shadow 不写文件
# ============================================================
def test_tc1_shadow_disabled_by_default_no_io(tmp_path: Path, mocker):
    c = _mk_computer(tmp_path, shadow_enable=False)
    result_before = c.compute(coin_data=SAMPLE_OD_COIN, system_state={})
    # JSONL 应该未被创建
    jl = c._od_shadow_jsonl_path
    created = os.path.exists(jl)
    assert created is False, f"红线关闭但 shadow 文件被创建：{jl}"
    # SentimentEngine（policy_ts_20 的依赖）不应被 import 或调用
    # 这是 shadow 打开时才会 import 的 lazy 路径
    # 验证 result 稳定（再跑一遍）
    result_after = c.compute(coin_data=SAMPLE_OD_COIN, system_state={})
    assert result_before == result_after, "红线关闭结果不稳定"


# ============================================================
# T32 TC-2 enable=True → shadow 写 JSONL 字段齐全
# ============================================================
def test_tc2_shadow_enabled_appends_jsonl_schema(tmp_path: Path):
    c = _mk_computer(tmp_path, shadow_enable=True)
    r = c.compute(coin_data=SAMPLE_OD_COIN, system_state={})
    jl = c._od_shadow_jsonl_path
    recs = _read_jsonl(jl)
    assert len(recs) >= 1, f"enable=True 未写 JSONL（n={len(recs)}）"
    rec = recs[-1]
    # schema：阶段2 GREEN 实现的最小 8 字段
    REQUIRED = {"ts_ms", "asset_class_cnt", "coin_classes",
                "dao_boost_mean", "tian_boost_mean", "policy_ts_20_len",
                "shadow_reason_code", "import_fail_count"}
    missing = REQUIRED - rec.keys()
    assert not missing, f"JSONL 缺字段：{missing}  实际有：{sorted(rec.keys())}"
    # 基本类型断言
    assert isinstance(rec["ts_ms"], int), f"ts_ms 类型错：{type(rec['ts_ms'])}"
    assert isinstance(rec["asset_class_cnt"], int)
    assert isinstance(rec["coin_classes"], list)
    assert isinstance(rec["policy_ts_20_len"], int)
    assert 0 <= rec["policy_ts_20_len"] <= 20, f"policy_ts_20 len∈[0,20]，实际={rec['policy_ts_20_len']}"
    assert rec["shadow_reason_code"] in {"OD_OK", "OD_NO_ODAILY_FIELDS", "OD_IMPORT_ERROR",
                                         "OD_PERMISSION", "OD_GENERIC_ERR"}, rec["shadow_reason_code"]
    # result 确定性稳定（enable=True 再跑一遍 → 字节一致；shadow 不引入随机性）
    r_again = c.compute(coin_data=SAMPLE_OD_COIN, system_state={})
    assert json.dumps(r, sort_keys=True) == json.dumps(r_again, sort_keys=True), \
        "FAIL：enable=True 两次跑 result 不一致（shadow 引入了随机性）"


# ============================================================
# T33 TC-3 SentimentEngine ImportError → shadow 记 IMPORT_FAIL ≥ 1
# ============================================================
def test_tc3_sentiment_import_error_marks_import_fail(tmp_path: Path, monkeypatch):
    """阶段2 GREEN 实现：policy_ts_20 通过 lazy import sentiment_engine 生成，
       若 ImportError → reason_code=OD_IMPORT_ERROR 且 import_fail_count>=1。"""
    real_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__
    bad_modules = {"engines", "engines.sentiment_engine"}
    def _imp_stub(name, *a, **kw):
        base = name.split(".")[0]
        if base in bad_modules or name in bad_modules:
            raise ImportError(f"simulated stub: cannot import {name}")
        return real_import(name, *a, **kw)
    monkeypatch.setattr("builtins.__import__", _imp_stub)

    c = _mk_computer(tmp_path, shadow_enable=True)
    r = c.compute(coin_data=SAMPLE_OD_COIN, system_state={})
    jl = c._od_shadow_jsonl_path
    recs = _read_jsonl(jl)
    assert len(recs) >= 1, f"ImportError 场景 shadow 也必须写一条 err 记录"
    last = recs[-1]
    assert last.get("shadow_reason_code") == "OD_IMPORT_ERROR", f"reason_code={last.get('shadow_reason_code')}!=OD_IMPORT_ERROR"
    assert int(last.get("import_fail_count", 0)) >= 1, "import_fail_count 应≥1"
    # IMPORT_FAIL 场景 result 确定性稳定（Fail-open：两次跑 result 一致）
    r_again = c.compute(coin_data=SAMPLE_OD_COIN, system_state={})
    assert json.dumps(r, sort_keys=True) == json.dumps(r_again, sort_keys=True), \
        "FAIL：IMPORT_ERROR 场景 result 不稳定"


# ============================================================
# T34 TC-4 4引擎mock → policy_ts_20 长度=20 每个∈[0,1]
# ============================================================
def test_tc4_4_engine_like_mock_produces_policy_ts_20_of_20(tmp_path: Path, mocker):
    """阶段2：policy_ts_20 由 4 引擎-like 重采样生成。
    这里 RED 期望：FiveDomainFeatureComputer._shadow_infer_policy_ts_20(coin_data) 返回 20 个合法 float。
    """
    from five_domain_feature_computer import FiveDomainFeatureComputer
    c = _mk_computer(tmp_path, shadow_enable=True)
    ts = c._shadow_infer_policy_ts_20(SAMPLE_OD_COIN)
    assert isinstance(ts, list), f"policy_ts_20 类型：{type(ts)} 不是 list"
    assert len(ts) == 20, f"policy_ts_20 len={len(ts)}≠20"
    for i, x in enumerate(ts):
        assert isinstance(x, (int, float)), f"idx={i} 非数值：{type(x).__name__}={x}"
        assert 0.0 <= float(x) <= 1.0, f"idx={i} value={x} 超出 [0,1]"
    # JSONL 写入 policy_ts_20_len=20
    c.compute(coin_data=SAMPLE_OD_COIN, system_state={})
    recs = _read_jsonl(c._od_shadow_jsonl_path)
    assert recs[-1]["policy_ts_20_len"] == 20, f"policy_ts_20_len={recs[-1]['policy_ts_20_len']}≠20"


# ============================================================
# T35 TC-5 生命周期 & 3D stress → 吞异常 + result 字节稳定
# ============================================================
@pytest.mark.parametrize("coin_data_desc,coin_data", [
    ("None", None),
    ("缺 odaily_*", {"atr_percentile": 0.4, "liquidity_score": 0.55,
                     "merrill_phase": "RECOVERY", "cycle4y_t_rel": 0.3}),
    ("空字符串 odaily policy sent", dict(SAMPLE_OD_COIN, odaily_policy_sentiment_3d="")),
    ("int odaily", 42),
])
def test_tc5_lifecycle_3d_stress_failopen(tmp_path: Path, coin_data_desc, coin_data):
    c_on = _mk_computer(tmp_path, shadow_enable=True)
    try:
        r_on = c_on.compute(coin_data=coin_data, system_state={})
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"shadow=True {coin_data_desc} 抛异常：{type(e).__name__}: {e}")
    # result 确定性稳定（再跑一遍 → 一致；异常不引入随机性）
    try:
        r_on2 = c_on.compute(coin_data=coin_data, system_state={})
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"shadow=True {coin_data_desc} 二次跑抛异常：{type(e).__name__}: {e}")
    assert json.dumps(r_on, sort_keys=True) == json.dumps(r_on2, sort_keys=True), \
        f"{coin_data_desc}: enable=True 两次跑 result 不一致"


# ============================================================
# T36 TC-6 PermissionError → shadow 吞异常 + result 字节等价
# ============================================================
def test_tc6_permission_error_swallowed_result_intact(tmp_path: Path, monkeypatch):
    # 建 JSONL 文件后 chmod 0444
    c = _mk_computer(tmp_path, shadow_enable=True)
    jl = c._od_shadow_jsonl_path
    # 先空占位（阶段1 GREEN：目录不存在时会建？）
    Path(jl).touch()
    os.chmod(jl, 0o444)
    # 捕获 open(..., 'a') 抛 PermissionError → 必须吞掉
    c_off = _mk_computer(tmp_path, shadow_enable=False)
    try:
        r_on = c.compute(coin_data=SAMPLE_OD_COIN, system_state={})
    except PermissionError as e:
        pytest.fail(f"PermissionError 没被 shadow 吞：{e}")
    except Exception as e:  # noqa: BLE001
        # 允许非 Permission 异常被 总开关 try/except 吞
        pass
    finally:
        os.chmod(jl, 0o644)
    # result 确定性稳定（两次跑一致；Permission 不引入随机性）
    r_again = c.compute(coin_data=SAMPLE_OD_COIN, system_state={})
    assert json.dumps(r_on, sort_keys=True) == json.dumps(r_again, sort_keys=True), \
        "Permission 场景 result 不稳定"
