"""
生成模拟交易Episode数据，用于测试L4 Pipeline

生成多种市场场景的交易记录，包括：
- 上升趋势
- 下降趋势  
- 横盘震荡
- 高波动
- 突破行情

输出格式：符合L4 Pipeline episode格式要求的JSON文件
"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np

rng = np.random.default_rng(42)

def generate_simulated_trades(n_trades=20):
    """生成模拟交易数据"""
    trades = []
    now = datetime.now(timezone.utc)
    
    scenarios = [
        {"name": "uptrend", "direction_bias": 0.6, "volatility": 0.02, "win_rate": 0.55},
        {"name": "downtrend", "direction_bias": 0.4, "volatility": 0.025, "win_rate": 0.5},
        {"name": "ranging", "direction_bias": 0.5, "volatility": 0.01, "win_rate": 0.45},
        {"name": "high_vol", "direction_bias": 0.5, "volatility": 0.04, "win_rate": 0.48},
        {"name": "breakout", "direction_bias": 0.65, "volatility": 0.03, "win_rate": 0.58},
    ]
    
    base_price = 60000.0
    current_price = base_price
    
    for i in range(n_trades):
        scenario = scenarios[i % len(scenarios)]
        
        entry_time = now - timedelta(hours=i * 4)
        exit_time = entry_time + timedelta(hours=int(rng.integers(4, 24)))
        
        move = rng.normal(0, scenario["volatility"])
        entry_price = current_price
        exit_price = entry_price * (1 + move)
        
        direction = "LONG" if rng.random() < scenario["direction_bias"] else "SHORT"
        
        if direction == "LONG":
            pnl_pct = (exit_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - exit_price) / entry_price
        
        pnl = pnl_pct * 100
        confidence = rng.uniform(0.4, 0.85)
        
        trade = {
            "trade_id": str(uuid.uuid4()),
            "symbol": "BTC-USDT",
            "inst_id": "BTC-USDT",
            "direction": direction,
            "entry_price": round(entry_price, 2),
            "exit_price": round(exit_price, 2),
            "position_size": 0.01,
            "leverage": 10,
            "margin_usdt": 100,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct * 100, 4),
            "exit_reason": "take_profit" if pnl > 0 else "stop_loss",
            "ts_entry": entry_time.isoformat(),
            "ts_exit": exit_time.isoformat(),
            "system_source": "yijing_inference",
            "decision_context": {
                "confidence": round(confidence, 2),
                "hexagram": f"卦_{scenario['name']}_{i}",
                "signal_strength": round(rng.uniform(0.3, 0.9), 2),
                "market_regime": scenario["name"],
            },
            "market_snapshot": {
                "regime": scenario["name"],
                "volatility": round(scenario["volatility"], 4),
                "trend_strength": round(rng.uniform(0.2, 0.8), 2),
                "price_position": round(rng.uniform(0.1, 0.9), 2),
                "is_ranging": scenario["name"] == "ranging",
            },
            "risk_events": [],
        }
        
        trades.append(trade)
        current_price = exit_price
    
    return trades

def generate_episode(trades):
    """生成Episode数据结构（兼容L4 Pipeline格式）"""
    episode_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    total_pnl = sum(t["pnl"] for t in trades)
    total_pnl_pct = sum(t["pnl_pct"] for t in trades) / len(trades) if trades else 0
    
    return {
        "episode_id": episode_id,
        "trace_id": trace_id,
        "version": "v1.0",
        "system": "yijing_inference",
        "ts": trades[0]["ts_entry"],
        "ts_start": trades[-1]["ts_entry"],
        "ts_end": trades[0]["ts_exit"],
        "inst_id": "BTC-USDT",
        "symbol": "BTC-USDT",
        "regime": trades[0]["market_snapshot"]["regime"],
        "status": "completed",
        "decision": "simulated_trading",
        "pnl_pct": round(total_pnl_pct, 4),
        "pnl_usdt": round(total_pnl, 2),
        "drawdown": round(abs(total_pnl) * 0.3, 2),
        "trades": trades,
        "summary": {
            "total_trades": len(trades),
            "wins": sum(1 for t in trades if t["pnl"] > 0),
            "losses": sum(1 for t in trades if t["pnl"] <= 0),
            "total_pnl": total_pnl,
            "avg_confidence": sum(t["decision_context"]["confidence"] for t in trades) / len(trades),
        },
        "metadata": {
            "source": "simulation",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }

def generate_single_scenario_episode(scenario_name: str, n_trades: int = 10, base_price: float = 60000.0) -> dict:
    """生成单个场景的episode"""
    scenarios_map = {
        "uptrend": {"direction_bias": 0.65, "volatility": 0.018, "win_rate": 0.6},
        "downtrend": {"direction_bias": 0.35, "volatility": 0.022, "win_rate": 0.55},
        "ranging": {"direction_bias": 0.5, "volatility": 0.01, "win_rate": 0.45},
        "high_vol": {"direction_bias": 0.5, "volatility": 0.04, "win_rate": 0.48},
        "breakout_up": {"direction_bias": 0.7, "volatility": 0.025, "win_rate": 0.65},
        "breakout_down": {"direction_bias": 0.3, "volatility": 0.028, "win_rate": 0.6},
        "low_vol": {"direction_bias": 0.5, "volatility": 0.006, "win_rate": 0.4},
        "recovery": {"direction_bias": 0.6, "volatility": 0.02, "win_rate": 0.58},
    }
    
    scenario = scenarios_map.get(scenario_name, scenarios_map["ranging"])
    now = datetime.now(timezone.utc)
    trades = []
    current_price = base_price
    
    for i in range(n_trades):
        entry_time = now - timedelta(hours=i * 4 + n_trades * 4)
        exit_time = entry_time + timedelta(hours=int(rng.integers(4, 24)))
        
        move = rng.normal(0, scenario["volatility"])
        entry_price = current_price
        exit_price = entry_price * (1 + move)
        
        direction = "LONG" if rng.random() < scenario["direction_bias"] else "SHORT"
        
        if direction == "LONG":
            pnl_pct = (exit_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - exit_price) / entry_price
        
        pnl = pnl_pct * 100
        confidence = rng.uniform(0.4, 0.85)
        
        trade = {
            "trade_id": str(uuid.uuid4()),
            "symbol": "BTC-USDT",
            "inst_id": "BTC-USDT",
            "direction": direction,
            "entry_price": round(entry_price, 2),
            "exit_price": round(exit_price, 2),
            "position_size": 0.01,
            "leverage": 10,
            "margin_usdt": 100,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct * 100, 4),
            "exit_reason": "take_profit" if pnl > 0 else "stop_loss",
            "ts_entry": entry_time.isoformat(),
            "ts_exit": exit_time.isoformat(),
            "system_source": "yijing_inference",
            "decision_context": {
                "confidence": round(confidence, 2),
                "hexagram": f"卦_{scenario_name}_{i}",
                "signal_strength": round(rng.uniform(0.3, 0.9), 2),
                "market_regime": scenario_name,
            },
            "market_snapshot": {
                "regime": scenario_name,
                "volatility": round(scenario["volatility"], 4),
                "trend_strength": round(rng.uniform(0.2, 0.8), 2),
                "price_position": round(rng.uniform(0.1, 0.9), 2),
                "is_ranging": scenario_name in ["ranging", "low_vol"],
            },
            "risk_events": [],
        }
        
        trades.append(trade)
        current_price = exit_price
    
    return generate_episode(trades)

def generate_batch_episodes(n_episodes: int = 10, trades_per_episode: int = 10) -> list:
    """批量生成多场景episodes"""
    scenarios = [
        "uptrend", "downtrend", "ranging", "high_vol",
        "breakout_up", "breakout_down", "low_vol", "recovery"
    ]
    
    episodes = []
    base_price = 60000.0
    
    for i in range(n_episodes):
        scenario = scenarios[i % len(scenarios)]
        base_price_variation = base_price * (1 + rng.normal(0, 0.05))
        episode = generate_single_scenario_episode(
            scenario_name=scenario,
            n_trades=trades_per_episode,
            base_price=base_price_variation
        )
        episodes.append(episode)
    
    return episodes

def save_episodes(episodes: list) -> list:
    """保存episodes到文件"""
    episodes_dir = Path(__file__).resolve().parents[3] / "data" / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    
    paths = []
    for ep in episodes:
        filename = f"sim_{ep['regime']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        output_path = episodes_dir / filename
        with open(output_path, 'w') as f:
            json.dump(ep, f, indent=2, ensure_ascii=False)
        paths.append(str(output_path))
    
    return paths

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate simulated trading episodes")
    parser.add_argument("--count", type=int, default=10, help="Number of episodes to generate")
    parser.add_argument("--trades", type=int, default=10, help="Trades per episode")
    parser.add_argument("--scenario", type=str, default=None, help="Single scenario name")
    args = parser.parse_args()
    
    print(f"Generating {args.count} simulated episodes ({args.trades} trades each)...")
    
    if args.scenario:
        episodes = [generate_single_scenario_episode(args.scenario, args.trades)]
    else:
        episodes = generate_batch_episodes(args.count, args.trades)
    
    paths = save_episodes(episodes)
    
    total_trades = sum(len(ep["trades"]) for ep in episodes)
    total_wins = sum(ep["summary"]["wins"] for ep in episodes)
    total_losses = sum(ep["summary"]["losses"] for ep in episodes)
    total_pnl = sum(ep["summary"]["total_pnl"] for ep in episodes)
    
    print(f"\nGenerated {len(episodes)} episodes:")
    for i, (ep, path) in enumerate(zip(episodes, paths)):
        print(f"  [{i+1}] {Path(path).name}: {ep['regime']} "
              f"({len(ep['trades'])} trades, PnL={ep['summary']['total_pnl']:.2f})")
    
    print(f"\nTotal: {total_trades} trades, {total_wins} wins, {total_losses} losses")
    print(f"Total PnL: {total_pnl:.2f} USDT")
    print(f"Win rate: {total_wins/total_trades*100:.1f}%" if total_trades > 0 else "")
    
    return paths

if __name__ == "__main__":
    main()