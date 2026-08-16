#!/usr/bin/env python3
"""精确持仓同步：确保 XAU/OKB 等持仓也正确同步到本地"""
import os
import sys
from pathlib import Path

_stdlib_paths = [p for p in sys.path if "site-packages" in p or "Frameworks/Python3" in p or p == ""]
_project_root = str(Path(__file__).resolve().parent.parent.parent)
sys.path = _stdlib_paths + [_project_root]

from dotenv import load_dotenv
env_path = Path(_project_root) / ".env"
load_dotenv(env_path)

from scripts.memory_l4.okx_simulated import OKXSimulatedClient
from scripts.memory_l4.trading_utils import PositionTracker, RiskManager

def main():
    okx = OKXSimulatedClient()
    pt = PositionTracker()
    rm = RiskManager()

    print("=" * 70)
    print("精确持仓同步")
    print("=" * 70)

    # 步骤1：一次获取所有持仓（避免逐个查询限流）
    print("\n[步骤1] 从OKX一次性拉取 ALL 持仓...")
    all_pos = okx.get_positions()  # 不传instId = 所有持仓
    if not all_pos.get("ok"):
        print(f"  失败: {all_pos.get('error')}")
        # 降级：逐个尝试关键币种
        target_coins = ["HYPE", "XAU", "OKB", "UNI", "PUMP", "MU", "SKHYNIX", "ETH", "BTC", "SOL", "AMZN", "BNB"]
        all_positions = []
        for coin in target_coins:
            inst_id = f"{coin}-USDT-SWAP"
            r = okx.get_positions(inst_id)
            if r.get("ok"):
                all_positions.extend(r.get("positions", []))
            time.sleep(0.1)
        all_pos = {"ok": True, "positions": all_positions}

    positions = all_pos.get("positions", [])
    print(f"  OKX端实际持仓数: {len(positions)} 个")
    for p in positions:
        print(f"    - {p['inst_id']} {p['pos_side']} sz={p['pos']} avg={p['avg_px']} mark={p['mark_px']}")

    print("\n[步骤2] 同步到本地 PositionTracker...")
    import time
    synced, skipped, cleaned = 0, 0, 0

    # 正向同步
    local_inst_ids = set()
    for p in positions:
        inst_id = p["inst_id"]
        local_inst_ids.add(inst_id)
        # 从inst_id提取coin
        coin = inst_id.split("-")[0]
        if pt.has_open_position(inst_id):
            print(f"  ⊘ {coin:<8} 本地已有记录，跳过 ({p['pos_side']} sz={p['pos']})")
            skipped += 1
            continue
        pt.open_position(
            coin=coin,
            inst_id=inst_id,
            direction=p["pos_side"],
            entry_price=float(p["avg_px"]),
            confidence=0.8,
            hexagram="已存在持仓",
            market_snapshot={"price": float(p["mark_px"])},
            strategy_source="bcrm",
            scale_params={
                "okx_actual_sz": float(p["pos"]),
                "okx_actual_side": p["pos_side"],
            },
        )
        print(f"  ✓ {coin:<8} 已同步 {p['pos_side']} @ {p['avg_px']} sz={p['pos']}")
        synced += 1

    print("\n[步骤3] 反向清理本地残留...")
    for lp in list(pt.all_open_positions()):
        inst_id = lp.inst_id
        coin = lp.coin
        if inst_id in local_inst_ids:
            continue
        # 再确认一次OKX端
        r = okx.get_positions(inst_id)
        okx_has = False
        if r.get("ok"):
            okx_has = any(float(x["pos"]) > 0 for x in r.get("positions", []))
        if not okx_has:
            pt.close_position(inst_id, exit_price=0.0, exit_reason="手动同步: OKX无对应持仓")
            print(f"  ✗ {coin:<8} 清理本地残留 ({lp.direction})")
            cleaned += 1
        else:
            print(f"  ? {coin:<8} OKX确认有持仓，保留")

    print()
    print("=" * 70)
    final_positions = pt.all_open_positions()
    print(f"[完成] 新增={synced}  跳过={skipped}  清理={cleaned}")
    print(f"[当前本地持仓总数] {len(final_positions)} 个")
    for p in final_positions:
        sz = p.scale_params.get("okx_actual_sz", "?")
        print(f"  - {p.coin:<8} {p.direction:<5} entry={p.entry_price:<10} sz={sz:<8} src={p.strategy_source}")
    print()
    print(f"[风控] daily_pnl={rm.state.daily_pnl:.2f} halted={rm.state.trading_halted}")
    print("=" * 70)

if __name__ == "__main__":
    import time
    main()
