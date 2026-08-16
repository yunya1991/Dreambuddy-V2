#!/usr/bin/env python3
"""
手动触发持仓同步脚本
- 从 OKX 拉取所有配置币种的真实持仓
- 同步到本地 PositionTracker
- 清理本地残留（OKX已无持仓但本地有的记录）
- 补全 risk_state.json 关键字段
"""
import os
import sys
import json
from datetime import datetime
from pathlib import Path

# 关键修复：把标准库路径放在最前，避免 scripts/memory_l4/inspect.py 掩盖标准库 inspect
_stdlib_paths = [p for p in sys.path if "site-packages" in p or "Frameworks/Python3" in p or p == ""]
_project_root = str(Path(__file__).resolve().parent.parent.parent)
# 重组：先标准库 + site-packages，最后再加项目根（避免 inspect.py 先被找到）
sys.path = _stdlib_paths + [_project_root]

# 加载环境变量
from dotenv import load_dotenv
env_path = Path(_project_root) / ".env"
load_dotenv(env_path)

from scripts.memory_l4.okx_simulated import OKXSimulatedClient
from scripts.memory_l4.trading_utils import PositionTracker, RiskManager


def main():
    print("=" * 60)
    print(f"[持仓同步] 开始手动同步 @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 配置币种列表
    coins_str = os.environ.get("POLLING_COINS", "UNI,PUMP,MU,SKHYNIX,HYPE,ETH,BTC,SOL,XAU,XAG,GOOGL,NVDA,AMZN,OKB,BNB")
    coins = [c.strip() for c in coins_str.split(",") if c.strip()]
    print(f"[持仓同步] 待检查币种: {len(coins)} 个 -> {coins}")
    print()

    # 初始化客户端
    okx_client = OKXSimulatedClient()
    position_tracker = PositionTracker()
    risk_manager = RiskManager(
        daily_loss_limit_usdt=float(os.environ.get("DAILY_LOSS_LIMIT", -50.0)),
        max_consecutive_losses=int(os.environ.get("MAX_CONSECUTIVE_LOSSES", 5)),
        default_position_pct=float(os.environ.get("DEFAULT_POSITION_PCT", 0.20)),
        min_position_usdt=float(os.environ.get("MIN_POSITION_USDT", 20.0)),
    )

    # ── 1. 正向同步：OKX → 本地 ──────────────────────────────────────
    synced_count = 0
    skipped_count = 0
    print("[1/2] 正同步：OKX持仓 → 本地...")
    for coin in coins:
        inst_id = f"{coin}-USDT-SWAP"
        pos_result = okx_client.get_positions(inst_id)
        if not pos_result.get("ok"):
            err = pos_result.get("msg", "unknown error")
            print(f"  ✗ {coin:<8} API查询失败: {err}")
            continue
        positions = pos_result.get("positions", [])
        has_pos = False
        for pos in positions:
            sz = float(pos.get("pos", 0))
            if sz <= 0:
                continue
            has_pos = True
            if position_tracker.has_open_position(inst_id):
                print(f"  ⊘ {coin:<8} 本地已有记录，跳过 ({pos.get('pos_side')} sz={sz})")
                skipped_count += 1
                continue
            # 新增本地记录
            avg_px = float(pos.get("avg_px", 0))
            mark_px = float(pos.get("mark_px", avg_px))
            pos_side = pos.get("pos_side")
            position_tracker.open_position(
                coin=coin,
                inst_id=inst_id,
                direction=pos_side,
                entry_price=avg_px,
                confidence=0.8,
                hexagram="已存在持仓",
                market_snapshot={"price": mark_px},
                strategy_source="bcrm",
                scale_params={
                    "okx_actual_sz": sz,
                    "okx_actual_side": pos_side,
                },
            )
            print(f"  ✓ {coin:<8} 已同步 {pos_side} @ {avg_px} sz={sz} [OKX实际持仓]")
            synced_count += 1
        if not has_pos:
            print(f"  - {coin:<8} OKX无持仓")

    print()
    # ── 2. 反向清理：本地残留 → 清理 ──────────────────────────────────
    cleaned_count = 0
    print("[2/2] 反清理：检查本地残留（OKX已无持仓）...")
    local_positions = position_tracker.all_open_positions()
    for p in list(local_positions):
        inst_id = p.inst_id
        coin = p.coin
        pos_result = okx_client.get_positions(inst_id)
        if not pos_result.get("ok"):
            print(f"  ? {coin:<8} API查询失败，暂保留本地")
            continue
        okx_positions = [pp for pp in pos_result.get("positions", []) if float(pp.get("pos", 0)) > 0]
        if not okx_positions:
            position_tracker.close_position(
                inst_id,
                exit_price=0.0,
                exit_reason="手动同步: OKX已无持仓，清理本地残留",
            )
            print(f"  ✗ {coin:<8} 本地残留已清理 ({p.direction})")
            cleaned_count += 1
        else:
            print(f"  ✓ {coin:<8} OKX有对应持仓，本地记录正常")

    print()
    # ── 3. 汇总报告 ──────────────────────────────────────────────────
    open_positions = position_tracker.all_open_positions()
    print("=" * 60)
    print(f"[持仓同步] 完成！汇总报告：")
    print(f"  新增同步:   {synced_count} 个")
    print(f"  已存在跳过: {skipped_count} 个")
    print(f"  清理残留:   {cleaned_count} 个")
    print(f"  当前本地持仓总数: {len(open_positions)} 个")
    if open_positions:
        print("  持仓明细:")
        for p in open_positions:
            sz = p.scale_params.get("okx_actual_sz", "?")
            print(f"    - {p.coin:<8} {p.direction:<5} @ {p.entry_price:<10} sz={sz} src={p.strategy_source}")
    else:
        print("  当前无持仓（系统从零开始 ✓）")

    print()
    print(f"[风控状态] daily_pnl={risk_manager.state.daily_pnl:.2f} "
          f"consecutive_losses={risk_manager.state.current_consecutive_losses} "
          f"halted={risk_manager.state.trading_halted}")
    initial_equity = float(os.environ.get("INITIAL_EQUITY", 200.0))
    trading_budget = initial_equity * 0.75  # 默认75%作为交易预算
    risk_threshold = trading_budget * 0.20
    print(f"[风控参数] initial_equity={initial_equity:.2f}U "
          f"trading_budget≈{trading_budget:.2f}U "
          f"risk20%_threshold≈{risk_threshold:.2f}U")

    print()
    print("=" * 60)
    print("[持仓同步] 全部完成 ✓")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
