"""
screen_engine 兼容层
桥接 data_server_fixed.py 期望的旧接口到 12-三屏趋势系统/engine.py

data_server_fixed.py 需要:
  - get_all()                      -> /api/state 端点
  - compute_full_trading_signal()  -> /api/trend-screen 端点
  - CANDIDATE_COINS                -> 币种列表
"""
import sys
from pathlib import Path

# 把 12-三屏趋势系统 加入 sys.path
_THREE_SCREEN_DIR = str(Path(__file__).resolve().parent.parent.parent.parent / "12-三屏趋势系统")
if _THREE_SCREEN_DIR not in sys.path:
    sys.path.insert(0, _THREE_SCREEN_DIR)

try:
    from engine import compute_full_trading_signal
    _ENGINE_AVAILABLE = True
except ImportError:
    _ENGINE_AVAILABLE = False
    compute_full_trading_signal = None

# 候选币种列表（与 12-三屏趋势系统/core/config.py 保持一致）
CANDIDATE_COINS = [
    {"symbol": "BTC", "inst": "BTC-USDT"},
    {"symbol": "ETH", "inst": "ETH-USDT"},
    {"symbol": "SOL", "inst": "SOL-USDT"},
    {"symbol": "BNB", "inst": "BNB-USDT"},
    {"symbol": "XRP", "inst": "XRP-USDT"},
]


def get_all() -> dict:
    """返回三屏系统全局状态（/api/state 用）。

    旧版 screen_engine.get_all() 返回完整多币种三屏扫描结果。
    此处返回轻量结构，前端 /api/state 仅用于监控页状态展示。
    """
    return {
        "status": "ok",
        "engine_available": _ENGINE_AVAILABLE,
        "candidates": CANDIDATE_COINS,
        "message": "screen_engine compat layer (12-三屏趋势系统)",
    }
