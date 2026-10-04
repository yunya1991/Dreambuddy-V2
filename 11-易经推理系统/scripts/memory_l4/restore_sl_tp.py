#!/usr/bin/env python3
"""
SL/TP 恢复脚本：为 OKX 端所有裸仓重新下发 Algo 止盈止损单。

使用场景：
  - 进程崩溃或 bug 导致 Algo SL/TP 单被误清理
  - OKX 端有持仓但无 SL/TP algo 单保护

SL/TP 计算规则（遵循项目硬约束）：
  - SL 间距 ≥ 8.0%（防低波扫损硬下限）
  - TP 间距 ≥ 6.0%
  - SL 必须位于爆仓价 + 0.3% 安全缓冲的安全侧（爆仓安全优先）
  - 多头 SL < entry, TP > entry；空头反之

用法:
  cd 11-易经推理系统/scripts/memory_l4
  python restore_sl_tp.py           # 检查并补设（dry_run=False 实盘）
  python restore_sl_tp.py --dry-run # 仅检查不下单
  python restore_sl_tp.py --sl-pct 0.10 --tp-pct 0.08  # 自定义间距
"""
import sys
import os
import time
from pathlib import Path

# 确保可以 import okx_simulated
sys.path.insert(0, str(Path(__file__).resolve().parent))

from okx_simulated import OKXSimulatedClient


def compute_sl_tp(entry_px: float, pos_side: str, liq_px: float = 0.0,
                  mark_px: float = 0.0,
                  sl_pct: float = 0.08, tp_pct: float = 0.06) -> tuple:
    """计算 SL/TP 价格。

    Args:
        entry_px: 开仓均价
        pos_side: long / short
        liq_px: 爆仓价（0 表示无数据）
        mark_px: 当前标记价（用于修正已盈利持仓的 TP）
        sl_pct: 止损间距比例（默认 8%）
        tp_pct: 止盈间距比例（默认 6%）

    Returns:
        (sl_px, tp_px)

    注意：
        - SL 始终基于 entry_px 计算（保护本金，不随盈利移动）
        - TP 优先基于 entry_px 计算；但如果持仓已盈利超过 TP 线（mark 已越过），
          则基于 mark_px 重新计算 TP，避免 TP 立即触发
    """
    is_long = pos_side == "long"

    # 基础 SL（始终基于 entry）
    if is_long:
        sl_px = entry_px * (1.0 - sl_pct)
        tp_base = entry_px * (1.0 + tp_pct)
    else:
        sl_px = entry_px * (1.0 + sl_pct)
        tp_base = entry_px * (1.0 - tp_pct)

    # TP 修正：如果 mark 已越过 entry-based TP，改用 mark-based TP
    tp_px = tp_base
    if mark_px > 0:
        if is_long and mark_px >= tp_base:
            # 多头已盈利超过 TP 线 → TP 基于 mark 再加 tp_pct
            tp_px = mark_px * (1.0 + tp_pct)
        elif not is_long and mark_px <= tp_base:
            # 空头已盈利超过 TP 线 → TP 基于 mark 再减 tp_pct
            tp_px = mark_px * (1.0 - tp_pct)

    # 爆仓安全约束：SL 必须在爆仓价 + 0.3% 缓冲的安全侧
    if liq_px > 0:
        if is_long:
            # 多头爆仓价在下方，SL 必须在 liq_px + 0.3% 之上
            safe_min = liq_px * (1.0 + 0.003)
            if sl_px < safe_min:
                sl_px = safe_min
        else:
            # 空头爆仓价在上方，SL 必须在 liq_px - 0.3% 之下
            safe_max = liq_px * (1.0 - 0.003)
            if sl_px > safe_max:
                sl_px = safe_max

    return round(sl_px, 4), round(tp_px, 4)


def main():
    dry_run = "--dry-run" in sys.argv
    sl_pct = 0.08
    tp_pct = 0.06

    # 解析自定义参数
    for i, arg in enumerate(sys.argv):
        if arg == "--sl-pct" and i + 1 < len(sys.argv):
            sl_pct = float(sys.argv[i + 1])
        if arg == "--tp-pct" and i + 1 < len(sys.argv):
            tp_pct = float(sys.argv[i + 1])

    print(f"=== SL/TP 恢复脚本 ===")
    print(f"模式: {'DRY-RUN（仅检查）' if dry_run else '实盘（将下发 algo 单）'}")
    print(f"SL 间距: {sl_pct*100:.1f}% | TP 间距: {tp_pct*100:.1f}%")
    print()

    client = OKXSimulatedClient()
    if not client._has_credentials():
        print("ERROR: OKX API 凭据未配置")
        sys.exit(1)

    print(f"API: {client.base_url}")
    print(f"模拟: {client.simulated} | Dry-run: {client.dry_run}")
    print()

    # 1. 获取所有持仓
    pos_result = client.get_positions()
    if not pos_result.get("ok"):
        print(f"ERROR: 获取持仓失败: {pos_result.get('error')}")
        sys.exit(1)

    positions = pos_result.get("positions", [])
    print(f"OKX 端持仓数: {len(positions)}")
    if not positions:
        print("无持仓，无需恢复 SL/TP")
        return

    # 2. 逐个检查并补设
    restored = 0
    skipped = 0
    failed = 0

    for pos in positions:
        inst_id = pos["inst_id"]
        pos_side = pos["pos_side"]
        pos_size = pos["pos"]
        entry_px = pos["avg_px"]
        liq_px = pos.get("liq_px", 0.0)
        mark_px = pos.get("mark_px", 0.0)

        print(f"--- {inst_id} ({pos_side}) ---")
        print(f"  数量: {pos_size} | 均价: {entry_px} | 爆仓: {liq_px} | 标记: {mark_px}")

        # 2a. 检查现有 algo 单
        algo_result = client.get_algo_orders(inst_id=inst_id)
        has_sl = False
        has_tp = False
        if algo_result.get("ok"):
            for od in algo_result.get("orders", []):
                _sl = od.get("sl_trigger_px") or od.get("trigger_px", 0)
                _tp = od.get("tp_trigger_px", 0)
                if _sl and float(_sl) > 0:
                    has_sl = True
                if _tp and float(_tp) > 0:
                    has_tp = True
        print(f"  现有 SL: {'有' if has_sl else '无'} | 现有 TP: {'有' if has_tp else '无'}")

        if has_sl and has_tp:
            print(f"  → SL/TP 均存在，跳过")
            skipped += 1
            continue

        # 2b. 计算 SL/TP
        sl_px, tp_px = compute_sl_tp(entry_px, pos_side, liq_px,
                                     mark_px=mark_px,
                                     sl_pct=sl_pct, tp_pct=tp_pct)
        print(f"  计算SL: {sl_px} ({abs(sl_px - entry_px) / entry_px * 100:.1f}%)")
        print(f"  计算TP: {tp_px} ({abs(tp_px - entry_px) / entry_px * 100:.1f}%)")

        # 2c. 安全检查：pos_size 不能为 0
        if pos_size == 0:
            print(f"  → pos_size=0，跳过")
            skipped += 1
            continue

        # 2d. 下发 algo 单
        if dry_run:
            print(f"  → [DRY-RUN] 将下发 SL={sl_px} TP={tp_px} sz={abs(pos_size)}")
            skipped += 1
            continue

        try:
            # 先取消残留 algo 单（避免冲突）
            if hasattr(client, "cancel_algo_orders"):
                client.cancel_algo_orders(inst_id=inst_id)
                time.sleep(0.5)

            r = client.place_stop_loss_take_profit(
                inst_id=inst_id,
                pos_side=pos_side,
                stop_loss_px=sl_px,
                take_profit_px=tp_px,
                sz=abs(pos_size),
                reason="restore_sl_tp_emergency",
            )
            if r.get("ok"):
                print(f"  → ✅ SL/TP 已下发 (mode={r.get('mode')})")
                restored += 1
            else:
                print(f"  → ❌ 下发失败: {r.get('error', 'unknown')}")
                if r.get("errors"):
                    print(f"    errors: {r['errors']}")
                failed += 1
        except Exception as e:
            print(f"  → ❌ 异常: {e}")
            failed += 1

        # 避免限流
        time.sleep(1.0)

    # 3. 汇总
    print()
    print(f"=== 汇总 ===")
    print(f"总持仓: {len(positions)}")
    print(f"已恢复: {restored}")
    print(f"已跳过: {skipped}")
    print(f"失败:   {failed}")


if __name__ == "__main__":
    main()
