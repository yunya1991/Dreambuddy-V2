#!/usr/bin/env python3
"""
Dreambuddy V2 — 双边全量持仓对账（本地 ↔ 云端）

用途：切换本地进入「影子模式」前的准入门禁。逐条比对 6 个交易子系统的持仓/状态，
标注「本地独有 / 云端独有 / 双向冲突」，并给出 md5 一致性。

用法:
    python3 31-分布式计算部署/phase7/09-bilateral-reconcile.py
    python3 ... --json   # 机读输出

数据源（两侧相对路径一致，根目录不同）：
  本地根: /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
  云端根: /home/luke/dreambuddy
  1) V15   : 14-V15经典马丁策略/data/v15_state.json          (positions)
  2) 主动仓: 11-易经推理系统/.workbuddy/memory_l4/open_positions/*.json
             (strategy_source/source_tag = bcrm/bdsm/strategic/evolution)
  3) 事件驱动: 11-易经推理系统/data/event_driven_state.json
  4) 战略层: 11-易经推理系统/scripts/memory_l4/runtime/five_domain_state.json
  5) BDSM : 11-易经推理系统/.workbuddy/bdsm/bdsm_snapshot_YYYYMMDD.json
  6) 自进化: 23-四层闭环自进化交易架构/dreambuddy_evolution/gene_data/
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

LOCAL_ROOT = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2"
REMOTE_ROOT = "/home/luke/dreambuddy"
SSH_ALIAS = "dreambuddy-remote"

# 相对路径
REL_V15 = "14-V15经典马丁策略/data/v15_state.json"
REL_OPEN_DIR = "11-易经推理系统/.workbuddy/memory_l4/open_positions"
REL_EVENT = "11-易经推理系统/data/event_driven_state.json"
REL_FIVE = "11-易经推理系统/scripts/memory_l4/runtime/five_domain_state.json"
REL_BDSM_DIR = "11-易经推理系统/.workbuddy/bdsm"
REL_GENE_DIR = "23-四层闭环自进化交易架构/dreambuddy_evolution/gene_data"

# open_positions 目录中需忽略的非持仓文件前缀
SKIP_PREFIXES = ("last_close_info", "last_open_info", "okx_close_history")


# ── SSH 取数 ─────────────────────────────────────────────
def _ssh(cmd: str) -> Tuple[int, str]:
    # 注意：路径含中文，不能用 json.dumps（会转义为 \uXXXX 破坏路径）；用双引号手工转义。
    quoted = '"' + cmd.replace("\\", "\\\\").replace('"', '\\"') + '"'
    p = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", SSH_ALIAS, f"sudo -n -u luke -H bash -c {quoted}"],
        capture_output=True, text=True, timeout=60,
    )
    return p.returncode, (p.stdout if p.returncode == 0 else p.stderr)


def remote_cat(rel: str) -> Optional[str]:
    rc, out = _ssh(f"cat '{REMOTE_ROOT}/{rel}' 2>/dev/null")
    return out if rc == 0 and out.strip() else None


def remote_md5(rel: str) -> Optional[str]:
    # 不用 awk '$1'（会被远端登录 shell 展开）；直接取 md5sum 输出首列。
    rc, out = _ssh(f"md5sum '{REMOTE_ROOT}/{rel}' 2>/dev/null")
    if rc != 0 or not out.strip():
        return None
    return out.split()[0]


def remote_list(rel_dir: str) -> List[str]:
    rc, out = _ssh(f"ls -1 '{REMOTE_ROOT}/{rel_dir}' 2>/dev/null")
    return [l.strip() for l in out.splitlines() if l.strip()] if rc == 0 else []


def local_md5(rel: str) -> Optional[str]:
    p = Path(LOCAL_ROOT) / rel
    if not p.exists():
        return None
    return hashlib.md5(p.read_bytes()).hexdigest()


def load_json(text: Optional[str]) -> Optional[dict]:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


# ── 持仓归一化 ───────────────────────────────────────────
def norm(coin, direction, entry, size=None, conf=None, src=None, tag=None, note="") -> dict:
    d = str(direction or "").upper()
    d = {"LONG": "LONG", "SHORT": "SHORT"}.get(d, d)
    return {
        "coin": str(coin or "").upper(),
        "dir": d,
        "entry": round(float(entry), 6) if entry not in (None, "") else None,
        "size": size,
        "conf": conf,
        "src": src or "",
        "tag": tag or "",
        "note": note,
    }


def positions_from_v15(state: Optional[dict]) -> Dict[str, dict]:
    out = {}
    if not state:
        return out
    for coin, p in (state.get("positions") or {}).items():
        out[coin.upper()] = norm(coin, p.get("direction"), p.get("entry_price") or p.get("open_price"),
                                 p.get("sz"), (p.get("confidence") or 0) / 100.0, "v15")
    return out


def positions_from_open_dir(files_json: Dict[str, dict]) -> Dict[Tuple[str, str], dict]:
    """key = (coin, strategy_source)"""
    out = {}
    for fn, obj in files_json.items():
        if not obj or fn.startswith(SKIP_PREFIXES):
            continue
        coin = (obj.get("coin") or fn.replace("-USDT-SWAP.json", "")).upper()
        src = obj.get("strategy_source") or obj.get("source_tag") or "unknown"
        tag = obj.get("source_tag") or ""
        key = (coin, str(src).lower())
        out[key] = norm(coin, obj.get("direction"), obj.get("entry_price"),
                        obj.get("position_qty"), obj.get("confidence"), str(src).lower(), tag)
    return out


# ── 差异裁决 ─────────────────────────────────────────────
def diff_dicts(local: Dict, cloud: Dict, keyname: str) -> List[str]:
    lines = []
    lk, ck = set(local), set(cloud)
    for k in sorted(lk - ck):
        lines.append(f"  [本地独有] {keyname}={k}  {local[k]}")
    for k in sorted(ck - lk):
        lines.append(f"  [云端独有] {keyname}={k}  {cloud[k]}")
    for k in sorted(lk & ck):
        a, b = local[k], cloud[k]
        if a["dir"] != b["dir"]:
            lines.append(f"  [双向冲突·方向] {keyname}={k} 本地={a['dir']}@{a['entry']} vs 云端={b['dir']}@{b['entry']}")
        elif a["entry"] is not None and b["entry"] is not None and abs(a["entry"] - b["entry"]) > 1e-4:
            lines.append(f"  [双向冲突·入场价] {keyname}={k} 本地={a['entry']} vs 云端={b['entry']}")
        else:
            lines.append(f"  [一致] {keyname}={k} {a['dir']}@{a['entry']}")
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    report: Dict = {"sources": {}}
    txt: List[str] = []
    W = txt.append

    W("═" * 68)
    W("双边全量持仓对账  (本地 ↔ 云端 yijing-polling-trader 体系)")
    W("═" * 68)

    # 1) V15
    l_v15 = load_json((Path(LOCAL_ROOT) / REL_V15).read_text() if (Path(LOCAL_ROOT) / REL_V15).exists() else None)
    c_v15 = load_json(remote_cat(REL_V15))
    lp, cp = positions_from_v15(l_v15), positions_from_v15(c_v15)
    W("\n[1] V15 经典马丁  (v15_state.json · positions)")
    W(f"    本地 {len(lp)} 仓 / 云端 {len(cp)} 仓")
    txt.extend(diff_dicts(lp, cp, "coin"))
    report["sources"]["v15"] = {"local": lp, "cloud": cp}

    # 2) 主动仓 open_positions
    ldir = Path(LOCAL_ROOT) / REL_OPEN_DIR
    lfiles = {f.name: load_json(f.read_text()) for f in ldir.glob("*.json")} if ldir.exists() else {}
    rnames = [n for n in remote_list(REL_OPEN_DIR) if n.endswith(".json") and not n.startswith(SKIP_PREFIXES)]
    rfiles = {n: load_json(remote_cat(f"{REL_OPEN_DIR}/{n}")) for n in rnames}
    lo, co = positions_from_open_dir(lfiles), positions_from_open_dir(rfiles)
    W("\n[2] 主动仓 open_positions  (strategy_source: bcrm/bdsm/strategic/evolution)")
    W(f"    本地 {len(lo)} 仓 / 云端 {len(co)} 仓")
    txt.extend(diff_dicts(lo, co, "(coin,src)"))
    report["sources"]["open_positions"] = {
        "local": {f"{k[0]}|{k[1]}": v for k, v in lo.items()},
        "cloud": {f"{k[0]}|{k[1]}": v for k, v in co.items()},
    }

    # 3) 事件驱动
    l_ev = load_json((Path(LOCAL_ROOT) / REL_EVENT).read_text() if (Path(LOCAL_ROOT) / REL_EVENT).exists() else None)
    c_ev = load_json(remote_cat(REL_EVENT))
    W("\n[3] 事件驱动  (event_driven_state.json)")
    for nm, ev in (("本地", l_ev), ("云端", c_ev)):
        if not ev:
            W(f"    {nm}: <缺失>")
            continue
        mc = ev.get("main_chain") or {}
        W(f"    {nm}: symbol={ev.get('symbol')} updated={ev.get('updated_at')} "
          f"d_star={mc.get('d_star')} regime={mc.get('regime')} mode={ev.get('mode')}")
    if l_ev and c_ev:
        b = [k for k in ("symbol",) if l_ev.get(k) != c_ev.get(k)]
        if (l_ev.get("main_chain") or {}).get("d_star") != (c_ev.get("main_chain") or {}).get("d_star"):
            b.append("main_chain.d_star")
        W(f"    → {'不一致: ' + ', '.join(b) if b else '一致'}")
        report["sources"]["event_driven"] = {"local": l_ev, "cloud": c_ev}

    # 4) 战略层
    l_fd = load_json((Path(LOCAL_ROOT) / REL_FIVE).read_text() if (Path(LOCAL_ROOT) / REL_FIVE).exists() else None)
    c_fd = load_json(remote_cat(REL_FIVE))
    W("\n[4] 战略层  (five_domain_state.json)")
    for nm, fd in (("本地", l_fd), ("云端", c_fd)):
        if not fd:
            W(f"    {nm}: <缺失>")
            continue
        W(f"    {nm}: war_state={fd.get('war_state')} cap={fd.get('aggregate_position_cap_pct')}")
    if l_fd and c_fd:
        b = [k for k in ("war_state", "aggregate_position_cap_pct", "direction_state") if l_fd.get(k) != c_fd.get(k)]
        W(f"    → {'不一致: ' + ', '.join(b) if b else '一致'}")
        report["sources"]["strategic"] = {"local": l_fd, "cloud": c_fd}

    # 5) BDSM 快照 md5
    W("\n[5] BDSM 快照  (bdsm_snapshot_YYYYMMDD.json · md5)")
    ldir2 = Path(LOCAL_ROOT) / REL_BDSM_DIR
    lb = sorted(ldir2.glob("bdsm_snapshot_*.json")) if ldir2.exists() else []
    rb = sorted(n for n in remote_list(REL_BDSM_DIR) if n.startswith("bdsm_snapshot_") and n.endswith(".json"))
    latest_l = lb[-1].name if lb else None
    latest_r = rb[-1] if rb else None
    W(f"    本地最新: {latest_l}  / 云端最新: {latest_r}")
    if latest_l and latest_r and latest_l == latest_r:
        lm, cm = local_md5(f"{REL_BDSM_DIR}/{latest_l}"), remote_md5(f"{REL_BDSM_DIR}/{latest_r}")
        W(f"    md5 本地={lm} 云端={cm} → {'一致' if lm == cm else '不一致'}")
    else:
        W("    → 文件名不同，快照不同步（不一致）")

    # 6) gene_data
    W("\n[6] 自进化 gene_data  (gene_data/ · md5)")
    lgene = Path(LOCAL_ROOT) / REL_GENE_DIR
    lnames = sorted(f.name for f in lgene.glob("*") if f.is_file()) if lgene.exists() else []
    rnames2 = sorted(n for n in remote_list(REL_GENE_DIR) if "." in n)
    W(f"    本地 {lnames} / 云端 {rnames2}")
    for fn in sorted(set(lnames) & set(rnames2)):
        lm, cm = local_md5(f"{REL_GENE_DIR}/{fn}"), remote_md5(f"{REL_GENE_DIR}/{fn}")
        W(f"    {fn}: md5 本地={lm} 云端={cm} → {'一致' if lm == cm else '不一致'}")

    # ── 裁决 ──
    W("\n" + "═" * 68)
    W("裁决口径：影子模式准入要求「本地 ⟂ 云端 无本地独有仓」")
    W("  · 方向冲突(如 ZEC LONG vs SHORT) → 必须以云端权威侧为准或人工裁决后再切")
    W("  · 本地独有仓 → 必须先平掉/移交，否则切影子会丢仓")
    W("═" * 68)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("\n".join(txt))


if __name__ == "__main__":
    main()
