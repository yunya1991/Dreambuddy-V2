#!/usr/bin/env python3
"""
Phase D 铁律 2（§3.2）双验证运行器 — AI_ENHANCEMENT_ROADMAP 门禁可执行化
====================================================================
对比: v15-final 基线(B+) vs Phase D 闸门（heuristic MVP 桥接 或 已训练模型）

验证项（docs/AI_ENHANCEMENT_ROADMAP.md §3.2）:
  ① 全量历史回测: 5 币总收益 ≥ 基线 +5% 且 平均 Calmar ≥ 基线 × 1.05
  ② Walk-Forward 5 段: 每段退化率 < 10% 且 ≥3 段正向增益（跨币池化分段）
  ③ 回撤控制: MDD ≤ 基线 × 1.10; 最大连续亏损笔数 ≤ 基线 + 2
  ④ OOD 极端行情(2024-11/2025-05): 离线缓存窗口不覆盖 → 标记 SKIPPED_OFFLINE

数据源: data/backtest_cache/{COIN}_4h_1500.json 直读（绕开 fetch_klines 7 天缓存
时限与网络依赖，保证完全离线可复现）。

报告输出: data/ai_benchmarks/phase_D_{mode}_{sha}_wf_report.json
用法:
  python3 phase_d_validate_iron2.py --mode heuristic
  python3 phase_d_validate_iron2.py --mode model \
      --bilstm data/ai_models/phase_d_bilstm_v1.pt \
      --patchtst data/ai_models/phase_d_patchtst_v1.pt
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

DIR = Path(__file__).parent
sys.path.insert(0, str(DIR / "core"))
sys.path.insert(0, str(DIR / "lib"))

from v15_backtest import run_backtest  # noqa: E402

COINS = ["BTC", "ETH", "SOL", "ARB", "OP"]  # §3.2 Phase4 小币种池 5 币
KLIMIT = 1500
INITIAL_CAPITAL = 10000.0

# v15-final 部署形态（data/v15_final_deployment.json active_config 映射）
BASE_KW = dict(
    initial_capital=INITIAL_CAPITAL,
    base_position_pct=0.22,
    max_addons=4,                    # MAX_ADDONS_PER_POSITION=4（5 单链路）
    long_only=False,                 # V15_ALLOW_SHORT=true
    use_direction_gate=True,         # 含 BTC 风向标智能模式内部路由
    use_atr=True,                    # ATR 动态止盈
    use_trailing_tp=True,            # 移动止盈
    trailing_atr_mult=1.0,
    trailing_start_pct_of_tp=0.8,
    use_elder_ray=True,              # ELDER-RAY 资金调度
    subregime_enabled=True,          # Phase B+ 子形态微调
    max_base_holding_hours=29.9,
    max_post_addon_hours=37.7,
    golden_window_hours=11.1,
    regime_cooldown_bars=12,
)


def load_klines_offline(coin: str):
    """直读 backtest_cache，绕开 fetch_klines 缓存时限/网络。"""
    cache = DIR / "data" / "backtest_cache" / f"{coin}_4h_{KLIMIT}.json"
    if not cache.exists():
        raise FileNotFoundError(f"离线缓存缺失: {cache}")
    payload = json.loads(cache.read_text(encoding="utf-8"))
    data = payload.get("data", [])
    if len(data) < 500:
        raise ValueError(f"{coin} 缓存 K 线不足: {len(data)}")
    return data


def max_consecutive_losses(trades) -> int:
    streak = best = 0
    for t in trades:
        if float(t.get("pnl_usd", 0.0)) <= 0:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    return best


def wf_segment(base_trades, test_trades, total_bars, n_seg=5):
    """跨币池化: 按 exit_idx 分 5 段，返回每段 (base_pnl, test_pnl)。"""
    def seg_pnl(trades):
        if not trades:
            return [0.0] * n_seg
        min_idx = min(t.get("exit_idx", 0) for t in trades)
        max_idx = max(t.get("exit_idx", 0) for t in trades)
        span = max_idx - min_idx + 1
        seg_size = max(1, span // n_seg)
        out = [0.0] * n_seg
        for t in trades:
            s = min(n_seg - 1, (t.get("exit_idx", 0) - min_idx) // seg_size)
            out[s] += float(t.get("pnl_usd", 0.0))
        return out

    b, x = [0.0] * n_seg, [0.0] * n_seg
    for bt, tt in zip(base_trades, test_trades):
        bp, tp = seg_pnl(bt), seg_pnl(tt)
        b = [b[i] + bp[i] for i in range(n_seg)]
        x = [x[i] + tp[i] for i in range(n_seg)]
    return b, x


def run_one(coin, klines, phase_d: bool):
    return run_backtest(
        coin=coin, klines=klines, phase_d_ai_enabled=phase_d, **BASE_KW
    )


def git_sha():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=DIR, text=True
        ).strip()
    except Exception:
        return "nogit"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["heuristic", "model"], default="heuristic")
    ap.add_argument("--bilstm", type=str, default="")
    ap.add_argument("--patchtst", type=str, default="")
    args = ap.parse_args()

    if args.mode == "model":
        # 注入模型路径: 替换 v15_backtest 的 gateway 工厂（铁律1: 失败→None→纯基线）
        import v15_backtest as vb
        from phase_d_gateway import PhaseDGateway

        def _make_gateway(enabled: bool, baseline_max: int = 4):
            if not enabled:
                return None
            try:
                return PhaseDGateway(
                    enabled=True,
                    bilstm_model_path=args.bilstm or None,
                    patchtst_model_path=args.patchtst or None,
                )
            except Exception:
                return None

        vb._phase_d_make_gateway = _make_gateway
        print(f"[model] bilstm={args.bilstm} patchtst={args.patchtst}")
        print(f"[model-debug] 工厂已注入: {vb._phase_d_make_gateway is _make_gateway} | run_backtest globals 一致: {run_backtest.__globals__.get('_phase_d_make_gateway') is _make_gateway}")
        # 推理计数诊断
        import phase_d_gateway as _pdg2
        _REAL_CALLS = {"bilstm": 0, "patchtst": 0, "bilstm_exc": 0, "patchtst_exc": 0, "first_exc": None}
        _ob2 = _pdg2.PhaseDGateway._run_real_bilstm
        _op2 = _pdg2.PhaseDGateway._run_real_patchtst
        def _spb(self, ctx):
            _REAL_CALLS["bilstm"] += 1
            try:
                return _ob2(self, ctx)
            except Exception as _e:
                _REAL_CALLS["bilstm_exc"] += 1
                if _REAL_CALLS["first_exc"] is None:
                    _REAL_CALLS["first_exc"] = f"{type(_e).__name__}: {str(_e)[:120]}"
                raise
        def _spp(self, ctx):
            _REAL_CALLS["patchtst"] += 1
            try:
                return _op2(self, ctx)
            except Exception as _e:
                _REAL_CALLS["patchtst_exc"] += 1
                if _REAL_CALLS["first_exc"] is None:
                    _REAL_CALLS["first_exc"] = f"{type(_e).__name__}: {str(_e)[:120]}"
                raise
        _pdg2.PhaseDGateway._run_real_bilstm = _spb
        _pdg2.PhaseDGateway._run_real_patchtst = _spp

    results = {}
    all_base_trades, all_test_trades = [], []
    tot_ret_base = tot_ret_test = 0.0
    calmar_base, calmar_test = [], []
    mdd_base, mdd_test = [], []
    cl_base, cl_test = [], []
    total_bars = KLIMIT

    for coin in COINS:
        klines = load_klines_offline(coin)
        total_bars = max(total_bars, len(klines))
        rb = run_one(coin, klines, phase_d=False)
        rt = run_one(coin, klines, phase_d=True)
        mb, mt = rb.get("metrics", {}), rt.get("metrics", {})
        results[coin] = {
            "base": {k: mb.get(k) for k in ("total_return_pct", "sharpe_ratio", "max_drawdown_pct", "total_trades", "win_rate", "profit_factor")},
            "test": {k: mt.get(k) for k in ("total_return_pct", "sharpe_ratio", "max_drawdown_pct", "total_trades", "win_rate", "profit_factor")},
            "base_max_consec_loss": max_consecutive_losses(rb.get("trades", [])),
            "test_max_consec_loss": max_consecutive_losses(rt.get("trades", [])),
        }
        all_base_trades.append(rb.get("trades", []))
        all_test_trades.append(rt.get("trades", []))
        tot_ret_base += float(mb.get("total_return_pct", 0.0) or 0.0)
        tot_ret_test += float(mt.get("total_return_pct", 0.0) or 0.0)
        # calmar: total_return / MDD（回测 metrics 无现成 calmar 键，按定义计算）
        _mb_mdd = float(mb.get("max_drawdown_pct", 0.0) or 0.0)
        _mt_mdd = float(mt.get("max_drawdown_pct", 0.0) or 0.0)
        calmar_base.append(
            float(mb.get("total_return_pct", 0.0) or 0.0) / _mb_mdd if _mb_mdd > 0 else 0.0
        )
        calmar_test.append(
            float(mt.get("total_return_pct", 0.0) or 0.0) / _mt_mdd if _mt_mdd > 0 else 0.0
        )
        mdd_base.append(float(mb.get("max_drawdown_pct", 0.0) or 0.0))
        mdd_test.append(float(mt.get("max_drawdown_pct", 0.0) or 0.0))
        cl_base.append(results[coin]["base_max_consec_loss"])
        cl_test.append(results[coin]["test_max_consec_loss"])
        print(
            f"[{coin}] base_ret={results[coin]['base']['total_return_pct']:.2f}% "
            f"test_ret={results[coin]['test']['total_return_pct']:.2f}% "
            f"base_mdd={results[coin]['base']['max_drawdown_pct']:.2f}% "
            f"test_mdd={results[coin]['test']['max_drawdown_pct']:.2f}%"
        )

    # ---- ① 全量回测相对增益 ----
    c1_return = tot_ret_test >= tot_ret_base + 5.0  # 总收益(5币和) ≥ 基线 +5pct
    cb = sum(calmar_base) / len(calmar_base)
    ct = sum(calmar_test) / len(calmar_test)
    c1_calmar = ct >= cb * 1.05 if cb > 0 else ct > 0
    crit1 = c1_return and c1_calmar

    # ---- ② Walk-Forward 5 段（池化） ----
    bseg, tseg = wf_segment(all_base_trades, all_test_trades, total_bars)
    seg_report, n_degraded, n_positive = [], 0, 0
    for i in range(5):
        b, x = bseg[i], tseg[i]
        if abs(b) < 1e-6:
            degraded = x < 0
            positive = x > 0
            deg_pct = 0.0 if not degraded else 100.0
        else:
            deg_pct = max(0.0, (b - x) / abs(b) * 100.0)
            degraded = deg_pct >= 10.0
            positive = x > b
        if degraded:
            n_degraded += 1
        if positive:
            n_positive += 1
        seg_report.append({"seg": i + 1, "base_pnl": round(b, 2), "test_pnl": round(x, 2), "degradation_pct": round(deg_pct, 2), "degraded": degraded, "positive": positive})
    crit2 = (n_degraded == 0) and (n_positive >= 3)

    # ---- ③ 回撤控制 ----
    mb_avg = sum(mdd_base) / len(mdd_base)
    mt_avg = sum(mdd_test) / len(mdd_test)
    c3_mdd = mt_avg <= mb_avg * 1.10
    c3_consec = all(t <= b + 2 for b, t in zip(cl_base, cl_test))
    crit3 = c3_mdd and c3_consec

    # ---- ④ OOD ----
    crit4 = "SKIPPED_OFFLINE"  # 缓存窗口(~2025-12~2026-08)不含 2024-11/2025-05

    # ---- S_bt (§3.4.1) ----
    gr = (tot_ret_test / tot_ret_base) if tot_ret_base > 0 else 0.0
    cr = (ct / cb) if cb > 0 else 0.0
    mdd_ratio = (mt_avg / mb_avg) if mb_avg > 0 else 1.0
    s_bt = 0.40 * gr + 0.30 * cr + 0.20 * (n_positive / 5) + 0.10 * max(0.0, 1 - abs(mdd_ratio - 1))
    if s_bt >= 1.20:
        k_bound = 1.20
    elif s_bt >= 1.05:
        k_bound = 1.00
    elif s_bt >= 1.00:
        k_bound = 0.80
    else:
        k_bound = None  # 不合格 → 禁止启用

    overall = crit1 and crit2 and crit3  # ④ 离线不可验证，不计入自动门禁，报告中标注
    report = {
        "phase": "D",
        "mode": args.mode,
        "git_sha": git_sha(),
        "coins": COINS,
        "baseline_form": "v15-final (Phase B+) per data/v15_final_deployment.json",
        "criteria": {
            "1_full_backtest": {
                "pass": crit1,
                "total_return_base_pct": round(tot_ret_base, 2),
                "total_return_test_pct": round(tot_ret_test, 2),
                "required_test_min_pct": round(tot_ret_base + 5.0, 2),
                "calmar_base_avg": round(cb, 3),
                "calmar_test_avg": round(ct, 3),
                "return_ok": c1_return,
                "calmar_ok": c1_calmar,
            },
            "2_walk_forward": {
                "pass": crit2,
                "segments": seg_report,
                "degraded_segments": n_degraded,
                "positive_segments": n_positive,
                "rule": "0 段退化≥10% 且 ≥3 段正向",
            },
            "3_drawdown": {
                "pass": crit3,
                "mdd_base_avg_pct": round(mb_avg, 2),
                "mdd_test_avg_pct": round(mt_avg, 2),
                "mdd_ok": c3_mdd,
                "consec_loss_ok": c3_consec,
            },
            "4_ood": crit4,
        },
        "per_coin": results,
        "s_bt": round(s_bt, 4),
        "k_bound_recommendation": k_bound,
        "overall_pass": overall,
        "note": "④ OOD 需 2024-11/2025-05 数据，离线缓存不覆盖，启用前须补验；heuristic 模式=MVP桥接闸门逻辑验证",
    }
    out_dir = DIR / "data" / "ai_benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"phase_D_{args.mode}_{report['git_sha']}_wf_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 72)
    if args.mode == "model":
        try:
            import phase_d_gateway as _pdg
            print(f"[model-debug] _MODEL_CACHE keys: {list(_pdg._MODEL_CACHE.keys())}")
            for _k, _v in _pdg._MODEL_CACHE.items():
                print(f"[model-debug]   {_k[0]}: {'加载成功' if _v is not None else '加载失败=None→降级heuristic'}")
            print(f"[model-debug] 真实推理调用: {_REAL_CALLS}")
        except Exception as _e:
            print(f"[model-debug] cache检查失败: {_e}")
    print(f"① 全量回测: {'PASS' if crit1 else 'FAIL'}  (ret {tot_ret_base:.2f}%→{tot_ret_test:.2f}%, 需≥{tot_ret_base + 5:.2f}%; calmar {cb:.3f}→{ct:.3f}, 需≥{cb * 1.05:.3f})")
    print(f"② Walk-Forward: {'PASS' if crit2 else 'FAIL'}  (退化段 {n_degraded}/5, 正向段 {n_positive}/5)")
    print(f"③ 回撤控制: {'PASS' if crit3 else 'FAIL'}  (MDD {mb_avg:.2f}%→{mt_avg:.2f}%, 上限 {mb_avg * 1.1:.2f}%)")
    print(f"④ OOD: {crit4}")
    print(f"S_bt={s_bt:.4f}  K_bound建议={k_bound}")
    print(f"总体门禁: {'✅ PASS — 可进入启用流程(快照+CHANGELOG+审批)' if overall else '❌ FAIL — 不得实盘启用 (铁律2)'}")
    print(f"报告: {out_path}")


if __name__ == "__main__":
    main()
