#!/usr/bin/env python3
"""
approval_agent.py — 审批超时 AI 兜底决策

工作流:
  1. 每次创建审批单时调用 register(instance_code, session_id, approval_type)
  2. Hermes cron 每 10 分钟调用 check_pending() 检查超时
  3. 超过 TIMEOUT_MINUTES 未处理 → AI 决策 → 执行 approve/reject
  4. 推送 [AI代决] 通知到 Trading-RiskControl

用法:
  python approval_agent.py register <instance_code> <session_id> <gate_c|a9>
  python approval_agent.py check    # Hermes cron 调用
"""
import json
import sys
import os
import subprocess
import requests
from datetime import datetime, timezone
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────────────────────────────
FEISHU_APP_ID     = "cli_aa9442bde4b89be9"
FEISHU_APP_SECRET = "dnHO43AQ68jua7Z8XEAQ3gJwNoMeYQ70"
RISK_CHAT         = "oc_20fcedf0c35035568ea8fa947380f75d"
TIMEOUT_MINUTES   = 30
STATE_FILE        = Path(__file__).parent.parent / "approval_state.json"
SESSION_BASE      = Path(__file__).parent.parent / "sessions"

# Gate-C 自动批准阈值
GATE_C_AUTO_APPROVE = {
    "composite_confidence": 0.70,   # 信号置信度下限
    "a7_score_min":         32,     # A7 评分下限（满分40）
    "screen1_score_min":    55,     # Screen1 综合得分下限
    "max_price_drift_pct":  5.0,    # 价格漂移上限
}
GATE_C_AUTO_REJECT = {
    "composite_confidence": 0.60,   # 低于此值直接拒绝
    "screen1_score_min":    40,     # Screen1 低于此值拒绝
    "consecutive_skip_max": 3,      # 连续 SKIP 超过此值拒绝
}

# A9 自动批准阈值
A9_AUTO_APPROVE = {
    "exit_score_min": 65,           # 离场评分下限
}
A9_AUTO_REJECT = {
    "exit_score_min": 40,           # 低于此值保持持仓
}


# ── 工具 ──────────────────────────────────────────────────────────────────────
def get_token() -> str:
    r = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}, timeout=10
    ).json()
    return r["tenant_access_token"]


def load_state() -> dict:
    return json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def send_msg(text: str):
    """推送通知到 Trading-RiskControl"""
    token = get_token()
    requests.post(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"receive_id": RISK_CHAT, "msg_type": "text",
              "content": json.dumps({"text": text}, ensure_ascii=False)},
        timeout=10
    )


def get_approval_status(instance_code: str) -> tuple[str, str]:
    """返回 (status, task_id)"""
    token = get_token()
    r = requests.get(
        f"https://open.feishu.cn/open-apis/approval/v4/instances/{instance_code}",
        headers={"Authorization": f"Bearer {token}"},
        params={"user_id_type": "user_id"}, timeout=10
    ).json()
    data   = r.get("data", {})
    status = data.get("status", "UNKNOWN")
    tasks  = data.get("task_list", [])
    task_id = str(tasks[0].get("id", "")) if tasks else ""
    return status, task_id


def execute_approval(task_id: str, approve: bool, reason: str):
    """通过 lark-cli 执行审批同意/拒绝"""
    action = "approve" if approve else "reject"
    result = subprocess.run(
        ["lark-cli", "--profile", "dream", "approval", "tasks", action,
         "--as", "user",
         "--task-id", task_id,
         "--comment", reason],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"lark-cli approval {action} failed: {result.stderr[:200]}")
    return result.stdout


# ── Gate-C AI 决策 ────────────────────────────────────────────────────────────
def decide_gate_c(session_id: str) -> tuple[bool, str]:
    """
    读取 session 数据，返回 (approve: bool, reason: str)
    """
    base = SESSION_BASE / session_id
    episode = {}
    gatec   = {}
    meta    = {}
    strategy = {}

    for p, var_name in [
        ("team-b/episode.json",              "episode"),
        ("team-b/gate-c/pretrade-check.json","gatec"),
        ("meta.json",                        "meta"),
        ("team-a/screen1/strategy-type.json","strategy"),
    ]:
        path = base / p
        if path.exists():
            locals()[var_name]  # noqa
            if var_name == "episode":   episode  = json.loads(path.read_text(encoding="utf-8"))
            elif var_name == "gatec":   gatec    = json.loads(path.read_text(encoding="utf-8"))
            elif var_name == "meta":    meta     = json.loads(path.read_text(encoding="utf-8"))
            elif var_name == "strategy":strategy = json.loads(path.read_text(encoding="utf-8"))

    # composite_confidence: 0-1 float 或从 signal.composite_score_pct (0-100) 取
    _conf_raw    = (episode.get("composite_confidence")
                   or episode.get("signal", {}).get("composite_score_pct", 0))
    confidence   = float(_conf_raw) / 100 if float(_conf_raw or 0) > 1 else float(_conf_raw or 0)

    # a7_score: 直接字段 或从 a7_gate_score / signal.signal_score_raw 解析
    _a7 = (episode.get("a7_gate_score")
           or episode.get("signal", {}).get("a7_gate_score", 0))
    if not _a7:
        raw = episode.get("signal", {}).get("signal_score_raw", "0/40")
        try: _a7 = int(raw.split("/")[0])
        except: _a7 = 0
    a7_score = int(_a7)

    # Screen1 得分：从 strategy > meta > session state 依次尝试
    _s1 = (strategy.get("weighted_total")
           or strategy.get("score")
           or meta.get("screen1_score")
           or episode.get("signal", {}).get("screen1_score")
           or 50)  # 默认中性分，避免因数据缺失误判
    s1_score = int(_s1)
    red_team     = bool(strategy.get("red_team_flag", False))
    consec_skip  = int(episode.get("consecutive_skip_count",
                        episode.get("skip_count", 0)))
    price_drift  = abs(float(meta.get("screen2_presets", {}).get("price_drift_pct", 0)))
    ach_result   = (gatec.get("gate_c_result")
                   or episode.get("gate_result", "UNKNOWN"))

    reasons = []

    # ── 强制拒绝条件 ──
    if confidence < GATE_C_AUTO_REJECT["composite_confidence"]:
        reasons.append(f"信号置信度 {confidence:.0%} < {GATE_C_AUTO_REJECT['composite_confidence']:.0%}")
        return False, f"AI自动拒绝: {'; '.join(reasons)}"

    if s1_score < GATE_C_AUTO_REJECT["screen1_score_min"]:
        reasons.append(f"Screen1得分 {s1_score} < {GATE_C_AUTO_REJECT['screen1_score_min']}")
        return False, f"AI自动拒绝: {'; '.join(reasons)}"

    if consec_skip >= GATE_C_AUTO_REJECT["consecutive_skip_max"]:
        reasons.append(f"连续SKIP {consec_skip} 次")
        return False, f"AI自动拒绝: {'; '.join(reasons)}"

    if red_team:
        reasons.append("red_team_flag=true，信号存疑")
        return False, f"AI自动拒绝（保守策略）: {'; '.join(reasons)}"

    # ── 强制批准条件 ──
    approve_checks = [
        confidence >= GATE_C_AUTO_APPROVE["composite_confidence"],
        a7_score   >= GATE_C_AUTO_APPROVE["a7_score_min"],
        s1_score   >= GATE_C_AUTO_APPROVE["screen1_score_min"],
        price_drift <= GATE_C_AUTO_APPROVE["max_price_drift_pct"],
    ]
    if all(approve_checks):
        return True, (
            f"AI自动批准: confidence={confidence:.0%} a7={a7_score}/40 "
            f"s1={s1_score} drift={price_drift:.1f}% ACH={ach_result}"
        )

    # ── 灰色地带 → 保守拒绝 ──
    return False, (
        f"AI保守拒绝（灰色地带）: confidence={confidence:.0%} a7={a7_score}/40 "
        f"s1={s1_score}，建议人工再次确认"
    )


# ── A9 AI 决策 ────────────────────────────────────────────────────────────────
def decide_a9(session_id: str) -> tuple[bool, str]:
    """读取 A9 评估结果，返回 (approve_exit: bool, reason: str)"""
    base = SESSION_BASE / session_id
    a9 = {}
    for p in ["a9-exit.json", "team-a/screen3/a9-exit.json"]:
        if (base / p).exists():
            a9 = json.loads((base / p).read_text(encoding="utf-8"))
            break

    exit_score = int(a9.get("exit_score", 0))
    decision   = a9.get("decision", "UNKNOWN")
    pnl        = a9.get("realized_pnl", 0)
    reason_txt = a9.get("reason", "")[:200]

    if exit_score >= A9_AUTO_APPROVE["exit_score_min"] or decision == "EXIT":
        return True, f"AI自动批准离场: score={exit_score} pnl={pnl} | {reason_txt}"

    if exit_score < A9_AUTO_REJECT["exit_score_min"]:
        return False, f"AI保守保持持仓: score={exit_score} 未达离场阈值"

    # 中间区间：参考 decision 字段
    if decision == "EXIT":
        return True, f"AI遵从A9建议离场: score={exit_score}"
    return False, f"AI保守保持持仓: score={exit_score} decision={decision}"


# ── 注册审批单 ────────────────────────────────────────────────────────────────
def register(instance_code: str, session_id: str, approval_type: str):
    """创建审批时调用，记录到 approval_state.json"""
    state = load_state()
    state[instance_code] = {
        "session_id":     session_id,
        "approval_type":  approval_type,   # gate_c | a9
        "created_at":     datetime.now(timezone.utc).isoformat(),
        "status":         "PENDING",
        "decision_by":    None,
    }
    save_state(state)
    print(f"[OK] 审批单已注册: {instance_code} ({approval_type}) session={session_id}")


# ── 检查超时（Hermes cron 调用）────────────────────────────────────────────────
def check_pending():
    state = load_state()
    if not state:
        print("[check] 无待处理审批单")
        return

    now    = datetime.now(timezone.utc)
    changed = False

    for instance_code, rec in list(state.items()):
        if rec.get("status") != "PENDING":
            continue

        # 检查飞书实际状态
        actual_status, task_id = get_approval_status(instance_code)

        if actual_status in ("APPROVED", "REJECTED", "CANCELED"):
            # 人工已处理，清除记录
            rec["status"]      = actual_status
            rec["decision_by"] = "human"
            changed = True
            print(f"[check] {instance_code}: 人工已处理 → {actual_status}")
            continue

        # 检查是否超时
        created_at = datetime.fromisoformat(rec["created_at"])
        elapsed    = (now - created_at).total_seconds() / 60

        if elapsed < TIMEOUT_MINUTES:
            print(f"[check] {instance_code}: PENDING {elapsed:.0f}min / {TIMEOUT_MINUTES}min")
            continue

        # 超时 → AI 决策
        print(f"[check] {instance_code}: 超时 {elapsed:.0f}min，启动 AI 决策...")
        session_id    = rec["session_id"]
        approval_type = rec["approval_type"]

        try:
            if approval_type == "gate_c":
                approve, reason = decide_gate_c(session_id)
            elif approval_type == "a9":
                approve, reason = decide_a9(session_id)
            else:
                approve, reason = False, f"未知审批类型: {approval_type}"

            if task_id:
                execute_approval(task_id, approve, reason)
                action_str = "批准" if approve else "拒绝"
                msg = (
                    f"[AI代决] {approval_type.upper()} 审批已{action_str}\n"
                    f"Session: {session_id}\n"
                    f"原因: {reason}\n"
                    f"超时: {elapsed:.0f}分钟未响应\n"
                    f"⚠️ 可在飞书审批中心查看/覆盖此决策"
                )
                send_msg(msg)
                print(f"[AI] {instance_code}: {action_str} → {reason}")
            else:
                print(f"[WARN] {instance_code}: task_id 为空，无法执行审批")

            rec["status"]      = "APPROVED" if approve else "REJECTED"
            rec["decision_by"] = "AI"
            rec["ai_reason"]   = reason
            changed = True

        except Exception as e:
            print(f"[ERROR] AI决策失败: {instance_code}: {e}")
            send_msg(f"[AI代决失败] {instance_code}\n错误: {str(e)[:200]}\n请手动处理审批！")

    if changed:
        save_state(state)


# ── 主入口 ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"

    if cmd == "register":
        if len(sys.argv) < 5:
            print("Usage: approval_agent.py register <instance_code> <session_id> <gate_c|a9>")
            sys.exit(1)
        register(sys.argv[2], sys.argv[3], sys.argv[4])

    elif cmd == "check":
        check_pending()

    elif cmd == "decide":
        # 手动触发 AI 决策（调试用）
        if len(sys.argv) < 4:
            print("Usage: approval_agent.py decide <session_id> <gate_c|a9>")
            sys.exit(1)
        atype = sys.argv[3]
        if atype == "gate_c":
            approve, reason = decide_gate_c(sys.argv[2])
        else:
            approve, reason = decide_a9(sys.argv[2])
        print(f"决策: {'APPROVE' if approve else 'REJECT'}")
        print(f"理由: {reason}")

    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)
