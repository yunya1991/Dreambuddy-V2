#!/usr/bin/env python3
"""TDD RED: P3 suggestions 定时刷新机制"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _seed_session_with_suggestions(tmpdir: str, hours_ago: float = 2,
                                    action_count: int = 0) -> tuple:
    """构造：tmpdir 下有老的 suggestions.md（hours_ago 前生成的）的会话"""
    sessions_dir = os.path.join(tmpdir, "sessions")
    session_id = "test-session-refresh"
    session_dir = os.path.join(sessions_dir, session_id)
    os.makedirs(session_dir, exist_ok=True)

    # 1) 写 .current（跨进程恢复需要）
    current_file = os.path.join(sessions_dir, ".current")
    with open(current_file, "w") as f:
        f.write(session_id)

    # 2) 写 session.json（模拟 CognitiveSession）—— 必须 status=active 才会被恢复
    created_ts = time.time() - hours_ago * 3600
    session_meta = {
        "id": session_id,
        "task_type": "认知系统修复",
        "status": "active",
        "created_at": created_ts,
        "last_activity_at": time.time() - 60,
        "total_actions": action_count,  # ⚠️ 模拟到目前为止的动作计数
        "chains": [],
    }
    with open(os.path.join(session_dir, "session.json"), "w") as f:
        json.dump(session_meta, f)

    # 3) 写 stale suggestions.md（mtime = created_ts）
    old_sug = f"""# 💡 认知系统建议
# 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(created_ts))}

## 📚 相关经验
1. 旧的建议1（过期）
"""
    sug_file = os.path.join(session_dir, "suggestions.md")
    with open(sug_file, "w") as f:
        f.write(old_sug)
    os.utime(sug_file, (created_ts, created_ts))

    return sessions_dir, session_id, sug_file


def test_should_refresh_true_when_ttl_expired():
    """P3: TTL过期（>15min）→ should_refresh=True，哪怕动作数=0"""
    from cognitive_session import CognitiveSessionManager
    from auto_update_trigger import SuggestionsRefresher

    tmpdir = tempfile.mkdtemp()
    try:
        sessions_dir, sid, _ = _seed_session_with_suggestions(tmpdir, hours_ago=1.0)  # 1小时前（TTL 15min已超）
        mgr = CognitiveSessionManager(sessions_dir=sessions_dir)
        refresher = SuggestionsRefresher(ttl_seconds=15 * 60, action_threshold=5)

        # 传 mgr（能访问 sessions_dir → 能读 mtime），TTL过期仍然刷新
        assert refresher.should_refresh(mgr, actions_since_last=0) is True, \
            "TTL过期 → 应刷新"
        print("✅ test_should_refresh_true_when_ttl_expired 通过")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_should_refresh_true_when_action_threshold_hit():
    """P3: 动作数>=阈值（>=5）→ should_refresh=True，哪怕TTL还剩很多"""
    from cognitive_session import CognitiveSessionManager
    from auto_update_trigger import SuggestionsRefresher

    tmpdir = tempfile.mkdtemp()
    try:
        sessions_dir, sid, _ = _seed_session_with_suggestions(tmpdir, hours_ago=0.01)  # 0.6分钟前（TTL未过期）
        mgr = CognitiveSessionManager(sessions_dir=sessions_dir)
        refresher = SuggestionsRefresher(ttl_seconds=15 * 60, action_threshold=5)

        # 5个新动作 → 触发（直接传 session 也能判断动作数阈值）
        assert refresher.should_refresh(mgr.current_session, actions_since_last=5) is True, \
            "动作数>=阈值 → 应刷新"
        print("✅ test_should_refresh_true_when_action_threshold_hit 通过")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_should_refresh_false_when_fresh_and_few_actions():
    """P3: 刚生成不久且动作数少 → should_refresh=False（不浪费算力重算）"""
    from cognitive_session import CognitiveSessionManager
    from auto_update_trigger import SuggestionsRefresher

    tmpdir = tempfile.mkdtemp()
    try:
        sessions_dir, sid, _ = _seed_session_with_suggestions(tmpdir, hours_ago=0.01)  # 0.6分钟前
        mgr = CognitiveSessionManager(sessions_dir=sessions_dir)
        refresher = SuggestionsRefresher(ttl_seconds=15 * 60, action_threshold=5)

        # 传 mgr（双检查）：仅 1 个动作 + TTL 未过期 → 不触发
        assert refresher.should_refresh(mgr, actions_since_last=1) is False, \
            "新 + 动作少 → 不应刷新"
        print("✅ test_should_refresh_false_when_fresh_and_few_actions 通过")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_refresh_updates_suggestions_file_keeps_history():
    """P3: 实际 refresh 会重写 suggestions.md，带 🔄 刷新次数标记 + 新时间戳"""
    from cognitive_session import CognitiveSessionManager
    from auto_update_trigger import SuggestionsRefresher

    tmpdir = tempfile.mkdtemp()
    try:
        sessions_dir, sid, sug_file = _seed_session_with_suggestions(tmpdir, hours_ago=2.0,
                                                                     action_count=10)
        mgr = CognitiveSessionManager(sessions_dir=sessions_dir)
        refresher = SuggestionsRefresher(ttl_seconds=600, action_threshold=5)

        before = Path(sug_file).read_text()

        # 记录 before 中没有 🔄 标记
        assert "🔄 刷新第" not in before

        # 刷新
        did_refresh = refresher.refresh_if_needed(mgr, actions_since_last=10)
        assert did_refresh is True, "满足刷新条件应返回 True"

        after = Path(sug_file).read_text()
        # 刷新过的应有 🔄
        assert "🔄 刷新第 1 次" in after, f"刷新后应有 🔄 标记，实际: {after[:500]}"
        # 新 suggestions 内容不应是旧的完全相同（时间戳肯定不同）
        assert before != after, "刷新后文件应有变化"
        print("✅ test_refresh_updates_suggestions_file_keeps_history 通过")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_refresh_skipped_when_not_needed():
    """P3: refresh_if_needed 在无刷新必要时是 NOOP，不会重写文件"""
    from cognitive_session import CognitiveSessionManager
    from auto_update_trigger import SuggestionsRefresher

    tmpdir = tempfile.mkdtemp()
    try:
        sessions_dir, sid, sug_file = _seed_session_with_suggestions(tmpdir, hours_ago=0.01,
                                                                     action_count=2)
        mgr = CognitiveSessionManager(sessions_dir=sessions_dir)
        refresher = SuggestionsRefresher(ttl_seconds=15 * 60, action_threshold=5)

        mtime_before = os.path.getmtime(sug_file)
        content_before = Path(sug_file).read_text()
        # 仅 1 个新动作，且 TTL 未过期 → 不刷新
        did_refresh = refresher.refresh_if_needed(mgr, actions_since_last=1)
        assert did_refresh is False, "无刷新必要时应返回 False"
        mtime_after = os.path.getmtime(sug_file)
        content_after = Path(sug_file).read_text()
        assert content_before == content_after, "NOOP 不应修改文件内容"
        print("✅ test_refresh_skipped_when_not_needed 通过")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    print("🔴 P3 RED 阶段（期望 SuggestionsRefresher 尚未定义 → ImportError）")
    tests = [
        ("ttl_expired", test_should_refresh_true_when_ttl_expired),
        ("action_threshold", test_should_refresh_true_when_action_threshold_hit),
        ("fresh_few_actions", test_should_refresh_false_when_fresh_and_few_actions),
        ("refresh_updates", test_refresh_updates_suggestions_file_keeps_history),
        ("noop_when_not_needed", test_refresh_skipped_when_not_needed),
    ]
    passed, failed = 0, 0
    for name, fn in tests:
        print(f"\n▶ {name}")
        try:
            if fn():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            print(f"   ❌ {type(e).__name__}: {e}")
    print(f"\n📊 {passed}/{len(tests)} 通过")
    sys.exit(0 if failed == 0 else 1)
