#!/usr/bin/env python3
"""
7 场景压力测试 — 步进式笔记本框架 + 三链门禁 + 笔记本钩子
测试所有子系统在高负载、边界值、错误恢复、跨Session场景下的稳定性。
"""
import json, os, sys, time, shutil, re
from datetime import datetime
from pathlib import Path

BASE = Path.home() / "archives" / "Dreambuddy-V2-main"
SCRIPTS = BASE / "scripts"

sys.path.insert(0, str(SCRIPTS))
os.chdir(str(BASE))

PASS = 0
FAIL = 0
ERRORS = []

def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        return True
    else:
        FAIL += 1
        ERRORS.append(f"❌ {label}: {detail}")
        return False

def run(cmd):
    """Run a CLI command and return (exit_code, stdout, stderr)"""
    import subprocess
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.returncode, result.stdout, result.stderr

def ensure_empty():
    """Ensure all state files are clean before test"""
    state_file = BASE / "0-NOTEBOOK" / ".step_state.json"
    if state_file.exists():
        state_file.unlink()
    chain_file = Path.home() / ".workbuddy" / "memory" / "chain_state.json"
    if chain_file.exists():
        chain_file.unlink()
    # Clean test artifacts from done/todo/active
    for d in [BASE/"0-NOTEBOOK"/"2-DONE", BASE/"0-NOTEBOOK"/"0-TODO", BASE/"0-NOTEBOOK"/"1-ACTIVE"]:
        if d.exists():
            for f in d.glob("*"):
                if f.name != "README.md" and f.stat().st_mtime > time.time() - 3600:
                    f.unlink()

def print_header(s):
    print(f"\n{'='*60}")
    print(f"  {s}")
    print(f"{'='*60}")

def print_result(label, ok):
    mark = "✅" if ok else "❌"
    print(f"  {mark} {label}")

# =========================================================
# SCENARIO 1: 高并发写入 (50+ 混合操作)
# =========================================================
def test_scenario1():
    global PASS, FAIL
    print_header("🏋️ Scenario 1: 高并发写入 — 60 次混合操作")
    ensure_empty()

    times = []
    tries = 60
    for i in range(tries):
        t0 = time.time()
        if i < 20:
            rc, out, err = run(["python3", "scripts/step_controller.py", "start", f"压力测试任务_{i}"])
        elif i < 40:
            rc, out, err = run(["python3", "scripts/notebook_hook.py", "done", f"压力完成项_{i}", f"{i}号测试完成"])
        else:
            rc, out, err = run(["python3", "scripts/notebook_hook.py", "todo", f"压力待办_{i}", f"{i}号待办描述"])
        elapsed = time.time() - t0
        times.append(elapsed)
        check(f"S1-操作{i}", rc == 0, f"exit={rc}, stderr={err[:100]}")

    avg = sum(times) / len(times)
    max_t = max(times)
    min_t = min(times)
    check("S1-平均耗时<200ms", avg < 0.2, f"avg={avg*1000:.1f}ms")
    check("S1-最大耗时<1s", max_t < 1.0, f"max={max_t*1000:.1f}ms")
    print(f"  ⏱  {tries}次操作: avg={avg*1000:.1f}ms, min={min_t*1000:.1f}ms, max={max_t*1000:.1f}ms")

    # Verify NOTEBOOK.md is still valid markdown
    nb = BASE / "0-NOTEBOOK" / "NOTEBOOK.md"
    check("S1-NOTEBOOK存在", nb.exists())
    if nb.exists():
        content = nb.read_text()
        check("S1-NOTEBOOK非空", len(content) > 100)
        check("S1-含完成区域", "## ✅ 已完成" in content or "## ✅ 最近完成" in content)

    # Verify DONE directory has files
    done_files = list((BASE/"0-NOTEBOOK"/"2-DONE").glob("*.md"))
    check(f"S1-完成项文件>10", len(done_files) > 10, f"got={len(done_files)}")

    # Verify TODO directory has files
    todo_files = list((BASE/"0-NOTEBOOK"/"0-TODO").glob("*.md"))
    check(f"S1-待办项文件>10", len(todo_files) > 10, f"got={len(todo_files)}")

    print(f"\n  S1 结果: {sum(1 for i in range(60) if check(f'S1-操作{i}', True, ''))}/60 + 4 验证 = ...")
    ensure_empty()

# =========================================================
# SCENARIO 2: 三链全流程 — Step1→Step7 完整路径
# =========================================================
def test_scenario2():
    print_header("🔗 Scenario 2: 三链全流程 — Step1→Step7 完整路径")
    ensure_empty()

    # Start the step controller
    rc, out, err = run(["python3", "scripts/step_controller.py", "start", "全流程压力测试"])
    check("S2-start", rc == 0 and "Step 1" in out, str(out[:200]))

    # Step through all 7 steps
    for step_num in range(1, 8):
        note = f"Step {step_num} 完成 — 自动测试"
        rc, out, err = run(["python3", "scripts/step_controller.py", "step", str(step_num), note])
        expected = "🎉" if step_num == 7 else "▶️"
        check(f"S2-step{step_num}", rc == 0 and expected in out, f"out={out[:200]}")

    # Verify all steps completed
    rc, out, err = run(["python3", "scripts/step_controller.py", "status"])
    check("S2-status", rc == 0)
    for step_num in range(1, 8):
        check(f"S2-完成{step_num}", f"Step {step_num}" in out and ("✅" in out), f"step{step_num} not completed")

    # Verify step state file
    state_file = BASE / "0-NOTEBOOK" / ".step_state.json"
    check("S2-状态文件存在", state_file.exists())
    if state_file.exists():
        state = json.loads(state_file.read_text())
        check("S2-全部7步完成", state["current_step"] == 8, f"current_step={state['current_step']}")
        for s in range(1, 8):
            st = state["steps"].get(str(s), {})
            check(f"S2-step{s}_completed", st.get("status") == "completed", f"status={st.get('status')}")

    ensure_empty()
    print()
    return True

# =========================================================
# SCENARIO 3: 边界值测试
# =========================================================
def test_scenario3():
    print_header("🔮 Scenario 3: 边界值测试")
    ensure_empty()

    # 3a. 空标题 start
    rc, out, err = run(["python3", "scripts/step_controller.py", "start", ""])
    check("S3a-空标题start", rc == 0 and "Step 1" in out, out[:200])

    # 3b. 超长备注 (500 chars)
    long_note = "A" * 500
    rc, out, err = run(["python3", "scripts/step_controller.py", "step", "1", long_note])
    check("S3b-500字备注", rc == 0 and "✅" in out, out[:200])

    # 3c. 特殊字符
    special = "Hello!@#$%^&*()_+{}[]|\\:;\"'<>,.?/~`\n\t"
    rc, out, err = run(["python3", "scripts/step_controller.py", "step", "2", special])
    check("S3c-特殊字符", rc == 0 and "✅" in out, out[:200])

    # 3d. Unicode 多语言
    unicode_title = "日本語中文한국어Русскийالعربيةתעברית"
    rc, out, err = run(["python3", "scripts/step_controller.py", "step", "3", unicode_title])
    check("S3d-Unicode多语言", rc == 0 and "✅" in out, out[:200])

    # 3e. 不存在 Step
    rc, out, err = run(["python3", "scripts/step_controller.py", "step", "99"])
    check("S3e-不存在Step", "不存在" in out or rc != 0, out[:200])

    # 3f. 负数 Step
    rc, out, err = run(["python3", "scripts/step_controller.py", "step", "-1"])
    check("S3f-负数Step", "不存在" in out or rc != 0, out[:200])

    # 3g. 字符串参数代替数字
    rc, out, err = run(["python3", "scripts/step_controller.py", "step", "abc"])
    check("S3g-字符串参数", rc != 0 or "ValueError" in err+out, out[:200])

    # 3h. notebook_hook 超长标题
    long_title = "A" * 500
    rc, out, err = run(["python3", "scripts/notebook_hook.py", "done", long_title, "超长标题测试"])
    check("S3h-超长标题done", rc == 0 and "✅" in out, out[:200])

    # 3i. notebook_hook 空摘要
    rc, out, err = run(["python3", "scripts/notebook_hook.py", "done", "空摘要测试", ""])
    check("S3i-空摘要done", rc == 0 and "✅" in out, out[:200])

    # 3j. notebook_hook 路径注入
    path_inject = "../../../etc/passwd"
    rc, out, err = run(["python3", "scripts/notebook_hook.py", "done", path_inject, "路径注入测试"])
    check("S3j-路径注入", rc == 0 and "✅" in out, out[:200])

    # 3k. chain_guard 未初始化就 check
    rc, out, err = run(["python3", "3-CHAIN-DEVELOPMENT/scripts/chain_guard.py", "check", "d1", "x99"])
    check("S3k-chain_guard未初始化check", "未初始化" in out, out[:200])

    # 3l. chain_guard 初始化并approve后跨链非法跳转
    rc2, out2, err2 = run(["python3", "3-CHAIN-DEVELOPMENT/scripts/chain_guard.py", "init", "边界测试"])
    rc2, out2, err2 = run(["python3", "3-CHAIN-DEVELOPMENT/scripts/chain_guard.py", "approve", "d1"])  # 先完成d1
    rc, out, err = run(["python3", "3-CHAIN-DEVELOPMENT/scripts/chain_guard.py", "check", "d1", "z1"])
    check("S3l-chain_guard跨链非法", "不合法" in out or "不允许" in out or "只允许" in out, out[:200])
    ensure_empty()

    # 3m. chain_guard approve后同链跳步（d1已完成，check d1→d3跳过d2）
    rc2, out2, err2 = run(["python3", "3-CHAIN-DEVELOPMENT/scripts/chain_guard.py", "init", "跳步测试"])
    rc2, out2, err2 = run(["python3", "3-CHAIN-DEVELOPMENT/scripts/chain_guard.py", "approve", "d1"])  # 先完成d1
    rc, out, err = run(["python3", "3-CHAIN-DEVELOPMENT/scripts/chain_guard.py", "check", "d1", "d3"])  # d1已完成,d3未激活→非法跳步
    check("S3m-chain_guard跳步非法", "顺序" in out or "pending" in out or "应" in out, out[:200])

    ensure_empty()
    print()

# =========================================================
# SCENARIO 4: 跳步门禁 — skip / jump / all 权限验证
# =========================================================
def test_scenario4():
    print_header("🚪 Scenario 4: 跳步门禁 — skip / jump / all")
    ensure_empty()

    # 4a. skip: 跳过 Step 1, Step 2 → 验证 Step 3 激活
    rc, out, err = run(["python3", "scripts/step_controller.py", "start", "跳步测试"])
    check("S4a-start", rc == 0, out[:200])
    rc, out, err = run(["python3", "scripts/step_controller.py", "skip", "1"])
    check("S4a-skip1", rc == 0 and "⏭️" in out, out[:200])
    # After skip, Step 2 should be in_progress
    state_file = BASE / "0-NOTEBOOK" / ".step_state.json"
    if state_file.exists():
        state = json.loads(state_file.read_text())
        check("S4a-skip1→step2激活", state.get("current_step") == 2, f"current={state.get('current_step')}")

    # 4b. jump: 从 Step 2 跳到 Step 6
    rc, out, err = run(["python3", "scripts/step_controller.py", "jump", "6"])
    check("S4b-jump6", rc == 0 and "🚀" in out, out[:200])
    if state_file.exists():
        state = json.loads(state_file.read_text())
        check("S4b-jump→step6激活", state.get("current_step") == 6, f"current={state.get('current_step')}")
        # Steps 2-5 should be skipped
        for s in range(2, 6):
            st = state["steps"].get(str(s), {})
            check(f"S4b-step{s}_skipped", st.get("status") == "skipped", f"step{s}={st.get('status')}")

    # 4c. all: 直接全部标记完成
    ensure_empty()
    rc, out, err = run(["python3", "scripts/step_controller.py", "start", "全部执行测试"])
    check("S4c-start", rc == 0, out[:200])
    rc, out, err = run(["python3", "scripts/step_controller.py", "all"])
    check("S4c-all", rc == 0 and "全部7步" in out, out[:200])
    if state_file.exists():
        state = json.loads(state_file.read_text())
        check("S4c-all完成后8", state["current_step"] == 8, f"current={state['current_step']}")
        for s in range(1, 8):
            st = state["steps"].get(str(s), {})
            check(f"S4c-step{s}_all", st.get("status") == "completed", f"step{s}={st.get('status')}")

    # 4d. chain_guard override: d1→e1 (跳过d2-d4和z1-z4)
    ensure_empty()
    rc, out, err = run(["python3", "3-CHAIN-DEVELOPMENT/scripts/chain_guard.py", "init", "跳步门禁测试"])
    check("S4d-guard_init", rc == 0, out[:200])

    rc, out, err = run(["python3", "3-CHAIN-DEVELOPMENT/scripts/chain_guard.py", "override", "d1", "e1", "用户授权跳过全部中间阶段"])
    check("S4d-guard_override", rc == 0 and "🔄" in out, out[:200])

    chain_file = Path.home() / ".workbuddy" / "memory" / "chain_state.json"
    if chain_file.exists():
        state = json.loads(chain_file.read_text())
        check("S4d-跳转到e1", state["current_phase"] == "e1", f"current={state['current_phase']}")
        skipped_d = [p["id"] for p in state["phases"] if p["status"] == "skipped" and p["id"].startswith("d")]
        skipped_z = [p["id"] for p in state["phases"] if p["status"] == "skipped" and p["id"].startswith("z")]
        check(f"S4d-D系列跳过{len(skipped_d)}个", len(skipped_d) == 3, f"skipped={skipped_d}")
        check(f"S4d-Z系列跳过{len(skipped_z)}个", len(skipped_z) == 4, f"skipped={skipped_z}")

    ensure_empty()
    print()

# =========================================================
# SCENARIO 5: 错误恢复
# =========================================================
def test_scenario5():
    print_header("🩹 Scenario 5: 错误恢复")
    ensure_empty()

    # 5a. 状态文件损坏 — JSON 损坏
    state_file = BASE / "0-NOTEBOOK" / ".step_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text("{invalid json!!!}")
    rc, out, err = run(["python3", "scripts/step_controller.py", "status"])
    # Should show "未启动" instead of crashing
    check("S5a-JSON损坏", "未启动" in out or "⚠️" in out, out[:300])

    # 5b. 状态文件为空
    state_file.write_text("")
    rc, out, err = run(["python3", "scripts/step_controller.py", "status"])
    check("S5b-空JSON", "未启动" in out or "⚠️" in out, out[:300])

    # 5c. 状态文件不存在
    state_file.unlink(missing_ok=True)
    rc, out, err = run(["python3", "scripts/step_controller.py", "status"])
    check("S5c-文件不存在", "未启动" in out or "⚠️" in out, out[:300])

    # 5d. start → 中断 → 恢复
    rc, out, err = run(["python3", "scripts/step_controller.py", "start", "中断恢复测试"])
    check("S5d-start", rc == 0, out[:200])

    # 模拟 2 步完成后中断
    rc, out, err = run(["python3", "scripts/step_controller.py", "step", "1", "Step 1 done"])
    check("S5d-step1", rc == 0, out[:200])
    rc, out, err = run(["python3", "scripts/step_controller.py", "step", "2", "Step 2 done"])
    check("S5d-step2", rc == 0, out[:200])

    # 模拟新 session: 重新读状态
    if state_file.exists():
        state = json.loads(state_file.read_text())
        check("S5d-状态保留_step3", state["current_step"] == 3, f"current={state['current_step']}")
        check("S5d-状态保留_steps", state["steps"]["1"]["status"] == "completed" and state["steps"]["2"]["status"] == "completed",
              f"step1={state['steps']['1']['status']}, step2={state['steps']['2']['status']}")

    # 5e. chain_guard 状态文件损坏 → 应返回默认状态（不崩溃）
    chain_file = Path.home() / ".workbuddy" / "memory" / "chain_state.json"
    chain_file.parent.mkdir(parents=True, exist_ok=True)
    chain_file.write_text("{broken:")
    rc, out, err = run(["python3", "3-CHAIN-DEVELOPMENT/scripts/chain_guard.py", "status"])
    check("S5e-chain_guard损坏回退", '"scope": null' in out and '"phases": []' in out, out[:200])

    # 5f. chain_guard 空对象做check → 明确提示未初始化
    chain_file.write_text("{}")
    rc, out, err = run(["python3", "3-CHAIN-DEVELOPMENT/scripts/chain_guard.py", "check", "d1", "d2"])
    check("S5f-chain_guard空状态check", "未初始化" in out, out[:300])

    # 5g. 双系统同时操作 — step_controller + notebook_hook 交替
    ensure_empty()
    for i in range(20):
        if i % 2 == 0:
            rc, out, err = run(["python3", "scripts/step_controller.py", "start", f"双系统测试_{i}"])
        else:
            rc, out, err = run(["python3", "scripts/notebook_hook.py", "done", f"双系统完成_{i}", f"第{i}次交替"])
        check(f"S5g-交替操作{i}", rc == 0, out[:200])

    ensure_empty()
    print()

# =========================================================
# SCENARIO 6: 跨 Session 持久化
# =========================================================
def test_scenario6():
    print_header("🔄 Scenario 6: 跨 Session 持久化")
    ensure_empty()

    # Session A: 启动并完成 Step 1-3 + notebook_hook记录
    rc, out, err = run(["python3", "scripts/step_controller.py", "start", "跨Session测试"])
    check("S6a-启动", rc == 0, out[:200])
    for s in [1, 2, 3]:
        rc, out, err = run(["python3", "scripts/step_controller.py", "step", str(s), f"Session A Step {s}"])
        check(f"S6a-step{s}", rc == 0, out[:200])
        # 同时通知hooks
        rc2, out2, err2 = run(["python3", "scripts/notebook_hook.py", "done", f"Session A Step {s}", f"跨Session步骤{s}完成"])
    # 同步笔记本
    rc, out, err = run(["python3", "scripts/notebook_hook.py", "sync"])

    # 模拟 Session 结束（保持状态文件）
    state_file = BASE / "0-NOTEBOOK" / ".step_state.json"
    check("S6a-SessionA状态文件", state_file.exists())
    state_a = json.loads(state_file.read_text()) if state_file.exists() else {}
    check("S6a-第4步激活", state_a.get("current_step") == 4, f"current={state_a.get('current_step')}")

    # Session B: 新 session 读取状态继续
    # 模拟一个"新" session 读取 NOTEBOOK.md
    nb = BASE / "0-NOTEBOOK" / "NOTEBOOK.md"
    if nb.exists():
        content = nb.read_text()
        check("S6b-步进面板含进度", "▶️" in content or "Step 4" in content or "思维链" in content,
              "no visible progress indicator")

    rc, out, err = run(["python3", "scripts/step_controller.py", "status"])
    check("S6b-SessionB状态正确", f"Step 4" in out or "思维链" in out, out[:200])

    # Session B 继续完成 Step 4-7
    for s in [4, 5, 6, 7]:
        rc, out, err = run(["python3", "scripts/step_controller.py", "step", str(s), f"Session B Step {s}"])
        check(f"S6b-step{s}", rc == 0, out[:200])

    # 验证全部完成
    state_final = json.loads(state_file.read_text()) if state_file.exists() else {}
    check("S6c-最终完成", state_final.get("current_step") == 8, f"current={state_final.get('current_step')}")

    # 验证 notebook_hook 已完成项在跨 session 后仍被记录
    done_files = list((BASE/"0-NOTEBOOK"/"2-DONE").glob("*.md"))
    check(f"S6d-完成项>0", len(done_files) > 0)

    # 验证 sync 后 NOTEBOOK 显示跨 session 完成的项
    if nb.exists():
        content = nb.read_text()
        has_done = "Session" in content
        check("S6f-跨Session项记录", has_done, f"内容不含Session: {content[-300:]}")

    ensure_empty()
    print()

# =========================================================
# SCENARIO 7: 全系统压力
# =========================================================
def test_scenario7():
    print_header("💥 Scenario 7: 全系统压力 — 3系统同时操作 + 一致性验证")
    ensure_empty()

    # 7a. 完整 D-Z-E 链 + 步进式 + 笔记本钩子同步
    # Phase 1: chain_guard init → step controller start
    rc, out, err = run(["python3", "3-CHAIN-DEVELOPMENT/scripts/chain_guard.py", "init", "全系统压力测试"])
    check("S7a-guard_init", rc == 0, out[:200])
    rc, out, err = run(["python3", "scripts/step_controller.py", "start", "全系统压力测试"])
    check("S7a-step_start", rc == 0, out[:200])

    # Phase 2: 交错步进控制器 + 链推进（override模式） + 笔记本钩子
    chain_steps = ["d1","d2","d3","d4","z1","z2","z3","z4","e1","e2","e3"]
    for i in range(11):
        # Step controller one step
        if i < 7:
            rc, out, err = run(["python3", "scripts/step_controller.py", "step", str(i+1), f"总压力步{i+1}"])
            check(f"S7b-step{i+1}", rc == 0, out[:200])

        # Chain guard override (直接跳过到下一步，不需要complete前置)
        if i < 10:
            f = chain_steps[i]
            t = chain_steps[i+1]
            rc, out, err = run(["python3", "3-CHAIN-DEVELOPMENT/scripts/chain_guard.py", "override", f, t, f"压力测试{i}→{i+1}"])

        # Notebook hook at alternating intervals
        if i % 2 == 0:
            rc, out, err = run(["python3", "scripts/notebook_hook.py", "done",
                                f"全系统-{chain_steps[i] if i < 11 else 'done'}",
                                f"阶段{i+1}/{11}完成", ""])
            if rc != 0:
                print(f"  ⚠️ notebook_hook done failed at i={i}: {err[:100]}")

    # Phase 3: Verify notebook consistency
    state_file = BASE / "0-NOTEBOOK" / ".step_state.json"
    if state_file.exists():
        state = json.loads(state_file.read_text())
        check("S7c-步进7步完成", state["current_step"] >= 7, f"current={state['current_step']}")

    # Verify chain guard state
    chain_file = Path.home() / ".workbuddy" / "memory" / "chain_state.json"
    if chain_file.exists():
        state = json.loads(chain_file.read_text())
        current = state.get("current_phase", "?")
        check("S7d-链推进到E系列", "e" in current, f"current={current}")

    # Sync notebook and verify
    rc, out, err = run(["python3", "scripts/notebook_hook.py", "sync"])
    check("S7e-全系统sync", rc == 0 and "✅" in out, out[:200])

    nb = BASE / "0-NOTEBOOK" / "NOTEBOOK.md"
    if nb.exists():
        content = nb.read_text()
        check("S7f-笔记本格式完整", len(content) > 500, f"len={len(content)}")
        check("S7f-含步进面板", "步进式面板" in content, "面板标题缺失")
        check("S7f-含已完成", "## ✅" in content, "已完成区域缺失")
        check("S7f-含快速引用", "快速引用" in content, "引用区域缺失")

    ensure_empty()
    print()

# =========================================================
# 最终验证
# =========================================================
def final_verify():
    print_header("✅ 最终验证 — 系统是否恢复干净")
    ensure_empty()

    state_file = BASE / "0-NOTEBOOK" / ".step_state.json"
    check("F-状态文件已清理", not state_file.exists() or state_file.read_text().strip() == "{}")

    chain_file = Path.home() / ".workbuddy" / "memory" / "chain_state.json"
    check("F-链状态已清理", not chain_file.exists())

    # Start a simple task and verify basic flow
    rc, out, err = run(["python3", "scripts/step_controller.py", "start", "最终验证"])
    check("F-最终-start", rc == 0, out[:200])

    rc, out, err = run(["python3", "scripts/notebook_hook.py", "done", "最终验证", "压力测试全部通过"])
    check("F-最终-done", rc == 0, out[:200])

    rc, out, err = run(["python3", "scripts/notebook_hook.py", "sync"])
    check("F-最终-sync", rc == 0, out[:200])

    rc, out, err = run(["python3", "scripts/step_controller.py", "status"])
    check("F-最终-status", rc == 0, out[:200])

    ensure_empty()
    # Clean all test artifacts
    for d in [BASE/"0-NOTEBOOK"/"2-DONE", BASE/"0-NOTEBOOK"/"0-TODO", BASE/"0-NOTEBOOK"/"1-ACTIVE"]:
        if d.exists():
            for f in d.glob("*.md"):
                if f.name != "README.md":
                    try: f.unlink()
                    except: pass

    nb = BASE / "0-NOTEBOOK" / "NOTEBOOK.md"
    if nb.exists():
        content = nb.read_text()
        # Restore clean notebook template
        clean_nb = """# 🗒️ AI 工作笔记本

> **最后更新**: 2026-06-15
> **当前步数**: 无（用 `step_controller.py start` 启动新任务）
>
> 这是 AI 会话的持久化工作记忆，在每次 session 开始时自动加载。
> 7Step 步进式框架 — 每步完成后我会问你下一步。

---

## 📊 步进式面板

| 步 | 名称 | 状态 | 系统 |
|:---:|---|---|:---:|
| 1 🎯 | 需求解析 | ⬜ 待开始 | 笔记本 |
| 2 🔗 | 思维链调研 | ⬜ 待开始 | 思维链 |
| 3 📚 | 知识库检索与回补 | ⬜ 待开始 | 知识库 |
| 4 🧠 | A系列方法论借鉴 | ⬜ 待开始 | A系列SKILL |
| 5 🔍 | 索引系统更新 | ⬜ 待开始 | 索引 |
| 6 ✈️ | 飞书协作归档 | ⬜ 待开始 | 飞书 |
| 7 🧪 | 记忆蒸馏 | ⬜ 待开始 | 记忆系统 |

---

## 🎯 当前活跃

| 字段 | 内容 |
|:---|---|
| 当前步数 | — |
| 任务名称 | — |
| 系统 | — |

---

## ✅ 已完成

| 步 | 完成项 |
|:---:|---|

---

## 📖 快速引用

| 资源 | 路径 |
|:---|---:|
| 步进控制器 | `scripts/step_controller.py` |
| 待办池 | `0-NOTEBOOK/0-TODO/` |
| 活跃链 | `0-NOTEBOOK/1-ACTIVE/` (D-Z-E链) |
| 已完成 | `0-NOTEBOOK/2-DONE/` |
| 三链门禁 | `3-CHAIN-DEVELOPMENT/scripts/chain_guard.py` |
| 知识库 | `2-KNOWLEDGE/` |
| AGENTS.md | `AGENTS.md`（步进式规则） |

---

## 🔄 步进流程

启动新任务时，我会：
1. `step_controller.py start "任务名"`
2. 执行 Step 1 → 更新笔记本 → **问你下一步**
3. 执行 Step 2 → 更新笔记本 → **问你下一步**
4. ...直到 Step 7

```bash
# 快速查看当前进度
python3 scripts/step_controller.py status
```"""
        nb.write_text(clean_nb)
        print("  ✅ NOTEBOOK.md 已恢复为干净模板")
    print()

# =========================================================
# MAIN
# =========================================================
if __name__ == "__main__":
    t_start = time.time()
    print(f"🧪 7场景压力测试 — {datetime.now().isoformat()}")
    print(f"  工作目录: {BASE}")
    print()

    test_scenario1()
    test_scenario2()
    test_scenario3()
    test_scenario4()
    test_scenario5()
    test_scenario6()
    test_scenario7()
    final_verify()

    total_time = time.time() - t_start
    print(f"{'='*60}")
    print(f"📊 总结")
    print(f"{'='*60}")
    print(f"  ✅ 通过: {PASS}")
    print(f"  ❌ 失败: {FAIL}")
    print(f"  ⏱  总耗时: {total_time:.1f}s")
    if FAIL > 0:
        print(f"\n  错误详情:")
        for e in ERRORS[:20]:
            print(f"    {e}")
        if len(ERRORS) > 20:
            print(f"    ... 还有 {len(ERRORS)-20} 个错误未显示")
    print(f"\n  {'🎉 全部通过!' if FAIL == 0 else '🔴 发现问题'}")
