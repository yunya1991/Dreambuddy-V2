"""
批量滚动回测 - 用于积累 L4 案例库

策略：
1. 滚动窗口：从 OKX 历史 K 线中滑动截取不同时间段
2. 参数扰动：随机调整滑点、仓位、阈值等参数，模拟不同交易者
3. 多周期混合：4H + 1H + 日K 交替训练
"""
import sys
import os
import json
import random
import copy
from pathlib import Path
from typing import List, Dict, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.memory_l4.yijing_trainer import (
    run_backtest, ScenarioResult, default_engine,
    _save_cases_to_l4, LIANGYI_STATE_FILE, _load_kline_from_okx,
    memory_l4_cases_dir,
)


def generate_window_slices(total: int, window: int, step: int = 10) -> List[Tuple[int, int]]:
    """生成滚动窗口切片 (start_idx, end_idx)"""
    slices = []
    for start in range(0, total - window, step):
        end = start + window
        if end <= total:
            slices.append((start, end))
    return slices


def run_batch_backtest(
    num_rounds: int = 50,
    target_case_count: int = 200,
    seed: int = 42,
) -> Dict:
    """
    批量回测入口

    Args:
        num_rounds: 最大回测轮次
        target_case_count: 目标案例数（达到后停止）
        seed: 随机种子

    Returns:
        统计结果
    """
    random.seed(seed)

    print("=" * 70)
    print("  批量滚动回测 - L4 案例库积累")
    print("=" * 70)

    engine = default_engine()

    print("\n正在从 OKX 获取历史 K 线数据...")
    kline_4h = _load_kline_from_okx(bar="4H", limit=300)
    kline_1h = _load_kline_from_okx(bar="1H", limit=500)
    kline_1d = _load_kline_from_okx(bar="1D", limit=100)

    if not kline_4h:
        print("获取 K 线数据失败")
        return {"ok": False, "reason": "no_kline_data"}

    print(f"获取到 {len(kline_4h)} 根 4H, {len(kline_1h)} 根 1H, {len(kline_1d)} 根 日K")

    current_cases = len(list(memory_l4_cases_dir().glob("*.json"))) if memory_l4_cases_dir().exists() else 0
    print(f"\n当前 L4 案例库: {current_cases} 个")
    print(f"目标案例数: {target_case_count}")

    total_rounds_done = 0
    total_cases_added = 0
    total_trades = 0
    total_pnl = 0.0

    configs = []

    windows_4h = generate_window_slices(len(kline_4h), window=80, step=15)
    windows_1h = generate_window_slices(len(kline_1h), window=200, step=30) if kline_1h else []
    windows_1d = generate_window_slices(len(kline_1d), window=50, step=8) if kline_1d else []

    print(f"窗口组合: 4H={len(windows_4h)}个, 1H={len(windows_1h)}个, 1D={len(windows_1d)}个")

    for round_i in range(num_rounds):
        if current_cases + total_cases_added >= target_case_count:
            print(f"\n✅ 已达目标案例数 ({target_case_count})，提前停止")
            break

        bar_choice = random.choice(["4H", "4H", "4H", "1H", "1D"])
        slippage = random.uniform(0.0002, 0.002)
        position_pct = random.uniform(0.05, 0.25)
        initial_capital = random.choice([5000, 8000, 10000, 15000, 20000])

        # 每轮用不同的引擎，参数随机扰动 → 产生参数多样性，支持权重/力学学习
        round_engine = default_engine()
        try:
            ly = round_engine.liangyi_engine
            ly.resonance_bonus *= random.uniform(0.7, 1.3)
            ly.conflict_penalty *= random.uniform(0.7, 1.3)
            se = round_engine.scale_engine
            se.base_market_mass *= random.uniform(0.7, 1.3)
            se.base_velocity_decay *= random.uniform(0.8, 1.1)
            se.base_confidence_threshold *= random.uniform(0.8, 1.2)
            se.base_reversal_threshold *= random.uniform(0.8, 1.2)
            w = [random.uniform(0.1, 0.4), random.uniform(0.05, 0.3),
                 random.uniform(0.2, 0.5), random.uniform(0.2, 0.5)]
            sw = sum(w)
            se.time_weight, se.space_weight, se.surface_weight, se.core_weight = [x / sw for x in w]
        except Exception:
            pass

        if bar_choice == "4H" and windows_4h:
            start_idx, end_idx = random.choice(windows_4h)
            kline = kline_4h
            bar = "4H"
        elif bar_choice == "1H" and windows_1h:
            start_idx, end_idx = random.choice(windows_1h)
            kline = kline_1h
            bar = "1H"
        elif windows_1d:
            start_idx, end_idx = random.choice(windows_1d)
            kline = kline_1d
            bar = "1D"
        else:
            continue

        scenario_name = f"batch_{round_i:03d}_{bar}_w{start_idx}-{end_idx}"

        try:
            result = run_backtest(
                scenario_name, kline, engine=round_engine,
                start_idx=start_idx, end_idx=end_idx,
                initial_capital=initial_capital,
                position_pct=position_pct,
                slippage=slippage,
            )
        except Exception as e:
            print(f"  轮次 {round_i}: 出错 {e}")
            continue

        cases = getattr(result, "learned_cases", []) or []
        case_count = len(cases)

        if cases:
            saved = _save_cases_to_l4(cases, source=f"batch_backtest_round{round_i}")
            total_cases_added += saved
            # 把本轮学到的统计合并到主引擎
            try:
                for k, v in round_engine.liangyi_engine._learned_stats.items():
                    if k not in engine.liangyi_engine._learned_stats:
                        engine.liangyi_engine._learned_stats[k] = dict(v)
                    else:
                        cs = engine.liangyi_engine._learned_stats[k]
                        for f in ["total", "correct", "wrong"]:
                            cs[f] += v[f]
                        for f in ["w_time_sum", "w_space_sum", "w_surface_sum", "w_core_sum",
                                  "mass_sum", "decay_sum",
                                  "w_time_correct_sum", "w_space_correct_sum", "w_surface_correct_sum",
                                  "w_core_correct_sum", "mass_correct_sum", "decay_correct_sum",
                                  "w_time_wrong_sum", "w_space_wrong_sum", "w_surface_wrong_sum",
                                  "w_core_wrong_sum", "mass_wrong_sum", "decay_wrong_sum"]:
                            cs[f] = cs.get(f, 0) + v.get(f, 0)
            except Exception:
                pass
        else:
            saved = 0

        total_rounds_done += 1
        total_trades += result.total_trades
        total_pnl += result.total_pnl

        configs.append({
            "round": round_i,
            "bar": bar,
            "window": f"{start_idx}-{end_idx}",
            "trades": result.total_trades,
            "win_rate": round(result.win_rate, 4),
            "pnl": round(result.total_pnl, 2),
            "cases": case_count,
            "slippage": round(slippage, 5),
            "position_pct": round(position_pct, 3),
        })

        if round_i % 10 == 0 or case_count > 0:
            stats_now = engine.liangyi_engine._learned_stats
            combo_str = ", ".join(
                f"{k[0]}|{k[1]}={v['total']}"
                for k, v in sorted(stats_now.items(), key=lambda x: -x[1]["total"])[:3]
            )
            print(f"  轮次 {round_i:3d}: {bar} {start_idx}-{end_idx} "
                  f"trades={result.total_trades:2d} wr={result.win_rate*100:5.1f}% "
                  f"pnl={result.total_pnl:+8.0f}$ cases={case_count} "
                  f"累计={current_cases + total_cases_added} [{combo_str}]")

    # 从 L4 读取所有真实案例（非 hypothetical）
    try:
        real_cases = []
        cases_dir = memory_l4_cases_dir()
        if cases_dir.exists():
            for fp in cases_dir.glob("*.json"):
                try:
                    with open(fp, encoding="utf-8") as f:
                        c = json.load(f)
                    if c.get("source") != "hypothetical":
                        real_cases.append(c)
                except Exception:
                    pass
        print(f"\n真实案例数: {len(real_cases)}")

        # 场景推演扩展
        if len(real_cases) >= 20:
            from scripts.memory_l4.scenario_extender import run_scenario_extension
            ext_result = run_scenario_extension(real_cases, multiplier=3)
            if ext_result.get("ok"):
                total_cases_added += ext_result.get("hypo_cases", 0)
                print(f"场景推演扩展: +{ext_result['hypo_cases']} 假设案例")
                if ext_result.get("combo_distribution"):
                    print("  组合分布:")
                    for combo, cnt in sorted(ext_result["combo_distribution"].items(), key=lambda x: -x[1])[:5]:
                        print(f"    {combo}: {cnt}")
        else:
            print(f"跳过场景推演: 真实案例不足(需要≥20)")
    except Exception as e:
        print(f"场景推演失败: {e}")

    # 重新从 L4 读取所有案例（真实 + 假设），完整学习一次
    try:
        all_cases_for_learn = []
        cases_dir = memory_l4_cases_dir()
        if cases_dir.exists():
            for fp in cases_dir.glob("*.json"):
                try:
                    with open(fp, encoding="utf-8") as f:
                        c = json.load(f)
                    all_cases_for_learn.append(c)
                except Exception:
                    pass
        if all_cases_for_learn:
            engine.liangyi_engine._learned_stats = {}
            engine.liangyi_engine._learned_season_stats = {}
            engine.liangyi_engine.learn_from_cases(all_cases_for_learn)
            print(f"\n重新从 L4 案例库完整学习: {len(all_cases_for_learn)} 个案例 (真实+假设)")
    except Exception as e:
        print(f"重新学习失败: {e}")

    try:
        ok = engine.liangyi_engine.save_state(str(LIANGYI_STATE_FILE))
        if ok:
            print(f"L4 两仪引擎: 状态已保存到 {LIANGYI_STATE_FILE}")
    except Exception as e:
        print(f"保存 liangyi 状态失败: {e}")

    stats = engine.liangyi_engine.get_learned_stats() if hasattr(engine, "liangyi_engine") else {}
    season_stats = engine.liangyi_engine.get_learned_season_stats() if hasattr(engine, "liangyi_engine") else {}

    print("\n" + "=" * 70)
    print("  批量回测完成")
    print("=" * 70)
    print(f"  回测轮次: {total_rounds_done}")
    print(f"  总交易数: {total_trades}")
    print(f"  总盈亏: ${total_pnl:+,.2f}")
    print(f"  新增案例: {total_cases_added}")
    print(f"  案例库总数: {current_cases + total_cases_added}")
    print(f"\n  LiangyiEngine 学习统计:")
    print(f"    组合数: {len(stats)}")
    print(f"    季节数: {len(season_stats)}")
    for k, v in sorted(stats.items(), key=lambda x: -x[1]["total"]):
        print(f"      {k[0]}|{k[1]}: total={v['total']} win_rate={v['win_rate']:.2%}")

    return {
        "ok": True,
        "rounds_done": total_rounds_done,
        "total_trades": total_trades,
        "total_pnl": total_pnl,
        "cases_added": total_cases_added,
        "total_cases": current_cases + total_cases_added,
        "learned_combos": len(stats),
        "learned_seasons": len(season_stats),
        "combo_details": {f"{k[0]}|{k[1]}": v for k, v in stats.items()},
        "configs": configs,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=100, help="最大回测轮次")
    parser.add_argument("--target", type=int, default=200, help="目标案例数")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    args = parser.parse_args()

    result = run_batch_backtest(
        num_rounds=args.rounds,
        target_case_count=args.target,
        seed=args.seed,
    )
