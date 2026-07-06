#!/usr/bin/env python3
"""
币种池每日自动筛选器 — 每24h运行一次
扫描Hyperliquid全市场，按交易量/资金费率/持仓量综合评分，
保留核心币种(BTC/ETH/HYPE/UNI) + 筛选Top扩展币种，最多10个。

更新范围：
  - aster_spot.py 的 UNIVERSE / _ASSET_INDEX / _price_decimals / _size_decimals
  - agent_a_runner.py 的 UNIVERSE_A
  - agent_b_runner.py 的 UNIVERSE_B
  - agent_a_memory.json 的 universe 字段
  - agent_b_memory.json 的 universe 字段
"""
import os
import sys
import json
import re
import requests
import warnings
from pathlib import Path
from datetime import datetime, timezone

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).parent.parent.resolve()
STATE_FILE = BASE_DIR / "data" / "universe_screen_state.json"
LOG_FILE = BASE_DIR / "logs" / "universe_screen.log"

# 核心币种（用户指定，不可替换）
CORE_COINS = ["BTC", "ETH", "HYPE", "UNI"]
MAX_TOTAL = 20
MAX_EXTENDED = MAX_TOTAL - len(CORE_COINS)  # 16个扩展位

# 排除列表（稳定币、已废弃等）
EXCLUDE = {
    "USDC", "USTC", "DAI", "USDT", "USDE", "DOLA", "CRAI", "SUSDE",
    "WUSDC", "WUSDT", "IUSDC", "HLP", "DFI", "STABLE",
}

# MEME 币排除列表（波动大、流动性不稳定）
MEME_EXCLUDE = {
    "PUMP", "XPL", "FARTCOIN", "kPEPE", "kBONK", "PENGU", "HMSTR",
    "MON", "WLFI", "TRUMP", "VIRTUAL", "KAITO", "VVV", "GRAM",
    "TURBO", "BANANA", "POPCAT", "WEN", "MOODENG", "FWOG",
    "BRETT", "MOTHER", "COOKIE", "DOGE", "SHIB", "FLOKI", "PEPE",
    "WIF", "BONK", "JUPITER",
    "SPX",  # SPX 是股票指数也排除
}


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def fetch_market_data():
    """获取Hyperliquid全市场数据"""
    s = requests.Session()
    s.trust_env = False
    resp = s.post("https://api.hyperliquid.xyz/info",
                  json={"type": "metaAndAssetCtxs"}, timeout=15)
    data = resp.json()
    meta = data[0]
    ctxs = data[1]
    universe = meta.get("universe", [])
    return universe, ctxs


def screen_coins(universe, ctxs):
    """筛选高潜力代币"""
    candidates = []
    for i, asset in enumerate(universe):
        name = asset.get("name", "")
        if name in CORE_COINS or name in EXCLUDE or name in MEME_EXCLUDE:
            continue
        if i >= len(ctxs):
            continue

        ctx = ctxs[i]
        volume = float(ctx.get("dayNtlVlm", 0))
        oi = float(ctx.get("openInterest", 0))
        funding = float(ctx.get("funding", 0))
        max_lev = int(asset.get("maxLeverage", 1))
        sz_dec = int(asset.get("szDecimals", 2))

        # 筛选门槛
        if volume < 1_000_000:  # 日交易量 > $1M
            continue
        if oi < 100_000:  # 持仓量 > $100K
            continue

        # 综合得分
        vol_score = min(volume / 10_000_000, 10)
        fr_score = abs(funding) * 1000
        oi_score = min(oi / 1_000_000, 10)
        total_score = vol_score * 0.5 + fr_score * 0.3 + oi_score * 0.2

        candidates.append({
            "name": name,
            "index": i,
            "szDecimals": sz_dec,
            "maxLeverage": max_lev,
            "funding": funding,
            "volume": volume,
            "oi": oi,
            "score": total_score,
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:MAX_EXTENDED]


def update_aster_spot(selected_extended):
    """更新 aster_spot.py"""
    fpath = BASE_DIR / "execution" / "aster_spot.py"
    content = fpath.read_text()

    all_coins = CORE_COINS + [c["name"] for c in selected_extended]
    # UNIVERSE
    new_universe = f'UNIVERSE = {json.dumps(all_coins)}'
    content = re.sub(r'UNIVERSE = \[.*?\]', new_universe, content, count=1)

    # _ASSET_INDEX
    index_entries = []
    for c in all_coins:
        if c in CORE_COINS:
            # 保留核心币种现有index
            continue
    # 重建完整 _ASSET_INDEX
    all_with_index = {}
    for c in CORE_COINS:
        # 从现有文件中提取
        m = re.search(rf'"{c}":\s*(\d+)', content)
        if m:
            all_with_index[c] = int(m.group(1))
    for c in selected_extended:
        all_with_index[c["name"]] = c["index"]

    index_lines = []
    for coin, idx in all_with_index.items():
        index_lines.append(f'"{coin}": {idx}')
    new_index = "_ASSET_INDEX = {\n    " + ", ".join(index_lines) + ",\n}"
    content = re.sub(r'_ASSET_INDEX = \{.*?\}', new_index, content, count=1, flags=re.DOTALL)

    # _price_decimals 和 _size_decimals
    price_dec_map = {}
    size_dec_map = {}
    for c in CORE_COINS:
        pm = re.search(rf'"{c}":\s*(\d+)', content.split("_price_decimals")[1].split("\n")[0])
        sm = re.search(rf'"{c}":\s*(\d+)', content.split("_size_decimals")[1].split("\n")[0])

    # 简化：直接用正则替换整个函数返回值
    pd_entries = []
    sd_entries = []
    # 保留核心
    core_pd = {"BTC": 1, "ETH": 2, "HYPE": 3, "UNI": 3}
    core_sd = {"BTC": 5, "ETH": 4, "HYPE": 2, "UNI": 1}
    for c in CORE_COINS:
        pd_entries.append(f'"{c}": {core_pd[c]}')
        sd_entries.append(f'"{c}": {core_sd[c]}')
    for c in selected_extended:
        pd_entries.append(f'"{c["name"]}": {min(5 - c["szDecimals"], 5) if c["szDecimals"] < 5 else 0}')
        sd_entries.append(f'"{c["name"]}": {c["szDecimals"]}')

    new_pd = f'def _price_decimals(coin: str) -> int:\n    return {{{", ".join(pd_entries)}}}.get(coin, 4)'
    new_sd = f'def _size_decimals(coin: str) -> int:\n    return {{\n        {", ".join(sd_entries)},\n    }}.get(coin, 2)'

    content = re.sub(r'def _price_decimals\(coin: str\) -> int:.*?\.get\(coin, 4\)',
                     new_pd, content, count=1, flags=re.DOTALL)
    content = re.sub(r'def _size_decimals\(coin: str\) -> int:.*?\.get\(coin, 2\)',
                     new_sd, content, count=1, flags=re.DOTALL)

    fpath.write_text(content)
    return all_coins


def update_runner(filepath, var_name, all_coins):
    """更新 agent runner 的 UNIVERSE"""
    content = filepath.read_text()
    if filepath.name == "agent_a_runner.py":
        new_val = f'UNIVERSE_A = [\n    {", ".join(json.dumps(c) for c in all_coins[:4])},\n    {", ".join(json.dumps(c) for c in all_coins[4:])},\n]'
        content = re.sub(r'UNIVERSE_A = \[.*?\]', new_val, content, count=1, flags=re.DOTALL)
    else:
        new_val = f'UNIVERSE_B = {json.dumps(all_coins)}'
        content = re.sub(r'UNIVERSE_B = \[.*?\]', new_val, content, count=1, flags=re.DOTALL)
    filepath.write_text(content)


def update_memory(agent_id, all_coins, selected_extended):
    """更新记忆文件"""
    fpath = BASE_DIR / "data" / f"agent_{agent_id}_memory.json"
    mem = json.loads(fpath.read_text())

    coin_details = {}
    for c in CORE_COINS:
        coin_details[c] = {"category": "核心", "reason": "用户指定币种"}
    for c in selected_extended:
        coin_details[c["name"]] = {
            "category": "扩展",
            "reason": f'日交易量${c["volume"]/1e6:.1f}M, OI${c["oi"]/1e6:.1f}M, FR={c["funding"]*100:+.4f}%',
            "score": round(c["score"], 2),
        }

    mem["universe"] = {
        "coins": all_coins,
        "core_coins": CORE_COINS,
        "extended_coins": [c["name"] for c in selected_extended],
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "selection_criteria": {
            "min_daily_volume_usd": 1000000,
            "min_open_interest_usd": 100000,
            "scoring": "volume(50%) + funding_rate_deviation(30%) + open_interest(20%)",
            "max_coins": MAX_TOTAL,
        },
        "coin_details": coin_details,
    }
    fpath.write_text(json.dumps(mem, indent=2, ensure_ascii=False))


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_screen": None, "history": []}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def should_run() -> bool:
    """检查是否需要运行（距上次>=24h）"""
    state = load_state()
    last = state.get("last_screen")
    if last is None:
        return True
    last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
    elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
    return elapsed >= 86400  # 24h


def run_screen(force=False):
    """执行筛选"""
    if not force and not should_run():
        log("距上次筛选不足24h，跳过")
        return False

    log("="*55)
    log("开始币种池筛选")
    log("="*55)

    # 1. 获取市场数据
    log("[1] 获取Hyperliquid全市场数据...")
    universe, ctxs = fetch_market_data()
    log(f"    总标的数: {len(universe)}")

    # 2. 筛选
    log("[2] 筛选高潜力代币...")
    selected = screen_coins(universe, ctxs)
    log(f"    选出 {len(selected)} 个扩展币种:")
    for c in selected:
        log(f'      {c["name"]:6s} Vol=${c["volume"]/1e6:.1f}M OI=${c["oi"]/1e6:.1f}M FR={c["funding"]*100:+.4f}% Score={c["score"]:.2f}')

    all_coins = CORE_COINS + [c["name"] for c in selected]

    # 3. 更新代码文件
    log("[3] 更新 aster_spot.py...")
    update_aster_spot(selected)

    log("[4] 更新 agent_a_runner.py...")
    update_runner(BASE_DIR / "agents" / "agent_a_runner.py", "A", all_coins)

    log("[5] 更新 agent_b_runner.py...")
    update_runner(BASE_DIR / "agents" / "agent_b_runner.py", "B", all_coins)

    # 4. 更新记忆
    log("[6] 更新 Agent A 记忆...")
    update_memory("a", all_coins, selected)

    log("[7] 更新 Agent B 记忆...")
    update_memory("b", all_coins, selected)

    # 5. 保存状态
    state = load_state()
    state["last_screen"] = datetime.now(timezone.utc).isoformat()
    state["history"].append({
        "ts": state["last_screen"],
        "coins": all_coins,
        "extended": [c["name"] for c in selected],
    })
    # 只保留最近30条历史
    state["history"] = state["history"][-30:]
    save_state(state)

    log(f"\n✅ 筛选完成! 币种池: {all_coins}")
    log(f"   核心币种: {CORE_COINS}")
    log(f"   扩展币种: {[c['name'] for c in selected]}")
    return True


if __name__ == "__main__":
    force = "--force" in sys.argv
    run_screen(force=force)
