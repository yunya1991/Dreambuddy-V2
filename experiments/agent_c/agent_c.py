"""
Agent C — 基于 Dream OS 内核的交易应用

设计目标:
    1. 使用 Dream OS 内核的 S-A-C-G 架构
    2. 通过注册表动态发现节点
    3. 实现完整的交易分析链路
    4. 与 Agent B 做对比测试
    5. 共用 Agent B 的 Hyperliquid API 和配置

架构:
    ┌─────────────────────────────────────┐
    │           Agent C App               │
    │  ┌───────────┐  ┌───────────────┐  │
    │  │ 单币种分析 │  │ 多币种扫描     │  │
    │  └─────┬─────┘  └───────┬───────┘  │
    └────────┼────────────────┼──────────┘
             ↓                ↓
    ┌─────────────────────────────────────┐
    │        Dream OS 内核                 │
    │  S层→A层→C层→G层                    │
    │  + 注册表 + 适配器                   │
    └─────────────────────────────────────┘
             ↓                ↓
    ┌─────────────────────────────────────┐
    │      共用 Agent B 执行层             │
    │  HyperliquidClient + 链上TP/SL      │
    └─────────────────────────────────────┘
"""

from __future__ import annotations

import json
import os
import sys
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

AB_TRADING_PATH = Path(__file__).parent.parent / "ab-trading"
sys.path.insert(0, str(AB_TRADING_PATH))
from execution.aster_spot import HyperliquidClient, scan_opportunities, get_candles, get_funding_rate

load_dotenv(str(AB_TRADING_PATH / "config" / ".env"))

from dreamos.shared.state import State, new_state
from dreamos.core.sense.intent_engine import IntentEngine
from dreamos.core.arrange.graph_planner import GraphPlanner
from dreamos.core.compute.graph_executor import GraphExecutor
from dreamos.registry import get_default_registry
from dreamos.nodes import register_all


class AgentC:
    """Agent C — 基于 Dream OS 的交易分析应用"""

    def __init__(self, agent_id: str = "b", data_dir: str = None):
        self._registry = get_default_registry()
        self._intent_engine = IntentEngine()
        self._planner = GraphPlanner(self._registry)
        self._executor = GraphExecutor()

        self._agent_id = agent_id
        self._client = HyperliquidClient(agent_id)

        if data_dir is None:
            data_dir = str(AB_TRADING_PATH / "data" / f"agent_c_{agent_id}")
        self._data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

        self._memory = self._load_memory()
        self._register_nodes()

    def _register_nodes(self) -> None:
        count = register_all(self._registry)
        print(f"✅ 已注册 {count} 个节点到注册表")

    def _load_memory(self) -> Dict[str, Any]:
        memory_file = os.path.join(self._data_dir, "memory.json")
        if os.path.exists(memory_file):
            try:
                with open(memory_file, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return self._default_memory()

    def _default_memory(self) -> Dict[str, Any]:
        return {
            "recent_decisions": [],
            "regime_history": [],
            "lessons": [],
            "active_positions": {},
            "win_streaks": 0,
            "loss_streaks": 0,
            "total_cycles": 0,
        }

    def _save_memory(self) -> None:
        memory_file = os.path.join(self._data_dir, "memory.json")
        with open(memory_file, 'w') as f:
            json.dump(self._memory, f, indent=2, default=str)

    def fetch_market_data(self, symbol: str) -> Dict[str, Any]:
        """从 Hyperliquid 获取真实市场数据"""
        try:
            mids = self._client.get_all_mids()
            price = mids.get(symbol, 0)
            if price <= 0:
                return {}

            candles_1h = get_candles(symbol, "1h", 48, self._client.proxies)
            candles_4h = get_candles(symbol, "4h", 14, self._client.proxies)

            closes_1h = [float(c["c"]) for c in candles_1h if "c" in c]
            closes_4h = [float(c["c"]) for c in candles_4h if "c" in c]
            vols_1h = [float(c["v"]) for c in candles_1h if "v" in c]

            if len(closes_1h) < 24:
                return {}

            def ema(prices, n):
                if len(prices) < n:
                    return prices[-1] if prices else 0
                k = 2 / (n + 1)
                e = prices[-n]
                for p in prices[-n + 1:]:
                    e = p * k + e * (1 - k)
                return e

            def rsi(prices, n=14):
                if len(prices) < n + 1:
                    return 50.0
                deltas = [prices[i] - prices[i - 1] for i in range(1, min(n + 1, len(prices)))]
                gains = [max(d, 0) for d in deltas]
                losses = [max(-d, 0) for d in deltas]
                avg_g = sum(gains) / n
                avg_l = sum(losses) / n
                if avg_l == 0:
                    return 100.0
                rs = avg_g / avg_l
                return 100 - 100 / (1 + rs)

            def atr(raw_candles, n=14):
                if len(raw_candles) < 2:
                    return 0
                trs = []
                for i in range(1, min(n + 1, len(raw_candles))):
                    h = float(raw_candles[i].get("h", 0))
                    l = float(raw_candles[i].get("l", 0))
                    c_prev = float(raw_candles[i - 1].get("c", 0))
                    trs.append(max(h - l, abs(h - c_prev), abs(l - c_prev)))
                return sum(trs) / len(trs) if trs else 0

            closes_rev = closes_1h[::-1]
            ema20 = ema(closes_rev, 20)
            ema50 = ema(closes_rev, min(50, len(closes_rev)))
            ema200 = ema(closes_4h[::-1], min(20, len(closes_4h)))
            rsi14 = rsi(closes_rev)
            atr14 = atr(candles_1h)

            change_1h = ((closes_1h[0] - closes_1h[1]) / closes_1h[1] * 100) if len(closes_1h) > 1 else 0
            change_24h = ((closes_1h[0] - closes_1h[23]) / closes_1h[23] * 100) if len(closes_1h) > 23 else 0
            change_4h = ((closes_4h[0] - closes_4h[3]) / closes_4h[3] * 100) if len(closes_4h) > 3 else 0

            avg_vol = sum(vols_1h) / len(vols_1h) if vols_1h else 0
            cur_vol = vols_1h[0] if vols_1h else 0
            vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 1.0

            funding_rate = get_funding_rate(symbol, self._client.proxies)

            return {
                "symbol": symbol,
                "price": price,
                "change_24h": round(change_24h, 3) / 100,
                "change_4h": round(change_4h, 3) / 100,
                "change_1h": round(change_1h, 3) / 100,
                "high_24h": price * (1 + abs(change_24h / 100) * 0.5),
                "low_24h": price * (1 - abs(change_24h / 100) * 0.5),
                "ema20": round(ema20, 2),
                "ema50": round(ema50, 2),
                "ema200": round(ema200, 2),
                "rsi14": round(rsi14, 1),
                "atr_pct": round(atr14 / price, 4),
                "vol_ratio": round(vol_ratio, 2),
                "funding_rate": funding_rate,
                "fgi": 50,
                "long_short_ratio": 1.0,
                "social_sentiment": 0,
                "exchange_netflow": 0,
                "whale_transfers": 0,
                "etf_flow": 0,
                "kdj_k": round(rsi14, 1),
                "kdj_d": round((rsi14 + 50) / 2, 1),
                "bb_width": round(atr14 / price * 2, 4),
                "iv_rank": 0.5,
                "vol_20d_avg": 0.02,
                "active_addresses": 0,
                "active_addresses_trend": 0,
                "chain_activity": 0.5,
                "dollar_index": 100,
                "spx_correlation": 0,
                "rate_env": "neutral",
                "risk_appetite": 0.5,
            }
        except Exception as e:
            print(f"⚠️ 获取 {symbol} 市场数据失败: {e}")
            return {}

    def analyze(self, symbol: str, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """单币种分析"""
        cycle_id = f"{symbol}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        state = new_state(cycle_id=cycle_id)
        state.market = market_data
        state.market["coin"] = symbol
        state.memory = self._memory
        state.config = {
            "risk_per_trade": 0.05,
            "max_leverage": 5,
            "confidence_gate": 0.65,
        }

        intent_result = self._intent_engine.recognize(state)
        state.intent = intent_result.to_dict() if hasattr(intent_result, 'to_dict') else {}

        plan = self._planner.plan(state)
        graph = self._planner.build_graph(plan)

        report = self._executor.execute(graph, state)

        decision = self._build_decision(symbol, state, report)

        self._update_memory(decision)

        if decision.get("action") != "HOLD":
            trade_result = self.execute_trade(decision, auto_execute=True)
            decision["trade_result"] = trade_result

        return decision

    def scan_universe(self, universe: List[str],
                      use_real_data: bool = False,
                      top_n: int = 3) -> List[Dict[str, Any]]:
        """多币种扫描"""
        if use_real_data:
            print(f"\n[Agent C/Scan] 从 Hyperliquid 获取真实市场数据...")
            market_data_map = {}
            for symbol in universe:
                mkt_data = self.fetch_market_data(symbol)
                if mkt_data and mkt_data.get("price", 0) > 0:
                    market_data_map[symbol] = mkt_data
                    print(f"  {symbol}: ${mkt_data['price']:.2f}")
        else:
            market_data_map = {symbol: generate_sample_market_data(symbol) for symbol in universe}

        results = []
        for symbol in universe:
            try:
                mkt_data = market_data_map.get(symbol, {})
                if not mkt_data or mkt_data.get("price", 0) == 0:
                    continue

                decision = self.analyze(symbol, mkt_data)
                if decision["action"] != "HOLD":
                    results.append(decision)
            except Exception as e:
                print(f"⚠️ 扫描 {symbol} 失败: {e}")
                continue

        results.sort(key=lambda x: x["confidence"], reverse=True)

        return results[:top_n]

    def execute_trade(self, decision: Dict[str, Any], auto_execute: bool = False) -> Dict[str, Any]:
        """执行交易"""
        trade_order = decision.get("trade_order", {})
        action = trade_order.get("action", "HOLD")
        coin = trade_order.get("coin", decision.get("symbol", ""))
        size_usdt = trade_order.get("position_size", 10.0)
        leverage = trade_order.get("leverage", 3)

        if action == "HOLD":
            return {"ok": False, "error": "HOLD signal, no trade"}

        if not auto_execute:
            return {
                "ok": True,
                "action": "simulated",
                "action_type": action,
                "coin": coin,
                "size_usdt": size_usdt,
                "leverage": leverage,
                "entry_price": trade_order.get("entry_price", 0),
                "stop_loss": trade_order.get("stop_loss", 0),
                "take_profit": trade_order.get("take_profit", 0),
            }

        try:
            current_price = self._client.get_mid_price(coin)
            print(f"  [实盘交易] {action} {coin} | 当前价格: ${current_price:.2f} | 仓位: {size_usdt} USDT | 杠杆: {leverage}x")

            if action == "LONG":
                result = self._client.open_long(coin, size_usdt, leverage, tag="c")
            else:
                result = self._client.open_short(coin, size_usdt, leverage, tag="c")

            print(f"  [交易结果] ok={result.get('ok')} | filled={result.get('filled', {})}")

            if result.get("ok"):
                self._memory["active_positions"][coin] = {
                    "action": action,
                    "entry_price": trade_order.get("entry_price", 0),
                    "stop_loss_price": trade_order.get("stop_loss", 0),
                    "take_profit_price": trade_order.get("take_profit", 0),
                    "position_size_usdt": size_usdt,
                    "leverage": leverage,
                    "cycle_id": decision.get("cycle_id", ""),
                }
                self._save_memory()

                from execution.onchain_tpsl import ensure_tpsl
                sl = trade_order.get("stop_loss")
                tp = trade_order.get("take_profit")
                if sl or tp:
                    tpsl_result = ensure_tpsl(self._client, coin, sl, tp)
                    print(f"  [TPSL] {tpsl_result.get('action')} — SL: ${sl} TP: ${tp}")

            return {
                "ok": result.get("ok", False),
                "action": "executed",
                "action_type": action,
                "coin": coin,
                "result": result,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _build_decision(self, symbol: str, state: State,
                        report: Any) -> Dict[str, Any]:
        """构建最终决策"""
        final_action = getattr(report, 'final_action', None)
        final_confidence = getattr(report, 'final_confidence', 0.0)

        if final_action is None or final_action == "HOLD":
            a5_result = state.get_result("A5")
            if a5_result and a5_result.outputs.get("trade_order"):
                order = a5_result.outputs["trade_order"]
                final_action = order.get("action", "HOLD")
                final_confidence = a5_result.confidence
            else:
                final_action = "HOLD"
                final_confidence = 0.5

        rationale = []
        for node_id, result in state.results.items():
            if hasattr(result, 'outputs') and result.outputs:
                r = result.outputs.get('rationale', [])
                if isinstance(r, list):
                    rationale.extend(r)

        trade_order = {}
        a5_result = state.get_result("A5")
        if a5_result and a5_result.outputs.get("trade_order"):
            trade_order = a5_result.outputs["trade_order"]

        a9_result = state.get_result("A9")
        exit_plan = {}
        if a9_result:
            exit_plan = {
                "exit_decision": a9_result.outputs.get("exit_decision", "HOLD"),
                "exit_reason": a9_result.outputs.get("exit_reason", ""),
            }

        return {
            "symbol": symbol,
            "action": final_action,
            "confidence": round(final_confidence, 3),
            "trade_order": trade_order,
            "exit_plan": exit_plan,
            "rationale": rationale,
            "state_trace": [t for t in state.trace],
            "cycle_id": state.cycle_id,
            "timestamp": datetime.now().isoformat(),
        }

    def _update_memory(self, decision: Dict[str, Any]) -> None:
        """更新记忆"""
        self._memory["total_cycles"] = self._memory.get("total_cycles", 0) + 1

        self._memory["recent_decisions"].append({
            "symbol": decision["symbol"],
            "action": decision["action"],
            "confidence": decision["confidence"],
            "timestamp": decision["timestamp"],
        })

        if len(self._memory["recent_decisions"]) > 50:
            self._memory["recent_decisions"] = self._memory["recent_decisions"][-50:]

        self._sync_real_positions()

        self._save_memory()

    def _sync_real_positions(self) -> None:
        """从 Hyperliquid 同步真实持仓，覆盖内存中的虚拟持仓"""
        try:
            acct = self._client.get_account()
            real_positions = acct.get("positions", {})
            self._memory["active_positions"] = {}
            for coin, pos in real_positions.items():
                self._memory["active_positions"][coin] = {
                    "action": "LONG" if pos.get("size", 0) > 0 else "SHORT",
                    "entry_price": pos.get("entry_px", 0),
                    "stop_loss_price": 0,
                    "take_profit_price": 0,
                    "position_size_usdt": 0,
                    "leverage": pos.get("leverage", 3),
                    "cycle_id": "",
                }
        except Exception as e:
            print(f"⚠️ 同步真实持仓失败: {e}")

    def get_memory(self) -> Dict[str, Any]:
        """获取记忆"""
        return self._memory

    def get_registered_nodes(self) -> List[Dict[str, Any]]:
        """获取已注册节点"""
        nodes = self._registry.list_nodes()
        return [{
            "node_id": n.node_id,
            "name": getattr(n, "name", ""),
            "chain": getattr(n, "chain", ""),
            "description": getattr(n, "description", ""),
        } for n in nodes]

    def get_account_info(self) -> Dict[str, Any]:
        """获取账户信息"""
        return self._client.get_account()


def generate_sample_market_data(symbol: str = "BTC") -> Dict[str, Any]:
    """生成示例市场数据（用于测试）"""
    price = {
        "BTC": 67500.0,
        "ETH": 3500.0,
        "SOL": 145.0,
        "AVAX": 42.0,
        "LINK": 15.5,
        "DOT": 6.8,
        "MATIC": 0.85,
        "BNB": 620.0,
    }.get(symbol, 67500.0)

    change_24h = (hash(symbol) % 200 - 100) / 1000
    change_4h = (hash(symbol + "4h") % 100 - 50) / 1000
    change_1h = (hash(symbol + "1h") % 60 - 30) / 1000

    rsi = 30 + (hash(symbol) % 40)
    macd = (hash(symbol) % 20 - 10) / 100
    macd_signal = (hash(symbol + "sig") % 20 - 10) / 100

    return {
        "symbol": symbol,
        "price": price,
        "change_24h": change_24h,
        "change_4h": change_4h,
        "change_1h": change_1h,
        "high_24h": price * (1 + abs(change_24h) * 0.5),
        "low_24h": price * (1 - abs(change_24h) * 0.5),
        "ema20": price * (1 + change_24h * 0.3),
        "ema50": price * (1 + change_24h * 0.1),
        "ema200": price * (1 + change_24h * 0.05),
        "rsi14": rsi,
        "macd": macd,
        "macd_signal": macd_signal,
        "atr_pct": 0.02 + (hash(symbol) % 20) / 1000,
        "vol_ratio": 0.8 + (hash(symbol) % 40) / 50,
        "funding_rate": (hash(symbol + "fund") % 200 - 100) / 100000,
        "fgi": 30 + (hash(symbol) % 40),
        "long_short_ratio": 0.6 + (hash(symbol) % 18) / 10,
        "social_sentiment": (hash(symbol + "social") % 200 - 100) / 200,
        "exchange_netflow": (hash(symbol + "flow") % 2000 - 1000),
        "whale_transfers": (hash(symbol + "whale") % 30) - 10,
        "etf_flow": (hash(symbol + "etf") % 400 - 200),
        "kdj_k": 30 + (hash(symbol) % 40),
        "kdj_d": 35 + (hash(symbol + "kdjd") % 30),
        "bb_width": 0.02 + (hash(symbol) % 30) / 1000,
        "iv_rank": 0.2 + (hash(symbol) % 60) / 100,
        "vol_20d_avg": 0.02,
        "active_addresses": 1000000 + (hash(symbol) % 500000),
        "active_addresses_trend": (hash(symbol + "addr") % 200 - 100) / 1000,
        "chain_activity": 0.3 + (hash(symbol) % 40) / 100,
        "dollar_index": 95 + (hash(symbol + "dxy") % 10),
        "spx_correlation": (hash(symbol + "spx") % 200 - 100) / 200,
        "rate_env": "neutral",
        "risk_appetite": 0.3 + (hash(symbol) % 40) / 100,
    }


def main():
    """Agent C 主入口"""
    import argparse

    parser = argparse.ArgumentParser(description="Agent C — Dream OS 交易应用")
    parser.add_argument("--coin", type=str, default="BTC", help="目标币种")
    parser.add_argument("--scan", action="store_true", help="扫描多币种")
    parser.add_argument("--real", action="store_true", help="使用真实市场数据")
    parser.add_argument("--execute", action="store_true", help="执行交易（模拟模式）")
    parser.add_argument("--auto-execute", action="store_true", help="自动执行真实交易")
    parser.add_argument("--list-nodes", action="store_true", help="列出已注册节点")
    parser.add_argument("--account", action="store_true", help="查看账户信息")
    parser.add_argument("--agent-id", type=str, default="b", help="Agent ID (a/b)")
    args = parser.parse_args()

    agent = AgentC(agent_id=args.agent_id)

    if args.list_nodes:
        print("\n=== 已注册节点 ===")
        nodes = agent.get_registered_nodes()
        for n in sorted(nodes, key=lambda x: x["node_id"]):
            print(f"  [{n['chain']}] {n['node_id']}: {n['name']}")
        return

    if args.account:
        acct = agent.get_account_info()
        print("\n=== 账户信息 ===")
        print(f"  权益: ${acct.get('equity', 0):.2f} USDC")
        print(f"  可用: ${acct.get('avail', 0):.2f} USDC")
        positions = acct.get("positions", {})
        if positions:
            print(f"  持仓:")
            for coin, pos in positions.items():
                print(f"    {coin}: sz={pos.get('size', 0)} upnl=${pos.get('upnl', 0):.2f}")
        else:
            print(f"  持仓: 无")
        return

    if args.scan:
        universe = ["BTC", "ETH", "SOL", "AVAX", "LINK", "DOT", "MATIC", "BNB", "OP", "ARB"]
        print(f"\n=== 扫描币种: {', '.join(universe)} ===")

        opportunities = agent.scan_universe(universe, use_real_data=args.real, top_n=3)

        print(f"\n=== 最佳交易机会 (Top {len(opportunities)}) ===")
        for i, opp in enumerate(opportunities, 1):
            print(f"\n{i}. {opp['symbol']}: {opp['action']} (置信度: {opp['confidence']:.1%})")
            if opp['trade_order']:
                o = opp['trade_order']
                print(f"   入场: ${o.get('entry_price', 0):.2f}")
                print(f"   止损: ${o.get('stop_loss', 0):.2f}")
                print(f"   止盈: ${o.get('take_profit', 0):.2f}")
                print(f"   杠杆: {o.get('leverage', 1)}x")
                print(f"   R:R: {o.get('rr_ratio', 0)}:1")

            if args.execute:
                print(f"\n   [执行交易]")
                result = agent.execute_trade(opp, auto_execute=args.auto_execute)
                if result.get("ok"):
                    print(f"     ✅ {result.get('action_type')} {opp['symbol']}")
                    if result.get("action") == "executed":
                        print(f"     结果: {result.get('result', {}).get('side')}")
                else:
                    print(f"     ❌ 失败: {result.get('error')}")

        return

    print(f"\n=== 分析 {args.coin} ===")

    if args.real:
        mkt_data = agent.fetch_market_data(args.coin)
        if not mkt_data:
            print(f"❌ 无法获取 {args.coin} 的市场数据")
            return
    else:
        mkt_data = generate_sample_market_data(args.coin)

    print(f"当前价格: ${mkt_data['price']:.2f}")
    print(f"24h涨跌: {mkt_data['change_24h']:+.2%}")
    print(f"RSI: {mkt_data['rsi14']:.1f}")
    print(f"ATR: {mkt_data['atr_pct']:.1%}")

    decision = agent.analyze(args.coin, mkt_data)

    print(f"\n=== 决策结果 ===")
    print(f"动作: {decision['action']}")
    print(f"置信度: {decision['confidence']:.1%}")

    if decision['trade_order']:
        o = decision['trade_order']
        print(f"\n交易指令:")
        print(f"  方向: {o.get('action')}")
        print(f"  入场价: ${o.get('entry_price', 0):.2f}")
        print(f"  止损价: ${o.get('stop_loss', 0):.2f}")
        print(f"  止盈价: ${o.get('take_profit', 0):.2f}")
        print(f"  仓位: {o.get('position_size', 0):.2f} USDT")
        print(f"  杠杆: {o.get('leverage', 1)}x")
        print(f"  R:R: {o.get('rr_ratio', 0)}:1")

    if decision['exit_plan']:
        print(f"\n离场计划:")
        print(f"  决策: {decision['exit_plan'].get('exit_decision')}")
        print(f"  理由: {decision['exit_plan'].get('exit_reason')}")

    print(f"\n=== 推理过程 ===")
    for line in decision['rationale']:
        print(f"  {line}")

    if args.execute and decision["action"] != "HOLD":
        print(f"\n=== 执行交易 ===")
        result = agent.execute_trade(decision, auto_execute=args.auto_execute)
        if result.get("ok"):
            print(f"✅ {result.get('action_type')} {decision['symbol']}")
            if result.get("action") == "executed":
                print(f"交易已执行")
            else:
                print(f"(模拟模式)")
        else:
            print(f"❌ 失败: {result.get('error')}")


if __name__ == "__main__":
    main()