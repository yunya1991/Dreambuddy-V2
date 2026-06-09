#!/usr/bin/env python3
"""
wiki_sync.py — 生成 Wiki 知识库自动同步内容

用法（供 lark-cli docs +update --content "$(python wiki_sync.py ...)" 调用）:
  python wiki_sync.py screen1   <session_dir>   # 市场研判追加内容
  python wiki_sync.py process_d <session_dir>   # 复盘档案追加内容
  python wiki_sync.py knowledge <session_dir>   # 知识积累更新内容

输出: Markdown 文本（stdout），供 lark-cli --content 参数读取
"""
import json
import sys
from datetime import datetime
from pathlib import Path


def screen1_entry(session_dir: str) -> str:
    base = Path(session_dir)
    sid  = base.name

    meta     = json.loads((base / "meta.json").read_text(encoding="utf-8")) if (base/"meta.json").exists() else {}
    strategy = json.loads((base / "team-a/screen1/strategy-type.json").read_text(encoding="utf-8")) \
               if (base / "team-a/screen1/strategy-type.json").exists() else {}
    wd_path  = base / "team-a/screen1/weekly-direction.md"
    wd_text  = wd_path.read_text(encoding="utf-8") if wd_path.exists() else ""

    score     = strategy.get("weighted_total", strategy.get("score", meta.get("screen1_score", 0)))
    direction = strategy.get("direction", meta.get("screen1_direction", "?"))
    clock     = strategy.get("clock_stage", meta.get("screen1_clock_stage", "?"))
    regime    = strategy.get("skill_regime", meta.get("screen1_skill_regime", "?"))
    vm        = strategy.get("position_multiplier", meta.get("position_multiplier", "?"))
    price     = meta.get("screen1_price", 0)
    valid     = strategy.get("valid_until", meta.get("valid_until", "?"))
    date_str  = sid[:8]
    try:
        d = datetime.strptime(date_str, "%Y%m%d")
        date_fmt = d.strftime("%Y-%m-%d")
    except Exception:
        date_fmt = date_str

    gh_url = f"https://github.com/yunya1991/Dreambuddy-V2/tree/main/6-TRADING/sessions/{sid}"

    # 提取七维度表格
    dim_lines = []
    dim_map = [
        ("A_tech_detector",    "技术检测器", "40%"),
        ("B_halving_cycle",    "减半周期",   "15%"),
        ("C_miner_economics",  "矿工经济",   "15%"),
        ("D_onchain_valuation","链上估值",   "15%"),
        ("E_macro_finance",    "宏观金融",   "10%"),
        ("F_cross_market",     "跨市场",     "5%"),
    ]
    cb = strategy.get("confidence_breakdown", {})
    for key, name, weight in dim_map:
        if key in cb:
            d = cb[key]
            sig = d.get("signal", "?")
            s   = d.get("score", 0)
            sig_emoji = {"BULL": "🟢", "BEAR": "🔴", "NEUTRAL": "🟡"}.get(sig, "⚪")
            dim_lines.append(f"| {sig_emoji} **{name}**({weight}) | {s:+d} | {sig} |")

    dir_emoji = {"LONG": "📈", "SHORT": "📉"}.get(str(direction).upper(), "")

    content = f"""
---

## {date_fmt} — {sid}

**方向** {dir_emoji} `{direction}`　**总分** `{score}/100`　**象限** `{clock}`　**制度** `{regime}`
**价格** `${price:,}`　**仓位乘数** `{vm}`　**有效至** `{valid}`

| 维度 | 得分 | 信号 |
|------|------|------|
{"".join(dim_lines)}

[完整报告 →]({gh_url})
"""
    return content.strip()


def process_d_entry(session_dir: str) -> str:
    base = Path(session_dir)
    sid  = base.name
    date_str = sid[:8]
    try:
        d = datetime.strptime(date_str, "%Y%m%d")
        date_fmt = d.strftime("%Y-%m-%d")
    except Exception:
        date_fmt = date_str

    a8_path = base / "review/a8-reflection.json"
    a8 = json.loads(a8_path.read_text(encoding="utf-8")) if a8_path.exists() else {}

    score    = a8.get("retrospective_score", "—")
    bias     = a8.get("bias_audit", {})
    findings = a8.get("key_findings", [])
    proposals= a8.get("improvement_suggestions", [])

    findings_txt  = "\n".join(f"- {f}" for f in findings[:3]) if findings else "（待写入）"
    proposals_txt = "\n".join(f"- {p}" for p in proposals[:3]) if proposals else "（待写入）"

    gh_url = f"https://github.com/yunya1991/Dreambuddy-V2/tree/main/6-TRADING/sessions/{sid}"

    content = f"""
---

## {date_fmt} ProcessD — {sid}

**A8 得分**: `{score}/100`　**偏见审计**: {bias.get("summary", "—")}

**关键发现**:
{findings_txt}

**改进提案**:
{proposals_txt}

[完整复盘 →]({gh_url}/review/)
"""
    return content.strip()


def knowledge_update(session_dir: str) -> str:
    """生成知识积累更新内容（Strategy Scores 新增一行）"""
    base = Path(session_dir)
    sid  = base.name

    meta     = json.loads((base / "meta.json").read_text(encoding="utf-8")) if (base/"meta.json").exists() else {}
    strategy = json.loads((base / "team-a/screen1/strategy-type.json").read_text(encoding="utf-8")) \
               if (base / "team-a/screen1/strategy-type.json").exists() else {}
    a9       = {}
    for p in ["a9-exit.json", "team-a/screen3/a9-exit.json"]:
        if (base / p).exists():
            a9 = json.loads((base / p).read_text(encoding="utf-8"))
            break

    direction = strategy.get("direction", meta.get("screen1_direction", "?"))
    score     = strategy.get("weighted_total", meta.get("screen1_score", 0))
    gate_c    = meta.get("gate_c_result", "—")
    pnl       = a9.get("realized_pnl", "—")
    conclusion= "盈利" if float(pnl or 0) > 0 else ("亏损" if float(pnl or 0) < 0 else "—")

    content = f"\n| {sid} | {direction} | {score} | {gate_c} | {pnl} | {conclusion} |"
    return content.strip()


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    if len(sys.argv) < 3:
        print("Usage: wiki_sync.py <screen1|process_d|knowledge> <session_dir>")
        sys.exit(1)

    cmd = sys.argv[1]
    session_path = sys.argv[2]

    if cmd == "screen1":
        print(screen1_entry(session_path))
    elif cmd == "process_d":
        print(process_d_entry(session_path))
    elif cmd == "knowledge":
        print(knowledge_update(session_path))
    else:
        print(f"未知命令: {cmd}", file=sys.stderr)
        sys.exit(1)
