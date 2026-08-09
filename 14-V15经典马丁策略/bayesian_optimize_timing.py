"""
Phase4 TimingGate 贝叶斯参数优化器
================================
目标：在 5 个主流 altcoin（ETH/SOL/DOGE/ADA/BNB）上，通过贝叶斯优化
      寻找 TimingGate 最优参数集，使得：
         objective = avg(total_return_pct) + 0.5 * avg(sharpe) → 最大

参数空间（8 维连续）：
  - threshold:          [0.25, 0.65]  放宽入场（默认 0.50）
  - lenient_unclear:    [0.55, 0.85]  UNCLEAR 基线分（strict=False，默认 0.60）
  - unclear_retrace_ext:[0.85, 0.98]  UNCLEAR 时回撤/EXT 分（默认 0.90）
  - retrace_mu:         [0.42, 0.62]  Fib 回撤高斯钟形中心（默认 0.50）
  - retrace_sigma:      [0.15, 0.35]  Fib 回撤高斯钟形宽度（默认 0.18；越大越宽容）
  - fib_retrace_lo:     [0.22, 0.38]  回撤区间下沿（默认 0.30）
  - fib_retrace_hi:     [0.62, 0.80]  回撤区间上沿（默认 0.72）
  - fib_ext_ratio:      [1.50, 2.00]  Fib 扩展倍数（默认 1.618）

固定（不优化）：
  strict=False, swing_window=2, apply_to_btc=False, strict_unclear_score=0.20

API：与 compare_phase4_timing_backtest.py 100% 一致（fetch_klines + run_backtest coin/klines）。
输出：
  - output/phase4_best_params.json   最优参数集
  - output/phase4_bayes_trace.csv    优化过程 trace
"""

from __future__ import annotations

import csv
import json
import sys
import time
import warnings
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "lib"))

OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
BEST_PARAMS_JSON = OUTPUT_DIR / "phase4_best_params.json"
TRACE_CSV = OUTPUT_DIR / "phase4_bayes_trace.csv"

# 贝叶斯优化 5 个小币（不含 BTC；BTC 默认关闭 timing，单独跑也不会受益）
OPT_COINS: List[str] = ["ETH", "SOL", "DOGE", "ADA", "BNB"]
KLIMIT = 1500  # 4h K 线根数（≈ 250 天）
INITIAL_CAPITAL = 10000

# --------------------------------------------------------------------------- #
# 导入回测引擎
# --------------------------------------------------------------------------- #
from v15_backtest import fetch_klines, run_backtest  # type: ignore


def _metrics(r: dict) -> Tuple[float, float, float, int]:
    """返回 (total_return_pct, sharpe, max_dd_pct, n_trades)"""
    m = r.get("metrics", {})
    return (
        float(m.get("total_return_pct", 0.0) or 0.0),
        float(m.get("sharpe_ratio", 0.0) or 0.0),
        float(m.get("max_drawdown_pct", 0.0) or 0.0),
        int(m.get("total_trades", 0) or 0),
    )


def _preload_klines() -> Dict[str, List[Dict]]:
    """一次性加载所有小币的 4h K 线，避免每轮重复 I/O"""
    out: Dict[str, List[Dict]] = {}
    for coin in OPT_COINS:
        k = fetch_klines(coin, "4h", KLIMIT)
        if not k:
            raise RuntimeError(
                f"[{coin}] 4h 历史数据为空，请先运行 `lib/fetch_all_data.py` 或 fetch_klines 拉取"
            )
        out[coin] = k
    return out


def objective(
    params: np.ndarray, klines_map: Dict[str, List[Dict]]
) -> Tuple[float, Dict[str, Tuple[float, float]]]:
    """
    params = [threshold, lenient_unclear, unclear_retrace_ext,
              retrace_mu, retrace_sigma, fib_retrace_lo, fib_retrace_hi, fib_ext_ratio,
              size_power, swing_fusion_idx]
    swing_fusion_idx: 0=daily_only, 1=or, 2=and
    soft_mode 固定 True（仓位软调控落位）
    返回 (objective_scalar, per_coin_metrics: {coin: (total_return_pct, sharpe)})
    """
    (
        threshold,
        lenient_unclear,
        unclear_retrace_ext,
        retrace_mu,
        retrace_sigma,
        fib_retrace_lo,
        fib_retrace_hi,
        fib_ext_ratio,
        size_power,
        swing_fusion_idx,
    ) = params

    _fusion_modes = ["daily_only", "or", "and"]
    swing_fusion_mode = _fusion_modes[int(swing_fusion_idx)]

    per_coin: Dict[str, Tuple[float, float]] = {}
    total_rets: List[float] = []
    sharpes: List[float] = []
    for coin in OPT_COINS:
        klines = klines_map[coin]
        result = run_backtest(
            coin=coin,
            klines=klines,
            initial_capital=INITIAL_CAPITAL,
            use_direction_gate=True,
            # Phase4 开启；默认 apply_to_btc=False → BTC 单独禁用（但本 objective 只跑小币）
            use_timing_gate=True,
            timing_gate_apply_to_btc=False,
            timing_gate_threshold=float(threshold),
            timing_gate_strict=False,
            timing_gate_swing_window=2,
            timing_gate_fib_retrace_lo=float(fib_retrace_lo),
            timing_gate_fib_retrace_hi=float(fib_retrace_hi),
            timing_gate_fib_ext_ratio=float(fib_ext_ratio),
            timing_gate_lenient_unclear=float(lenient_unclear),
            timing_gate_strict_unclear_score=0.20,
            timing_gate_retrace_mu=float(retrace_mu),
            timing_gate_retrace_sigma=float(retrace_sigma),
            timing_gate_unclear_retrace_ext=float(unclear_retrace_ext),
            # 新增：仓位软调控落位 + swing 融合
            timing_gate_soft_mode=True,
            timing_size_power=float(size_power),
            timing_gate_swing_fusion_mode=swing_fusion_mode,
            timing_gate_intraday_swing_window=3,
        )
        ret_pct, sharpe, _dd, _n = _metrics(result)
        per_coin[coin] = (ret_pct, sharpe)
        total_rets.append(ret_pct)
        sharpes.append(sharpe)
    avg_ret = float(np.mean(total_rets))
    avg_sharpe = float(np.mean(sharpes))
    # 目标函数：以收益为主，+0.5*sharpe 奖励（sharpe 量纲远小于 total_return_pct，
    # 权重 0.5 大致等价于每提升 1 点夏普 → 奖励 0.5% 收益，不碾压收益维度）
    return avg_ret + 0.5 * avg_sharpe, per_coin


# --------------------------------------------------------------------------- #
# 简易贝叶斯优化（高斯过程回归 + 期望改进）
# --------------------------------------------------------------------------- #
from scipy.stats import norm  # noqa
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel
from sklearn.preprocessing import MinMaxScaler

BOUNDS = np.array(
    [
        [0.25, 0.65],  # 0: threshold
        [0.55, 0.85],  # 1: lenient_unclear
        [0.85, 0.98],  # 2: unclear_retrace_ext
        [0.42, 0.62],  # 3: retrace_mu
        [0.15, 0.35],  # 4: retrace_sigma
        [0.22, 0.38],  # 5: fib_retrace_lo
        [0.62, 0.80],  # 6: fib_retrace_hi
        [1.50, 2.00],  # 7: fib_ext_ratio
        [0.5, 2.5],  # 8: size_power（>1强化低分惩罚，<1弱化）
        [0.0, 2.999],  # 9: swing_fusion_idx（0=daily_only, 1=or, 2=and）
    ]
)

PARAM_NAMES = [
    "threshold",
    "lenient_unclear",
    "unclear_retrace_ext",
    "retrace_mu",
    "retrace_sigma",
    "fib_retrace_lo",
    "fib_retrace_hi",
    "fib_ext_ratio",
    "size_power",
    "swing_fusion_idx",
]


def expected_improvement(
    X_cand: np.ndarray, gpr: GaussianProcessRegressor, y_best: float, xi: float = 0.01
) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mu, sigma = gpr.predict(X_cand, return_std=True)
    sigma = np.maximum(sigma, 1e-9)
    z = (mu - y_best - xi) / sigma
    ei = (mu - y_best - xi) * norm.cdf(z) + sigma * norm.pdf(z)
    return ei


def bayesian_optimize(
    n_iter: int = 25, n_init: int = 5, seed: int = 42
) -> Tuple[np.ndarray, float, List[Dict], Dict[str, Tuple[float, float]]]:
    rng = np.random.default_rng(seed)

    # 1. 一次性预加载全部小币 K 线
    print(f"[BayesOpt] 预加载 {len(OPT_COINS)} 个小币 4h K 线 (KLIMIT={KLIMIT})...")
    klines_map = _preload_klines()
    for c, k in klines_map.items():
        print(f"  · {c}: {len(k)} bars")
    print("[BayesOpt] 数据加载完成，开始贝叶斯优化...")

    # 2. 初始化：均匀随机 n_init 个点
    X_train: List[np.ndarray] = []
    y_train: List[float] = []
    trace: List[Dict] = []
    best_per_coin: Dict[str, Tuple[float, float]] = {}

    for i in range(n_init):
        x = rng.uniform(BOUNDS[:, 0], BOUNDS[:, 1])
        t0 = time.time()
        val, per_coin = objective(x, klines_map)
        dt = time.time() - t0
        X_train.append(x)
        y_train.append(val)
        if i == 0 or val > max(y_train[:-1]):
            best_per_coin = per_coin
        row = {
            "iter": i,
            "stage": "init",
            "elapsed_sec": round(dt, 1),
            "objective": round(val, 4),
            **{k: round(float(v), 5) for k, v in zip(PARAM_NAMES, x, strict=False)},
        }
        trace.append(row)
        print(f"  [init {i+1}/{n_init}] obj={val:.4f} t={dt:.1f}s")

    X_arr = np.vstack(X_train)
    y_arr = np.asarray(y_train, dtype=float)

    # 3. 高斯过程 + 期望改进迭代采点
    scaler = MinMaxScaler()
    kernel = ConstantKernel(1.0, (1e-3, 1e3)) * RBF(
        length_scale=1.0, length_scale_bounds=(1e-2, 1e2)
    ) + WhiteKernel(noise_level=1e-2, noise_level_bounds=(1e-5, 1e-1))

    for it in range(n_iter):
        X_scaled = scaler.fit_transform(X_arr)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            gpr = GaussianProcessRegressor(
                kernel=kernel,
                alpha=1e-4,
                n_restarts_optimizer=5,
                normalize_y=True,
                random_state=seed + it,
            )
            gpr.fit(X_scaled, y_arr)

        # 候选采点：随机 5000 → 取期望改进最大
        N_CAND = 5000
        cand_raw = rng.uniform(BOUNDS[:, 0], BOUNDS[:, 1], size=(N_CAND, BOUNDS.shape[0]))
        cand_scaled = scaler.transform(cand_raw)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            y_best = float(np.max(y_arr))
            ei = expected_improvement(cand_scaled, gpr, y_best)
        best_idx = int(np.argmax(ei))
        x_next = cand_raw[best_idx]

        t0 = time.time()
        val_next, per_coin = objective(x_next, klines_map)
        dt = time.time() - t0

        if val_next > y_best:
            best_per_coin = per_coin

        X_arr = np.vstack([X_arr, x_next.reshape(1, -1)])
        y_arr = np.append(y_arr, val_next)

        row = {
            "iter": n_init + it,
            "stage": "BO",
            "elapsed_sec": round(dt, 1),
            "objective": round(val_next, 4),
            **{k: round(float(v), 5) for k, v in zip(PARAM_NAMES, x_next, strict=False)},
        }
        trace.append(row)
        best_so_far = float(np.max(y_arr))
        print(
            f"  [BO {it+1}/{n_iter}] obj={val_next:.4f} t={dt:.1f}s | best_so_far={best_so_far:.4f}"
        )

    best_idx = int(np.argmax(y_arr))
    best_x = X_arr[best_idx]
    best_y = float(y_arr[best_idx])
    return best_x, best_y, trace, best_per_coin


def main():
    print("=" * 72)
    print("Phase4 TimingGate 贝叶斯参数优化")
    print(f"  优化币种(仅小币，BTC默认关): {OPT_COINS}")
    print("  目标 = avg(total_return_pct) + 0.5 * avg(sharpe) → 最大")
    print("=" * 72)

    best_x, best_y, trace, best_per_coin = bayesian_optimize(n_iter=25, n_init=5, seed=42)

    # ---- 最优参数 JSON ----
    _fusion_modes = ["daily_only", "or", "and"]
    _best_fusion = _fusion_modes[int(best_x[9])]
    best_dict = {
        "objective": round(best_y, 5),
        "note": "Phase4 TimingGate BO 最优参数 v2（soft_mode仓位落位 + swing双周期融合）",
        "coins": OPT_COINS,
        "per_coin_best": {
            c: {"total_return_pct": round(v[0], 3), "sharpe": round(v[1], 4)}
            for c, v in best_per_coin.items()
        },
        "params": {
            "use_timing_gate": True,
            "timing_gate_apply_to_btc": False,
            "timing_gate_threshold": round(float(best_x[0]), 5),
            "timing_gate_strict": False,
            "timing_gate_swing_window": 2,
            "timing_gate_lenient_unclear": round(float(best_x[1]), 5),
            "timing_gate_unclear_retrace_ext": round(float(best_x[2]), 5),
            "timing_gate_retrace_mu": round(float(best_x[3]), 5),
            "timing_gate_retrace_sigma": round(float(best_x[4]), 5),
            "timing_gate_fib_retrace_lo": round(float(best_x[5]), 5),
            "timing_gate_fib_retrace_hi": round(float(best_x[6]), 5),
            "timing_gate_fib_ext_ratio": round(float(best_x[7]), 5),
            "timing_gate_strict_unclear_score": 0.20,
            # v2 新增
            "timing_gate_soft_mode": True,
            "timing_size_power": round(float(best_x[8]), 5),
            "timing_gate_swing_fusion_mode": _best_fusion,
            "timing_gate_intraday_swing_window": 3,
        },
    }
    BEST_PARAMS_JSON.write_text(
        json.dumps(best_dict, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n[最优参数] 已写入 {BEST_PARAMS_JSON}")
    print(json.dumps(best_dict, indent=2, ensure_ascii=False))

    # ---- trace CSV ----
    fields = ["iter", "stage", "elapsed_sec", "objective"] + PARAM_NAMES
    with open(TRACE_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in trace:
            w.writerow(r)
    print(f"\n[BO trace CSV] 已写入 {TRACE_CSV}")


if __name__ == "__main__":
    main()
