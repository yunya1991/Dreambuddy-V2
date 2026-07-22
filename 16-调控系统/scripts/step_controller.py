#!/usr/bin/env python3
"""
步进式笔记本控制器 v2.0 — 7步框架 + 物理门禁

每个 Session 按 7 步走，每步完成后询问用户：
  1️⃣ 继续下一步
  2️⃣ 跳过下一步
  3️⃣ 跳到指定步
  4️⃣ 直接执行全部
  5️⃣ 暂停

物理门禁（三重）:
  🔒 Gate 0 (Session 入口) — EVERY 命令检查 .session_gate 文件
     创立于 start，24h 过期自动销毁。无 gate = 一切 BLOCKED。
  🔒 Gate 1 (开工) — step/skip/jump/all 需要活跃任务
     → 提示也调用 chain_guard.py init (项目级)
  🔔 Gate 2 (收工) — Step 7 检查输出格式（数字选择+推荐）

用法:
  python3 step_controller.py start "任务名"  # 启动（创建 .session_gate）
  python3 step_controller.py status         # 查看状态（自动检查门禁）
  python3 step_controller.py step N 备注     # 标记完成
  python3 step_controller.py skip N         # 跳过
  python3 step_controller.py jump N         # 跳到指定步
  python3 step_controller.py all            # 全部完成
  python3 step_controller.py check          # 🔒 快速门禁检查（CI用）
"""
import json, os, sys
from datetime import datetime
from pathlib import Path

BASE = Path.home() / "archives" / "Dreambuddy-V2-main"
STATE_FILE = BASE / "0-NOTEBOOK" / ".step_state.json"
SESSION_GATE = BASE / "0-NOTEBOOK" / ".session_gate"
GATE_TIMEOUT_HOURS = 24

# ── Gate 0: Session 入口门禁 ──────────────────
def gate0_check():
    """
    🔒 Gate 0: 物理 Session 门禁
    每一条命令（除 start 和 check）都先检查此门禁。
    无 .session_gate 文件 → 显式 BLOCKED → exit 1
    """
    if not SESSION_GATE.exists():
        _print_gate0_blocked("未找到 .session_gate 文件")
        sys.exit(1)

    try:
        gate_data = json.loads(SESSION_GATE.read_text())
    except (json.JSONDecodeError, OSError):
        _print_gate0_blocked(".session_gate 文件损坏")
        sys.exit(1)

    # 检查过期
    created_str = gate_data.get("created_at", "")
    if not created_str:
        _print_gate0_blocked(".session_gate 缺少 created_at")
        sys.exit(1)

    created = datetime.fromisoformat(created_str)
    elapsed_h = (datetime.now() - created).total_seconds() / 3600
    if elapsed_h > GATE_TIMEOUT_HOURS:
        print()
        print(f"⌛ Session 已过期（{elapsed_h:.0f}h > {GATE_TIMEOUT_HOURS}h）")
        print(f"   原任务: {gate_data.get('title', '未知')}")
        _try_remove_gate()
        _print_gate0_blocked("Session 超时，已自动销毁 gate")
        sys.exit(1)

    return gate_data


def _print_gate0_blocked(reason: str):
    """门禁拦截信息"""
    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║   🔒🔒🔒 GATE 0: 开工门禁 BLOCKED 🔒🔒🔒     ║")
    print("╠══════════════════════════════════════════════════╣")
    print(f"║  原因: {reason:<36}║")
    print("╠══════════════════════════════════════════════════╣")
    print("║  本 Session 未初始化！                           ║")
    print("║  必须先运行:                                    ║")
    print("║                                                ║")
    print("║    step_controller.py start \"任务名\"          ║")
    print("║                                                ║")
    print("║  D-Z-E 项目级任务还需:                          ║")
    print("║    chain_guard.py init \"任务描述\"              ║")
    print("╚══════════════════════════════════════════════════╝")
    print()


def _try_remove_gate():
    """尝试删除 gate 文件（过期时自动清理）"""
    try:
        if SESSION_GATE.exists():
            SESSION_GATE.unlink()
    except OSError:
        pass


# ── Gate 1: 开工门禁 ──────────────────────────
def _require_active(state=None):
    """所有需要活跃任务的操作必须先通过此门禁"""
    if state is None:
        state = _load()
    if not state.get("session_id"):
        print("=" * 50)
        print("🔒 Gate 1 BLOCKED：未启动任务")
        print("  请先运行: step_controller.py start \"任务名\"")
        print()
        print("  D-Z-E 项目级任务还需:")
        print("  chain_guard.py init \"任务描述\"   ← 三链阶段管理")
        print("=" * 50)
        sys.exit(1)

# ── Gate 2: 收工门禁 ──────────────────────────
END_FORMAT_CHECK_LIST = [
    ("步进结束格式", "数字选择", lambda n: any(kw in n for kw in ["1️⃣","2️⃣","3️⃣","1.","2.","3.","下一步"])),
    ("步进结束格式", "推荐意见", lambda n: any(kw in n for kw in ["推荐","建议","我建议","建议你"])),
]

def _check_end_format(note: str) -> list:
    """检查收工时的输出格式"""
    issues = []
    for category, check_name, check_fn in END_FORMAT_CHECK_LIST:
        if not check_fn(note):
            issues.append(f"⚠️ {category}: 缺少「{check_name}」")
    return issues

STEPS = [
    {"id": 1, "name": "需求解析", "emoji": "🎯",
     "desc": "理解用户需求 → 更新笔记本TODO → 初始化chain_guard",
     "systems": ["笔记本"]},
    {"id": 2, "name": "D-Z-E", "emoji": "🔗",
     "desc": "D-Z-E方法论：D调研→Z规划→E执行（用户可跳步）",
     "systems": ["思维链", "chain_guard"]},
    {"id": 3, "name": "知识库检索与回补", "emoji": "📚",
     "desc": "查2-KNOWLEDGE/ → 知识不足时联网搜 → 搜到必回补",
     "systems": ["知识库"]},
    {"id": 4, "name": "A系列方法论借鉴", "emoji": "🧠",
     "desc": "加载相关dream-* skill → 矛盾论/第一性原理等理论框架",
     "systems": ["A系列SKILL"]},
    {"id": 5, "name": "索引系统更新", "emoji": "🔍",
     "desc": "相关INDEX.md更新 → 确保全系统可索引查",
     "systems": ["索引系统"]},
    {"id": 6, "name": "飞书协作归档", "emoji": "✈️",
     "desc": "Base同步 / 审批提案 / Wiki更新（如有需要）",
     "systems": ["飞书协作"]},
    {"id": 7, "name": "记忆蒸馏", "emoji": "🧪",
     "desc": "关键发现蒸馏 → memory更新 → 知识库追加 → 演化日志",
     "systems": ["记忆系统"]},
]

def _load():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, ValueError):
            # 损坏/空JSON -> 重置为默认状态
            print("⚠️ 状态文件损坏，已重置")
            return {"session_id": None, "current_step": 0, "steps": {}, "created_at": None}
    return {"session_id": None, "current_step": 0, "steps": {}, "created_at": None}

def _save(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
def cmd_start(session_title: str = ""):
    state = _load()
    state["session_id"] = datetime.now().strftime("%Y%m%d_%H%M%S")
    state["current_step"] = 1
    state["title"] = session_title or f"Session {state['session_id']}"
    state["created_at"] = datetime.now().isoformat()
    state["steps"] = {str(s["id"]): {"status": "pending", "note": ""} for s in STEPS}
    state["steps"]["1"]["status"] = "in_progress"
    _save(state)

    # ── 🔒 创建 .session_gate 文件（Gate 0 的物理锚点）──
    SESSION_GATE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_GATE.write_text(json.dumps({
        "session_id": state["session_id"],
        "title": state["title"],
        "created_at": state["created_at"],
        "expires_after_hours": GATE_TIMEOUT_HOURS,
    }, indent=2))

    print(f"✅ 步进式启动: Step 1 — {STEPS[0]['emoji']} {STEPS[0]['name']}")
    print(f"   任务: {state['title']}")
    print(f"   🔒 .session_gate 已创建（{GATE_TIMEOUT_HOURS}h 后自动过期）")
    return state


def cmd_status():
    gate_data = gate0_check()  # ── 🔒 Gate 0 ──
    state = _load()
    if not state.get("session_id"):
        # Gate 0 通过了但状态丢了 → 修复
        print("⚠️ 状态文件丢失但 Gate 0 存在，修复中...")
        state["session_id"] = gate_data["session_id"]
        state["title"] = gate_data.get("title", "未知")
        state["current_step"] = 1
        state["created_at"] = gate_data["created_at"]
        state["steps"] = {str(s["id"]): {"status": "pending", "note": ""} for s in STEPS}
        state["steps"]["1"]["status"] = "in_progress"
        _save(state)
    print(f"📋 步进式状态 — {state.get('title', '未知')}")
    print(f"   当前: Step {state['current_step']}")
    print()
    for s in STEPS:
        st = state["steps"].get(str(s["id"]), {"status": "pending"})
        status_icon = {"completed": "✅", "in_progress": "▶️", "skipped": "⏭️", "pending": "⬜"}
        icon = status_icon.get(st["status"], "⬜")
        curr = " ← 当前" if state["current_step"] == s["id"] else ""
        print(f"  {icon} Step {s['id']}: {s['emoji']} {s['name']}{curr}")
        if st.get("note"):
            print(f"      备注: {st['note']}")
    print()

def cmd_step(step_id: int, note: str = ""):
    gate0_check()  # ── 🔒 Gate 0 ──
    state = _load()
    _require_active(state)  # ── Gate 1 ──
    sid = str(step_id)
    if sid not in state["steps"]:
        print(f"❌ Step {step_id} 不存在")
        return
    state["steps"][sid] = {"status": "completed", "note": note or ""}
    # ── Gate 2: Step 7 收工门禁 ──
    if step_id == len(STEPS):
        issues = _check_end_format(note)
        if issues:
            print(f"🔔 Gate 2 收工门禁 — 输出格式警告:")
            for i in issues:
                print(f"  {i}")
            print(f"  建议修复后再提交，使用: step {len(STEPS)} \"正确格式备注\"")
    # 自动推进到下一步
    next_id = step_id + 1
    if next_id <= len(STEPS):
        state["steps"][str(next_id)]["status"] = "in_progress"
        state["current_step"] = next_id
    else:
        state["current_step"] = len(STEPS) + 1  # all done
    _save(state)
    step = STEPS[step_id - 1]
    print(f"✅ Step {step_id} ({step['emoji']} {step['name']}) 完成")
    if next_id <= len(STEPS):
        next_step = STEPS[next_id - 1]
        print(f"▶️  下一步: Step {next_id} — {next_step['emoji']} {next_step['name']}")
    else:
        print("🎉 全部7步完成！")

def cmd_skip(step_id: int):
    gate0_check()  # ── 🔒 Gate 0 ──
    state = _load()
    _require_active(state)  # ── Gate 1 ──
    sid = str(step_id)
    if sid not in state["steps"]:
        print(f"❌ Step {step_id} 不存在")
        return
    state["steps"][sid] = {"status": "skipped", "note": "用户跳过"}
    # 如果跳过的是当前步骤，推进
    if state["current_step"] == step_id:
        next_id = step_id + 1
        if next_id <= len(STEPS):
            state["steps"][str(next_id)]["status"] = "in_progress"
            state["current_step"] = next_id
        else:
            state["current_step"] = len(STEPS) + 1
    _save(state)
    print(f"⏭️ Step {step_id} ({STEPS[step_id-1]['emoji']} {STEPS[step_id-1]['name']}) 已跳过")

def cmd_jump(target_id: int):
    """跳到指定步骤（跳过中间所有）"""
    gate0_check()  # ── 🔒 Gate 0 ──
    state = _load()
    _require_active(state)  # ── Gate 1 ──
    for i in range(state["current_step"], target_id):
        sid = str(i)
        if sid in state["steps"] and state["steps"][sid]["status"] not in ("completed", "skipped"):
            state["steps"][sid] = {"status": "skipped", "note": f"跳过→Step {target_id}"}
    state["steps"][str(target_id)]["status"] = "in_progress"
    state["current_step"] = target_id
    _save(state)
    print(f"🚀 跳到 Step {target_id}: {STEPS[target_id-1]['emoji']} {STEPS[target_id-1]['name']}")

def cmd_all():
    """标记所有步骤为完成"""
    gate0_check()  # ── 🔒 Gate 0 ──
    state = _load()
    _require_active(state)  # ── Gate 1 ──
    for s in STEPS:
        sid = str(s["id"])
        if state["steps"].get(sid, {}).get("status") in ("pending", "in_progress"):
            state["steps"][sid] = {"status": "completed", "note": "直接执行全部"}
    state["current_step"] = len(STEPS) + 1
    _save(state)
    # ── Gate 2: 全部完成也检查 ──
    last_note = state["steps"].get(str(len(STEPS)), {}).get("note", "")
    if last_note:
        issues = _check_end_format(last_note)
        if issues:
            print("🔔 Gate 2 收工门禁 — 输出格式警告（直接执行模式）:")
            for i in issues:
                print(f"  {i}")
    print("🚀 全部7步标记完成（直接执行模式）")

def cmd_check():
    """🔒 快速门禁检查 — 用于 session 开始的强制验证"""
    if not SESSION_GATE.exists():
        _print_gate0_blocked("门禁未初始化")
        sys.exit(1)
    gate_data = gate0_check()
    print(f"🔒 Gate 0 通过")
    print(f"   Session: {gate_data['session_id']}")
    print(f"   任务: {gate_data.get('title', '未知')}")
    print(f"   创建: {gate_data['created_at']}")
    print(f"   过期: {GATE_TIMEOUT_HOURS}h")
    return gate_data


def main():
    if len(sys.argv) < 2:
        print("用法: step_controller.py <start|status|step|skip|jump|all|check> [参数]")
        return
    cmd = sys.argv[1]
    if cmd == "start":
        title = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
        cmd_start(title)
    elif cmd == "status":
        cmd_status()
    elif cmd == "check":
        cmd_check()
    elif cmd == "step":
        if len(sys.argv) < 3:
            print("用法: step_controller.py step <N> [备注]")
            return
        note = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else ""
        cmd_step(int(sys.argv[2]), note)
    elif cmd == "skip":
        if len(sys.argv) < 3:
            print("用法: step_controller.py skip <N>")
            return
        cmd_skip(int(sys.argv[2]))
    elif cmd == "jump":
        if len(sys.argv) < 3:
            print("用法: step_controller.py jump <N>")
            return
        cmd_jump(int(sys.argv[2]))
    elif cmd == "all":
        cmd_all()
    else:
        print(f"未知命令: {cmd}")

if __name__ == "__main__":
    main()
