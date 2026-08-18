#!/usr/bin/env python3
"""
approval_agent.py — 审批超时 AI 兜底决策 (v3: 四类门禁 + lark REST)

v3 分类门禁（2026-06-15 规范，2026-08-14 重修复——8/10 归档恢复曾把本脚本回退为 v2）：
  - governance        → 永不自动，等人（仅打印 [GOVERNANCE]，提醒由 cron agent 推送）
  - trading_emergency → 超时 5min 自动批准（A6 触发）
  - trading           → 永不自动，等人（仅打印 [TRADING]，提醒由 cron agent 推送）
  - gate_c / a9       → 超时 30min AI 评分决策
回归测试: cd 6-TRADING && python3 scripts/test_approval_gates.py (42 cases)
"""
import json, sys, os, subprocess
from datetime import datetime, timezone
from pathlib import Path

# ── 配置 ──
RISK_CHAT         = "oc_20fcedf0c35035568ea8fa947380f75d"
TIMEOUT_MINUTES   = 30
EMERGENCY_TIMEOUT_MINUTES = 5
STATE_FILE        = Path(__file__).parent.parent / "approval_state.json"
SESSION_BASE      = Path(__file__).parent.parent / "sessions"

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

# ── 四类门禁：模板 → 类别映射 ────────────────────────────────────────────────
GOVERNANCE_TEMPLATES = {
    "2F40FE12-255E-4FD4-AAD7-FD36C45FEA66": "索引系统审批",
    "E6175C65-C112-473A-A39B-0143F4812B62": "治理系统审批V2",
}
TRADING_TEMPLATES = {
    "096DC318-681B-478A-90CC-BD9701FC732C": "交易进化审批",
}
CATEGORY_LABELS = {
    "gate_c":            "交易入场(AI评分)",
    "a9":                "交易离场(AI评分)",
    "trading_emergency": "交易紧急审批(A6触发)",
    "trading":           "交易审批",
}


def resolve_category(approval_type: str, template_code: str, is_emergency: bool = False) -> tuple:
    """(approval_type, template_code, is_emergency) -> (category, label)。
    未知类型默认归入 trading（等人，最安全——即使误分类也不会意外自动批准）。"""
    if approval_type == "gate_c":
        return "gate_c", CATEGORY_LABELS["gate_c"]
    if approval_type == "a9":
        return "a9", CATEGORY_LABELS["a9"]
    if approval_type == "governance" or template_code in GOVERNANCE_TEMPLATES:
        name = GOVERNANCE_TEMPLATES.get(template_code, "治理审批")
        return "governance", f"治理审批({name})"
    if is_emergency or approval_type == "trading_emergency":
        return "trading_emergency", CATEGORY_LABELS["trading_emergency"]
    return "trading", CATEGORY_LABELS["trading"]


def resolve_record_category(rec: dict) -> str:
    """已注册记录的类别解析：已有 category 字段优先；旧条目向后兼容默认 trading。"""
    if not isinstance(rec, dict):
        return "trading"
    cat = rec.get("category")
    if cat:
        return cat
    return resolve_category(
        rec.get("approval_type", ""),
        rec.get("template_code", ""),
        bool(rec.get("is_emergency", False)),
    )[0]


# ── 工具（REST）──────────────────────────────────────────────────────────────

def load_state() -> dict:
    return json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def send_msg(text: str):
    """REST API 推送通知到风控审批群"""
    import requests as _r
    token = _get_feishu_token()
    _r.post(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"receive_id": RISK_CHAT, "msg_type": "text",
              "content": json.dumps({"text": text}, ensure_ascii=False)},
        timeout=10
    )


def _get_feishu_token() -> str:
    """获取飞书 tenant_access_token（用于审批 REST API）"""
    import requests as _r
    env_path = os.path.expanduser("~/.hermes/.env")
    env_vars = {}
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env_vars[k.strip()] = v.strip()
    resp = _r.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": env_vars["FEISHU_APP_ID"], "app_secret": env_vars["FEISHU_APP_SECRET"]},
        timeout=10
    ).json()
    return resp["tenant_access_token"]


def get_approval_status(instance_code: str) -> tuple:
    """REST API 查询审批实例状态 → (status, task_id)。
    PROP-* 等本地跟踪记录不是飞书实例，返回 ("UNKNOWN", "")，正常穿透。"""
    import requests as _r
    token = _get_feishu_token()
    r = _r.get(
        f"https://open.feishu.cn/open-apis/approval/v4/instances/{instance_code}",
        headers={"Authorization": f"Bearer {token}"},
        params={"user_id_type": "user_id"}, timeout=10
    ).json()
    data = r.get("data", {})
    status = data.get("status", "UNKNOWN")
    tasks = data.get("task_list", [])
    task_id = str(tasks[0].get("id", "")) if tasks else ""
    return status, task_id


def execute_approval(instance_code: str, task_id: str, approve: bool, reason: str):
    """REST API 执行审批 approve/reject（自动尝试 user_id 和 open_id）"""
    import requests as _r
    token = _get_feishu_token()
    action = "approve" if approve else "reject"
    url = f"https://open.feishu.cn/open-apis/approval/v4/instances/{instance_code}/tasks/{task_id}/{action}"

    # Try user_id first (production), fallback to open_id
    for id_type, id_val in [("user_id", "f9g91eae"), ("open_id", "ou_a7862ec46b0eeb32073f676439d8d9fe")]:
        r = _r.post(url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={f"{id_type}_type": id_type, id_type: id_val, "comment": reason},
            timeout=15
        )
        try:
            data = r.json()
        except:
            continue
        if data.get("code") == 0:
            return data
    raise RuntimeError(f"approval {action} failed with both identity types")


# ── Gate-C / A9 AI 决策（逻辑不变）───────────────────────────────────────────

def decide_gate_c(session_id: str) -> tuple:
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


def decide_a9(session_id: str) -> tuple:
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

def register(instance_code: str, session_id: str, approval_type: str,
             template_code: str = "", is_emergency: bool = False):
    category, label = resolve_category(approval_type, template_code, is_emergency)
    state = load_state()
    state[instance_code] = {
        "session_id": session_id,
        "approval_type": approval_type,
        "template_code": template_code,
        "is_emergency": is_emergency,
        "category": category,
        "category_label": label,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "PENDING",
        "decision_by": None,
    }
    save_state(state)
    print(f"[OK] 审批单已注册: {instance_code} ({category}|{label}) session={session_id}")


def check_pending():
    state = load_state()
    if not state:
        print("[check] 无待处理审批单")
        return

    now = datetime.now(timezone.utc)
    changed = False

    for instance_code, rec in list(state.items()):
        if not isinstance(rec, dict):
            continue  # _note/_mechanisms 等元数据字段防御
        if rec.get("status") != "PENDING":
            continue

        category = resolve_record_category(rec)

        # 实时状态核验：回查飞书是否已人工处理（PROP-* 本地记录返回 UNKNOWN，正常穿透）
        try:
            actual_status, task_id = get_approval_status(instance_code)
        except Exception:
            actual_status, task_id = "UNKNOWN", ""

        if actual_status in ("APPROVED", "REJECTED", "CANCELED"):
            rec["status"] = actual_status
            rec["decision_by"] = "human"
            changed = True
            print(f"[check] {instance_code}: 人工已处理 → {actual_status}")
            continue

        created_at = datetime.fromisoformat(rec["created_at"])
        elapsed = (now - created_at).total_seconds() / 60

        # ── 类别分流 ──
        if category == "governance":
            print(f"[GOVERNANCE] {instance_code}: 治理审批→需人工处理 (PENDING {elapsed:.0f}min, 不自动)")
            continue
        if category == "trading":
            print(f"[TRADING] {instance_code}: 交易非紧急审批→需人工处理 (PENDING {elapsed:.0f}min, 不自动)")
            continue

        if category == "trading_emergency":
            if elapsed < EMERGENCY_TIMEOUT_MINUTES:
                print(f"[EMERGENCY] {instance_code}: PENDING {elapsed:.0f}min / {EMERGENCY_TIMEOUT_MINUTES}min (超时自动批准)")
                continue
            approve, reason = True, "AI自动批准（A6紧急交易审批）"
        else:  # gate_c / a9 — 保持 30min AI 评分逻辑
            if elapsed < TIMEOUT_MINUTES:
                print(f"[check] {instance_code}: PENDING {elapsed:.0f}min / {TIMEOUT_MINUTES}min")
                continue
            print(f"[check] {instance_code}: 超时 {elapsed:.0f}min，AI 决策中...")
            session_id = rec["session_id"]
            try:
                approve, reason = (decide_gate_c(session_id) if category == "gate_c"
                                   else decide_a9(session_id))
            except Exception as e:
                print(f"[ERROR] AI决策失败: {instance_code}: {e}")
                try:
                    send_msg(f"[AI代决失败] {instance_code}\n错误: {str(e)[:200]}")
                except Exception:
                    pass
                continue

        # ── 执行决策（trading_emergency / gate_c / a9）──
        try:
            if task_id:
                execute_approval(instance_code, task_id, approve, reason)
                action_str = "批准" if approve else "拒绝"
                msg = (f"[AI代决] {category.upper()} 审批已{action_str}\n"
                       f"Session: {rec.get('session_id','')} \n原因: {reason}\n"
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
            try:
                send_msg(f"[AI代决失败] {instance_code}\n错误: {str(e)[:200]}")
            except Exception:
                pass

    if changed:
        save_state(state)


# ── 主入口 ──
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"

    if cmd == "register":
        args = sys.argv[2:]
        if len(args) < 3:
            print("Usage: approval_agent.py register <instance_code> <session_id> <approval_type> [--template CODE] [--emergency]")
            sys.exit(1)
        _code, _session, _atype = args[0], args[1], args[2]
        _template, _emergency, _i = "", False, 3
        while _i < len(args):
            if args[_i] == "--template" and _i + 1 < len(args):
                _template = args[_i + 1]; _i += 2
            elif args[_i] == "--emergency":
                _emergency = True; _i += 1
            else:
                _i += 1
        register(_code, _session, _atype, _template, _emergency)

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
