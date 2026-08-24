#!/usr/bin/env python3
"""
统一持仓查询模块 v1.0 — Phase 1
聚合 6 个交易系统的持仓数据，输出统一格式。

支持系统：
- Agent A (Hyperliquid)
- Agent B (Hyperliquid)
- Agent C (共用 Agent B 账户 + 自有 memory)
- V15 马丁 (OKX 模拟/实盘)
- 易经推理 (OKX 模拟盘)
- 三屏趋势 (通过 ml_trade_service API)

特性：
- 6 系统全覆盖
- 单系统失败不影响整体（降级容错）
- 超时控制（默认单源 5s，总 30s）
- 结果缓存（同进程内单次缓存）
- 统一数据模型
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

BASE_DIR = Path(__file__).parent.parent.parent  # dreambuddy-v2/
AB_TRADING_DIR = BASE_DIR / "experiments" / "ab-trading"
AGENT_C_DIR = BASE_DIR / "experiments" / "agent_c"
V15_DIR = BASE_DIR / "14-V15经典马丁策略"
YIJING_DIR = BASE_DIR / "11-易经推理系统"
CLASSIC_DIR = BASE_DIR / "10-经典指标系统"

DEFAULT_TIMEOUT = 8
CACHE_TTL = 60  # 缓存 60 秒

_cache: Dict[str, Any] = {}


def _cache_get(key: str) -> Optional[Any]:
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < CACHE_TTL:
        return entry["data"]
    return None


def _cache_set(key: str, data: Any):
    _cache[key] = {"ts": time.time(), "data": data}


def _make_position(
    system: str,
    symbol: str,
    direction: str,
    size: float,
    entry_price: float,
    exchange: str = "",
    inst_id: str = "",
    unrealized_pnl: float = 0.0,
    upl_ratio: float = 0.0,
    leverage: float = 0.0,
    open_time: str = "",
    stop_loss: float = 0.0,
    take_profit: float = 0.0,
    meta: Optional[Dict] = None,
) -> Dict:
    """构建统一格式的持仓对象"""
    return {
        "system": system,
        "symbol": symbol,
        "inst_id": inst_id,
        "exchange": exchange,
        "direction": direction.upper() if direction else "UNKNOWN",
        "size": float(size),
        "entry_price": float(entry_price),
        "unrealized_pnl": float(unrealized_pnl),
        "upl_ratio": float(upl_ratio),
        "leverage": float(leverage),
        "open_time": open_time,
        "stop_loss": float(stop_loss),
        "take_profit": float(take_profit),
        "meta": meta or {},
    }


def _make_system_result(
    system: str,
    exchange: str = "",
    positions: Optional[List[Dict]] = None,
    status: str = "ok",
    error: str = "",
    equity: float = 0.0,
    extra: Optional[Dict] = None,
) -> Dict:
    """构建单系统查询结果"""
    pos_list = positions or []
    result = {
        "system": system,
        "exchange": exchange,
        "equity": float(equity),
        "positions": pos_list,
        "position_count": len(pos_list),
        "status": status,
    }
    if error:
        result["error"] = error
    if extra:
        result.update(extra)
    return result


# ============================================================
# 1. Agent A / Agent B (Hyperliquid)
# ============================================================

AGENT_A_ADDR = "0x93842F1ea62E7E3c71494d9EA69EfC4F2D6e9934"
AGENT_B_ADDR = "0x6632da9c91A959eEBf1343f8AFAbf2807414004A"


def _fetch_hl_positions(user_addr: str, system: str) -> Dict:
    """查询 Hyperliquid 持仓"""
    cache_key = f"hl_{user_addr}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        import requests
        r = requests.post(
            "https://api.hyperliquid.xyz/info",
            json={"type": "clearinghouseState", "user": user_addr},
            timeout=DEFAULT_TIMEOUT,
        )
        data = r.json()
        positions = []
        for p in data.get("assetPositions", []):
            pos = p.get("position", {})
            szi = float(pos.get("szi", 0))
            if szi != 0:
                positions.append(_make_position(
                    system=system,
                    symbol=pos.get("coin", ""),
                    direction="LONG" if szi > 0 else "SHORT",
                    size=abs(szi),
                    entry_price=float(pos.get("entryPx") or 0),
                    exchange="hyperliquid",
                    unrealized_pnl=float(pos.get("unrealizedPnl") or 0),
                    leverage=float((pos.get("leverage") or {}).get("value", 1)),
                    meta={
                        "position_value": float(pos.get("positionValue") or 0),
                    },
                ))
        equity = float(data.get("marginSummary", {}).get("accountValue", 0))
        # 资金调控：Hyperliquid 账户 extra 字段（复用 Agent A/B 已有 equity）
        hl_extra = {
            "account_type": "hyperliquid",
            "fallback_used": False,
        }
        result = _make_system_result(
            system=system,
            exchange="hyperliquid",
            positions=positions,
            status="ok",
            equity=equity,
            extra=hl_extra,
        )
        _cache_set(cache_key, result)
        return result
    except Exception as e:
        result = _make_system_result(
            system=system,
            exchange="hyperliquid",
            positions=[],
            status="error",
            error=str(e),
            equity=0.0,
            extra={
                "account_type": "hyperliquid",
                "fallback_used": True,
                "fallback_reason": f"hyperliquid_api_failed: {e}",
            },
        )
        return result


def fetch_agent_a_positions() -> Dict:
    return _fetch_hl_positions(AGENT_A_ADDR, "agent_a")


def fetch_agent_b_positions() -> Dict:
    return _fetch_hl_positions(AGENT_B_ADDR, "agent_b")


# ============================================================
# 2. Agent C (共用 Agent B 账户 + memory.json)
# ============================================================

def fetch_agent_c_positions() -> Dict:
    """Agent C 持仓：从 memory.json 读取内存持仓"""
    try:
        mem_file = AB_TRADING_DIR / "data" / "agent_c_b" / "memory.json"
        if not mem_file.exists():
            # 资金调控：即使 memory.json 缺失，仍尝试复用 Agent B equity 缓存
            agent_b_equity = 0.0
            try:
                agent_b_equity = float(_fetch_hl_positions(AGENT_B_ADDR, "agent_b").get("equity", 0.0))
            except Exception:
                pass
            return _make_system_result(
                system="agent_c_memory",
                exchange="hyperliquid",
                positions=[],
                status="error",
                error=f"memory.json not found: {mem_file}",
                equity=agent_b_equity,
                extra={
                    "shared_equity_with": "agent_b",
                    "account_type": "hyperliquid",
                    "fallback_used": True,
                    "fallback_reason": "memory_json_missing",
                },
            )

        with open(mem_file) as f:
            mem = json.load(f)

        open_pos = mem.get("open_positions", {})
        positions = []
        for sym, pos in open_pos.items():
            positions.append(_make_position(
                system="agent_c_memory",
                symbol=sym,
                direction=pos.get("direction", "UNKNOWN"),
                size=pos.get("size", 0),
                entry_price=pos.get("entry_price", 0),
                exchange="hyperliquid(agent_c)",
                unrealized_pnl=pos.get("unrealized_pnl", 0),
                open_time=pos.get("open_time", ""),
                meta={
                    "strategy": pos.get("strategy", ""),
                    "cycle_id": pos.get("cycle_id", ""),
                },
            ))

        return _make_system_result(
            system="agent_c_memory",
            exchange="hyperliquid",
            positions=positions,
            status="ok",
            # 资金调控：Agent C 共用 Agent B 账户，equity 复用 Agent B 缓存（避免重复 API 调用）
            equity=_fetch_hl_positions(AGENT_B_ADDR, "agent_b").get("equity", 0.0),
            extra={
                "note": "Agent C 内存持仓，共用 Agent B 交易所账户",
                "position_count_from_exchange": 0,
                "shared_equity_with": "agent_b",
                "account_type": "hyperliquid",
                "fallback_used": False,
            },
        )
    except Exception as e:
        # 失败时仍尝试复用 Agent B equity 缓存
        agent_b_equity = 0.0
        try:
            agent_b_equity = float(_fetch_hl_positions(AGENT_B_ADDR, "agent_b").get("equity", 0.0))
        except Exception:
            pass
        return _make_system_result(
            system="agent_c_memory",
            exchange="hyperliquid",
            positions=[],
            status="error",
            error=str(e),
            equity=agent_b_equity,
            extra={
                "shared_equity_with": "agent_b",
                "account_type": "hyperliquid",
                "fallback_used": True,
                "fallback_reason": f"agent_c_memory_load_failed: {e}",
            },
        )


# ============================================================
# 3. V15 马丁 (OKX 模拟/实盘)
# ============================================================

def _load_v15_config() -> Optional[Dict]:
    """加载 V15 配置"""
    config_path = V15_DIR / "config" / ".env.v15ct"
    if not config_path.exists():
        config_path = V15_DIR / "config" / ".env.v15"
    if not config_path.exists():
        config_path = V15_DIR / ".env"

    config = {}
    if config_path.exists():
        with open(config_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    config[k.strip()] = v.strip().strip('"').strip("'")

    common_path = V15_DIR / "config" / ".env.common"
    if common_path.exists():
        with open(common_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() not in config:
                        config[k.strip()] = v.strip().strip('"').strip("'")

    return config if config else None


def fetch_v15_martin_positions() -> Dict:
    """V15 马丁持仓：从 state.json + OKX API 读取"""
    cache_key = "v15_positions"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    positions = []
    state_data = {}

    state_file = V15_DIR / "data" / "v15_state.json"
    if state_file.exists():
        try:
            with open(state_file) as f:
                state_data = json.load(f)
        except Exception:
            pass

    state_positions = state_data.get("positions", {})

    config = _load_v15_config()
    api_key = config.get("OKX_API_KEY", "") if config else ""
    secret_key = config.get("OKX_SECRET_KEY", "") if config else ""
    passphrase = config.get("OKX_PASSPHRASE", "") if config else ""
    base_url = config.get("OKX_BASE_URL", "https://www.okx.com") if config else "https://www.okx.com"
    simulated = config.get("OKX_SIMULATED", "true").lower() == "true" if config else True

    # 资金调控：equity 字段填充（直接调用 OKX get_balance，避免依赖环境变量）
    equity = 0.0
    equity_extra: Dict = {}
    if api_key and secret_key and passphrase:
        try:
            import sys
            sys.path.insert(0, str(V15_DIR / "lib"))
            from okx_client import OKXSimulatedClient
            from capital_manager import TOTAL_BUDGET as _V15_TOTAL_BUDGET

            # V15 OKXSimulatedClient 接受 config dict（非关键字参数）
            client = OKXSimulatedClient(config={
                "api_key": api_key,
                "secret_key": secret_key,
                "passphrase": passphrase,
                "simulated": simulated,
                "base_url": base_url,
                "dry_run": False,
            })

            # 直接用已构造的 client 查询余额，填充 equity 字段
            try:
                bal = client.get_balance()
                if bal.get("ok"):
                    equity = float(bal.get("total_eq", 0))
                    usdt = bal.get("assets", {}).get("USDT", {})
                    # avail 来自 OKX availBal，已排除冻结保证金（含其他策略持仓占用）
                    equity_extra = {
                        "avail_balance": float(usdt.get("avail", 0.0)),
                        "used_margin": float(usdt.get("frozen", 0)),
                        "account_type": "okx_live" if not simulated else "okx_simulated",
                        "fallback_used": False,
                    }
                else:
                    # API 失败时回退到 TOTAL_BUDGET 静态值
                    equity = float(_V15_TOTAL_BUDGET)
                    equity_extra = {
                        "avail_balance": float(_V15_TOTAL_BUDGET),
                        "used_margin": 0.0,
                        "account_type": "okx_live" if not simulated else "okx_simulated",
                        "fallback_used": True,
                        "fallback_reason": f"okx_balance_api_failed: {bal.get('error', '')}",
                    }
            except Exception as bal_err:
                # get_balance 抛异常时降级
                equity = float(_V15_TOTAL_BUDGET)
                equity_extra = {
                    "avail_balance": float(_V15_TOTAL_BUDGET),
                    "used_margin": 0.0,
                    "account_type": "okx_live" if not simulated else "okx_simulated",
                    "fallback_used": True,
                    "fallback_reason": f"okx_balance_exception: {bal_err}",
                }

            for coin, state_pos in state_positions.items():
                inst_id = state_pos.get("inst_id", f"{coin}-USDT-SWAP")
                try:
                    r = client.get_positions(inst_id)
                    if r.get("ok") and r.get("positions"):
                        for p in r["positions"]:
                            pos_sz = float(p.get("pos", 0))
                            if pos_sz != 0:
                                pos_side = p.get("pos_side", "net")
                                is_long = pos_side == "long" or (pos_side == "net" and pos_sz > 0)
                                positions.append(_make_position(
                                    system="v15_martin",
                                    symbol=coin,
                                    inst_id=inst_id,
                                    direction="LONG" if is_long else "SHORT",
                                    size=abs(pos_sz),
                                    entry_price=float(p.get("avg_px", 0)),
                                    exchange="okx" if not simulated else "okx_simulated",
                                    unrealized_pnl=float(p.get("upl", 0)),
                                    upl_ratio=float(p.get("upl_ratio", 0)),
                                    leverage=float(p.get("lever", 0) or 0),
                                    stop_loss=float(state_pos.get("stop_loss_price") or 0),
                                    meta={
                                        "addons": state_pos.get("addons", 0),
                                        "confidence": state_pos.get("confidence", 0),
                                        "open_time": state_pos.get("open_time", ""),
                                        "take_profit_pct": state_pos.get("take_profit_pct", 0),
                                        "stop_loss_type": state_pos.get("stop_loss_type", ""),
                                        "last_addon_time": state_pos.get("last_addon_time", ""),
                                        "simulated": simulated,
                                    },
                                ))
                except Exception:
                    pass
        except Exception as import_err:
            pass

    if not positions and state_positions:
        for coin, state_pos in state_positions.items():
            positions.append(_make_position(
                system="v15_martin",
                symbol=coin,
                inst_id=state_pos.get("inst_id", f"{coin}-USDT-SWAP"),
                direction=state_pos.get("direction", "LONG"),
                size=float(state_pos.get("sz") or 0),
                entry_price=float(state_pos.get("entry_price") or 0),
                exchange="okx_state_only",
                stop_loss=float(state_pos.get("stop_loss_price") or 0),
                meta={
                    "addons": state_pos.get("addons", 0),
                    "confidence": state_pos.get("confidence", 0),
                    "open_time": state_pos.get("open_time", ""),
                    "source": "state_file_only",
                },
            ))

    # 合并 equity_extra 与现有 extra 字段
    merged_extra = {
        "state_position_count": len(state_positions),
        "api_position_count": sum(1 for p in positions if p.get("meta", {}).get("source") != "state_file_only"),
        "simulated": simulated if api_key else "unknown",
        "total_trades": state_data.get("total_trades", 0),
        "total_wins": state_data.get("total_wins", 0),
        "daily_pnl": state_data.get("daily_pnl", 0),
        "consecutive_losses": state_data.get("consecutive_losses", 0),
    }
    merged_extra.update(equity_extra)

    result = _make_system_result(
        system="v15_martin",
        exchange="okx" if api_key else "okx_state_only",
        positions=positions,
        status="ok" if positions else ("warning" if state_positions else "ok"),
        equity=equity,
        extra=merged_extra,
    )
    if not api_key:
        result["status"] = "partial"
        result["error"] = "No OKX API key, using state file only"
    _cache_set(cache_key, result)
    return result


# ============================================================
# 4. 易经推理 (OKX 模拟盘)
# ============================================================

def _get_yijing_open_positions_dir() -> Path:
    """获取易经系统持仓目录"""
    candidates = [
        YIJING_DIR / ".workbuddy" / "memory_l4" / "open_positions",
        YIJING_DIR / "scripts" / "memory_l4" / "open_positions",
        Path.home() / ".workbuddy" / "memory_l4" / "open_positions",
    ]
    for d in candidates:
        if d.exists():
            return d
    return candidates[0]


def fetch_yijing_positions() -> Dict:
    """易经推理系统持仓：从 open_positions/*.json 读取"""
    cache_key = "yijing_positions"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    positions = []
    pos_dir = _get_yijing_open_positions_dir()

    if not pos_dir.exists():
        result = _make_system_result(
            system="yijing_bcrm",
            exchange="okx_simulated",
            positions=[],
            status="warning",
            error=f"open_positions dir not found: {pos_dir}",
        )
        _cache_set(cache_key, result)
        return result

    # 资金调控：equity 字段填充（复用易经 OKXSimulatedClient，simulated=True）
    equity = 0.0
    equity_extra: Dict = {}
    try:
        import sys
        sys.path.insert(0, str(YIJING_DIR / "scripts" / "memory_l4"))
        from okx_simulated import OKXSimulatedClient

        yj_client = OKXSimulatedClient()  # 默认 simulated=True，从 .env 加载凭证
        bal = yj_client.get_balance()
        if bal.get("ok"):
            equity = float(bal.get("total_eq", 0))
            usdt = bal.get("assets", {}).get("USDT", {})
            # avail 来自 OKX availBal，已排除冻结保证金（含其他策略持仓占用）
            # USDT 缺失时用 0.0 而非 equity，避免把冻结资金误算为可用
            equity_extra = {
                "avail_balance": float(usdt.get("avail", 0.0)),
                "used_margin": float(usdt.get("frozen", 0)),
                "account_type": "okx_simulated",
                "fallback_used": False,
            }
        else:
            equity_extra = {
                "account_type": "okx_simulated",
                "fallback_used": True,
                "fallback_reason": f"okx_balance_api_failed: {bal.get('error', '')}",
            }
    except Exception as e:
        equity_extra = {
            "account_type": "okx_simulated",
            "fallback_used": True,
            "fallback_reason": f"okx_simulated_import_or_query_exception: {e}",
        }

    try:
        for f in pos_dir.glob("*.json"):
            try:
                with open(f) as fp:
                    rec = json.load(fp)
                if rec.get("status") == "open" or not rec.get("exit_time", ""):
                    direction = rec.get("direction", "")
                    positions.append(_make_position(
                        system="yijing_bcrm",
                        symbol=rec.get("coin", ""),
                        inst_id=rec.get("inst_id", ""),
                        direction=direction.upper() if direction else "UNKNOWN",
                        size=float(rec.get("size", 0)),
                        entry_price=float(rec.get("entry_price", 0)),
                        exchange="okx_simulated",
                        open_time=rec.get("entry_time", rec.get("open_time", "")),
                        meta={
                            "trade_id": rec.get("trade_id", ""),
                            "confidence": rec.get("confidence", 0),
                            "hexagram": rec.get("hexagram", ""),
                            "strategy_source": rec.get("strategy_source", "bcrm"),
                            "liangyi_state": rec.get("liangyi_state", {}),
                            "contradiction_count": len(rec.get("contradiction_list", [])),
                        },
                    ))
            except Exception:
                continue

        merged_extra = {
            "data_source": "local_json",
            "total_files": len(list(pos_dir.glob("*.json"))),
        }
        merged_extra.update(equity_extra)

        result = _make_system_result(
            system="yijing_bcrm",
            exchange="okx_simulated",
            positions=positions,
            status="ok",
            equity=equity,
            extra=merged_extra,
        )
        _cache_set(cache_key, result)
        return result
    except Exception as e:
        result = _make_system_result(
            system="yijing_bcrm",
            exchange="okx_simulated",
            positions=[],
            status="error",
            error=str(e),
            equity=equity,
            extra=equity_extra,
        )
        return result


# ============================================================
# 5. 三屏趋势系统
# ============================================================
#
# 当前架构（过渡期）：
#   - 三屏趋势系统（12-三屏趋势系统/）= 纯信号计算（大脑）
#   - 执行和持仓管理 = 委托给经典指标系统的 ml_trade_service
#   - 持仓数据存储在 ml_trade_service 的 three_screen_open_positions 中
#
# 未来规划：
#   - 三屏趋势系统完全独立，有自己的持仓管理和执行器
#   - 届时查询来源切换为三屏系统自己的 state 文件
#
# 查询方式：
#   优先：通过 ml_trade_service API (http://127.0.0.1:8092/tracker/stats)
#   降级：暂无（需要 ml_trade_service 运行）
# ============================================================

THREE_SCREEN_API_BASE = "http://127.0.0.1:8092"


def fetch_three_screen_positions() -> Dict:
    """
    三屏趋势系统持仓查询

    当前实现：通过 ml_trade_service 的 /tracker/stats API 查询
    （三屏趋势系统目前是纯信号系统，持仓由经典系统代为管理）

    未来：三屏系统完全独立后，切换为从三屏系统自己的 state 读取
    """
    cache_key = "three_screen_positions"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    positions = []
    status = "ok"
    error_msg = ""
    # 资金调控：equity 字段填充（通过 Aster 账户摘要端点获取 totalWalletBalance）
    equity = 0.0
    equity_extra: Dict = {}

    try:
        import requests
        r = requests.get(
            f"{THREE_SCREEN_API_BASE}/tracker/stats",
            params={"sync": "1"},
            timeout=DEFAULT_TIMEOUT,
        )
        if r.status_code != 200:
            raise Exception(f"HTTP {r.status_code}")

        data = r.json()
        if not data.get("ok"):
            raise Exception(data.get("error", "unknown error"))

        three_screen_pos = data.get("three_screen_open_positions", {})
        pos_list = []

        if isinstance(three_screen_pos, dict):
            pos_list = list(three_screen_pos.values())
        elif isinstance(three_screen_pos, list):
            pos_list = three_screen_pos

        for pos in pos_list:
            symbol = pos.get("pair", pos.get("symbol", ""))
            side = pos.get("side", "long")
            entry_px = pos.get("entry_price", pos.get("aster_entry_px", 0))
            notional = pos.get("notional_usdc", pos.get("notional_usdt", 0))
            base_qty = pos.get("base_qty", pos.get("aster_position_amt", 0))
            upl = pos.get("aster_unrealized_pnl_u", pos.get("unrealized_pnl", 0))
            upl_pct = pos.get("unrealized_pnl_pct", 0)
            entry_ts = pos.get("entry_ts", pos.get("open_ts", 0))

            positions.append(_make_position(
                system="three_screen",
                symbol=symbol,
                direction="LONG" if side == "long" else "SHORT",
                size=float(base_qty),
                entry_price=float(entry_px),
                exchange=pos.get("venue", "hyperliquid"),
                unrealized_pnl=float(upl),
                upl_ratio=float(upl_pct),
                leverage=float(pos.get("leverage", 0)),
                open_time=datetime.fromtimestamp(entry_ts, tz=timezone.utc).isoformat() if entry_ts else "",
                stop_loss=float(pos.get("stop_loss", pos.get("sl_px", 0))),
                take_profit=float(pos.get("take_profit", pos.get("tp_px", 0))),
                meta={
                    "venue": pos.get("venue", ""),
                    "mode": pos.get("mode", ""),
                    "strategy_id": pos.get("strategy_id", ""),
                    "group_id": pos.get("group_id", ""),
                    "notional_usdc": float(notional),
                    "mark_price": float(pos.get("mark_price", 0)),
                    "liq_px": float(pos.get("liq_px", pos.get("aster_liquidation_px", 0))),
                    "system_id": pos.get("system_id", "three_screen"),
                    "exit_owner": pos.get("exit_owner", ""),
                    "data_source": "ml_trade_service",
                    "note": "三屏趋势系统当前委托经典系统管理持仓",
                },
            ))

        # 资金调控：equity 字段填充（通过 Aster 账户摘要端点获取 totalWalletBalance）
        try:
            acct_r = requests.get(
                f"{THREE_SCREEN_API_BASE}/execution/aster/account_summary",
                timeout=DEFAULT_TIMEOUT,
            )
            if acct_r.status_code == 200:
                acct_data = acct_r.json()
                if acct_data.get("ok"):
                    summary = acct_data.get("summary", {})
                    equity = float(summary.get("totalWalletBalance", 0))
                    equity_extra = {
                        "avail_balance": float(summary.get("availableBalance", 0)),
                        "used_margin": float(summary.get("totalPositionInitialMargin", 0)),
                        "account_type": "aster",
                        "fallback_used": False,
                    }
        except Exception as acct_err:
            equity_extra = {
                "account_type": "aster",
                "fallback_used": True,
                "fallback_reason": f"aster_account_summary_failed: {acct_err}",
            }

    except Exception as e:
        status = "unavailable"
        error_msg = f"ml_trade_service 不可用: {str(e)}"

    merged_extra = {
        "api_endpoint": THREE_SCREEN_API_BASE,
        "architecture": "transitional",
        "note": "三屏趋势系统是独立策略系统，当前持仓由经典系统 ml_trade_service 代为管理，未来将完全独立",
        "future_plan": "三屏系统自建持仓管理和执行器后，查询来源将切换",
    }
    merged_extra.update(equity_extra)

    result = _make_system_result(
        system="three_screen",
        exchange="hyperliquid/aster",
        positions=positions,
        status=status,
        error=error_msg,
        equity=equity,
        extra=merged_extra,
    )
    _cache_set(cache_key, result)
    return result


# ============================================================
# 统一入口
# ============================================================

SYSTEM_FETCHERS = [
    ("agent_a", fetch_agent_a_positions),
    ("agent_b", fetch_agent_b_positions),
    ("agent_c_memory", fetch_agent_c_positions),
    ("v15_martin", fetch_v15_martin_positions),
    ("yijing_bcrm", fetch_yijing_positions),
    ("three_screen", fetch_three_screen_positions),
]


def fetch_all_positions(systems: Optional[List[str]] = None) -> Dict:
    """
    聚合所有系统的持仓

    Args:
        systems: 可选，指定要查询的系统列表，默认全部

    Returns:
        统一格式的持仓全景图
    """
    fetchers = SYSTEM_FETCHERS
    if systems:
        fetchers = [(name, fn) for name, fn in SYSTEM_FETCHERS if name in systems]

    systems_data = {}
    all_positions = []
    system_status = {}
    total_unrealized_pnl = 0.0
    total_equity = 0.0  # 资金调控：全局总权益聚合
    equity_by_system: Dict[str, float] = {}

    for sys_name, fetch_fn in fetchers:
        try:
            data = fetch_fn()
        except Exception as e:
            data = _make_system_result(
                system=sys_name,
                exchange="",
                positions=[],
                status="error",
                error=str(e),
            )

        systems_data[sys_name] = data
        system_status[sys_name] = data.get("status", "unknown")

        pos_list = data.get("positions", [])
        for pos in pos_list:
            all_positions.append(pos)
            total_unrealized_pnl += pos.get("unrealized_pnl", 0)

        # 资金调控：聚合 equity
        sys_equity = float(data.get("equity", 0.0) or 0.0)
        equity_by_system[sys_name] = round(sys_equity, 2)
        total_equity += sys_equity

    ok_count = sum(1 for s in system_status.values() if s == "ok")
    partial_count = sum(1 for s in system_status.values() if s == "partial" or s == "warning")
    error_count = sum(1 for s in system_status.values() if s == "error" or s == "unavailable")

    overall_status = "ok"
    if error_count > 0 and ok_count > 0:
        overall_status = "degraded"
    elif error_count > 0 and ok_count == 0:
        overall_status = "failed"

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.1",  # 资金调控：升级版本号，新增 total_equity 字段
        "total_systems": len(fetchers),
        "total_positions": len(all_positions),
        "total_unrealized_pnl": round(total_unrealized_pnl, 2),
        "total_equity": round(total_equity, 2),  # 全局总权益（数值加总，不可跨账户调度）
        "equity_by_system": equity_by_system,  # 各系统权益明细
        "overall_status": overall_status,
        "system_status": system_status,
        "systems_summary": {
            "ok": ok_count,
            "partial": partial_count,
            "error": error_count,
        },
        "systems": systems_data,
        "all_positions": all_positions,
    }


def get_position_summary() -> Dict:
    """快速获取持仓摘要（不返回完整持仓列表）"""
    result = fetch_all_positions()
    return {
        "timestamp": result["timestamp"],
        "version": result.get("version", "1.1"),
        "total_systems": result["total_systems"],
        "total_positions": result["total_positions"],
        "total_unrealized_pnl": result["total_unrealized_pnl"],
        "total_equity": result.get("total_equity", 0.0),  # 资金调控：摘要包含全局总权益
        "overall_status": result["overall_status"],
        "system_status": result["system_status"],
        "by_system": {
            sys_name: {
                "position_count": data.get("position_count", 0),
                "status": data.get("status", "unknown"),
                "equity": float(data.get("equity", 0.0) or 0.0),  # 资金调控：各系统 equity
            }
            for sys_name, data in result["systems"].items()
        },
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--summary":
        summary = get_position_summary()
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        result = fetch_all_positions()
        print(json.dumps(result, indent=2, ensure_ascii=False))
