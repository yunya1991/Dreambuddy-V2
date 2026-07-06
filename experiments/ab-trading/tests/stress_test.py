#!/usr/bin/env python3
"""
AB实验调度系统压力测试
======================
测试范围（18个场景）：
  A组 - orchestrator 4层触发决策（6场景）：4H心跳/市场波动/Agent申请/优先级/过期清理/等待态
  B组 - Agent A 自调度4场景：高置信度/成交量异常/连败保护/置信度近门槛
  C组 - Agent B 自调度3场景：矛盾清晰/置信度近门槛+A2看多/连败保护
  D组 - 边缘case（5场景）：连败4次/置信度边界/空文件/多pending排序/时间控制

运行方式：
  cd experiments/ab-trading
  python3 tests/stress_test.py
"""
import os, sys, json, time, tempfile, shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

# ── 路径设置 ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "agents"))

# ── 导入被测模块 ────────────────────────────────────────────────────────────
import orchestrator
from agent_a_runner import _self_schedule
from agent_b_runner import _b_self_schedule

# ── 备份原始路径（测试用临时目录隔离）────────────────────────────────────────
ORIGINAL_SCHED_FILE = orchestrator.SCHED_FILE
ORIGINAL_STATE_FILE = orchestrator.STATE_FILE

# ── 测试结果收集 ────────────────────────────────────────────────────────────
results = []
stats = {"total": 0, "passed": 0, "failed": 0}


def setup_env():
    """创建隔离的临时测试环境"""
    tmpdir = tempfile.mkdtemp(prefix="ab_stress_")
    orchestrator.SCHED_FILE = Path(tmpdir) / "self_schedule.json"
    orchestrator.STATE_FILE = Path(tmpdir) / "orchestrator_state.json"
    orchestrator.SCHED_FILE.parent.mkdir(parents=True, exist_ok=True)
    # 初始化空申请文件
    with open(orchestrator.SCHED_FILE, "w") as f:
        json.dump([], f)
    return tmpdir


def teardown_env(tmpdir):
    """恢复原始路径并清理"""
    orchestrator.SCHED_FILE = ORIGINAL_SCHED_FILE
    orchestrator.STATE_FILE = ORIGINAL_STATE_FILE
    shutil.rmtree(tmpdir, ignore_errors=True)


def write_sched(requests_list):
    """写入 self_schedule.json 测试数据"""
    with open(orchestrator.SCHED_FILE, "w") as f:
        json.dump(requests_list, f)


def record(name, category, expected, actual, passed, detail=""):
    stats["total"] += 1
    if passed:
        stats["passed"] += 1
    else:
        stats["failed"] += 1
    results.append({
        "name": name, "category": category,
        "expected": expected, "actual": actual,
        "passed": passed, "detail": detail
    })
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"  {status} | {name}")
    if not passed:
        print(f"         预期: {expected}")
        print(f"         实际: {actual}")


# ════════════════════════════════════════════════════════════════════════════
# A组 - orchestrator 4层触发决策（6场景）
# ════════════════════════════════════════════════════════════════════════════
def test_a1_heartbeat_4h():
    """T1: 4H心跳触发 - last_run_ts距今5H，无申请/无波动/无事件"""
    now = time.time()
    state = {"last_run_ts": now - 5 * 3600, "run_count": 0}
    write_sched([])
    with patch.object(orchestrator, "check_market_volatility",
                      return_value={"change_pct": 0, "direction": "NEUTRAL"}), \
         patch.object(orchestrator, "check_upcoming_events_local", return_value=[]):
        trigger, reason = orchestrator.should_trigger(state)
    passed = trigger and "常规心跳" in reason and "5.0H" in reason
    record("T1: 4H心跳触发(距上次5H)",
           "A-orchestrator-4层触发",
           "trigger=True, reason含'常规心跳'+5.0H",
           f"trigger={trigger}, reason={reason}", passed)


def test_a2_market_volatility():
    """T2: 市场波动触发 - BTC 1H涨4%，距上次仅1H（不到4H心跳）"""
    now = time.time()
    state = {"last_run_ts": now - 1 * 3600, "run_count": 0}
    write_sched([])
    with patch.object(orchestrator, "check_market_volatility",
                      return_value={"change_pct": 4.0, "direction": "UP"}), \
         patch.object(orchestrator, "check_upcoming_events_local", return_value=[]):
        trigger, reason = orchestrator.should_trigger(state)
    passed = trigger and "市场波动" in reason and "4.0" in reason and "UP" in reason
    record("T2: 市场波动触发(BTC 1H +4.0%)",
           "A-orchestrator-4层触发",
           "trigger=True, reason含'市场波动'+4.0+UP",
           f"trigger={trigger}, reason={reason}", passed)


def test_a3_agent_request():
    """T3: Agent申请触发 - 有pending normal申请，距上次仅1H"""
    now = time.time()
    state = {"last_run_ts": now - 1 * 3600, "run_count": 0}
    write_sched([{
        "reason": "A高置信度78%信号",
        "run_at_ts": now - 600,        # 10分钟前到点
        "expires_ts": now + 3000,       # 50分钟后过期
        "priority": "normal",
        "created_ts": now - 700,
    }])
    with patch.object(orchestrator, "check_market_volatility",
                      return_value={"change_pct": 0, "direction": "NEUTRAL"}), \
         patch.object(orchestrator, "check_upcoming_events_local", return_value=[]):
        trigger, reason = orchestrator.should_trigger(state)
    passed = trigger and "Agent自主申请" in reason and "78%" in reason
    record("T3: Agent申请触发(pending normal)",
           "A-orchestrator-4层触发",
           "trigger=True, reason含'Agent自主申请'+78%",
           f"trigger={trigger}, reason={reason}", passed)


def test_a4_priority_urgent_wins():
    """T4: 优先级测试 - urgent+normal+市场波动+4H同时存在，urgent Agent申请应胜出"""
    now = time.time()
    state = {"last_run_ts": now - 5 * 3600, "run_count": 0}  # 已过5H，4H心跳也满足
    write_sched([
        {  # normal申请
            "reason": "A高置信度75%信号",
            "run_at_ts": now - 600,
            "expires_ts": now + 3000,
            "priority": "normal",
            "created_ts": now - 700,
        },
        {  # urgent申请
            "reason": "A连败3次，6H后复盘",
            "run_at_ts": now - 500,
            "expires_ts": now + 3100,
            "priority": "urgent",
            "created_ts": now - 800,
        },
    ])
    # 市场波动也满足（4%≥3%）
    with patch.object(orchestrator, "check_market_volatility",
                      return_value={"change_pct": 4.0, "direction": "DOWN"}), \
         patch.object(orchestrator, "check_upcoming_events_local", return_value=[]):
        trigger, reason = orchestrator.should_trigger(state)
    # 应该返回 urgent 申请，而不是 normal 或 市场波动
    passed = trigger and "连败3次" in reason and "urgent" not in reason.lower()
    record("T4: 优先级测试(urgent>normal>波动>4H)",
           "A-orchestrator-4层触发",
           "trigger=True, reason含'连败3次'(urgent优先)",
           f"trigger={trigger}, reason={reason}", passed)


def test_a5_expired_cleanup():
    """T5: 过期申请清理 - 申请expires_ts已过，应被清理且不触发"""
    now = time.time()
    state = {"last_run_ts": now - 0.5 * 3600, "run_count": 0}  # 距上次0.5H
    write_sched([{
        "reason": "旧的高置信度信号",
        "run_at_ts": now - 7200,        # 2H前到点
        "expires_ts": now - 3600,        # 1H前已过期
        "priority": "normal",
        "created_ts": now - 8000,
    }])
    with patch.object(orchestrator, "check_market_volatility",
                      return_value={"change_pct": 0, "direction": "NEUTRAL"}), \
         patch.object(orchestrator, "check_upcoming_events_local", return_value=[]):
        trigger, reason = orchestrator.should_trigger(state)
    # 应该不触发（申请已过期，距上次0.5H不到4H，无波动无事件）
    passed = (not trigger) and "等待中" in reason
    # 验证文件已被清理
    with open(orchestrator.SCHED_FILE) as f:
        remaining = json.load(f)
    cleaned = len(remaining) == 0
    passed = passed and cleaned
    record("T5: 过期申请清理(expires_ts已过)",
           "A-orchestrator-4层触发",
           "trigger=False, 申请被清理(remaining=0)",
           f"trigger={trigger}, reason={reason}, remaining={len(remaining)}", passed)


def test_a6_waiting_state():
    """T6: 等待状态 - 距上次1H，无申请/无波动/无事件 → 不触发"""
    now = time.time()
    state = {"last_run_ts": now - 1 * 3600, "run_count": 0}
    write_sched([])
    with patch.object(orchestrator, "check_market_volatility",
                      return_value={"change_pct": 1.5, "direction": "UP"}), \
         patch.object(orchestrator, "check_upcoming_events_local", return_value=[]):
        trigger, reason = orchestrator.should_trigger(state)
    passed = (not trigger) and "等待中" in reason and "1.0H" in reason
    record("T6: 等待状态(距上次1H，波动1.5%<3%)",
           "A-orchestrator-4层触发",
           "trigger=False, reason含'等待中'+1.0H",
           f"trigger={trigger}, reason={reason}", passed)


# ════════════════════════════════════════════════════════════════════════════
# B组 - Agent A 自调度4场景
# ════════════════════════════════════════════════════════════════════════════
def test_b1_high_confidence():
    """T7: Agent A 高置信度 - conf=0.78, action=LONG → 1H normal申请"""
    write_sched([])
    with patch("agent_a_runner.request_early_run") as mock_req:
        decision = {"action": "LONG", "confidence": 0.78}
        mkt = {"coins": {"BTC": {"vol_ratio": 1.0}}}
        memory = {"loss_streak": 0}
        _self_schedule(decision, mkt, memory)
        calls = mock_req.call_args_list
    # 应调用1次：高置信度场景
    passed = len(calls) == 1
    detail = ""
    if calls:
        args, kwargs = calls[0]
        reason = args[0] if args else kwargs.get("reason", "")
        run_at_ts = kwargs.get("run_at_ts", args[1] if len(args) > 1 else 0)
        priority = kwargs.get("priority", "normal")
        now = time.time()
        delta_h = (run_at_ts - now) / 3600
        passed = passed and "高置信度" in reason and "78%" in reason \
                 and priority == "normal" and 0.9 <= delta_h <= 1.1
        detail = f"reason={reason}, priority={priority}, delta={delta_h:.2f}H"
    record("T7: Agent A 高置信度(78%→1H normal)",
           "B-AgentA-自调度",
           "调用1次, reason含'高置信度'+78%', priority=normal, delta≈1H",
           f"调用{len(calls)}次, {detail}", passed)


def test_b2_volume_anomaly():
    """T8: Agent A 成交量异常 - vol_ratio=3.0 → 2H normal申请"""
    write_sched([])
    with patch("agent_a_runner.request_early_run") as mock_req:
        decision = {"action": "HOLD", "confidence": 0.5}
        mkt = {"coins": {"BTC": {"vol_ratio": 3.0}, "ETH": {"vol_ratio": 1.0}}}
        memory = {"loss_streak": 0}
        _self_schedule(decision, mkt, memory)
        calls = mock_req.call_args_list
    passed = len(calls) == 1
    detail = ""
    if calls:
        args, kwargs = calls[0]
        reason = args[0] if args else kwargs.get("reason", "")
        run_at_ts = kwargs.get("run_at_ts", args[1] if len(args) > 1 else 0)
        priority = kwargs.get("priority", "normal")
        now = time.time()
        delta_h = (run_at_ts - now) / 3600
        passed = passed and "成交量异常" in reason and "3.0" in reason \
                 and priority == "normal" and 1.9 <= delta_h <= 2.1
        detail = f"reason={reason}, priority={priority}, delta={delta_h:.2f}H"
    record("T8: Agent A 成交量异常(3.0x→2H normal)",
           "B-AgentA-自调度",
           "调用1次, reason含'成交量异常'+3.0', priority=normal, delta≈2H",
           f"调用{len(calls)}次, {detail}", passed)


def test_b3_loss_streak_urgent():
    """T9: Agent A 连败3次 - loss_streak=3 → 6H urgent申请"""
    write_sched([])
    with patch("agent_a_runner.request_early_run") as mock_req:
        decision = {"action": "HOLD", "confidence": 0.5}
        mkt = {"coins": {"BTC": {"vol_ratio": 1.0}}}
        memory = {"loss_streak": 3}
        _self_schedule(decision, mkt, memory)
        calls = mock_req.call_args_list
    passed = len(calls) == 1
    detail = ""
    if calls:
        args, kwargs = calls[0]
        reason = args[0] if args else kwargs.get("reason", "")
        run_at_ts = kwargs.get("run_at_ts", args[1] if len(args) > 1 else 0)
        priority = kwargs.get("priority", "normal")
        now = time.time()
        delta_h = (run_at_ts - now) / 3600
        passed = passed and "连败3次" in reason and priority == "urgent" \
                 and 5.9 <= delta_h <= 6.1
        detail = f"reason={reason}, priority={priority}, delta={delta_h:.2f}H"
    record("T9: Agent A 连败3次(→6H urgent)",
           "B-AgentA-自调度",
           "调用1次, reason含'连败3次', priority=urgent, delta≈6H",
           f"调用{len(calls)}次, {detail}", passed)


def test_b4_near_threshold():
    """T10: Agent A 置信度近门槛 - conf=0.60, HOLD → 1H normal申请"""
    write_sched([])
    with patch("agent_a_runner.request_early_run") as mock_req:
        decision = {"action": "HOLD", "confidence": 0.60}
        mkt = {"coins": {"BTC": {"vol_ratio": 1.0}}}
        memory = {"loss_streak": 0}
        _self_schedule(decision, mkt, memory)
        calls = mock_req.call_args_list
    passed = len(calls) == 1
    detail = ""
    if calls:
        args, kwargs = calls[0]
        reason = args[0] if args else kwargs.get("reason", "")
        run_at_ts = kwargs.get("run_at_ts", args[1] if len(args) > 1 else 0)
        priority = kwargs.get("priority", "normal")
        now = time.time()
        delta_h = (run_at_ts - now) / 3600
        passed = passed and "接近门槛" in reason and "60%" in reason \
                 and priority == "normal" and 0.9 <= delta_h <= 1.1
        detail = f"reason={reason}, priority={priority}, delta={delta_h:.2f}H"
    record("T10: Agent A 置信度60% HOLD(→1H normal)",
           "B-AgentA-自调度",
           "调用1次, reason含'接近门槛'+60%', priority=normal, delta≈1H",
           f"调用{len(calls)}次, {detail}", passed)


# ════════════════════════════════════════════════════════════════════════════
# C组 - Agent B 自调度3场景
# ════════════════════════════════════════════════════════════════════════════
def test_c1_contradiction_clear():
    """T11: Agent B 矛盾清晰 - conflict=0, bull=5, bear=1 → 2H normal"""
    write_sched([])
    with patch("agent_b_runner.request_early_run") as mock_req:
        final = {"confidence": 0.7}
        a0 = {"conflict_count": 0, "bull_count": 5, "bear_count": 1}
        a2 = {"least_resistance": "NEUTRAL"}
        memory = {"loss_streaks": 0}
        _b_self_schedule(final, a0, a2, memory)
        calls = mock_req.call_args_list
    passed = len(calls) == 1
    detail = ""
    if calls:
        args, kwargs = calls[0]
        reason = args[0] if args else kwargs.get("reason", "")
        run_at_ts = kwargs.get("run_at_ts", args[1] if len(args) > 1 else 0)
        priority = kwargs.get("priority", "normal")
        now = time.time()
        delta_h = (run_at_ts - now) / 3600
        passed = passed and "矛盾清晰" in reason and "多" in reason \
                 and priority == "normal" and 1.9 <= delta_h <= 2.1
        detail = f"reason={reason}, priority={priority}, delta={delta_h:.2f}H"
    record("T11: Agent B 矛盾清晰(bull=5,bear=1→2H normal)",
           "C-AgentB-自调度",
           "调用1次, reason含'矛盾清晰'+多', priority=normal, delta≈2H",
           f"调用{len(calls)}次, {detail}", passed)


def test_c2_near_threshold_a2_up():
    """T12: Agent B 置信度60% + A2 UP → 1H normal"""
    write_sched([])
    with patch("agent_b_runner.request_early_run") as mock_req:
        final = {"confidence": 0.60}
        a0 = {"conflict_count": 2, "bull_count": 3, "bear_count": 1}
        a2 = {"least_resistance": "UP"}
        memory = {"loss_streaks": 0}
        _b_self_schedule(final, a0, a2, memory)
        calls = mock_req.call_args_list
    passed = len(calls) == 1
    detail = ""
    if calls:
        args, kwargs = calls[0]
        reason = args[0] if args else kwargs.get("reason", "")
        run_at_ts = kwargs.get("run_at_ts", args[1] if len(args) > 1 else 0)
        priority = kwargs.get("priority", "normal")
        now = time.time()
        delta_h = (run_at_ts - now) / 3600
        passed = passed and "接近门槛" in reason and "60%" in reason \
                 and priority == "normal" and 0.9 <= delta_h <= 1.1
        detail = f"reason={reason}, priority={priority}, delta={delta_h:.2f}H"
    record("T12: Agent B 置信度60%+A2 UP(→1H normal)",
           "C-AgentB-自调度",
           "调用1次, reason含'接近门槛'+60%', priority=normal, delta≈1H",
           f"调用{len(calls)}次, {detail}", passed)


def test_c3_loss_streak_3():
    """T13: Agent B 连败恰好3次 - loss_streaks==3 → 6H urgent"""
    write_sched([])
    with patch("agent_b_runner.request_early_run") as mock_req:
        final = {"confidence": 0.7}
        a0 = {"conflict_count": 2, "bull_count": 3, "bear_count": 2}
        a2 = {"least_resistance": "NEUTRAL"}
        memory = {"loss_streaks": 3}
        _b_self_schedule(final, a0, a2, memory)
        calls = mock_req.call_args_list
    passed = len(calls) == 1
    detail = ""
    if calls:
        args, kwargs = calls[0]
        reason = args[0] if args else kwargs.get("reason", "")
        run_at_ts = kwargs.get("run_at_ts", args[1] if len(args) > 1 else 0)
        priority = kwargs.get("priority", "normal")
        now = time.time()
        delta_h = (run_at_ts - now) / 3600
        passed = passed and "连败" in reason and priority == "urgent" \
                 and 5.9 <= delta_h <= 6.1
        detail = f"reason={reason}, priority={priority}, delta={delta_h:.2f}H"
    record("T13: Agent B 连败恰好3次(→6H urgent)",
           "C-AgentB-自调度",
           "调用1次, reason含'连败', priority=urgent, delta≈6H",
           f"调用{len(calls)}次, {detail}", passed)


# ════════════════════════════════════════════════════════════════════════════
# D组 - 边缘case（5场景）
# ════════════════════════════════════════════════════════════════════════════
def test_d1_b_loss_streak_4_no_trigger():
    """T14: Agent B 连败4次 - loss_streaks==4（≠3）→ 不触发连败场景"""
    write_sched([])
    with patch("agent_b_runner.request_early_run") as mock_req:
        final = {"confidence": 0.7}
        a0 = {"conflict_count": 2, "bull_count": 3, "bear_count": 2}
        a2 = {"least_resistance": "NEUTRAL"}
        memory = {"loss_streaks": 4}  # 注意是 ==3 判断，4不会触发
        _b_self_schedule(final, a0, a2, memory)
        calls = mock_req.call_args_list
    # 连败场景不触发（因为是 ==3 而非 >=3）
    passed = len(calls) == 0
    record("T14: Agent B 连败4次(==3判断,不触发)",
           "D-边缘case",
           "调用0次(连败场景不触发)",
           f"调用{len(calls)}次", passed)


def test_d2_a_confidence_boundary_65():
    """T15: Agent A 置信度65% - 边界值(0.58<=conf<0.65 不含65) → 不触发近门槛"""
    write_sched([])
    with patch("agent_a_runner.request_early_run") as mock_req:
        decision = {"action": "HOLD", "confidence": 0.65}  # 边界外
        mkt = {"coins": {"BTC": {"vol_ratio": 1.0}}}
        memory = {"loss_streak": 0}
        _self_schedule(decision, mkt, memory)
        calls = mock_req.call_args_list
    # 0.65 不在 [0.58, 0.65) 范围内
    passed = len(calls) == 0
    record("T15: Agent A 置信度65%(边界外不触发)",
           "D-边缘case",
           "调用0次(conf=0.65不在[0.58,0.65))",
           f"调用{len(calls)}次", passed)


def test_d3_a_confidence_below_58():
    """T16: Agent A 置信度57.9% - 低于0.58 → 不触发近门槛"""
    write_sched([])
    with patch("agent_a_runner.request_early_run") as mock_req:
        decision = {"action": "HOLD", "confidence": 0.579}
        mkt = {"coins": {"BTC": {"vol_ratio": 1.0}}}
        memory = {"loss_streak": 0}
        _self_schedule(decision, mkt, memory)
        calls = mock_req.call_args_list
    passed = len(calls) == 0
    record("T16: Agent A 置信度57.9%(低于0.58不触发)",
           "D-边缘case",
           "调用0次(conf=0.579<0.58)",
           f"调用{len(calls)}次", passed)


def test_d4_empty_schedule_file():
    """T17: 空self_schedule.json - 应正常处理不报错"""
    now = time.time()
    state = {"last_run_ts": now - 0.5 * 3600, "run_count": 0}
    # 写入空数组
    write_sched([])
    with patch.object(orchestrator, "check_market_volatility",
                      return_value={"change_pct": 0, "direction": "NEUTRAL"}), \
         patch.object(orchestrator, "check_upcoming_events_local", return_value=[]):
        trigger, reason = orchestrator.should_trigger(state)
    passed = (not trigger) and "等待中" in reason
    record("T17: 空self_schedule.json处理",
           "D-边缘case",
           "trigger=False, reason含'等待中'",
           f"trigger={trigger}, reason={reason}", passed)


def test_d5_multiple_pending_sort():
    """T18: 多pending申请排序 - 2 normal + 1 urgent，urgent应排第一"""
    now = time.time()
    state = {"last_run_ts": now - 0.5 * 3600, "run_count": 0}
    write_sched([
        {"reason": "normal申请1", "run_at_ts": now - 600,
         "expires_ts": now + 3000, "priority": "normal", "created_ts": now - 700},
        {"reason": "normal申请2", "run_at_ts": now - 500,
         "expires_ts": now + 3100, "priority": "normal", "created_ts": now - 600},
        {"reason": "urgent连败3次", "run_at_ts": now - 400,
         "expires_ts": now + 3200, "priority": "urgent", "created_ts": now - 800},
    ])
    with patch.object(orchestrator, "check_market_volatility",
                      return_value={"change_pct": 0, "direction": "NEUTRAL"}), \
         patch.object(orchestrator, "check_upcoming_events_local", return_value=[]):
        trigger, reason = orchestrator.should_trigger(state)
    passed = trigger and "urgent连败3次" in reason
    record("T18: 多pending排序(2normal+1urgent,urgent优先)",
           "D-边缘case",
           "trigger=True, reason含'urgent连败3次'",
           f"trigger={trigger}, reason={reason}", passed)


# ════════════════════════════════════════════════════════════════════════════
# 集成测试 - 端到端自调度闭环
# ════════════════════════════════════════════════════════════════════════════
def test_e1_e2e_self_schedule_loop():
    """T19: 端到端闭环 - Agent A写申请 → orchestrator读取并触发"""
    # _self_schedule 内部用 `import time as _t` 局部导入，无法 patch 模块属性
    # 改为真实写入申请，然后 patch 全局 time.time 让 orchestrator 看到申请已到点
    real_now = time.time()
    state = {"last_run_ts": real_now - 0.5 * 3600, "run_count": 0}  # 距上次0.5H
    write_sched([])

    # Step 1: Agent A 写入连败3次urgent申请（真实调用 request_early_run）
    # request_early_run 会用真实 time.time() 写入 run_at_ts = now + 21600
    decision = {"action": "HOLD", "confidence": 0.5}
    mkt = {"coins": {"BTC": {"vol_ratio": 1.0}}}
    memory = {"loss_streak": 3}
    _self_schedule(decision, mkt, memory)

    # Step 2: 验证申请已写入 self_schedule.json
    with open(orchestrator.SCHED_FILE) as f:
        reqs = json.load(f)
    step2_ok = len(reqs) == 1 and reqs[0]["priority"] == "urgent" \
               and "连败3次" in reqs[0]["reason"]
    expected_run_at = reqs[0].get("run_at_ts", 0) if reqs else 0

    # Step 3: orchestrator 检查是否触发
    # mock time.time 让 orchestrator 认为 run_at_ts 已到点（now >= run_at_ts）
    # 同时 mock check_market_volatility 和 check_upcoming_events_local
    with patch.object(orchestrator, "check_market_volatility",
                      return_value={"change_pct": 0, "direction": "NEUTRAL"}), \
         patch.object(orchestrator, "check_upcoming_events_local", return_value=[]), \
         patch("orchestrator.time") as mock_otime:
        # 让 time.time() 返回 run_at_ts + 100（申请已到点100秒）
        mock_otime.time.return_value = expected_run_at + 100
        trigger, reason = orchestrator.should_trigger(state)

    step3_ok = trigger and "连败3次" in reason
    passed = step2_ok and step3_ok
    record("T19: 端到端闭环(Agent A写urgent→orchestrator触发)",
           "E-集成测试",
           "Step2: 申请写入(urgent+连败3次), Step3: orchestrator触发",
           f"step2={step2_ok}, step3={step3_ok}, trigger={trigger}, reason={reason}", passed)


def test_e2_e2e_priority_loop():
    """T20: 端到端优先级 - Agent A写normal + Agent B写urgent → urgent胜出"""
    real_now = time.time()
    state = {"last_run_ts": real_now - 0.5 * 3600, "run_count": 0}
    write_sched([])

    # Step 1: Agent A 写入高置信度normal申请（真实写入）
    decision = {"action": "LONG", "confidence": 0.78}
    mkt = {"coins": {"BTC": {"vol_ratio": 1.0}}}
    memory = {"loss_streak": 0}
    _self_schedule(decision, mkt, memory)

    # Step 2: Agent B 写入连败3次urgent申请（真实写入）
    final = {"confidence": 0.7}
    a0 = {"conflict_count": 2, "bull_count": 3, "bear_count": 2}
    a2 = {"least_resistance": "NEUTRAL"}
    memory_b = {"loss_streaks": 3}
    _b_self_schedule(final, a0, a2, memory_b)

    # Step 3: 验证两条申请都已写入
    with open(orchestrator.SCHED_FILE) as f:
        reqs = json.load(f)
    step3_ok = len(reqs) == 2
    # 找到 urgent 申请的 run_at_ts（6H后）
    urgent_run_at = max([r.get("run_at_ts", 0) for r in reqs
                         if r.get("priority") == "urgent"], default=0)

    # Step 4: orchestrator 在 urgent 到点后检查（urgent优先）
    with patch.object(orchestrator, "check_market_volatility",
                      return_value={"change_pct": 0, "direction": "NEUTRAL"}), \
         patch.object(orchestrator, "check_upcoming_events_local", return_value=[]), \
         patch("orchestrator.time") as mock_otime:
        mock_otime.time.return_value = urgent_run_at + 100
        trigger, reason = orchestrator.should_trigger(state)

    step4_ok = trigger and "连败" in reason
    passed = step3_ok and step4_ok
    record("T20: 端到端优先级(A normal + B urgent → urgent胜出)",
           "E-集成测试",
           "Step3: 2条申请写入, Step4: orchestrator选urgent(连败)",
           f"step3={step3_ok}(reqs={len(reqs)}), step4={step4_ok}, reason={reason}", passed)


# ════════════════════════════════════════════════════════════════════════════
# 主函数
# ════════════════════════════════════════════════════════════════════════════
def main():
    print("=" * 78)
    print("  AB实验调度系统 压力测试")
    print("  测试范围: orchestrator 4层触发 + Agent A/B 自调度 + 边缘case + 端到端闭环")
    print("=" * 78)

    tmpdir = setup_env()
    print(f"\n[环境] 临时隔离目录: {tmpdir}")
    print(f"[环境] SCHED_FILE: {orchestrator.SCHED_FILE}")
    print(f"[环境] STATE_FILE: {orchestrator.STATE_FILE}\n")

    all_tests = [
        # A组 - orchestrator 4层触发
        ("A组 - orchestrator 4层触发决策", [
            test_a1_heartbeat_4h,
            test_a2_market_volatility,
            test_a3_agent_request,
            test_a4_priority_urgent_wins,
            test_a5_expired_cleanup,
            test_a6_waiting_state,
        ]),
        # B组 - Agent A 自调度
        ("B组 - Agent A 自调度4场景", [
            test_b1_high_confidence,
            test_b2_volume_anomaly,
            test_b3_loss_streak_urgent,
            test_b4_near_threshold,
        ]),
        # C组 - Agent B 自调度
        ("C组 - Agent B 自调度3场景", [
            test_c1_contradiction_clear,
            test_c2_near_threshold_a2_up,
            test_c3_loss_streak_3,
        ]),
        # D组 - 边缘case
        ("D组 - 边缘case", [
            test_d1_b_loss_streak_4_no_trigger,
            test_d2_a_confidence_boundary_65,
            test_d3_a_confidence_below_58,
            test_d4_empty_schedule_file,
            test_d5_multiple_pending_sort,
        ]),
        # E组 - 端到端集成
        ("E组 - 端到端集成测试", [
            test_e1_e2e_self_schedule_loop,
            test_e2_e2e_priority_loop,
        ]),
    ]

    for group_name, tests in all_tests:
        print(f"\n── {group_name} ──")
        for test_fn in tests:
            try:
                # 每个测试前重置环境
                write_sched([])
                test_fn()
            except Exception as e:
                stats["total"] += 1
                stats["failed"] += 1
                print(f"  ❌ ERROR | {test_fn.__name__}: {type(e).__name__}: {e}")
                results.append({
                    "name": test_fn.__name__, "category": group_name,
                    "expected": "正常执行",
                    "actual": f"异常: {type(e).__name__}: {e}",
                    "passed": False, "detail": ""
                })

    teardown_env(tmpdir)

    # ── 输出汇总报告 ────────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("  压力测试汇总报告")
    print("=" * 78)
    print(f"\n  总场景数: {stats['total']}")
    print(f"  通过:     {stats['passed']} ✅")
    print(f"  失败:     {stats['failed']} ❌")
    pass_rate = (stats["passed"] / stats["total"] * 100) if stats["total"] > 0 else 0
    print(f"  通过率:   {pass_rate:.1f}%\n")

    # 分组统计
    print("  ── 分组统计 ──")
    categories = {}
    for r in results:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = {"total": 0, "passed": 0}
        categories[cat]["total"] += 1
        if r["passed"]:
            categories[cat]["passed"] += 1
    for cat, s in categories.items():
        rate = s["passed"] / s["total"] * 100
        print(f"    {cat}: {s['passed']}/{s['total']} ({rate:.0f}%)")

    # 失败详情
    failed_tests = [r for r in results if not r["passed"]]
    if failed_tests:
        print(f"\n  ── 失败场景详情 ({len(failed_tests)}个) ──")
        for r in failed_tests:
            print(f"    ❌ {r['name']}")
            print(f"       预期: {r['expected']}")
            print(f"       实际: {r['actual']}")
    else:
        print("\n  🎉 全部场景通过！系统调度逻辑验证有效。")

    print("\n" + "=" * 78)
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
