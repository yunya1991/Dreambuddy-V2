#!/usr/bin/env python3
"""Chain Guard — 三链接力协议的状态管理与合法性检查

用法:
  python3 chain_guard.py init "任务描述"    ← 启动新任务
  python3 chain_guard.py status             ← 查看当前状态
  python3 chain_guard.py check d1 d2        ← 检查跳转合法性
  python3 chain_guard.py transition d1 d2   ← 执行跳转
  python3 chain_guard.py override d1 d3 "用户指定跳过"  ← 用户跳过
  python3 chain_guard.py approve d1         ← 标记某阶段已批准
  python3 chain_guard.py start d1           ← 标记某阶段进行中
"""

import json
import os
import sys
from datetime import datetime, timezone

# ── 路径配置 ────────────────────────────────────
STATE_DIR = os.path.expanduser("~/.workbuddy/memory")
STATE_FILE = os.path.join(STATE_DIR, "chain_state.json")

# ── 阶段定义 ────────────────────────────────────
PHASES_ORDER = [
    "d1", "d2", "d3", "d4",
    "z1", "z2", "z3", "z4",
    "e1", "e2", "e3",
]

PHASE_NAMES = {
    "d1": "D1 深度调研",
    "d2": "D2 分析诊断",
    "d3": "D3 推演验证",
    "d4": "D4 Spec合成",
    "z1": "Z1 代码扫描",
    "z2": "Z2 范围划分",
    "z3": "Z3 路径设计",
    "z4": "Z4 验收方案",
    "e1": "E1 任务执行",
    "e2": "E2 测试验证",
    "e3": "E3 部署交付",
}

PHASE_METHODOLOGIES = {
    "d1": "四准则调研法",
    "d2": "三问分析框架",
    "d3": "三景推演法",
    "d4": "四段Spec法",
    "z1": "模块依赖分析",
    "z2": "拓扑切割+回滚点设计",
    "z3": "完整实施步骤模板",
    "z4": "四层验收策略",
    "e1": "todo驱动逐任务执行",
}

# ── 跨链规则 ────────────────────────────────────
# D系列只能在D系列内部顺序跳转
# Z系列只能在Z系列内部顺序跳转
# 跨链只允许: D4→Z1, Z4→E1

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def _get_chain(phase_id):
    prefix = phase_id[0] if phase_id else None
    return prefix if prefix in ("d", "z", "e") else None

def _default_state():
    return {
        "scope": None,
        "created_at": None,
        "modified_at": None,
        "current_phase": None,
        "phases": [],
        "relay_history": [],
    }

def _load():
    if not os.path.exists(STATE_FILE):
        return _default_state()
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        # 损坏/空JSON -> 重置为默认状态
        return _default_state()

def _save(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    state["modified_at"] = _now_iso()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ── Guard 函数 ──────────────────────────────────

def chain_init(scope):
    """初始化新任务的状态文件"""
    state = _default_state()
    now = _now_iso()
    state["scope"] = scope
    state["created_at"] = now
    state["modified_at"] = now
    state["current_phase"] = "d1"

    for pid in PHASES_ORDER:
        name = PHASE_NAMES.get(pid, pid)
        methodology = PHASE_METHODOLOGIES.get(pid, "")
        state["phases"].append({
            "id": pid,
            "name": name,
            "methodology": methodology,
            "status": "in_progress" if pid == "d1" else "pending",
            "approval": "pending",
            "output_ref": None,
            "completed_at": None,
            "step_count": 0,
        })
    _save(state)
    return state


def chain_check(state, from_phase, to_phase):
    """检查跳转是否合法。返回 {"allowed": bool, "reason": str}"""
    phases = state.get("phases", [])
    if not phases:
        return {"allowed": False, "reason": "状态未初始化，请先运行 chain_guard.py init"}
    phase_ids = {p["id"] for p in phases}
    if from_phase not in phase_ids:
        return {"allowed": False, "reason": f"来源阶段 {from_phase} 不存在"}
    if to_phase not in phase_ids:
        return {"allowed": False, "reason": f"目标阶段 {to_phase} 不存在"}

    from_p = next(p for p in state["phases"] if p["id"] == from_phase)
    to_p = next(p for p in state["phases"] if p["id"] == to_phase)

    # 规则1: from_phase 必须已完成或已跳过
    if from_p["status"] not in ("completed", "skipped"):
        return {"allowed": False,
                "reason": f"{from_phase}({from_p['name']}) 尚未完成（status={from_p['status']}）"}

    # 规则2: to_phase 必须是 pending
    if to_p["status"] != "pending":
        return {"allowed": False,
                "reason": f"{to_phase}({to_p['name']}) 状态不是 pending（当前={to_p['status']}）"}

    # 规则3: 跨链检查
    from_chain = _get_chain(from_phase)
    to_chain = _get_chain(to_phase)
    if from_chain != to_chain:
        allowed_cross = False
        if from_chain == "d" and to_chain == "z" and from_phase == "d4" and to_phase == "z1":
            allowed_cross = True
        if from_chain == "z" and to_chain == "e" and from_phase == "z4" and to_phase == "e1":
            allowed_cross = True
        if not allowed_cross:
            return {"allowed": False,
                    "reason": f"跨链跳转 {from_phase}({from_chain})→{to_phase}({to_chain}) 不允许"
                              f"（只允许 D4→Z1 和 Z4→E1）"}

    # 规则4: 同链内必须顺序跳转
    if from_chain == to_chain:
        chain_phases = [p for p in PHASES_ORDER if _get_chain(p) == from_chain]
        try:
            from_idx = chain_phases.index(from_phase)
            to_idx = chain_phases.index(to_phase)
        except ValueError:
            return {"allowed": False, "reason": f"阶段不在链中"}
        if to_idx != from_idx + 1:
            expected = chain_phases[from_idx + 1] if from_idx + 1 < len(chain_phases) else "无下一步"
            return {"allowed": False,
                    "reason": f"同链跳转必须按顺序（{from_phase}→{to_phase}，"
                              f"但应为 {from_phase}→{expected}）"}

    return {"allowed": True, "reason": None}


def chain_transition(state, from_phase, to_phase):
    """执行合法跳转"""
    check = chain_check(state, from_phase, to_phase)
    if not check["allowed"]:
        return {"success": False, "reason": check["reason"], "state": state}

    now = _now_iso()

    for p in state["phases"]:
        if p["id"] == from_phase:
            if p["status"] == "in_progress":
                p["status"] = "completed"
                p["completed_at"] = now
        if p["id"] == to_phase:
            p["status"] = "in_progress"

    state["current_phase"] = to_phase
    state["relay_history"].append({
        "from": from_phase,
        "to": to_phase,
        "trigger": "chain_transition",
        "reason": None,
        "at": now,
    })
    _save(state)
    return {"success": True, "state": state}


def chain_override(state, from_phase, to_phase, reason):
    """用户指定跳过，记录理由。不检查合法性。"""
    now = _now_iso()

    # 标记从 from 到 to 之间的所有阶段为 skipped
    # 处理同链和跨链两种情况
    try:
        from_idx = PHASES_ORDER.index(from_phase)
        to_idx = PHASES_ORDER.index(to_phase)
    except ValueError:
        from_idx = to_idx = -1

    if from_idx >= 0 and to_idx >= 0 and to_idx > from_idx:
        for i in range(from_idx + 1, to_idx):  # 跳过 from_phase，不标记其为 skipped
            pid = PHASES_ORDER[i]
            for p in state["phases"]:
                if p["id"] == pid and p["status"] in ("pending", "in_progress"):
                    p["status"] = "skipped"
                    p["approval"] = "approved"
                    p["completed_at"] = now

    for p in state["phases"]:
        if p["id"] == to_phase:
            p["status"] = "in_progress"

    state["current_phase"] = to_phase
    state["relay_history"].append({
        "from": from_phase,
        "to": to_phase,
        "trigger": "chain_override",
        "reason": reason,
        "at": now,
    })
    _save(state)
    return {"success": True, "state": state}


def chain_status():
    """读取当前完整状态"""
    return _load()


def chain_approve(phase_id):
    """标记某阶段为用户已批准，同时标记为已完成"""
    state = _load()
    now = _now_iso()
    for p in state["phases"]:
        if p["id"] == phase_id:
            p["approval"] = "approved"
            if p["status"] in ("in_progress", "pending"):
                p["status"] = "completed"
                p["completed_at"] = now
    state["relay_history"].append({
        "from": state["current_phase"],
        "to": phase_id,
        "trigger": "user_approval",
        "reason": None,
        "at": _now_iso(),
    })
    _save(state)
    return state


def chain_mark_in_progress(phase_id):
    """标记某阶段为进行中（阶段启动时）"""
    state = _load()
    for p in state["phases"]:
        if p["id"] == phase_id:
            p["status"] = "in_progress"
            state["current_phase"] = phase_id
    _save(state)
    return state


# ── CLI ─────────────────────────────────────────

def _cli():
    if len(sys.argv) < 2:
        print("Chain Guard — 三链接力协议")
        print()
        print("命令:")
        print("  init \"描述\"       初始化新任务")
        print("  status             查看当前状态")
        print("  check <从> <到>     检查跳转合法性")
        print("  transition <从> <到> 执行合法跳转")
        print("  override <从> <到> <理由>  用户跳过")
        print("  approve <阶段ID>    标记已批准")
        print("  start <阶段ID>      标记进行中")
        return

    cmd = sys.argv[1]

    if cmd == "init":
        scope = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "未知任务"
        result = chain_init(scope)
        print(f"✅ 初始化完成")
        print(f"   任务: {scope}")
        print(f"   当前: D1 深度调研")

    elif cmd == "status":
        result = chain_status()
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif cmd == "check":
        if len(sys.argv) < 4:
            print("用法: chain_guard.py check <from> <to>")
            return
        f, t = sys.argv[2], sys.argv[3]
        state = _load()
        result = chain_check(state, f, t)
        if result["allowed"]:
            print(f"✅ 跳转 {f} → {t} 合法")
        else:
            print(f"❌ 拒绝: {result['reason']}")

    elif cmd == "transition":
        if len(sys.argv) < 4:
            print("用法: chain_guard.py transition <from> <to>")
            return
        f, t = sys.argv[2], sys.argv[3]
        state = _load()
        result = chain_transition(state, f, t)
        mark = "✅" if result["success"] else "❌"
        print(f"{mark} {f} → {t}: {result.get('reason', '成功')}")

    elif cmd == "override":
        if len(sys.argv) < 4:
            print("用法: chain_guard.py override <from> <to> [理由]")
            return
        f, t = sys.argv[2], sys.argv[3]
        reason = " ".join(sys.argv[4:]) if len(sys.argv) > 4 else "用户指定跳过（无理由）"
        state = _load()
        result = chain_override(state, f, t, reason)
        print(f"🔄 跳过 {f} → {t}: {reason}")

    elif cmd == "approve":
        if len(sys.argv) < 3:
            print("用法: chain_guard.py approve <phase_id>")
            return
        pid = sys.argv[2]
        chain_approve(pid)
        print(f"✅ {pid} 已批准")

    elif cmd == "start":
        if len(sys.argv) < 3:
            print("用法: chain_guard.py start <phase_id>")
            return
        pid = sys.argv[2]
        chain_mark_in_progress(pid)
        print(f"▶️ {pid} 进行中")

    else:
        print(f"未知命令: {cmd}")


if __name__ == "__main__":
    _cli()
