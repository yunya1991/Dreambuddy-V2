#!/usr/bin/env python3
"""
approval_agent.py — 审批超时 AI 兜底决策 (v2: lark-cli)
"""
import json, sys, os, subprocess
from datetime import datetime, timezone
from pathlib import Path

# ── 配置 ──
RISK_CHAT         = "oc_20fcedf0c35035568ea8fa947380f75d"
TIMEOUT_MINUTES   = 30
STATE_FILE        = Path(__file__).parent.parent / "approval_state.json"
SESSION_BASE      = Path(__file__).parent.parent / "sessions"

LARK_CLI = ["lark-cli", "--profile", "dream"]

# Gate-C / A9 阈值（不变）
GATE_C_AUTO_APPROVE = {
    "composite_confidence": 0.70,
    "a7_score_min":         32,
    "screen1_score_min":    55,
    "max_price_drift_pct":  5.0,
}
GATE_C_AUTO_REJECT = {
    "composite_confidence": 0.60,
    "screen1_score_min":    40,
    "consecutive_skip_max": 3,
}
A9_AUTO_APPROVE = {"exit_score_min": 65}
A9_AUTO_REJECT  = {"exit_score_min": 40}


# ── 工具（lark-cli 替代手写 REST）─────────────────────────────────────────────

def load_state() -> dict:
    return json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def send_msg(text: str):
    """通过 lark-cli 推送通知到风控审批群"""
    subprocess.run(
        LARK_CLI + ["im", "message", "send",
                    "--receive-id", RISK_CHAT,
                    "--receive-id-type", "chat_id",
                    "--msg-type", "text",
                    "--content", json.dumps({"text": text}, ensure_ascii=False)],
        capture_output=True, text=True, timeout=15
    )


def get_approval_status(instance_code: str) -> tuple[str, str]:
    """通过 lark-cli 查询审批实例状态 → (status, task_id)"""
    r = subprocess.run(
        LARK_CLI + ["approval", "instances", "get",
                    "--instance-code", instance_code,
                    "--as", "user"],
        capture_output=True, text=True, timeout=15
    )
    if r.returncode != 0:
        raise RuntimeError(f"lark-cli approval instances get failed: {r.stderr[:200]}")
    data = json.loads(r.stdout).get("data", {})
    status = data.get("status", "UNKNOWN")
    tasks = data.get("task_list", [])
    task_id = str(tasks[0].get("id", "")) if tasks else ""
    return status, task_id


def execute_approval(task_id: str, approve: bool, reason: str):
    """通过 lark-cli 执行审批"""
    action = "approve" if approve else "reject"
    r = subprocess.run(
        LARK_CLI + ["approval", "tasks", action,
                    "--as", "user",
                    "--task-id", task_id,
                    "--comment", reason],
        capture_output=True, text=True, timeout=30
    )
    if r.returncode != 0:
        raise RuntimeError(f"lark-cli approval {action} failed: {r.stderr[:200]}")
    return r.stdout


# ── Gate-C / A9 AI 决策（逻辑不变）───────────────────────────────────────────

def decide_gate_c(session_id: str) -> tuple[bool, str]:
    base = SESSION_BASE / session_id
    episode  = json.loads((base / "team-b/episode.json").read_text(encoding="utf-8")) if (base / "team-b/episode.json").exists() else {}
    gatec    = json.loads((base / "team-b/gate-c/pretrade-check.json").read_text(encoding="utf-8")) if (base / "team-b/gate-c/pretrade-check.json").exists() else {}
    meta     = json.loads((base / "meta.json").read_text(encoding="utf-8")) if (base / "meta.json").exists() else {}
    strategy = json.loads((base / "team-a/screen1/strategy-type.json").read_text(encoding="utf-8")) if (base / "team-a/screen1/strategy-type.json").exists() else {}

    _conf_raw = (episode.get("composite_confidence") or episode.get("signal", {}).get("composite_score_pct", 0))
    confidence = float(_conf_raw) / 100 if float(_conf_raw or 0) > 1 else float(_conf_raw or 0)

    _a7 = (episode.get("a7_gate_score") or episode.get("signal", {}).get("a7_gate_score", 0))
    if not _a7:
        raw = episode.get("signal", {}).get("signal_score_raw", "0/40")
        try: _a7 = int(raw.split("/")[0])
        except: _a7 = 0
    a7_score = int(_a7)

    _s1 = (strategy.get("weighted_total") or strategy.get("score") or meta.get("screen1_score")
           or episode.get("signal", {}).get("screen1_score") or 50)
    s1_score = int(_s1)
    red_team     = bool(strategy.get("red_team_flag", False))
    consec_skip  = int(episode.get("consecutive_skip_count", episode.get("skip_count", 0)))
    price_drift  = abs(float(meta.get("screen2_presets", {}).get("price_drift_pct", 0)))
    ach_result   = gatec.get("gate_c_result") or episode.get("gate_result", "UNKNOWN")
    reasons = []

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
        reasons.append("red_team_flag=true")
        return False, f"AI自动拒绝（保守）: {'; '.join(reasons)}"

    approve_checks = [
        confidence >= GATE_C_AUTO_APPROVE["composite_confidence"],
        a7_score   >= GATE_C_AUTO_APPROVE["a7_score_min"],
        s1_score   >= GATE_C_AUTO_APPROVE["screen1_score_min"],
        price_drift <= GATE_C_AUTO_APPROVE["max_price_drift_pct"],
    ]
    if all(approve_checks):
        return True, f"AI自动批准: confidence={confidence:.0%} a7={a7_score}/40 s1={s1_score} drift={price_drift:.1f}%"
    return False, f"AI保守拒绝（灰色地带）: confidence={confidence:.0%} a7={a7_score}/40 s1={s1_score}"


def decide_a9(session_id: str) -> tuple[bool, str]:
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
        return False, f"AI保守保持持仓: score={exit_score}"
    if decision == "EXIT":
        return True, f"AI遵从A9建议离场: score={exit_score}"
    return False, f"AI保守保持持仓: score={exit_score} decision={decision}"


# ── 注册 + 检查 ──────────────────────────────────────────────────────────────

def register(instance_code: str, session_id: str, approval_type: str):
    state = load_state()
    state[instance_code] = {
        "session_id": session_id,
        "approval_type": approval_type,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "PENDING",
        "decision_by": None,
    }
    save_state(state)
    print(f"[OK] 审批单已注册: {instance_code} ({approval_type}) session={session_id}")


def check_pending():
    state = load_state()
    if not state:
        print("[check] 无待处理审批单")
        return

    now = datetime.now(timezone.utc)
    changed = False

    for instance_code, rec in list(state.items()):
        if rec.get("status") != "PENDING":
            continue

        actual_status, task_id = get_approval_status(instance_code)

        if actual_status in ("APPROVED", "REJECTED", "CANCELED"):
            rec["status"] = actual_status
            rec["decision_by"] = "human"
            changed = True
            print(f"[check] {instance_code}: 人工已处理 → {actual_status}")
            continue

        created_at = datetime.fromisoformat(rec["created_at"])
        elapsed = (now - created_at).total_seconds() / 60
        if elapsed < TIMEOUT_MINUTES:
            print(f"[check] {instance_code}: PENDING {elapsed:.0f}min / {TIMEOUT_MINUTES}min")
            continue

        print(f"[check] {instance_code}: 超时 {elapsed:.0f}min，AI 决策中...")
        session_id = rec["session_id"]
        approval_type = rec["approval_type"]

        try:
            approve, reason = (decide_gate_c(session_id) if approval_type == "gate_c"
                               else decide_a9(session_id))

            if task_id:
                execute_approval(task_id, approve, reason)
                action_str = "批准" if approve else "拒绝"
                msg = (f"[AI代决] {approval_type.upper()} 审批已{action_str}\n"
                       f"Session: {session_id}\n原因: {reason}\n"
                       f"超时: {elapsed:.0f}分钟\n⚠️ 可在飞书审批中心覆盖")
                send_msg(msg)
                print(f"[AI] {instance_code}: {action_str} → {reason}")
            else:
                print(f"[WARN] {instance_code}: task_id 为空，无法执行审批")

            rec["status"] = "APPROVED" if approve else "REJECTED"
            rec["decision_by"] = "AI"
            rec["ai_reason"] = reason
            changed = True

        except Exception as e:
            print(f"[ERROR] AI决策失败: {instance_code}: {e}")
            send_msg(f"[AI代决失败] {instance_code}\n错误: {str(e)[:200]}")

    if changed:
        save_state(state)


# ── 主入口 ──
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
        if len(sys.argv) < 4:
            print("Usage: approval_agent.py decide <session_id> <gate_c|a9>")
            sys.exit(1)
        atype = sys.argv[3]
        approve, reason = decide_gate_c(sys.argv[2]) if atype == "gate_c" else decide_a9(sys.argv[2])
        print(f"决策: {'APPROVE' if approve else 'REJECT'}")
        print(f"理由: {reason}")

    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)
