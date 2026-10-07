"""
调研项 2: 3 种断裂类型在真实 BTC 历史数据的命中率实测
调研项 4: 不同周期的自相关衰减长度 τ 估计 (用于推导 persistence_threshold)
"""
import sys, json, os, time
import importlib.util
import numpy as np

# 直接加载模块避免触发 dreambuddy_evolution/__init__.py 完整导入
_spec = importlib.util.spec_from_file_location(
    "structural_break_detector",
    "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/structural_break_detector.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
StructuralBreakDetector = _mod.StructuralBreakDetector

DATA_DIR = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/data"
DATA_1H = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/data/btc_closes_1h.json"

def load(path):
    with open(path) as f:
        return np.array(json.load(f), dtype=float)

def autocorr_decay_tau(returns, max_lag=200):
    """估计自相关衰减长度 τ: 找 |ACF(k)| < 0.05 的最小 k."""
    returns = np.asarray(returns, dtype=float)
    returns = returns[~np.isnan(returns)]
    n = len(returns)
    if n < 50:
        return None
    mean = returns.mean()
    var = returns.var()
    if var < 1e-12:
        return None
    max_lag = min(max_lag, n // 4)
    for k in range(1, max_lag + 1):
        ac = np.mean((returns[k:] - mean) * (returns[:-k] - mean)) / var
        if abs(ac) < 0.05:
            return k
    return max_lag

def run_detector_rolling(price, label, window=120, step=10, min_samples=60):
    """在价格序列上以滚动窗口运行 StructuralBreakDetector.detect_all()"""
    detector = StructuralBreakDetector(min_samples=min_samples)
    n = len(price)
    if n < window + step:
        return None
    counts = {'vol': 0, 'corr': 0, 'hurst': 0, 'any': 0, 'samples': 0}
    method_counts = {'markov_regression': 0, 'simple_threshold': 0,
                     'cusum_ols': 0, 'rolling_zscore': 0,
                     'hurst_exponent': 0, 'fallback': 0}
    total = 0
    t0 = time.time()
    for start in range(0, n - window, step):
        end = start + window
        chunk = price[start:end]
        rets = np.diff(np.log(chunk))
        bench = rets[:len(rets)//2]
        ret_for_corr = rets[len(rets)//2:]
        bench_for_corr = bench[-len(ret_for_corr):]
        try:
            r = detector.detect_all(chunk, returns=rets, benchmark=bench_for_corr)
        except Exception:
            continue
        total += 1
        for key, alias in [('volatility_regime_shift','vol'),
                           ('correlation_break','corr'),
                           ('market_form_shift','hurst')]:
            v = r.get(key)
            if v is not None and v.get('detected'):
                counts[alias] += 1
                m = v.get('method', 'unknown')
                method_counts[m] = method_counts.get(m, 0) + 1
        if r.get('any_structural_break'):
            counts['any'] += 1
    counts['samples'] = total
    counts['elapsed_sec'] = time.time() - t0
    counts['label'] = label
    counts['method_counts'] = method_counts
    return counts

if __name__ == '__main__':
    print("="*80)
    print("调研项 4: 各周期自相关衰减长度 tau 估计")
    print("="*80)

    p_1h_10y = load(os.path.join(DATA_DIR, "btc_close_10y.json"))
    p_30m = load(os.path.join(DATA_DIR, "btc_close_30m.json"))
    p_1h_short = load(DATA_1H)
    p_daily = load(os.path.join(DATA_DIR, "btc_close.json"))

    print(f"\n数据集:")
    print(f"  10y hourly close  : {len(p_1h_10y):>6} 点  ({p_1h_10y[0]:.2f} -> {p_1h_10y[-1]:.2f})")
    print(f"  30min close       : {len(p_30m):>6} 点  ({p_30m[0]:.2f} -> {p_30m[-1]:.2f})")
    print(f"  1h short close    : {len(p_1h_short):>6} 点  ({p_1h_short[0]:.2f} -> {p_1h_short[-1]:.2f})")
    print(f"  daily close       : {len(p_daily):>6} 点  ({p_daily[0]:.2f} -> {p_daily[-1]:.2f})")

    rets_1h_10y = np.diff(np.log(p_1h_10y))
    rets_30m = np.diff(np.log(p_30m))
    rets_1h_short = np.diff(np.log(p_1h_short))
    rets_daily = np.diff(np.log(p_daily))

    tau_30m = autocorr_decay_tau(rets_30m)
    tau_1h = autocorr_decay_tau(rets_1h_10y)
    tau_daily = autocorr_decay_tau(rets_daily)

    print(f"\n  tau(30m)   = {tau_30m}   (5 期 = {5*30} 分钟)")
    print(f"  tau(1h)    = {tau_1h}   (5 期 = {5*60} 分钟)")
    print(f"  tau(daily) = {tau_daily}   (5 期 = 5 天)")

    print()
    print("="*80)
    print("调研项 2: 3 种断裂类型命中率实测 (BTC 历史)")
    print("="*80)

    configs = [
        (p_30m, "30m (60h窗口, step=30)", 120, 30, 60),
        (p_1h_10y, "1h (5天窗口, step=20)", 120, 20, 60),
        (p_daily, "daily (4月窗口, step=10)", 120, 10, 60),
    ]
    results = []
    for price, label, win, step, ms in configs:
        print(f"\n--- {label}: {len(price)} 点 ---")
        if len(price) < win + step:
            print("  数据不足, 跳过")
            continue
        if len(price) > 5000:
            price_used = price[-5000:]
            print(f"  截取最近 5000 点")
        else:
            price_used = price
        r = run_detector_rolling(price_used, label, window=win, step=step, min_samples=ms)
        if r:
            results.append(r)
            n = r['samples']
            if n > 0:
                print(f"  样本数={n}  耗时={r['elapsed_sec']:.1f}s")
                print(f"  vol_regime_shift 命中: {r['vol']:>4d} ({100*r['vol']/n:.2f}%)")
                print(f"  correlation_break 命中: {r['corr']:>4d} ({100*r['corr']/n:.2f}%)")
                print(f"  market_form_shift 命中: {r['hurst']:>4d} ({100*r['hurst']/n:.2f}%)")
                print(f"  any_break 命中       : {r['any']:>4d} ({100*r['any']/n:.2f}%)")
                if r['any'] > 0:
                    print(f"  条件概率:")
                    print(f"    P(vol | any)    = {r['vol']/r['any']:.3f}")
                    print(f"    P(corr | any)   = {r['corr']/r['any']:.3f}")
                    print(f"    P(hurst | any)  = {r['hurst']/r['any']:.3f}")
                print(f"  方法分布:", r['method_counts'])
    print("\n[完成]")
