#!/usr/bin/env python3
"""补全新同步持仓的默认SL/TP ROI + 最终校验"""
import os
import sys
import json
from pathlib import Path

_stdlib_paths = [p for p in sys.path if "site-packages" in p or "Frameworks/Python3" in p or p == ""]
_yj_root = str(Path(__file__).resolve().parent.parent.parent)
sys.path = _stdlib_paths + [_yj_root]

positions_dir = Path(_yj_root) / ".workbuddy" / "memory_l4" / "open_positions"
DEFAULT_SL_ROI = 0.75  # 参考HYPE
DEFAULT_TP_ROI = 1.5   # 参考HYPE

print("补全新同步持仓的 base_sl_roi / base_tp_roi...")
updated = 0
for f in positions_dir.glob("*.json"):
    if f.name == "last_close_info.json":
        continue
    with open(f, "r", encoding="utf-8") as fp:
        data = json.load(fp)
    sl = data.get("base_sl_roi", 0.0) or 0.0
    tp = data.get("base_tp_roi", 0.0) or 0.0
    coin = data.get("coin", f.name)
    if sl == 0.0 or tp == 0.0:
        data["base_sl_roi"] = DEFAULT_SL_ROI
        data["base_tp_roi"] = DEFAULT_TP_ROI
        with open(f, "w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2, ensure_ascii=False)
        print(f"  ✓ {coin:<8} 补全: SL_ROI={DEFAULT_SL_ROI}%  TP_ROI={DEFAULT_TP_ROI}%")
        updated += 1
    else:
        print(f"  ⊘ {coin:<8} 已有: SL_ROI={sl}%  TP_ROI={tp}%  跳过")

print(f"\n完成: 更新 {updated} 个文件")
print()
print("=" * 70)
print("最终持仓校验报告")
print("=" * 70)
print("\n【易经推理系统 - 本地持仓】")
yj_count = 0
for f in sorted(positions_dir.glob("*.json")):
    if f.name == "last_close_info.json":
        continue
    with open(f) as fp:
        d = json.load(fp)
    sz = d.get("scale_params", {}).get("okx_actual_sz", "?")
    print(f"  - {d['coin']:<8} {d['direction']:<5} entry={d['entry_price']:<10} sz={sz:<8} "
          f"SL={d.get('base_sl_roi')}% TP={d.get('base_tp_roi')}% src={d.get('strategy_source')}")
    yj_count += 1
if yj_count == 0:
    print("  （零持仓）")

# V15校验
v15_state = Path(_yj_root).parent / "14-V15经典马丁策略" / "data" / "v15_state.json"
print(f"\n【V15马丁系统 - 本地持仓】")
v15_count = 0
if v15_state.exists():
    with open(v15_state) as fp:
        s = json.load(fp)
    for coin, p in sorted(s.get("positions", {}).items()):
        print(f"  - {coin:<8} {p.get('direction','?'):<5} entry={p.get('entry_price','?'):<12} sz={p.get('sz','?'):<8}")
        v15_count += 1
if v15_count == 0:
    print("  （零持仓）")

print()
print("=" * 70)
print(f"总计: 易经={yj_count}  V15={v15_count}")
print("=" * 70)
