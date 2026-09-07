#!/usr/bin/env python3
"""
统一监控调度器
定时执行所有系统的监控检查，并发送飞书告警

双层调度架构：
- 5分钟轻量轮询：持仓同步（对比交易所真实持仓+更新盈亏）
- 60分钟完整监控：健康检查+性能统计+风险评估+告警发送
"""
import json
import os
import sys
import time
import schedule
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent
REPO_ROOT = BASE_DIR.parent

# dreambuddy-v2 MVP alert_bridge（Lark 可选依赖）
try:
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "23-四层闭环自进化交易架构"))
    from dreambuddy_evolution.alert_bridge import send_alert as _mvp_send_alert
except Exception:  # pragma: no cover
    def _mvp_send_alert(level: str, msg: str, **_kw) -> None:
        print(f"[MVP-SHADOW:{level}] {msg}")


# ============================================================
# dreambuddy-v2 MVP L1 × L2 Shadow Scheduler（Phase 3 Step 12）
# ============================================================
_MVP_SHADOW_STATS = {
    "mvp_fo7": 0,              # FO-7 熔断总次数
    "DISABLED": False,         # FO-7 熔断标志（真=永久停止调度本轮重启前）
    "fail_streak": 0,          # 连续失败计数
    "last_run_at": None,       # 上次 UTC 时间戳
    "last_ok_count": 0,        # 上次成功处理 symbol 数（调试用）
    "pipeline_actions": {},    # 四层闭环管 pipeline 输出 action
    "pipeline_l3_count": 0,    # L3 ShadowRL 样本累计
    "pipeline_l4_v": {},       # L4 Bellman V(s) 值
}
_MVP_FO7_FAIL_THRESHOLD = 5  # FO-7：连续 ≥5 次失败 → DISABLED


def _generate_mvp_mock_symbols(n: int = 3):
    """生成 n 个 mock symbol raw data（复用 resistance_features 的 mock generator）。
    纯本地 numpy，无 OKX API。返回 dict[symbol]->raw_data_dict。"""
    import numpy as np
    import random as _r
    rng = np.random.default_rng(42)
    rnd = _r.Random(1337)
    out = {}
    for i in range(1, n + 1):
        base = float(rnd.choice([25000.0, 30000.0, 38000.0, 55000.0, 1800.0, 160.0, 1.2]))
        N = 200
        t = np.arange(N)
        close = base + 0.7 * t + rng.normal(0, base * 0.002, N)  # 线性微噪声
        L = rnd.uniform(0.40, 0.60); S = 1.0 - L
        out[f"MVPSYM-{i:02d}"] = {
            "close": close,
            "volume": np.full(N, float(rnd.randint(500, 5000))),
            "okx_positions": {"long": L, "short": S},
            "liquidation_buy": np.full(N, 0.0),
            "liquidation_sell": np.full(N, 0.0),
            "ma_200": float(np.mean(close)),
            "fib_retrace_0786": base * 1.05,
            "fib_retrace_0618": base * 1.03,
            "fib_retrace_0500": base * 1.02,
            "bid_ask_spread_bps": float(rnd.choice([1.5, 2.0, 3.0, 5.0])),
            "news_sentiment_score": float(rnd.uniform(0.35, 0.70)),
        }
    return out


def shadow_resistance_gene_mvp() -> None:
    """
    dreambuddy-v2 L1 × L2 MVP 影子调度（UTC 00:05 每日）：
      - 不产生真实交易/信号 → 纯计算 pipeline 健康 & 覆盖率
      - FO-7 熔断：连续 ≥5 次失败 → 标记 DISABLED 并发送 Lark ERROR
    """
    stats = _MVP_SHADOW_STATS
    stats["last_run_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if stats["DISABLED"]:
        # 熔断中：静默跳过（不持续告警）
        print(f"[{stats['last_run_at']}] MVP-SHADOW SKIP (FO-7 DISABLED since streak ≥5)")
        return

    try:
        # ---- 路径注入 ----
        for p in [
            str(REPO_ROOT),
            str(REPO_ROOT / "23-四层闭环自进化交易架构"),
        ]:
            if p not in sys.path:
                sys.path.insert(0, p)

        # ---- A. L1 ResistanceVector（3 symbol mock） ----
        from dreambuddy_evolution.core.resistance_vector import ResistanceVector as _RV  # noqa: E402
        import dreambuddy_evolution.core.resistance_vector as rf_mod  # noqa: E402
        rv = rf_mod.ResistanceVector()
        sym_to_data = _generate_mvp_mock_symbols(3)
        out_ok = 0
        for sym, d in sym_to_data.items():
            o = rv.calculate(sym, d)
            if (isinstance(o, dict) and "R_up" in o and "quality_score" in o
                    and isinstance(o.get("timestamp_ms"), int)
                    and 0.0 <= float(o["R_up"]) <= 1.0):
                out_ok += 1
        stats["last_ok_count"] = out_ok

        # ---- B. L2 Strategy Gene schema load + search（冒烟） ----
        from dreambuddy_evolution.core import strategy_gene as sgs_mod  # noqa: E402
        gene_root = REPO_ROOT / "23-四层闭环自进化交易架构" / "dreambuddy_evolution" / "gene_data"
        lib = sgs_mod.load_gene_library(gene_root)
        n_cond = len(lib.get("conditions") or [])
        n_act  = len(lib.get("actions") or [])
        n_comb = len(sgs_mod.top_combinations_by_ess(lib, min_sample=0))
        trend_ids = sgs_mod.search_genes_by_category(gene_root, "trend")
        if (n_cond + n_act) < 40 or n_comb < 12 or not trend_ids:
            raise RuntimeError(
                f"L2 基因库冒烟失败：cond+act={n_cond+n_act}<40 or comb={n_comb}<12 or trend_ids=empty"
            )

        # ---- C. 通过 ----
        stats["fail_streak"] = 0

        # ---- D. 四层闭环 EvolutionPipeline (L1→Level0→L2→L3→L4) ----
        try:
            for p in [str(REPO_ROOT / "23-四层闭环自进化交易架构")]:
                if p not in sys.path:
                    sys.path.insert(0, p)
            from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline  # noqa: E402
            pipe = EvolutionPipeline(gene_root=gene_root)
            results = pipe.run_batch(sym_to_data, rv=rv)
            actions = {s: r["action"] for s, r in results.items()}
            fb = pipe.get_feedback()
            stats["pipeline_actions"] = actions
            stats["pipeline_l3_count"] = fb["l3_stats"]["sample_count"]
            stats["pipeline_l4_v"] = fb["l4_v_all"]
            pipe_line = (f"Pipeline(actions={actions}, "
                         f"L3_samples={fb['l3_stats']['sample_count']}, "
                         f"L4_V={fb['l4_v_all']})")
        except Exception as pe:  # noqa: BLE001 — pipeline crash 不影响主冒烟通过
            pipe_line = f"Pipeline(skip: {type(pe).__name__}: {pe!s:.120s})"

        print(
            f"[{stats['last_run_at']}] MVP-SHADOW OK: "
            f"RV({out_ok}/{len(sym_to_data)}), "
            f"Lib(cond={n_cond},act={n_act},comb={n_comb}), "
            f"FO7_fail_streak={stats['fail_streak']}, "
            f"{pipe_line}"
        )
    except Exception as exc:  # noqa: BLE001 — 影子跑：任何异常计失败，FO-7 计数
        stats["fail_streak"] += 1
        stats["mvp_fo7"] += 1
        msg = (f"MVP-SHADOW FAIL streak={stats['fail_streak']} "
               f"(total_fo7={stats['mvp_fo7']}) — {type(exc).__name__}: {exc!s:.200s}")
        print(f"[{stats['last_run_at']}] {msg}")
        if stats["fail_streak"] >= _MVP_FO7_FAIL_THRESHOLD and not stats["DISABLED"]:
            stats["DISABLED"] = True
            try:
                _mvp_send_alert(
                    "error",
                    f"[dreambuddy-v2 MVP FO-7 DISABLED] shadow_resistance_gene_mvp "
                    f"连续失败{stats['fail_streak']}次≥{_MVP_FO7_FAIL_THRESHOLD}阈值，"
                    f"本轮调度器重启前自动熔断（避免每天异常刷屏）。最后一次={msg}",
                )
            except Exception as alert_err:  # pragma: no cover
                print(f"[MVP-SHADOW] FO-7 Lark ERROR send fail: {alert_err}")


def run_monitor():
    """执行完整监控任务（60分钟）"""
    from monitor_core import UnifiedMonitor

    try:
        monitor = UnifiedMonitor()
        results = monitor.monitor_all()
        monitor.send_alerts(results)

        healthy_count = sum(1 for r in results.values() if r.is_healthy())
        print(f"\n[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] "
              f"完整监控完成: {healthy_count}/{len(results)} 系统正常")

    except Exception as e:
        print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] "
              f"完整监控执行异常: {e}")


def run_position_sync():
    """执行持仓同步任务（5分钟轻量轮询）"""
    from position_sync import run_position_sync as sync_func

    try:
        sync_func()
        print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] "
              f"持仓同步完成")

    except Exception as e:
        print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] "
              f"持仓同步异常: {e}")


def main():
    print("=" * 60)
    print("统一监控调度器启动")
    print("=" * 60)

    config_path = BASE_DIR / "config" / "monitor_config.json"
    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)
        monitor_interval = config.get("scheduler", {}).get("interval_minutes", 60)
        sync_interval = config.get("scheduler", {}).get("sync_interval_minutes", 5)
    else:
        monitor_interval = 60
        sync_interval = 5

    print(f"完整监控间隔: {monitor_interval} 分钟")
    print(f"持仓同步间隔: {sync_interval} 分钟")
    print(f"启动时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")

    run_position_sync()
    run_monitor()

    # dreambuddy-v2 MVP L1+L2 影子冷启动冒烟（启动时立即跑 1 次验证 pipeline 健康；之后 UTC 00:05 每日）
    try:
        shadow_resistance_gene_mvp()
    except Exception as e:  # pragma: no cover — 启动冒烟 fail 不让调度器崩（FO-7 会记录）
        print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] "
              f"[WARN] MVP-SHADOW cold-start smoke failed (scheduler continues): {e}")

    schedule.every(sync_interval).minutes.do(run_position_sync)
    schedule.every(monitor_interval).minutes.do(run_monitor)
    # dreambuddy-v2 MVP：UTC 00:05 每日 L1×L2 影子
    schedule.every().day.at("00:05", "UTC").do(shadow_resistance_gene_mvp)

    print(f"MVP shadow cron: every day @ 00:05 UTC registered (FO-7 streak fail≥5 → auto DISABLED)")

    while True:
        try:
            schedule.run_pending()
            time.sleep(60)
        except KeyboardInterrupt:
            print("\n调度器已停止")
            break
        except Exception as e:
            print(f"调度器异常: {e}")
            time.sleep(60)


if __name__ == "__main__":
    main()
