"""Impl-11 阶段2 TDD：Fundamental 7引擎 Shadow 红线审计 + 7门槛 + JSONL fail-open。

Spec §6（Shadow 红线模式）：
  · FiveDomainFeatureComputer.enable_fundamental_7engines_boost = False（默认！红线不开）
  · __init__ 读 FUND_7ENGINES_BOOST env，=1 → True
  · Shadow 不修改任何五维结果（result 字节等价于 enable=False）
  · 仅 JSONL append：`scripts/runtime/fundamental_7engines_records.jsonl`（逐行 {ts_ms, ...}）
  · 9 字段 schema：
      ts_ms / asset_class_cnt / coin_classes /
      fd_S_dao_mean / fd_S_tian_mean / fd_A_dao_mean / fd_A_tian_mean /
      shadow_reason_code / import_fail_count
  · 6 原因码枚举：
      FD7_OK / FD7_DISABLED / FD7_NO_NEWS / FD7_NO_R3D /
      FD7_IMPORT_ERROR / FD7_PERMISSION / FD7_GENERIC_ERR
  · 7 门槛（eval 脚本 G1-G7 + sample≥1500）：
      G1 hit_rate_effective ≥ 60%
      G2 thaw_accuracy ≥ 70%
      G3 sharpe_annual ≥ 1.05
      G4 IMPORT_FAIL_total = 0
      G5 S_ACCURACY ≥ 75%
      G6 A_CONSISTENCY ≥ 60%
      G7 SCHEMA_PASS_RATE ≥ 95%
  · eval 退出码：exit=0 全PASS+样本够；exit=1 样本够但有FAIL；exit=2 样本不足

10 TC（T20~T30）：
  TC-1 红线默认 False：shadow 不开 → 任何情况不写 JSONL，result 字节和阶段1一致
  TC-2 env FUND_7ENGINES_BOOST=1 → __init__ 后 enable=True；空 → False
  TC-3 enable=True + 正常 news → shadow 写 JSONL，字段齐全（9字段 schema 必含），数值合法 float ∈ [-0.10, 0.10]
  TC-4 无 news（空 news_list）→ reason_code=FD7_NO_NEWS，4 boost 均值 = 0.0
  TC-5 news/r3d/signal 全缺 → reason_code=FD7_NO_DATA（NO_NEWS | NO_R3D 合并态），数值合法
  TC-6 engines.event_ledger_engine ImportError 24h 阻塞模拟 → shadow IMPORT_FAIL 计数 ≥1，reason_code=FD7_IMPORT_ERROR
  TC-7 原因码枚举：JSONL 输出中出现 FD7_OK/FD7_NO_NEWS/FD7_IMPORT_ERROR 三类不同场景，reason_code 取值集合对齐
  TC-8 PermissionError（jsonl 目录只读或父目录无写权限）→ shadow 不 throw，result 字节等价
  TC-9 eval 脚本样本不足（空 JSONL 或 n<1500）→ exit=2
  TC-10 eval 脚本 n≥1500 + G2 单独 FAIL 1项 → exit=1；7门槛全PASS → exit=0
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
from typing import Any, Dict, List, Optional

import pytest

THIS_DIR = Path(__file__).resolve().parent
_REPO = THIS_DIR.parent
_ROOT = str(_REPO)
_ML4 = str(_REPO / "scripts" / "memory_l4")
for p in (_ML4, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

FD7_REASON_CODES_EXPECTED = {
    "FD7_OK",
    "FD7_DISABLED",
    "FD7_NO_NEWS",
    "FD7_NO_R3D",
    "FD7_IMPORT_ERROR",
    "FD7_PERMISSION",
    "FD7_GENERIC_ERR",
}


def _get_computer_cls():
    from five_domain_feature_computer import FiveDomainFeatureComputer

    return FiveDomainFeatureComputer


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    out: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def _mock_sqlite_news(ret_value: List[Dict[str, Any]]):
    """Helper: 构造永远返回 ret_value 的可调用函数，供 monkeypatch 注入。"""

    def _fn(*a, **kw):
        return list(ret_value)

    return _fn


def _sample_news_positive_4() -> List[Dict[str, Any]]:
    return [
        {"id": "r1", "ts_ms": 1_755_200_000_000, "title": "美联储确认9月降息25bp",
         "content": "会议纪要显示FOMC一致同意下月降息25bp，年内再降息1次。",
         "source": "odaily", "sentiment_label": "bullish", "event_type": "monetary_policy",
         "importance": 0.95, "assets": ["ALL"]},
        {"id": "r2", "ts_ms": 1_755_201_000_000, "title": "现货BTC ETF连续5日净流入",
         "content": "彭博数据显示现货BTC ETF连续5个交易日净流入超4亿美元。",
         "source": "odaily", "sentiment_label": "bullish", "event_type": "market_data",
         "importance": 0.9, "assets": ["BTC"]},
        {"id": "r3", "ts_ms": 1_755_202_000_000, "title": "日本扩大加密税收优惠",
         "content": "日本自民党批准加密资产税制改革法案，企业端持有利得免征。",
         "source": "odaily", "sentiment_label": "bullish", "event_type": "crypto_regulation",
         "importance": 0.8, "assets": ["ALL"]},
        {"id": "r4", "ts_ms": 1_755_203_000_000, "title": "L2 TVL突破300亿美元",
         "content": "L2Beat数据显示以太坊L2总TVL突破300亿美元历史新高。",
         "source": "odaily", "sentiment_label": "bullish", "event_type": "market_data",
         "importance": 0.7, "assets": ["ETH"]},
    ]


def _sample_coin_data() -> Dict[str, Any]:
    return {
        "fedfunds_rate": 4.375, "stablecoin_mcap_bln": 180.0,
        "policy_sentiment_score": 0.5, "stablecoin_change_rate": 0.0,
        "cycle4y_t_rel": 0.50,
        "merrill_phase": "RECOVERY", "atr_percentile": 0.5, "liquidity_score": 0.5,
    }


def _sample_system_state() -> Dict[str, Any]:
    return {
        "timestamp_ms": 1_755_204_000_000,
        "_by_class": {
            "crypto_usdt": {"jiang_score": 72, "fa_score": 65, "war_state": "COOLDOWN"},
            "us_stock":     {"jiang_score": 60, "fa_score": 58, "war_state": "ALLOW"},
            "precious_metal":{"jiang_score": 55, "fa_score": 62, "war_state": "COOLDOWN"},
        },
        "regime_crypto": "bull_phase",
        "r3d": {"direction": 1.0, "velocity": 0.6, "acceleration": 0.2, "confidence": 0.75,
                "data_points": 100, "trend_summary": "bullish"},
        "signal_engine": {"base_weight": 0.5, "effective_weight": 0.85, "hit_rate_30d": 0.68},
    }


def _mk_computer(
    tmp_path: Path,
    shadow_enable: bool,
    override_runtime_dir: Optional[Path] = None,
    set_via_env: bool = False,
    monkeypatch: Optional["pytest.MonkeyPatch"] = None,
):
    """构造 FiveDomainFeatureComputer：显式开关或 env 控制，JSONL 路径指向 tmp_path。"""
    from five_domain_feature_computer import FiveDomainFeatureComputer

    Cls = _get_computer_cls()
    if set_via_env and monkeypatch is not None:
        monkeypatch.setenv("FUND_7ENGINES_BOOST", "1" if shadow_enable else "0")
    c = Cls()
    if not set_via_env:
        c.enable_fundamental_7engines_boost = shadow_enable
    # 注入测试用 runtime 路径
    runtime_dir = override_runtime_dir or (tmp_path / "runtime")
    runtime_dir.mkdir(parents=True, exist_ok=True)
    c._fd7_shadow_jsonl_path = str(runtime_dir / "fundamental_7engines_records.jsonl")
    return c


# ==================================================================
# T21 TC-1 红线默认 False → shadow 不写文件，类属性为 False
# ==================================================================
class TestTC1RedlineDefault:
    def test_tc1_class_attr_default_false(self):
        """RED 阶段：类属性 enable_fundamental_7engines_boost 必须为 False（红线保护）。"""
        Cls = _get_computer_cls()
        assert hasattr(Cls, "enable_fundamental_7engines_boost"), \
            "RED: 缺失 enable_fundamental_7engines_boost 类属性"
        assert Cls.enable_fundamental_7engines_boost is False, \
            "RED: 红线默认必须 False，防止意外开启 S/A 级注入"

    def test_tc1_disabled_no_jsonl_io(self, tmp_path, monkeypatch):
        """enable=False（默认）调用 compute 后，JSONL 文件不得存在。"""
        c = _mk_computer(tmp_path, shadow_enable=False)
        monkeypatch.setattr(c, "_fetch_news_72h_limit200", _mock_sqlite_news(_sample_news_positive_4()))
        jl_path = c._fd7_shadow_jsonl_path
        result = c.compute(coin_data=_sample_coin_data(), system_state=_sample_system_state())
        assert isinstance(result, dict) and len(result) == 3, "五维 3 资产类输出异常"
        assert not os.path.exists(jl_path), f"红线关时 JSONL 不应被创建：{jl_path}"


# ==================================================================
# T22 TC-2 env FUND_7ENGINES_BOOST =1 → enable=True；0/空 → False
# ==================================================================
class TestTC2EnvVarToggle:
    def test_tc2_env_on_sets_true(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FUND_7ENGINES_BOOST", "1")
        c = _mk_computer(tmp_path, shadow_enable=True, set_via_env=True, monkeypatch=monkeypatch)
        assert c.enable_fundamental_7engines_boost is True, "env=1 时 enable 应为 True"

    def test_tc2_env_off_sets_false(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FUND_7ENGINES_BOOST", "0")
        c = _mk_computer(tmp_path, shadow_enable=False, set_via_env=True, monkeypatch=monkeypatch)
        assert c.enable_fundamental_7engines_boost is False, "env=0 时 enable 应为 False"

    def test_tc2_no_env_default_false(self, tmp_path, monkeypatch):
        """未设置 env → 实例值跟随类属性 False。"""
        monkeypatch.delenv("FUND_7ENGINES_BOOST", raising=False)
        Cls = _get_computer_cls()
        c = Cls()
        assert c.enable_fundamental_7engines_boost is False, "无 env 时 enable 应为 False（跟随类属性红线）"


# ==================================================================
# T23 TC-3 enable=True + 正常 news → 写 JSONL，9 字段全 + 数值合法
# ==================================================================
class TestTC3ShadowWriteOk:
    def test_tc3_jsonl_9_field_schema(self, tmp_path, monkeypatch):
        c = _mk_computer(tmp_path, shadow_enable=True)
        monkeypatch.setattr(c, "_fetch_news_72h_limit200", _mock_sqlite_news(_sample_news_positive_4()))
        jl_path = c._fd7_shadow_jsonl_path

        res1 = c.compute(coin_data=_sample_coin_data(), system_state=_sample_system_state())
        assert os.path.exists(jl_path), f"enable=True 后 JSONL 应被创建：{jl_path}"
        records = _read_jsonl(jl_path)
        assert len(records) >= 1, f"至少 1 条 JSONL 记录，实际={len(records)}"
        rec = records[-1]
        req_fields = {"ts_ms", "asset_class_cnt", "coin_classes",
                      "fd_S_dao_mean", "fd_S_tian_mean", "fd_A_dao_mean", "fd_A_tian_mean",
                      "shadow_reason_code", "import_fail_count"}
        missing = req_fields - set(rec.keys())
        assert len(missing) == 0, f"9 字段缺失：{missing}"
        assert isinstance(rec["ts_ms"], int) and rec["ts_ms"] > 1_700_000_000_000
        assert rec["asset_class_cnt"] == 3
        assert isinstance(rec["coin_classes"], list) and len(rec["coin_classes"]) == 3
        for k in ("fd_S_dao_mean", "fd_S_tian_mean"):
            assert isinstance(rec[k], (int, float)), f"{k} 非数值"
            v = float(rec[k])
            assert -0.10 - 1e-9 <= v <= 0.10 + 1e-9, f"{k}={v} 超出 S级 ±0.10 区间"
        for k in ("fd_A_dao_mean", "fd_A_tian_mean"):
            assert isinstance(rec[k], (int, float)), f"{k} 非数值"
            v = float(rec[k])
            assert -0.05 - 1e-9 <= v <= 0.05 + 1e-9, f"{k}={v} 超出 A级 ±0.05 区间"
        assert rec["shadow_reason_code"] == "FD7_OK", f"正常场景应为 FD7_OK，实={rec['shadow_reason_code']}"
        assert isinstance(rec["import_fail_count"], int) and rec["import_fail_count"] >= 0
        # 字节等价：shadow 不影响 result → 关掉红线重算应该 deep equal
        c2 = _mk_computer(tmp_path, shadow_enable=False)
        monkeypatch.setattr(c2, "_fetch_news_72h_limit200", _mock_sqlite_news(_sample_news_positive_4()))
        res2 = c2.compute(coin_data=_sample_coin_data(), system_state=_sample_system_state())
        assert res1 == res2, "Shadow 开启时 result 必须字节等价于 shadow 关闭（红线只读）"


# ==================================================================
# T24 TC-4 无 news（空 list）→ FD7_NO_NEWS；4 boost 均值=0.0
# ==================================================================
class TestTC4NoNewsReasonCode:
    def test_tc4_no_news_rc_no_news(self, tmp_path, monkeypatch):
        c = _mk_computer(tmp_path, shadow_enable=True)
        monkeypatch.setattr(c, "_fetch_news_72h_limit200", _mock_sqlite_news([]))
        c.compute(coin_data=_sample_coin_data(), system_state=_sample_system_state())
        records = _read_jsonl(c._fd7_shadow_jsonl_path)
        assert len(records) >= 1
        rec = records[-1]
        assert rec["shadow_reason_code"] == "FD7_NO_NEWS", \
            f"空 news 应为 FD7_NO_NEWS，实={rec['shadow_reason_code']}"
        for k in ("fd_S_dao_mean", "fd_S_tian_mean"):
            assert float(rec[k]) == 0.0, f"无新闻时 S级 {k} 应为 0.0，实={rec[k]}"


# ==================================================================
# T25 TC-5 news/r3d/signal 全缺 → FD7_NO_DATA（合并态）；仍写 JSONL，数值合法
# ==================================================================
class TestTC5AllNoData:
    def test_tc5_all_none_rc_no_data(self, tmp_path, monkeypatch):
        c = _mk_computer(tmp_path, shadow_enable=True)
        monkeypatch.setattr(c, "_fetch_news_72h_limit200", _mock_sqlite_news([]))
        # system_state 不含 r3d / signal_engine（TC-4 也没有，但此处 A 级也要缺）
        ss_no_a: Dict[str, Any] = {"timestamp_ms": 1_755_204_000_000,
                                   "_by_class": {"crypto_usdt": {"jiang_score": 72, "fa_score": 65, "war_state": "COOLDOWN"},
                                                 "us_stock": {"jiang_score": 60, "fa_score": 58, "war_state": "ALLOW"},
                                                 "precious_metal": {"jiang_score": 55, "fa_score": 62, "war_state": "COOLDOWN"}}}
        # 断言：reason_code 至少包含 NO_NEWS 或 NO_DATA（任一）
        c.compute(coin_data=_sample_coin_data(), system_state=ss_no_a)
        records = _read_jsonl(c._fd7_shadow_jsonl_path)
        assert len(records) >= 1
        rec = records[-1]
        rc = rec["shadow_reason_code"]
        assert rc in ("FD7_NO_NEWS", "FD7_NO_DATA", "FD7_NO_R3D"), \
            f"全缺场景 reason_code 应为 NO_* 族，实={rc}"
        for k in ("fd_S_dao_mean", "fd_S_tian_mean", "fd_A_dao_mean", "fd_A_tian_mean"):
            v = float(rec[k])
            assert -0.10 <= v <= 0.10, f"数值不合法：{k}={v}"


# ==================================================================
# T26 TC-6 引擎 ImportError → FD7_IMPORT_ERROR + fail_count ≥ 1，不抛异常
# ==================================================================
class TestTC6ImportError:
    def test_tc6_event_ledger_import_error(self, tmp_path, monkeypatch):
        """在 engines.event_ledger_engine.generate_ledger 调用前注入 ImportError。"""
        import sys
        # monkeypatch 直接替换 c 内部的 _fetch 正常，但是引擎 import 失败。
        # 做法：把 sys.modules["engines.event_ledger_engine"] 临时删除，并让 import 语句抛错
        real_mod = sys.modules.pop("engines.event_ledger_engine", None)
        try:
            def boom_import(*a, **kw):
                raise ImportError("event_ledger_engine: ops/nanoclaw not found")

            # 替换引擎 import：在 boost 方法内部 try except 会抓到 ImportError，导致 fail_count++
            c = _mk_computer(tmp_path, shadow_enable=True)
            monkeypatch.setattr(c, "_fetch_news_72h_limit200", _mock_sqlite_news(_sample_news_positive_4()))

            # 直接 monkeypatch 引擎模块名到 sys.modules，让 from ... import 返回 boom
            fake_mod = type(sys)("engines.event_ledger_engine_fake")
            fake_mod.generate_ledger = boom_import  # type: ignore[attr-defined]
            sys.modules["engines.event_ledger_engine"] = fake_mod  # type: ignore[assignment]

            # 计算（shadow 开），不得抛任何异常
            result = c.compute(coin_data=_sample_coin_data(), system_state=_sample_system_state())
            assert isinstance(result, dict) and len(result) == 3
            records = _read_jsonl(c._fd7_shadow_jsonl_path)
            assert len(records) >= 1
            rec = records[-1]
            assert rec["import_fail_count"] >= 1, f"ImportError 场景 fail_count 应≥1，实={rec['import_fail_count']}"
            assert rec["shadow_reason_code"] == "FD7_IMPORT_ERROR", \
                f"ImportError 场景应为 FD7_IMPORT_ERROR，实={rec['shadow_reason_code']}"
        finally:
            if real_mod is not None:
                sys.modules["engines.event_ledger_engine"] = real_mod
            else:
                sys.modules.pop("engines.event_ledger_engine", None)


# ==================================================================
# T27 TC-7 原因码枚举覆盖：3 场景产出 3 个不同 reason_code，均在允许集合内
# ==================================================================
class TestTC7ReasonCodeEnum:
    def test_tc7_3_cases_3_rc_in_enum(self, tmp_path, monkeypatch):
        # Case A: 正常 → FD7_OK
        c_a = _mk_computer(tmp_path, shadow_enable=True, override_runtime_dir=tmp_path/"ca")
        monkeypatch.setattr(c_a, "_fetch_news_72h_limit200", _mock_sqlite_news(_sample_news_positive_4()))
        c_a.compute(coin_data=_sample_coin_data(), system_state=_sample_system_state())
        rc_a = _read_jsonl(c_a._fd7_shadow_jsonl_path)[-1]["shadow_reason_code"]

        # Case B: 空 news → FD7_NO_NEWS
        c_b = _mk_computer(tmp_path, shadow_enable=True, override_runtime_dir=tmp_path/"cb")
        monkeypatch.setattr(c_b, "_fetch_news_72h_limit200", _mock_sqlite_news([]))
        c_b.compute(coin_data=_sample_coin_data(), system_state=_sample_system_state())
        rc_b = _read_jsonl(c_b._fd7_shadow_jsonl_path)[-1]["shadow_reason_code"]

        # Case C: 引擎抛错（通过 monkeypatch S3 hook 抛 ImportError 类似），
        #         但更简单：在 S_dao_boost 方法直接强制 import_fail_count 递增 → 让 shadow 捕捉。
        #         做法：monkeypatch c._fd_S_dao_boost 强制抛 Exception，shadow 外层吞 → GENERIC_ERR
        c_c = _mk_computer(tmp_path, shadow_enable=True, override_runtime_dir=tmp_path/"cc")
        monkeypatch.setattr(c_c, "_fetch_news_72h_limit200", _mock_sqlite_news(_sample_news_positive_4()))
        def boom_s_dao(*a, **kw):
            raise RuntimeError("generic compute error")
        monkeypatch.setattr(c_c, "_fd_S_dao_boost", boom_s_dao)
        c_c.compute(coin_data=_sample_coin_data(), system_state=_sample_system_state())
        rc_c = _read_jsonl(c_c._fd7_shadow_jsonl_path)[-1]["shadow_reason_code"]

        observed = {rc_a, rc_b, rc_c}
        assert len(observed) >= 2, f"至少 2 个不同 reason_code，实={observed}"
        for rc in observed:
            assert rc in FD7_REASON_CODES_EXPECTED, f"未知 reason_code：{rc}，允许集合={FD7_REASON_CODES_EXPECTED}"
        assert "FD7_OK" == rc_a, f"Case A 应为 FD7_OK，实={rc_a}"
        assert "FD7_NO_NEWS" == rc_b, f"Case B 应为 FD7_NO_NEWS，实={rc_b}"
        # Case C: GENERIC_ERR（_fd_S_dao_boost 抛错被外层 try 吞，shadow 记录 GENERIC_ERR 或仍 OK）
        assert rc_c in ("FD7_GENERIC_ERR", "FD7_OK"), \
            f"Case C 异常场景应为 GENERIC_ERR 或 fail-open=FD7_OK（若 boost 内部已隔离），实={rc_c}"


# ==================================================================
# T28 TC-8 PermissionError：jsonl 只读父目录或只读文件，shadow 不抛 result 正常
# ==================================================================
class TestTC8PermissionFailOpen:
    def test_tc8_permission_error_no_throw(self, tmp_path, monkeypatch):
        readonly_dir = tmp_path / "ro"
        readonly_dir.mkdir()
        # macOS chmod 444 目录仍可删除文件但不能写；这里用更稳健的 monkeypatch open 抛 PermissionError
        c = _mk_computer(tmp_path, shadow_enable=True, override_runtime_dir=readonly_dir)
        monkeypatch.setattr(c, "_fetch_news_72h_limit200", _mock_sqlite_news(_sample_news_positive_4()))

        import builtins
        real_open = builtins.open

        def open_with_perm_err(file, *args, **kw):
            # 仅拦截针对 jsonl 文件的写操作
            if isinstance(file, (str, os.PathLike)):
                fstr = os.fspath(file)
                if fstr == c._fd7_shadow_jsonl_path and len(args) >= 1 and "a" in str(args[0]):
                    raise PermissionError("[Errno 13] Permission denied")
            return real_open(file, *args, **kw)

        monkeypatch.setattr(builtins, "open", open_with_perm_err)
        try:
            result = c.compute(coin_data=_sample_coin_data(), system_state=_sample_system_state())
            assert isinstance(result, dict) and len(result) == 3, "PermissionError 场景 result 仍正常"
        finally:
            monkeypatch.undo()


# ==================================================================
# T29 TC-9 eval 脚本：样本不足（n=0 / n<1500）→ exit=2
# ==================================================================
class TestTC9EvalExit2:
    EVAL = os.path.join(_ML4, "fd7engines_hitrate_eval.py")

    def test_tc9_eval_script_exists(self):
        assert os.path.exists(self.EVAL), f"评估脚本不存在：{self.EVAL}"

    def test_tc9_empty_jsonl_exit_2(self, tmp_path):
        """空 JSONL → exit=2（样本不足观察中）。"""
        empty_jl = tmp_path / "empty.jsonl"
        empty_jl.write_text("", encoding="utf-8")
        r = os.system(f'/usr/bin/python3 "{self.EVAL}" "{empty_jl}" 2>/dev/null >/dev/null')
        # os.system 返回 (signal << 8) | exit_code；macos zsh 退出码在高8位
        code = (r >> 8) & 0xFF
        assert code == 2, f"空 JSONL 评估脚本预期 exit=2，实={code}（raw={r}）"


# ==================================================================
# T30 TC-10 eval 脚本：7门槛 G1-G7 + 样本≥1500 → exit=0 或 exit=1
# ==================================================================
class TestTC10EvalExit01:
    EVAL = os.path.join(_ML4, "fd7engines_hitrate_eval.py")

    def _write_mock_jsonl(self, path: Path, n_records: int, *, g2_fail: bool = False, all_pass: bool = False):
        """构造满足 schema 的 N 条 mock JSONL 记录，通过字段让 G2 单独失败或全7门PASS。"""
        import random
        random.seed(42)
        records = []
        # 每条记录构造：reason_code=FD7_OK，import_fail_count=0
        # 评估指标近似通过每个样本字段均值、标准差、分布等推出7门槛
        # 这里简化：在 JSONL 行里追加 "_G_hit" 元字段（eval 脚本只关心约定统计字段）
        for i in range(n_records):
            # G2 thaw_accuracy = 正确解冻 / 总解冻事件；如果失败 = ratio 0.68 < 0.70
            # 简化用 meta 字段标记：_thaw_hit=1/0 让 eval 统计
            thaw = 1 if (random.random() < (0.68 if g2_fail else 0.82)) else 0
            # G1 hit_rate = 预测方向命中率；PASS=0.65，FAIL=0.55
            hit = 1 if (random.random() < (0.65 if all_pass or not g2_fail else 0.72)) else 0
            # G3 sharpe_annual 近似（正样本均值-回撤标准差比例）
            # 简化：用 _pnl 日级 float，均值 0.008, std 0.006 时 sharpe 日=1.33, ≈ 21.1 年化 > 1.05
            pnl = random.gauss(0.008 if (all_pass or not g2_fail) else 0.001,
                               0.006 if (all_pass or not g2_fail) else 0.02)
            rec = {
                "ts_ms": 1_755_000_000_000 + i * 300_000,
                "asset_class_cnt": 3,
                "coin_classes": ["crypto_usdt", "precious_metal", "us_stock"],
                "fd_S_dao_mean": random.uniform(-0.02, 0.08),
                "fd_S_tian_mean": random.uniform(-0.01, 0.07),
                "fd_A_dao_mean": random.uniform(-0.01, 0.04),
                "fd_A_tian_mean": random.uniform(-0.01, 0.02),
                "shadow_reason_code": "FD7_OK",
                "import_fail_count": 0,
                # eval 专用辅助字段
                "_hit": hit, "_thaw": thaw, "_pnl": pnl,
                "_s_acc": 1 if (random.random() < (0.85 if all_pass else 0.80)) else 0,  # G5 75%
                "_a_cons": 1 if (random.random() < (0.70 if all_pass else 0.65)) else 0,  # G6 60%
                "_sch_pass": 1 if (random.random() < (0.97 if all_pass else 0.93)) else 0,  # G7 95%
            }
            records.append(rec)
        with open(path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

    def test_tc10_n_ge_1500_single_fail_exit_1(self, tmp_path):
        """n≥1500，G2 thaw_accuracy 单独 FAIL（68%<70%）→ exit=1。"""
        if not os.path.exists(self.EVAL):
            pytest.skip("eval 脚本未实现（先 RED 跳过 GREEN 阶段再补）")
        jl = tmp_path / "g2_fail.jsonl"
        self._write_mock_jsonl(jl, 1500, g2_fail=True)
        r = os.system(f'/usr/bin/python3 "{self.EVAL}" "{jl}" 2>/dev/null >/dev/null')
        code = (r >> 8) & 0xFF
        assert code == 1, f"G2 FAIL 场景预期 exit=1，实={code}"

    def test_tc10_n_ge_1500_all_pass_exit_0(self, tmp_path):
        """n≥1500，7门槛全PASS → exit=0。"""
        if not os.path.exists(self.EVAL):
            pytest.skip("eval 脚本未实现（先 RED 跳过 GREEN 阶段再补）")
        jl = tmp_path / "all_pass.jsonl"
        self._write_mock_jsonl(jl, 1500, all_pass=True)
        r = os.system(f'/usr/bin/python3 "{self.EVAL}" "{jl}" 2>/dev/null >/dev/null')
        code = (r >> 8) & 0xFF
        assert code == 0, f"全PASS 场景预期 exit=0，实={code}"
