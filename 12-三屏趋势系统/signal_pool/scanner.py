"""信号池扫描器 — 定时为全币种生成 Freqtrade 策略信号

工作流程：
1. 从 config.CANDIDATE_COINS 加载全币种池
2. import ml_trade_service（模块级调用，不启动 Flask）
3. 对每个币种运行多策略投票（1h + 4h）
4. 写入 pool.json 供 engine.py 读取

用法：
  # 单次扫描
  python3 signal_pool/scanner.py --once

  # 守护模式（每5分钟扫描一次）
  python3 signal_pool/scanner.py --daemon

  # 自定义间隔（秒）
  python3 signal_pool/scanner.py --daemon --interval 300
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime, timezone
from typing import Dict, List

# 路径设置
TREND_SYSTEM_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLASSIC_SYSTEM_PATH = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/10-经典指标系统"

if TREND_SYSTEM_PATH not in sys.path:
    sys.path.insert(0, TREND_SYSTEM_PATH)
if CLASSIC_SYSTEM_PATH not in sys.path:
    sys.path.insert(0, CLASSIC_SYSTEM_PATH)

# 信号池文件路径
POOL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pool.json")

# 策略配置（与 screen_engine.py 保持一致）
STRATEGIES_4H = [
    ("user_data.strategies.MultiGroupStrategy", "MultiGroupStrategy", 0.55),
    ("user_data.strategies.TrendConfirmationStrategy", "TrendConfirmationStrategy", 0.45),
]
STRATEGIES_1H = [
    ("user_data.strategies.RegimeHybridStrategy", "RegimeHybridStrategy", 0.6),
    ("user_data.strategies.Bot2StrategyTrend", "Bot2StrategyTrend", 0.4),
]


def _get_candidate_coins() -> List[Dict]:
    """获取候选币种列表"""
    try:
        from core.config import CANDIDATE_COINS
        return CANDIDATE_COINS
    except ImportError:
        from config import CANDIDATE_COINS
        return CANDIDATE_COINS


def _import_ml_trade_service():
    """import ml_trade_service 模块（不启动 Flask）"""
    import ml_trade_service
    return ml_trade_service


def _run_strategy_vote(ml_svc, coin: str, strategies: list) -> Dict:
    """
    多策略加权投票

    参数:
        ml_svc: ml_trade_service 模块
        coin: 币种符号，如 "BTC"
        strategies: [(module_path, class_name, weight), ...]

    返回:
        {"signal": "BUY"/"SELL"/"HOLD", "confidence": 0-100, "strategy": "xxx", "details": [...]}
    """
    votes = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
    details = []

    for mod, cls, weight in strategies:
        try:
            res = ml_svc._run_freqtrade_strategy_signal_hyperliquid(mod, cls, coin)
            if res.get("ok") and res.get("side"):
                side = res["side"]
                sig = "BUY" if side == "long" else ("SELL" if side == "short" else "HOLD")
                votes[sig] += weight
                details.append({"strategy": cls, "signal": sig, "weight": weight})
            else:
                details.append({"strategy": cls, "signal": "HOLD", "weight": weight, "error": res.get("error", "no_signal")})
        except Exception as e:
            details.append({"strategy": cls, "signal": "HOLD", "weight": weight, "error": str(e)[:100]})

    # 投票结果
    if votes["BUY"] > votes["SELL"] and votes["BUY"] > votes["HOLD"]:
        return {"signal": "BUY", "confidence": int(votes["BUY"] * 100), "strategy": "Freqtrade_Vote", "details": details}
    elif votes["SELL"] > votes["BUY"] and votes["SELL"] > votes["HOLD"]:
        return {"signal": "SELL", "confidence": int(votes["SELL"] * 100), "strategy": "Freqtrade_Vote", "details": details}
    else:
        return {"signal": "HOLD", "confidence": 0, "strategy": "Freqtrade_Vote", "details": details}


def scan_single_coin(ml_svc, coin: Dict) -> Dict:
    """
    扫描单个币种，生成 1h + 4h 信号

    参数:
        ml_svc: ml_trade_service 模块
        coin: {"symbol": "BTC", "spot": "BTC-USDT", ...}

    返回:
        {"1h": {...}, "4h": {...}}
    """
    symbol = coin["symbol"]
    return {
        "1h": _run_strategy_vote(ml_svc, symbol, STRATEGIES_1H),
        "4h": _run_strategy_vote(ml_svc, symbol, STRATEGIES_4H),
    }


def scan_all_coins() -> Dict:
    """
    扫描全币种池，生成信号池

    返回:
        {
            "updated_at": "2026-07-10T12:00:00Z",
            "scanner_version": "1.0",
            "signals": {
                "BTC": {"1h": {...}, "4h": {...}},
                "ETH": {"1h": {...}, "4h": {...}},
                ...
            }
        }
    """
    coins = _get_candidate_coins()
    print(f"[Scanner] 开始扫描 {len(coins)} 个币种...")

    try:
        ml_svc = _import_ml_trade_service()
    except Exception as e:
        print(f"[Scanner] ml_trade_service import 失败: {e}")
        return {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "scanner_version": "1.0",
            "error": f"import_failed: {str(e)[:200]}",
            "signals": {},
        }

    signals = {}
    success_count = 0
    fail_count = 0

    for i, coin in enumerate(coins):
        symbol = coin["symbol"]
        try:
            sig = scan_single_coin(ml_svc, coin)
            signals[symbol] = sig
            success_count += 1
            s1 = sig["1h"]["signal"]
            s4 = sig["4h"]["signal"]
            print(f"  [{i+1}/{len(coins)}] {symbol:6s} 1h={s1:4s} 4h={s4:4s}")
        except Exception as e:
            fail_count += 1
            signals[symbol] = {
                "1h": {"signal": "HOLD", "confidence": 0, "strategy": "error", "error": str(e)[:100]},
                "4h": {"signal": "HOLD", "confidence": 0, "strategy": "error", "error": str(e)[:100]},
            }
            print(f"  [{i+1}/{len(coins)}] {symbol:6s} ERROR: {str(e)[:80]}")

    pool = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "scanner_version": "1.0",
        "total_coins": len(coins),
        "success_count": success_count,
        "fail_count": fail_count,
        "signals": signals,
    }

    # 原子写入 pool.json
    tmp_file = POOL_FILE + ".tmp"
    with open(tmp_file, "w") as f:
        json.dump(pool, f, indent=2, ensure_ascii=False)
    os.rename(tmp_file, POOL_FILE)

    print(f"[Scanner] 扫描完成: 成功{success_count} 失败{fail_count} → {POOL_FILE}")
    return pool


def run_daemon(interval: int = 300):
    """
    守护模式：定时扫描

    参数:
        interval: 扫描间隔（秒），默认 300（5分钟）
    """
    print(f"[Scanner] 守护模式启动，间隔 {interval}秒")
    while True:
        try:
            scan_all_coins()
        except Exception as e:
            print(f"[Scanner] 扫描异常: {e}")
        print(f"[Scanner] 下次扫描: {interval}秒后")
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="Freqtrade 信号池扫描器")
    parser.add_argument("--once", action="store_true", help="单次扫描后退出")
    parser.add_argument("--daemon", action="store_true", help="守护模式（定时扫描）")
    parser.add_argument("--interval", type=int, default=300, help="扫描间隔（秒），默认300")
    args = parser.parse_args()

    if args.once:
        scan_all_coins()
    elif args.daemon:
        run_daemon(args.interval)
    else:
        # 默认单次扫描
        scan_all_coins()


if __name__ == "__main__":
    main()
