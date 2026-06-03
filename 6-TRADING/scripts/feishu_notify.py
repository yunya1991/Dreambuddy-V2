#!/usr/bin/env python3
"""
飞书通知推送模块 - Dreambuddy-V2 交易部门
用法:
  python feishu_notify.py screen1      <session_dir>    # 研究室 + 管理看板摘要
  python feishu_notify.py screen2      <session_dir>    # 交易台
  python feishu_notify.py execution    <session_dir>    # 交易台执行日志
  python feishu_notify.py a6_monitor   <session_dir>    # 交易台定时监控
  python feishu_notify.py a6_alert     <alert_json>     # 交易台阈值预警
  python feishu_notify.py a9           <session_dir>    # 管理看板 + 复盘室
  python feishu_notify.py escalate     <reason_json>    # 风控审批（人工介入，旧版兼容）
  python feishu_notify.py gate_c_approval <session_dir> # Gate-C 正式审批单
  python feishu_notify.py a9_approval  <session_dir>    # A9 离场正式审批单
  python feishu_notify.py review       <session_dir>    # 复盘室
  python feishu_notify.py bitable      <session_dir>    # 写入多维表格交易记录
"""
import json
import sys
import os
import requests
from datetime import datetime
from pathlib import Path

# ── 配置 ─────────────────────────────────────────────────────────────────────
FEISHU_APP_ID     = "cli_aa9442bde4b89be9"
FEISHU_APP_SECRET = "dnHO43AQ68jua7Z8XEAQ3gJwNoMeYQ70"

# 多维表格
BITABLE_APP_TOKEN = "CMlnbvAKYafUL0sxLpFcxNfVnoc"
BITABLE_TABLE_ID  = "tblSDdfk2sbBAVsr"  # Trading Episodes

# 正式审批定义 Code
APPROVAL_CODES = {
    "gate_c": "3901A0B3-5E7F-4A2F-A76E-74A5752BFD1F",  # Gate-C 入场审批
    "a9":     "1D4CB111-9E67-4430-AA05-3CD1C262E174",  # A9 离场审批
}
APPROVAL_USER_ID = "f9g91eae"  # 审批人 user_id（审批 API 用 user_id 不是 open_id）

# 交易部门五群组
CHAT_IDS = {
    "research":    "oc_36c575b6f39a8df3dd75057a96685a21",  # 交易部-研究室
    "trading":     "oc_36c8543cea823b7546fcaad55d111f9f",  # 交易部-交易台
    "management":  "oc_9cf9f141613b4e6a0f34651843cf8b9b",  # 交易部-管理看板
    "review":      "oc_8868a5c84f3d8427afa9ed1a9ad7fb76",  # 交易部-复盘室
    "risk":        "oc_20fcedf0c35035568ea8fa947380f75d",  # 交易部-风控审批
}

# ESCALATE_TO_HUMAN 强制触发条件（可在此调整阈值）
ESCALATE_RULES = {
    "single_loss_usdt":    500,    # 单笔浮亏超过 X USDT
    "consecutive_sl":      3,      # 连续止损次数
    "quadrant_switch":     True,   # 象限切换时强制上报
}

TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
MSG_URL   = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"

# ── 工具函数 ──────────────────────────────────────────────────────────────────
SIGNAL_EMOJI = {"BULL": "🟢", "BEAR": "🔴", "NEUTRAL": "🟡"}
DIR_EMOJI    = {"LONG": "📈", "SHORT": "📉"}
ALERT_COLOR  = {"info": "blue", "warning": "orange", "critical": "red"}

def get_token() -> str:
    resp = requests.post(TOKEN_URL, json={
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET,
    }, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data["code"] != 0:
        raise RuntimeError(f"token error: {data}")
    return data["tenant_access_token"]


def send_message(chat_id: str, msg_type: str, content: dict) -> dict:
    token = get_token()
    resp = requests.post(MSG_URL, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }, json={
        "receive_id": chat_id,
        "msg_type":   msg_type,
        "content":    json.dumps(content, ensure_ascii=False),
    }, timeout=10)
    resp.raise_for_status()
    result = resp.json()
    if result["code"] != 0:
        raise RuntimeError(f"send error: {result}")
    return result


def send_to(channel: str, msg_type: str, content: dict) -> str:
    chat_id = CHAT_IDS[channel]
    result  = send_message(chat_id, msg_type, content)
    msg_id  = result["data"]["message_id"]
    print(f"[OK] -> #{channel}: {msg_id}")
    return msg_id


def github_url(session_id: str) -> str:
    return (f"https://github.com/yunya1991/Dreambuddy-V2/tree/main/"
            f"6-TRADING/sessions/{session_id}")


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def hr() -> dict:
    return {"tag": "hr"}


def md(text: str) -> dict:
    return {"tag": "markdown", "content": text}


def card(title: str, color: str, elements: list) -> dict:
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": color,
        },
        "body": {"elements": elements},
    }


# ── Screen1：研究室（完整）+ 管理看板（摘要）────────────────────────────────
def notify_screen1(session_dir: str):
    base     = Path(session_dir)
    meta     = json.loads((base / "meta.json").read_text(encoding="utf-8"))
    strategy = json.loads((base / "team-a/screen1/strategy-type.json").read_text(encoding="utf-8"))
    wd_path  = base / "team-a/screen1/weekly-direction.md"
    wd_text  = wd_path.read_text(encoding="utf-8") if wd_path.exists() else ""

    sid       = meta.get("session_id", "UNKNOWN")
    score     = strategy.get("weighted_total", strategy.get("score", 0))
    direction = strategy.get("direction", "?")
    regime    = strategy.get("skill_regime", "?")
    clock     = strategy.get("clock_stage", "?")
    price     = meta.get("screen1_price", 0)
    valid     = strategy.get("valid_until", meta.get("valid_until", "?"))
    vm        = strategy.get("position_multiplier", meta.get("position_multiplier", "?"))
    alloc     = strategy.get("allocation", {})
    alloc_txt = "  ".join(f"{k} {v}" for k, v in alloc.items()) if alloc else "—"
    color     = "red" if direction == "SHORT" else "green"
    de        = DIR_EMOJI.get(direction, "")

    # 七维度行
    cb = strategy.get("confidence_breakdown", {})
    dim_map = [
        ("A_tech_detector",    "技术检测器", "40%"),
        ("B_halving_cycle",    "减半周期",   "15%"),
        ("C_miner_economics",  "矿工经济",   "15%"),
        ("D_onchain_valuation","链上估值",   "15%"),
        ("E_macro_finance",    "宏观金融",   "10%"),
        ("F_cross_market",     "跨市场",     "5%"),
    ]
    dim_lines = []
    for key, name, weight in dim_map:
        if key in cb:
            d   = cb[key]
            sig = d.get("signal", "?")
            s   = d.get("score", 0)
            dim_lines.append(
                f"{SIGNAL_EMOJI.get(sig,'⚪')} **{name}**({weight})  `{s:+d}`  "
                f"_{d.get('key','')}_"
            )

    # A1/A2/A3 摘要段（从 weekly-direction.md 提取）
    a_sections = {}
    current = None
    for line in wd_text.splitlines():
        if line.startswith("## A1"):
            current = "A1"
            a_sections["A1"] = []
        elif line.startswith("## A2"):
            current = "A2"
            a_sections["A2"] = []
        elif line.startswith("## A3"):
            current = "A3"
            a_sections["A3"] = []
        elif line.startswith("## ") and current:
            current = None
        elif current:
            a_sections[current].append(line)

    a_text = ""
    for k in ["A1", "A2", "A3"]:
        if k in a_sections:
            body = "\n".join(a_sections[k]).strip()[:600]
            a_text += f"**{k}**\n{body}\n\n"

    # ① 研究室：完整卡片（七维度 + A1/A2/A3 + 配置）
    research_elements = [
        md(f"**方向** {de} `{direction}`　**总分** `{score}/100`　**制度** `{regime}`\n"
           f"**价格** `${price:,}`　**象限** `{clock}`　**仓位乘数** `{vm}`"),
        hr(),
        md("**七维度信号**\n" + "\n".join(dim_lines)),
        hr(),
        md(a_text.strip() or "_A1/A2/A3 内容未找到_"),
        hr(),
        md(f"**配置**  {alloc_txt}\n**有效期至** `{valid}`"),
        hr(),
        md(f"_生成: {now_str()} | [GitHub]({github_url(sid)})_"),
    ]
    send_to("research", "interactive",
            card(f"[研究室] Screen1 周线研判 — {sid}", color, research_elements))

    # ② 管理看板：仅摘要一行
    mgmt_elements = [
        md(f"**Screen1 完成** | {de} `{direction}` | 得分 `{score}` | `{clock}` | "
           f"价格 `${price:,}` | vm `{vm}` | 有效至 `{valid}`\n"
           f"[查看完整报告]({github_url(sid)})"),
    ]
    send_to("management", "interactive",
            card(f"[管理看板] Screen1 摘要 — {sid}", color, mgmt_elements))


# ── Screen2：交易台 ───────────────────────────────────────────────────────────
def notify_screen2(session_dir: str):
    base = Path(session_dir)
    meta = json.loads((base / "meta.json").read_text(encoding="utf-8"))
    sid  = meta.get("session_id", "UNKNOWN")

    presets_path = base / "team-a/screen2/daily-presets.json"
    grid_path    = base / "team-a/screen2/martingale-grid.json"
    presets = json.loads(presets_path.read_text(encoding="utf-8")) if presets_path.exists() else {}
    grid    = json.loads(grid_path.read_text(encoding="utf-8"))    if grid_path.exists()    else {}

    direction = presets.get("direction", meta.get("screen1_direction", "?"))
    entry     = presets.get("entry_price", presets.get("entry", "?"))
    tp        = presets.get("take_profit", presets.get("tp", "?"))
    sl        = presets.get("stop_loss",   presets.get("sl", "?"))
    layers    = grid.get("max_layers", presets.get("max_layers", "?"))
    interval  = grid.get("interval_pct", presets.get("interval_pct", "?"))
    de        = DIR_EMOJI.get(direction, "")
    color     = "red" if direction == "SHORT" else "green"

    elements = [
        md(f"**方向** {de} `{direction}`　**入场** `{entry}`\n"
           f"**止盈** `{tp}`　**止损** `{sl}`\n"
           f"**马丁层数** `{layers}`　**加仓间隔** `{interval}%`"),
        hr(),
        md(f"_生成: {now_str()} | [GitHub]({github_url(sid)})_"),
    ]
    send_to("trading", "interactive",
            card(f"[交易台] Screen2 日线预设 — {sid}", color, elements))


# ── A6 定时监控报告（4h）→ 交易台 ──────────────────────────────────────────
def notify_a6_monitor(session_dir: str):
    base = Path(session_dir)
    sid  = base.name

    monitor_path = base / "team-a/screen3/a6-monitor.json"
    if not monitor_path.exists():
        monitor_path = base / "a6-monitor.json"
    monitor = json.loads(monitor_path.read_text(encoding="utf-8")) if monitor_path.exists() else {}

    price     = monitor.get("current_price", "?")
    pnl       = monitor.get("unrealized_pnl", "?")
    pnl_pct   = monitor.get("pnl_pct", "?")
    funding   = monitor.get("funding_rate", "?")
    next_layer= monitor.get("next_martin_level", "?")
    status    = monitor.get("status", "NORMAL")
    color     = "orange" if status != "NORMAL" else "blue"

    elements = [
        md(f"**价格** `${price}`　**浮盈/亏** `{pnl} USDT ({pnl_pct}%)`\n"
           f"**资金费率** `{funding}`　**下一马丁层** `{next_layer}`\n"
           f"**状态** `{status}`"),
        hr(),
        md(f"_A6 定时监控 {now_str()}_"),
    ]
    send_to("trading", "interactive",
            card(f"[交易台] A6 监控报告 — {sid}", color, elements))


# ── A6 阈值预警 → 交易台（+ 必要时升级风控）────────────────────────────────
def notify_a6_alert(alert_json: str):
    alert = json.loads(alert_json) if isinstance(alert_json, str) else alert_json

    alert_type = alert.get("type", "UNKNOWN")    # MARTIN_TRIGGER / SL_WARNING / FUNDING / QUADRANT
    price      = alert.get("price", "?")
    detail     = alert.get("detail", "")
    severity   = alert.get("severity", "warning") # warning / critical
    sid        = alert.get("session_id", "?")
    loss_usdt  = alert.get("loss_usdt", 0)
    consec_sl  = alert.get("consecutive_sl", 0)
    is_quadrant= alert.get("quadrant_switch", False)
    color      = ALERT_COLOR.get(severity, "orange")

    elements = [
        md(f"**预警类型** `{alert_type}`　**价格** `${price}`\n{detail}"),
        hr(),
        md(f"_A6 预警 {now_str()}_"),
    ]
    send_to("trading", "interactive",
            card(f"[交易台] A6 预警 — {alert_type}", color, elements))

    # 判断是否需要 ESCALATE_TO_HUMAN
    reasons = []
    if loss_usdt  >= ESCALATE_RULES["single_loss_usdt"]:
        reasons.append(f"单笔浮亏 {loss_usdt} USDT >= {ESCALATE_RULES['single_loss_usdt']} USDT")
    if consec_sl  >= ESCALATE_RULES["consecutive_sl"]:
        reasons.append(f"连续止损 {consec_sl} 次 >= {ESCALATE_RULES['consecutive_sl']} 次")
    if is_quadrant and ESCALATE_RULES["quadrant_switch"]:
        reasons.append("象限切换检测到，需要重新评估战略方向")

    if reasons:
        notify_escalate({
            "session_id": sid,
            "trigger":    alert_type,
            "reasons":    reasons,
            "price":      price,
            "detail":     detail,
        })


# ── A9 离场评估 → 管理看板 + 复盘室 ─────────────────────────────────────────
def notify_a9(session_dir: str):
    base = Path(session_dir)
    sid  = base.name

    a9_path = base / "team-a/screen3/a9-exit.json"
    if not a9_path.exists():
        a9_path = base / "a9-exit.json"
    a9 = json.loads(a9_path.read_text(encoding="utf-8")) if a9_path.exists() else {}

    decision   = a9.get("decision", "?")       # EXIT / HOLD / ESCALATE_TO_HUMAN
    score      = a9.get("exit_score", "?")
    pnl        = a9.get("realized_pnl", "?")
    pnl_pct    = a9.get("pnl_pct", "?")
    reason     = a9.get("reason", "")
    color_map  = {"EXIT": "green", "HOLD": "blue", "ESCALATE_TO_HUMAN": "red"}
    color      = color_map.get(decision, "orange")

    # 管理看板摘要
    mgmt_elements = [
        md(f"**A9 离场评估** | 决策 `{decision}` | 离场分 `{score}`\n"
           f"**已实现盈亏** `{pnl} USDT ({pnl_pct}%)`\n{reason}"),
        hr(),
        md(f"_评估时间: {now_str()} | [GitHub]({github_url(sid)})_"),
    ]
    send_to("management", "interactive",
            card(f"[管理看板] A9 离场评估 — {sid}", color, mgmt_elements))

    # 复盘室：写入完整分析
    review_elements = [
        md(f"**决策** `{decision}`　**离场分** `{score}`\n"
           f"**已实现盈亏** `{pnl} USDT ({pnl_pct}%)`"),
        hr(),
        md(reason or "_A9 分析详情未提供_"),
        hr(),
        md(f"_离场时间: {now_str()} | [GitHub]({github_url(sid)})_"),
    ]
    send_to("review", "interactive",
            card(f"[复盘室] A9 离场复盘 — {sid}", color, review_elements))

    # 若需要人工介入
    if decision == "ESCALATE_TO_HUMAN":
        notify_escalate({
            "session_id": sid,
            "trigger":    "A9_ESCALATE",
            "reasons":    [reason],
            "exit_score": score,
        })


# ── ProcessD 复盘 → 复盘室 ───────────────────────────────────────────────────
def notify_review(session_dir: str):
    base = Path(session_dir)
    sid  = base.name

    reflection_path = base / "review/a8-reflection.md"
    if not reflection_path.exists():
        reflection_path = base / "review/a8-reflection.json"
    text = reflection_path.read_text(encoding="utf-8")[:1500] if reflection_path.exists() else "_复盘文件未找到_"

    elements = [
        md(text),
        hr(),
        md(f"_ProcessD 复盘 {now_str()} | [GitHub]({github_url(sid)})_"),
    ]
    send_to("review", "interactive",
            card(f"[复盘室] ProcessD 复盘 — {sid}", "blue", elements))


# ── Screen3 执行日志（ENTER / SKIP）→ 交易台 ─────────────────────────────────
def notify_execution(session_dir: str):
    base = Path(session_dir)
    sid  = base.name

    episode_path = base / "team-b/episode.json"
    gatec_path   = base / "team-b/gate-c/pretrade-check.json"
    episode = json.loads(episode_path.read_text(encoding="utf-8")) if episode_path.exists() else {}
    gatec   = json.loads(gatec_path.read_text(encoding="utf-8"))   if gatec_path.exists()   else {}

    outcome       = episode.get("outcome", episode.get("gate_c_result", "UNKNOWN"))  # ENTER / SKIP
    direction     = episode.get("direction", "?")
    entry_price   = episode.get("entry_price", episode.get("btc_price", "?"))
    signal_score  = episode.get("composite_confidence", episode.get("signal_score", "?"))
    a7_score      = episode.get("a7_gate_score", "?")
    skip_reason   = episode.get("skip_reason", episode.get("reason", ""))
    consec_skip   = episode.get("consecutive_skip_count", 0)
    ach_summary   = gatec.get("ach_summary", "")

    is_enter  = str(outcome).upper() in ("ENTER", "PASS")
    color     = "green" if is_enter else "blue"
    de        = DIR_EMOJI.get(str(direction).upper(), "")
    label     = "入场" if is_enter else "跳过"

    lines = [f"**Gate C** `{outcome}`　**信号得分** `{signal_score}`　**A7** `{a7_score}`"]
    if is_enter:
        lines.append(f"**入场价** `{entry_price}`　**方向** {de} `{direction}`")
    else:
        lines.append(f"**原因** {skip_reason}　**连续SKIP** `{consec_skip}` 次")
    if ach_summary:
        lines.append(f"**ACH** {ach_summary}")

    elements = [
        md("\n".join(lines)),
        hr(),
        md(f"_执行时间: {now_str()} | [GitHub]({github_url(sid)})_"),
    ]
    send_to("trading", "interactive",
            card(f"[交易台] Screen3 {label} — {sid}", color, elements))


# ── 任务追踪 ─────────────────────────────────────────────────────────────────
TASK_STATE_FILE = Path(__file__).parent.parent / "task_state.json"

def _load_task_state() -> dict:
    return json.loads(TASK_STATE_FILE.read_text(encoding="utf-8")) if TASK_STATE_FILE.exists() else {}

def _save_task_state(state: dict):
    TASK_STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

def task_create(summary: str, description: str, due_days: int = 7) -> str:
    """创建飞书任务，返回 task_guid"""
    import time as _t
    due_ms = str(int((_t.time() + due_days * 86400) * 1000))
    token = get_token()
    r = requests.post(
        "https://open.feishu.cn/open-apis/task/v2/tasks",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "summary": summary,
            "description": description,
            "due": {"timestamp": due_ms},
            "origin": {"platform_i18n_name": {"zh_cn": "Dreambuddy Trading"}},
        }
    ).json()
    if r.get("code") != 0:
        raise RuntimeError(f"Task create error: {r.get('msg')}")
    guid = r["data"]["task"]["guid"]
    print(f"[OK] Task created: {guid} | {summary[:50]}")
    return guid


def task_complete(guid: str):
    """完成飞书任务"""
    token = get_token()
    r = requests.patch(
        f"https://open.feishu.cn/open-apis/task/v2/tasks/{guid}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"task": {"completed_at": str(int(__import__("time").time() * 1000))},
              "update_fields": ["completed_at"]}
    ).json()
    if r.get("code") != 0:
        raise RuntimeError(f"Task complete error: {r.get('msg')}")
    print(f"[OK] Task completed: {guid}")


def notify_task(event: str, session_dir: str):
    """
    event:
      screen1_done   → 创建"本周研判"任务
      screen2_done   → 创建"日线预设"任务
      enter          → 创建"持仓监控"任务
      skip           → 完成"日线预设"任务（未入场）
      exit           → 完成"持仓监控"任务
      process_d_done → 创建"复盘待审阅"任务
    """
    base = Path(session_dir)
    sid  = base.name
    state = _load_task_state()

    if event == "screen1_done":
        meta     = json.loads((base / "meta.json").read_text(encoding="utf-8"))
        strategy = json.loads((base / "team-a/screen1/strategy-type.json").read_text(encoding="utf-8")) if (base / "team-a/screen1/strategy-type.json").exists() else {}
        score    = strategy.get("weighted_total", meta.get("screen1_score", 0))
        direction = strategy.get("direction", meta.get("screen1_direction", "?"))
        valid    = strategy.get("valid_until", meta.get("valid_until", "?"))
        guid = task_create(
            f"[Screen1] 本周研判 — {direction} {score}分",
            f"Session: {sid}\n得分: {score} | 方向: {direction} | 有效至: {valid}\n{github_url(sid)}",
            due_days=7
        )
        state["screen1_task"] = guid
        _save_task_state(state)

    elif event == "screen2_done":
        guid = task_create(
            f"[Screen2] 日线预设 — {sid}",
            f"Session: {sid}\n日线预设已生成，等待 Screen3 入场评估。\n{github_url(sid)}",
            due_days=1
        )
        state["screen2_task"] = guid
        _save_task_state(state)

    elif event == "enter":
        episode = json.loads((base / "team-b/episode.json").read_text(encoding="utf-8")) if (base / "team-b/episode.json").exists() else {}
        entry_price = episode.get("entry_price", episode.get("btc_price", "?"))
        direction   = episode.get("direction", "?")
        # 完成 screen2 任务
        if state.get("screen2_task"):
            try: task_complete(state.pop("screen2_task"))
            except Exception as e: print(f"[WARN] screen2 task: {e}")
        # 创建持仓监控任务
        guid = task_create(
            f"[持仓] 监控中 — {direction} @{entry_price}",
            f"Session: {sid}\n入场价: {entry_price} | 方向: {direction}\nA6 每4h自动监控，等待 A9 离场信号。\n{github_url(sid)}",
            due_days=30
        )
        state["position_task"] = guid
        _save_task_state(state)

    elif event == "skip":
        if state.get("screen2_task"):
            try: task_complete(state.pop("screen2_task"))
            except Exception as e: print(f"[WARN] screen2 task: {e}")
            _save_task_state(state)
        print(f"[OK] Skip — screen2 task closed")

    elif event == "exit":
        a9 = {}
        for p in ["a9-exit.json", "team-a/screen3/a9-exit.json"]:
            if (base / p).exists():
                a9 = json.loads((base / p).read_text(encoding="utf-8"))
                break
        pnl = a9.get("realized_pnl", 0)
        if state.get("position_task"):
            try: task_complete(state.pop("position_task"))
            except Exception as e: print(f"[WARN] position task: {e}")
        # 创建复盘任务
        guid = task_create(
            f"[复盘] 本次交易待复盘 — PnL {pnl:+.1f} USDT",
            f"Session: {sid}\n已实现盈亏: {pnl} USDT\n请查看 ProcessD 复盘报告。\n{github_url(sid)}",
            due_days=3
        )
        state["review_task"] = guid
        _save_task_state(state)

    elif event == "process_d_done":
        if state.get("review_task"):
            try: task_complete(state.pop("review_task"))
            except Exception as e: print(f"[WARN] review task: {e}")
        # 完成 screen1 任务
        if state.get("screen1_task"):
            try: task_complete(state.pop("screen1_task"))
            except Exception as e: print(f"[WARN] screen1 task: {e}")
        _save_task_state(state)
        print(f"[OK] ProcessD tasks closed")

    else:
        raise ValueError(f"Unknown task event: {event}")


# ── 多维表格：写入交易记录 ────────────────────────────────────────────────────
def bitable_upsert(session_dir: str) -> str:
    """
    从 session 目录读取所有可用数据，写入/更新多维表格一行。
    返回 record_id。支持部分字段（缺失字段跳过不报错）。
    """
    import time as _time
    base = Path(session_dir)
    sid  = base.name

    # ── 读取各数据源（缺失则用空值）────────────────────────────────────────
    def load(path):
        p = base / path
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    meta     = load("meta.json")
    strategy = load("team-a/screen1/strategy-type.json")
    episode  = load("team-b/episode.json")
    gatec    = load("team-b/gate-c/pretrade-check.json")
    a9       = load("a9-exit.json") or load("team-a/screen3/a9-exit.json")
    a8       = load("review/a8-reflection.json")

    # ── 解析字段 ─────────────────────────────────────────────────────────────
    direction   = (strategy.get("direction") or meta.get("screen1_direction") or "")
    gate_result = (episode.get("outcome") or gatec.get("gate_c_result") or "SKIP")
    clock       = (strategy.get("clock_stage") or meta.get("screen1_clock_stage") or "")
    regime      = (strategy.get("skill_regime") or meta.get("screen1_skill_regime") or "")
    s1_score    = int(strategy.get("weighted_total") or strategy.get("score") or meta.get("screen1_score") or 0)
    entry_price = float(episode.get("entry_price") or episode.get("btc_price") or meta.get("screen1_price") or 0)
    signal_pct  = float(episode.get("composite_confidence") or episode.get("signal_score") or 0)
    if signal_pct <= 1:
        signal_pct = round(signal_pct * 100, 1)
    martin_layers   = int(episode.get("martin_layers") or episode.get("max_layers") or 0)
    position_cap    = float(
        strategy.get("allocation", {}).get("BTC_SHORT", "0").replace("%","").strip() or
        meta.get("position_cap_usdt") or 0
    )
    exit_price  = float(a9.get("exit_price") or 0)
    realized_pnl= float(a9.get("realized_pnl") or 0)
    pnl_pct     = float(a9.get("pnl_pct") or 0)
    exit_reason = str(a9.get("reason") or a9.get("decision") or "")[:200]
    a8_score    = int(a8.get("retrospective_score") or 0)
    red_team    = bool(strategy.get("red_team_flag") or False)
    notes       = str(meta.get("notes") or "")[:300]

    # 日期：从 session_id 前缀解析 YYYYMMDD
    date_ms = 0
    try:
        date_str = sid[:8]  # "20260602"
        from datetime import datetime as _dt
        date_ms = int(_dt.strptime(date_str, "%Y%m%d").timestamp() * 1000)
    except Exception:
        date_ms = int(_time.time() * 1000)

    gh_url = f"https://github.com/yunya1991/Dreambuddy-V2/tree/main/6-TRADING/sessions/{sid}"

    fields = {
        "Session ID":        sid,
        "Date":              date_ms,
        "Direction":         direction,
        "Gate C Result":     gate_result,
        "Screen1 Score":     s1_score,
        "Exit Reason":       exit_reason,
        "Red Team Flag":     red_team,
        "Notes":             notes,
        "GitHub URL":        {"link": gh_url, "text": sid},
    }
    # 仅在有值时写入，避免 0 覆盖有效数据
    if clock:               fields["Clock Stage"]        = clock
    if regime:              fields["Skill Regime"]       = regime
    if entry_price > 0:     fields["Entry Price"]        = entry_price
    if signal_pct > 0:      fields["Signal Score"]       = signal_pct
    if martin_layers > 0:   fields["Martin Layers"]      = martin_layers
    if position_cap > 0:    fields["Position Cap USDT"]  = position_cap
    if exit_price > 0:      fields["Exit Price"]         = exit_price
    if realized_pnl != 0:   fields["Realized PnL"]       = realized_pnl
    if pnl_pct != 0:        fields["PnL Pct"]            = pnl_pct
    if a8_score > 0:        fields["A8 Score"]           = a8_score

    # episode_id 单独处理
    ep_id = episode.get("episode_id") or meta.get("hermes_session_id") or ""
    if ep_id: fields["Episode ID"] = ep_id

    # ── 检查是否已有该 Session 的记录（upsert）────────────────────────────────
    token = get_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    base_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}"

    search = requests.post(f"{base_url}/records/search", headers=headers, json={
        "filter": {"conjunction": "and", "conditions": [
            {"field_name": "Session ID", "operator": "is", "value": [sid]}
        ]},
        "page_size": 1
    }).json()

    existing = search.get("data", {}).get("items", [])
    if existing:
        record_id = existing[0]["record_id"]
        r = requests.put(f"{base_url}/records/{record_id}", headers=headers,
                         json={"fields": fields}).json()
        action = "updated"
    else:
        r = requests.post(f"{base_url}/records", headers=headers,
                          json={"fields": fields}).json()
        record_id = r.get("data", {}).get("record", {}).get("record_id", "")
        action = "created"

    if r.get("code") != 0:
        raise RuntimeError(f"Bitable write error: {r.get('msg')} | {r.get('code')}")

    print(f"[OK] Bitable {action}: {sid} -> {record_id}")
    return record_id


def notify_bitable(session_dir: str):
    """写入多维表格 + 推送确认消息到管理看板"""
    record_id = bitable_upsert(session_dir)
    sid = Path(session_dir).name
    bitable_url = f"https://icnic28nu1x5.feishu.cn/base/{BITABLE_APP_TOKEN}"
    elements = [
        md(f"交易记录已归档 `{sid}`\n[查看多维表格]({bitable_url})"),
    ]
    send_to("management", "interactive",
            card(f"[管理看板] 记录已归档 — {sid}", "blue", elements))


# ── 正式飞书审批单（Gate-C / A9）────────────────────────────────────────────
APPROVAL_URL = "https://open.feishu.cn/open-apis/approval/v4/instances"

def create_approval_instance(approval_code: str, form_values: list) -> str:
    """创建飞书正式审批实例，返回 instance_code"""
    token = get_token()
    payload = {
        "approval_code": approval_code,
        "user_id":       APPROVAL_USER_ID,
        "form":          json.dumps(form_values, ensure_ascii=False),
    }
    resp = requests.post(
        f"{APPROVAL_URL}?user_id_type=user_id",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload, timeout=15,
    ).json()
    if resp.get("code") != 0:
        raise RuntimeError(f"审批创建失败: {resp.get('msg')} | {resp.get('code')}")
    instance_code = resp["data"]["instance_code"]
    print(f"[OK] 正式审批单已创建: {instance_code}")
    return instance_code


def notify_gate_c_approval(session_dir: str) -> str:
    """Gate-C 入场：创建正式飞书审批单 + 推送通知到风控审批群"""
    base = Path(session_dir)
    sid  = base.name
    meta     = json.loads((base / "meta.json").read_text(encoding="utf-8"))
    strategy = json.loads((base / "team-a/screen1/strategy-type.json").read_text(encoding="utf-8")) \
               if (base / "team-a/screen1/strategy-type.json").exists() else {}
    episode  = json.loads((base / "team-b/episode.json").read_text(encoding="utf-8")) \
               if (base / "team-b/episode.json").exists() else {}
    gatec    = json.loads((base / "team-b/gate-c/pretrade-check.json").read_text(encoding="utf-8")) \
               if (base / "team-b/gate-c/pretrade-check.json").exists() else {}

    direction    = strategy.get("direction", meta.get("screen1_direction", "?"))
    signal_score = f"{episode.get('composite_confidence', 0)*100:.0f}% | A7: {episode.get('a7_gate_score','?')}/40"
    entry_price  = str(episode.get("entry_price", episode.get("btc_price", "?")))
    ach_summary  = gatec.get("ach_summary", "ACH分析未找到")

    form_values = [
        {"id": "session_id",   "type": "input",    "value": sid},
        {"id": "direction",    "type": "input",    "value": direction},
        {"id": "signal",       "type": "input",    "value": signal_score},
        {"id": "entry_price",  "type": "input",    "value": entry_price},
        {"id": "ach",          "type": "textarea", "value": ach_summary},
    ]

    instance_code = create_approval_instance(APPROVAL_CODES["gate_c"], form_values)

    # 同时推一条通知到风控审批群（告知有新审批单）
    approval_url = f"https://applink.feishu.cn/client/mini_program/open?appId=cli_approval&path=pages/detail/index&query=instanceCode%3D{instance_code}"
    elements = [
        md(f"**Gate-C 入场审批** | Session: `{sid}`\n"
           f"**方向** `{direction}`　**信号** `{signal_score}`　**入场价** `{entry_price}`\n"
           f"[点击处理审批]({approval_url})"),
    ]
    send_to("risk", "interactive",
            card(f"[风控审批] Gate-C 入场审批 — {sid}", "red", elements))
    return instance_code


def notify_a9_approval(session_dir: str) -> str:
    """A9 离场：创建正式飞书审批单 + 推送通知到风控审批群"""
    base = Path(session_dir)
    sid  = base.name
    a9 = {}
    for p in ["a9-exit.json", "team-a/screen3/a9-exit.json"]:
        if (base / p).exists():
            a9 = json.loads((base / p).read_text(encoding="utf-8"))
            break

    decision   = a9.get("decision", "?")
    exit_score = str(a9.get("exit_score", "?"))
    pnl        = str(a9.get("realized_pnl", "?"))
    reason     = a9.get("reason", "")[:500]

    form_values = [
        {"id": "session_id",  "type": "input",    "value": sid},
        {"id": "decision",    "type": "input",    "value": decision},
        {"id": "exit_score",  "type": "input",    "value": exit_score},
        {"id": "pnl",         "type": "input",    "value": pnl},
        {"id": "reason",      "type": "textarea", "value": reason},
    ]

    instance_code = create_approval_instance(APPROVAL_CODES["a9"], form_values)

    approval_url = f"https://applink.feishu.cn/client/mini_program/open?appId=cli_approval&path=pages/detail/index&query=instanceCode%3D{instance_code}"
    color = "green" if decision == "EXIT" else "blue"
    elements = [
        md(f"**A9 离场审批** | Session: `{sid}`\n"
           f"**决策** `{decision}`　**离场分** `{exit_score}`　**预计PnL** `{pnl} USDT`\n"
           f"[点击处理审批]({approval_url})"),
    ]
    send_to("risk", "interactive",
            card(f"[风控审批] A9 离场审批 — {sid}", color, elements))
    return instance_code


# ── ESCALATE_TO_HUMAN → 风控审批 ─────────────────────────────────────────────
def notify_escalate(data: dict):
    sid     = data.get("session_id", "?")
    trigger = data.get("trigger", "UNKNOWN")
    reasons = data.get("reasons", [])
    reason_text = "\n".join(f"- {r}" for r in reasons)

    elements = [
        md(f"**触发来源** `{trigger}`　**会话** `{sid}`\n\n"
           f"**需要人工介入原因：**\n{reason_text}"),
        hr(),
        md(f"_上报时间: {now_str()}_"),
    ]
    send_to("risk", "interactive",
            card(f"[风控审批] ESCALATE — {trigger}", "red", elements))
    print(f"[ESCALATE] -> #risk: {trigger} | {reasons}")


# ── 主入口 ────────────────────────────────────────────────────────────────────
def resolve_path(p: str) -> str:
    if os.path.isabs(p):
        return p
    base = Path(__file__).parent.parent.parent  # Dreambuddy-V2/
    return str(base / p)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    cmd  = sys.argv[1]
    arg  = sys.argv[2] if len(sys.argv) > 2 else ""

    # task 命令特殊处理：python feishu_notify.py task <event> <session_dir>
    if cmd == "task":
        if len(sys.argv) < 4:
            print("Usage: python feishu_notify.py task <event> <session_dir>")
            print("Events: screen1_done screen2_done enter skip exit process_d_done")
            sys.exit(1)
        notify_task(sys.argv[2], resolve_path(sys.argv[3]))
        sys.exit(0)

    dispatch = {
        "screen1":    lambda: notify_screen1(resolve_path(arg)),
        "screen2":    lambda: notify_screen2(resolve_path(arg)),
        "execution":  lambda: notify_execution(resolve_path(arg)),
        "a6_monitor": lambda: notify_a6_monitor(resolve_path(arg)),
        "a6_alert":   lambda: notify_a6_alert(arg),
        "a9":         lambda: notify_a9(resolve_path(arg)),
        "review":     lambda: notify_review(resolve_path(arg)),
        "escalate":   lambda: notify_escalate(json.loads(arg)),
        "bitable":          lambda: notify_bitable(resolve_path(arg)),
        "gate_c_approval":  lambda: notify_gate_c_approval(resolve_path(arg)),
        "a9_approval":      lambda: notify_a9_approval(resolve_path(arg)),
    }

    if cmd not in dispatch:
        print(f"未知类型: {cmd}")
        print(f"支持: {', '.join(dispatch.keys())}")
        sys.exit(1)

    try:
        dispatch[cmd]()
    except Exception as e:
        print(f"[ERROR] {cmd}: {e}")
        sys.exit(1)
