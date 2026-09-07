"""D2: 性能统计脚本测试 — TDD 先红后绿。

覆盖指标：
  1. IC（Spearman 信息系数）7d/14d/30d
  2. 命中率：sign(score) == sign(ret) 比例，score=0 剔除
  3. S-C Sharpe 模拟：S=+1，C=-1，A/B=0，按 7d 持有期年化
  4. 衰减分析：7d IC > 14d IC > 30d IC 趋势
  5. 不足样本：return_Nd 非空 < 30 → 标记 insufficient
  6. 滚动窗口：timestamp 在 [now-window_days, now] 才纳入
  7. score=0/接近0 记录不参与命中率（避免信号中性 0 污染）
  8. compute_metrics 返回结构含 sample_sizes / ic / hit_rate / s_c_sharpe
  9. write_report 写 JSON 报告（原子）
  10. 单窗口可用但其他不足：该窗口指标标记 None 不影响其他
  11. rank 分布统计（S/A/B/C 计数）
  12. CLI 入口：--jsonl-path / --window-days / --out-path
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))
if str(_L4_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(_L4_DIR / "scripts"))


def _ts(days_ago: int, tz_offset=8) -> str:
    tz = timezone(timedelta(hours=tz_offset))
    return (datetime.now(tz) - timedelta(days=days_ago)).isoformat()


def _make_records(n=100, score_to_ret_corr: float = 0.8,
                  window_days_age: int = 14, score_zero_ratio=0.1):
    """构造 n 条合成数据：score ~ Uniform(-1,1)，ret_7d = corr*score + eps。

    所有记录设为 window_days_age 天前（保证能进入 7d/14d 窗口，若≥30天则入 30d）。
    只填充 7d/14d/30d return（真实地模拟 D1 已回填）。
    其中 score_zero_ratio 比例强制 score=0.0（用于命中率剔除测试）。
    """
    import random
    import math
    random.seed(42)
    records = []
    for i in range(n):
        raw_score = random.uniform(-1, 1)
        eps = random.gauss(0, 0.2)
        ret = score_to_ret_corr * raw_score * 10.0 + eps * 2.0
        # 某比例强制 score=0（命中率剔除样本）
        if i < int(n * score_zero_ratio):
            raw_score = 0.0
        # 随机分配等级
        rank = "B"
        if raw_score > 0.6:
            rank = "S"
        elif raw_score > 0.3:
            rank = "A"
        elif raw_score < -0.3:
            rank = "C"
        rec = {
            "coin": f"COIN{i % 8}",
            "asset_class": "crypto_usdt" if i % 8 < 5 else ("us_stock" if i % 8 < 7 else "precious_metal"),
            "timestamp": _ts(window_days_age),
            "fundamental_score": round(raw_score, 4),
            "rank": rank,
            "sub_signals": {}, "data_quality": "sufficient",
            "confidence": 1.0, "error": None,
            "price_at_signal": 100.0 + i * 0.1,
            "price_7d_after": None, "price_14d_after": None, "price_30d_after": None,
            "return_7d": None, "return_14d": None, "return_30d": None,
        }
        # 7d 永远填
        rec["return_7d"] = round(ret, 4)
        rec["price_7d_after"] = rec["price_at_signal"] * (1.0 + ret / 100.0)
        if window_days_age >= 14:
            rec["return_14d"] = round(ret * 1.2, 4)  # 14d 放大一些
            rec["price_14d_after"] = rec["price_at_signal"] * (1.0 + rec["return_14d"] / 100.0)
        if window_days_age >= 30:
            rec["return_30d"] = round(ret * 0.6, 4)  # 30d 衰减
            rec["price_30d_after"] = rec["price_at_signal"] * (1.0 + rec["return_30d"] / 100.0)
        records.append(rec)
    return records


def _write_jsonl(records, path: Path):
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ===========================================================================
# 单测 IC / 命中率 / S-C Sharpe
# ===========================================================================

class TestSpearmanIC:
    def test_ic_positive_corr_returns_positive(self):
        from coin_fundamental_perf_stats import _spearman_ic
        scores = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        rets   = [0.5, 0.8, 1.0, 1.5, 2.0, 2.3, 2.7, 3.2, 3.6, 4.0]  # 严格正相关
        ic = _spearman_ic(scores, rets)
        assert ic is not None and ic > 0.9

    def test_ic_negative_corr_returns_negative(self):
        from coin_fundamental_perf_stats import _spearman_ic
        scores = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        rets   = [4.0, 3.6, 3.2, 2.7, 2.3, 2.0, 1.5, 1.0, 0.8, 0.5]  # 严格负相关
        ic = _spearman_ic(scores, rets)
        assert ic is not None and ic < -0.9

    def test_ic_insufficient_samples_returns_none(self):
        from coin_fundamental_perf_stats import _spearman_ic
        assert _spearman_ic([1.0], [2.0], min_samples=30) is None
        assert _spearman_ic([], []) is None

    def test_ic_length_mismatch_returns_none(self):
        from coin_fundamental_perf_stats import _spearman_ic
        assert _spearman_ic([0.1, 0.2], [0.5]) is None


class TestHitRate:
    def test_hit_rate_all_sign_match_returns_one(self):
        from coin_fundamental_perf_stats import _hit_rate
        scores = [0.5, 0.8, -0.3, -0.6]
        rets = [2.0, 3.0, -1.0, -4.0]
        assert _hit_rate(scores, rets) == pytest.approx(1.0)

    def test_hit_rate_zero_scores_excluded(self):
        from coin_fundamental_perf_stats import _hit_rate
        # 2 条 0-score 被剔除，剩余 2 条全中
        scores = [0.5, 0.0, -0.3, 0.0]
        rets = [2.0, -99.0, -1.0, 99.0]
        hr = _hit_rate(scores, rets)
        assert hr == pytest.approx(1.0)

    def test_hit_rate_none_after_exclude_returns_none(self):
        from coin_fundamental_perf_stats import _hit_rate
        assert _hit_rate([0.0, 0.0, 0.0], [1.0, -1.0, 0.5]) is None


class TestSCSHarpe:
    def test_long_s_short_c_consistent_gain(self):
        """S 级全正收益，C 级全负收益（做空赚钱）→ 高 Sharpe。"""
        from coin_fundamental_perf_stats import _sc_sharpe
        ranks = ["S", "S", "S", "C", "C"]
        rets = [1.0, 1.5, 2.0, -1.0, -2.0]  # S做对+4.5, C做空+3.0 合计7.5
        # 持有期7d → 年化 sqrt(365/7) ≈ 7.22
        sharpe = _sc_sharpe(ranks, rets, holding_days=7)
        assert sharpe is not None
        assert sharpe > 1.0

    def test_sc_sharpe_no_s_or_c_returns_none(self):
        from coin_fundamental_perf_stats import _sc_sharpe
        assert _sc_sharpe(["A", "B", "B"], [1.0, -0.5, 0.2]) is None

    def test_sc_sharpe_holding_14d_scales(self):
        """14d 持有期年化因子 sqrt(365/14) < 7d 版本 → Sharpe 更小。"""
        from coin_fundamental_perf_stats import _sc_sharpe
        ranks = ["S", "S", "S", "C", "C"]
        rets = [1.0, 1.5, 2.0, -1.0, -2.0]
        sh7 = _sc_sharpe(ranks, rets, holding_days=7)
        sh14 = _sc_sharpe(ranks, rets, holding_days=14)
        assert sh7 > sh14


# ===========================================================================
# compute_metrics 结构 + 窗口/不足样本/衰减 + 滚动
# ===========================================================================

class TestComputeMetrics:
    def test_returns_correct_keys(self):
        from coin_fundamental_perf_stats import compute_metrics
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "bf.jsonl"
            _write_jsonl(_make_records(100, window_days_age=31, score_to_ret_corr=0.9), src)
            report = compute_metrics(str(src), window_days=60)
            for k in ("generated_at", "window_days", "sample_sizes",
                      "ic", "hit_rate", "s_c_sharpe", "rank_counts"):
                assert k in report

    def test_30d_age_100_samples_all_windows_have_values(self):
        from coin_fundamental_perf_stats import compute_metrics
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "bf.jsonl"
            _write_jsonl(_make_records(100, window_days_age=31, score_to_ret_corr=0.9), src)
            rep = compute_metrics(str(src), window_days=60)
            # 30d age 数据：7/14/30 return 均已填，sample 应 n>=30
            for w in ("7d", "14d", "30d"):
                assert rep["sample_sizes"][w] >= 30
                assert rep["ic"][w] is not None and rep["ic"][w] > 0.3
                assert rep["hit_rate"][w] is not None and rep["hit_rate"][w] > 0.5

    def test_14d_age_no_30d_window(self):
        from coin_fundamental_perf_stats import compute_metrics
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "bf.jsonl"
            _write_jsonl(_make_records(100, window_days_age=15, score_to_ret_corr=0.9), src)
            rep = compute_metrics(str(src), window_days=60)
            assert rep["sample_sizes"]["30d"] == 0
            assert rep["ic"]["30d"] is None  # insufficient
            assert rep["ic"]["7d"] is not None

    def test_rolling_window_excludes_old(self):
        """100 条 = 90 天前（超 60 天窗口）+ 10 条 = 10 天前（窗口内）。
        7d 样本数应仅包含窗口内的 10 条，不足 30 → insufficient。"""
        from coin_fundamental_perf_stats import compute_metrics
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "bf.jsonl"
            old = _make_records(90, window_days_age=90, score_to_ret_corr=0.9)
            recent = _make_records(10, window_days_age=10, score_to_ret_corr=0.9)
            _write_jsonl(old + recent, src)
            rep = compute_metrics(str(src), window_days=60)
            assert rep["sample_sizes"]["7d"] == 10
            # 10 < 30 → insufficient → 返回 None
            assert rep["ic"]["7d"] is None

    def test_rank_counts_all_four_ranks(self):
        from coin_fundamental_perf_stats import compute_metrics
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "bf.jsonl"
            recs = _make_records(200, window_days_age=31, score_to_ret_corr=0.9)
            # 手工加入一条 S 与 C 保证覆盖（合成数据可能缺少极端）
            for s_val, rank in [(-0.9, "C"), (0.9, "S")]:
                recs.append({
                    "coin": "BTC", "asset_class": "crypto_usdt",
                    "timestamp": _ts(31), "fundamental_score": s_val,
                    "rank": rank,
                    "sub_signals": {}, "data_quality": "sufficient",
                    "confidence": 1.0, "error": None,
                    "price_at_signal": 100.0, "price_7d_after": 105.0,
                    "return_7d": 5.0, "return_14d": 7.0, "return_30d": 9.0,
                })
            _write_jsonl(recs, src)
            rep = compute_metrics(str(src))
            for rk in ("S", "A", "B", "C"):
                assert rk in rep["rank_counts"]


# ===========================================================================
# write_report 原子落地
# ===========================================================================

class TestWriteReport:
    def test_atomic_write_json(self, tmp_path=None):
        from coin_fundamental_perf_stats import write_report
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "rep.json")
            rep = {"ic": {"7d": 0.5}, "generated_at": _ts(0)}
            out = write_report(rep, target)
            assert os.path.exists(out)
            with open(out) as f:
                data = json.load(f)
            assert data["ic"]["7d"] == 0.5


# ===========================================================================
# CLI 入口（返回码）
# ===========================================================================

class TestCLI:
    def test_cli_missing_jsonl_returns_nonzero(self):
        from coin_fundamental_perf_stats import main
        rc = main(["--jsonl-path", "/nope/path.jsonl"])
        assert rc != 0

    def test_cli_dry_run_without_out(self):
        from coin_fundamental_perf_stats import main
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "bf.jsonl"
            _write_jsonl(_make_records(100, window_days_age=31), src)
            rc = main(["--jsonl-path", str(src), "--dry-run"])
        assert rc == 0
