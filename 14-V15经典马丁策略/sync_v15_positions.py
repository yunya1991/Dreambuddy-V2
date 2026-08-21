#!/usr/bin/env python3
"""V15马丁系统持仓同步 - 简化版
复用易经系统的OKX客户端，但在初始化前覆盖环境变量为V15的配置
"""
import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime

# ===== 步骤0：切换到V15根目录 + 加载V15环境变量（必须最先做）=====
_v15_root = Path(__file__).resolve().parent
os.chdir(_v15_root)

# 手动读取V15配置并覆盖环境变量（优先级高于易经系统的）
env_vars = {}
env_file = _v15_root / "config" / ".env.common"
with open(env_file, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()
# 强制覆盖环境变量
for k, v in env_vars.items():
    os.environ[k] = v

print(f"[env] V15 API key: {os.environ.get('OKX_API_KEY', 'NOT SET')[:16]}...")
print(f"[env] OKX_BASE_URL: {os.environ.get('OKX_BASE_URL')}")

# ===== 步骤1：导入易经系统的 OKX 客户端（会从os.environ读取）=====
# 把易经系统项目根加入sys.path
_yj_root = _v15_root.parent / "11-易经推理系统"
sys.path.insert(0, str(_yj_root))
sys.path.insert(0, str(_v15_root))

_stdlib_paths = [p for p in sys.path if "site-packages" in p or "Frameworks/Python3" in p]
# 重新排序避免inspect.py冲突
sys.path = _stdlib_paths + [str(_yj_root), str(_v15_root)]

from dotenv import load_dotenv as _noop  # 已经手动加载了

# 导入OKX客户端（使用易经系统的已验证版本）
from scripts.memory_l4.okx_simulated import OKXSimulatedClient

def main():
    print("=" * 70)
    print(f"V15马丁系统 持仓同步 @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 初始化客户端（会从os.environ读取V15的API密钥）
    okx = OKXSimulatedClient()
    state_file = _v15_root / "data" / "v15_state.json"

    # 步骤1：拉取OKX所有持仓
    print("\n[步骤1] 从OKX拉取V15账户所有持仓...")
    r = okx.get_positions()
    if not r.get("ok"):
        print(f"  全部持仓查询失败: {r.get('error')}，尝试逐个币种...")
        all_positions = []
        coins = ["BTC", "ETH", "SOL", "BNB", "OKB", "PUMP", "UNI", "AMZN", "XAU", "HYPE", "MU", "SKHYNIX", "NVDA", "GOOGL", "XAG", "CRCL", "COIN", "BMNR", "MSTR"]
        for coin in coins:
            inst_id = f"{coin}-USDT-SWAP"
            rr = okx.get_positions(inst_id)
            if rr.get("ok"):
                all_positions.extend(rr.get("positions", []))
            time.sleep(0.05)
        positions = all_positions
    else:
        positions = r.get("positions", [])

    print(f"  OKX端实际持仓: {len(positions)} 个")
    for p in positions:
        print(f"    - {p['inst_id']} {p['pos_side']} sz={p['pos']} avg={p['avg_px']} upl={p.get('upl')}")

    # 步骤2：读取本地state
    print("\n[步骤2] 读取本地 v15_state.json...")
    if state_file.exists():
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
    else:
        state = {"positions": {}, "stats": {}}
    local_positions = state.get("positions", {})
    print(f"  本地原记录持仓: {len(local_positions)} 个")
    for coin, pos in local_positions.items():
        print(f"    - {coin} {pos.get('direction')} sz={pos.get('sz')} entry={pos.get('entry_price')}")

    # 步骤3：OKX → 本地同步
    print("\n[步骤3] 同步 OKX → 本地...")
    okx_coins = set()
    synced, removed, kept = 0, 0, 0

    for p in positions:
        inst_id = p["inst_id"]
        coin = inst_id.split("-")[0]
        okx_coins.add(coin)
        # 判断方向
        pos_val = float(p["pos"])
        if p["pos_side"] in ("long", "short"):
            direction = p["pos_side"].upper()
        else:  # net模式
            direction = "LONG" if pos_val > 0 else "SHORT"
        sz_abs = abs(pos_val)

        if coin in local_positions:
            old = local_positions[coin]
            old_dir = str(old.get("direction", "")).upper()
            old_sz = float(old.get("sz", 0))
            if old_dir == direction and abs(old_sz - sz_abs) < 0.001:
                print(f"  ⊘ {coin:<8} 本地已有匹配记录，保留 ({direction} sz={sz_abs})")
                kept += 1
                continue
            else:
                print(f"  ↻ {coin:<8} 记录不匹配，更新: {old_dir} sz={old_sz} → {direction} sz={sz_abs}")

        # 写入最小结构（V15的light_poll或orchestrator下一轮会补全addon_grid等完整字段）
        mark_px = float(p.get("mark_px", p["avg_px"]) or 0)
        local_positions[coin] = {
            "inst_id": inst_id,
            "direction": direction,
            "entry_price": float(p["avg_px"]),
            "open_price": float(p["avg_px"]),
            "sz": sz_abs,
            "addons": 0,
            "confidence": 50,
            "open_time": datetime.utcnow().isoformat() + "+00:00",
            "take_profit_pct": 0.04,
            "addon_pct": 0.08,
            "stop_loss_price": None,
            "stop_loss_type": None,
            "trailing_active": False,
            "peak_price": mark_px,
            "current_price": mark_px,
            "unrealized_pnl": float(p.get("upl", 0)),
            "upl_ratio": float(p.get("upl_ratio", 0)),
            "profit_pct": 0.0,
            "external_sync": True,  # 标记来源
        }
        print(f"  ✓ {coin:<8} 已同步 {direction} @ {p['avg_px']} sz={sz_abs}")
        synced += 1

    # 步骤4：反向清理
    print("\n[步骤4] 清理本地残留（OKX已无持仓）...")
    for coin in list(local_positions.keys()):
        if coin in okx_coins:
            continue
        inst_id = local_positions[coin].get("inst_id", f"{coin}-USDT-SWAP")
        rr = okx.get_positions(inst_id)
        okx_has = False
        if rr.get("ok"):
            okx_has = any(float(x["pos"]) != 0 for x in rr.get("positions", []))
        if not okx_has:
            old = local_positions.pop(coin)
            print(f"  ✗ {coin:<8} 清理本地残留 ({old.get('direction')} sz={old.get('sz')})")
            removed += 1
        else:
            print(f"  ? {coin:<8} OKX确认有持仓，保留")

    # 保存state
    state["positions"] = local_positions
    if "stats" not in state:
        state["stats"] = {}
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    print()
    print("=" * 70)
    print(f"[V15同步完成] 新增/更新={synced}  匹配保留={kept}  清理残留={removed}")
    print(f"[V15当前本地持仓] {len(local_positions)} 个")
    for coin, pos in local_positions.items():
        print(f"  - {coin:<8} {pos['direction']:<5} entry={pos['entry_price']:<12} sz={pos['sz']:<8}")
    if not local_positions:
        print("  （零持仓，系统从零开始 ✓）")
    print("=" * 70)

if __name__ == "__main__":
    main()
