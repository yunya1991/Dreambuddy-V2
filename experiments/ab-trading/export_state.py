#!/usr/bin/env python3
"""
采集 AB Trading 监控数据并导出为 state.json
- 本地 data_server.py 可调用
- GitHub Actions 可直接运行并提交到仓库
用法：python3 export_state.py [output_path]
"""
import json, os, sys, warnings
from pathlib import Path

warnings.filterwarnings("ignore")
BASE_DIR = Path(__file__).parent
LOG_A    = BASE_DIR / "logs" / "agent_a"
LOG_B    = BASE_DIR / "logs" / "agent_b"

USER_A = "0x93842F1ea62E7E3c71494d9EA69EfC4F2D6e9934"
USER_B = "0x6632da9c91A959eEBf1343f8AFAbf2807414004A"


def load_logs(log_dir: Path, limit: int = 30):
    logs = []
    if not log_dir.exists():
        return logs
    for f in sorted(log_dir.glob("*.json"))[-limit:]:
        try:
            with open(f) as fp:
                logs.append(json.load(fp))
        except Exception:
            pass
    return logs


def get_perp_state(user: str) -> dict:
    import requests
    s = requests.Session()
    s.trust_env = False
    try:
        r = s.post("https://api.hyperliquid.xyz/info",
                   json={"type": "clearinghouseState", "user": user}, timeout=8).json()
    except Exception as e:
        return {"equity": 0, "avail": 0, "positions": [], "error": str(e)}
    m = r.get("marginSummary", {})
    positions = []
    for p in r.get("assetPositions", []):
        pos = p.get("position", {})
        if float(pos.get("szi", 0)) != 0:
            positions.append({
                "coin":     pos.get("coin"),
                "size":     float(pos.get("szi", 0)),
                "entry_px": float(pos.get("entryPx") or 0),
                "upnl":     float(pos.get("unrealizedPnl") or 0),
                "leverage": float((pos.get("leverage") or {}).get("value", 1)),
            })
    equity = float(m.get("accountValue", 0))
    avail  = float(m.get("marginAvailable") or 0)

    if equity == 0:
        try:
            r2 = s.post("https://api.hyperliquid.xyz/info",
                        json={"type": "spotClearinghouseState", "user": user}, timeout=8).json()
            spot_usdc = next(
                (float(b["total"]) for b in r2.get("balances", []) if b.get("coin") == "USDC"), 0
            )
            if spot_usdc > 0:
                equity = spot_usdc
                avail  = spot_usdc
        except Exception:
            pass

    return {
        "equity":    equity,
        "avail":     avail,
        "positions": positions,
    }


def build_state() -> dict:
    a = get_perp_state(USER_A)
    b = get_perp_state(USER_B)
    hl = {
        "perp_equity":    a["equity"],
        "perp_avail":     a["avail"],
        "perp_positions": a["positions"],
        "b_equity":       b["equity"],
        "b_avail":        b["avail"],
        "b_positions":    b["positions"],
        "spot_usdc":      0,
        "total_equity":   a["equity"] + b["equity"],
    }
    return {
        **hl,
        "logs_a": load_logs(LOG_A),
        "logs_b": load_logs(LOG_B),
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
    }


def main():
    output_path = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "state.json"
    state = build_state()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print(f"✅ state.json 已生成 -> {output_path}")
    print(f"   总资产: ${state['total_equity']:.2f}")
    print(f"   Agent A 日志: {len(state['logs_a'])} 条")
    print(f"   Agent B 日志: {len(state['logs_b'])} 条")


if __name__ == "__main__":
    main()
