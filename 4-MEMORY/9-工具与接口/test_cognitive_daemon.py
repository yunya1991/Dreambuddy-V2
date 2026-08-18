#!/usr/bin/env python3
"""
认知守护进程测试 — TDD红阶段
验证文件监听daemon的核心逻辑
"""

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent))


def test_daemon_scan_changed_files():
    """daemon：扫描变更文件，基于mtime快照对比"""
    from cognitive_daemon import scan_changed_files

    tmpdir = tempfile.mkdtemp()
    try:
        # 创建初始文件
        f1 = Path(tmpdir) / "code.py"
        f1.write_text("print('hello')")
        f2 = Path(tmpdir) / "doc.md"
        f2.write_text("# Doc")

        # 第一次快照
        snapshot1 = scan_changed_files(tmpdir)
        assert isinstance(snapshot1, dict)
        assert len(snapshot1) == 2, f"快照应含2个文件: {len(snapshot1)}"

        # 等待一下确保mtime不同
        time.sleep(0.1)

        # 修改一个文件
        f1.write_text("print('hello world')")
        # 新增一个文件
        f3 = Path(tmpdir) / "new.py"
        f3.write_text("new file")

        # 第二次快照，对比变更
        changed = scan_changed_files(tmpdir, snapshot1)
        assert isinstance(changed, dict)
        assert "code.py" in changed or any("code.py" in k for k in changed), f"应检测到code.py变更: {changed}"
        assert "new.py" in changed or any("new.py" in k for k in changed), f"应检测到new.py新增: {changed}"
        # doc.md没变，不应在changed中
        assert "doc.md" not in changed, f"doc.md未变更不应出现: {changed}"

        print("✅ test_daemon_scan_changed_files 通过")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_daemon_filter_code_files():
    """daemon：只监听代码文件，忽略无关文件"""
    from cognitive_daemon import is_code_file

    assert is_code_file("hello.py") == True
    assert is_code_file("hello.js") == True
    assert is_code_file("hello.ts") == True
    assert is_code_file("hello.md") == True
    assert is_code_file("hello.json") == True
    assert is_code_file("hello.yaml") == True
    assert is_code_file("hello.sh") == True

    # 非代码文件
    assert is_code_file("image.png") == False
    assert is_code_file("video.mp4") == False
    assert is_code_file("data.db") == False
    assert is_code_file(".DS_Store") == False
    assert is_code_file("__pycache__/foo.pyc") == False
    assert is_code_file(".git/config") == False

    print("✅ test_daemon_filter_code_files 通过")
    return True


def test_daemon_exclude_noise_files():
    """daemon P1：排除自动生成的噪声文件（heartbeat/.trade_time/.workbuddy等）"""
    from cognitive_daemon import is_code_file

    # === 真实 Top 噪声源（来自 action_chain 2026-08-01 体检） ===
    # 1) .workbuddy 目录下的自动产物（整个目录排除）
    assert is_code_file("11-易经推理系统/.workbuddy/memory_l4/guardian/heartbeat.json") == False, \
        ".workbuddy/下的heartbeat是噪声应排除"
    assert is_code_file("11-易经推理系统/.workbuddy/memory_l4/stats/performance.json") == False, \
        ".workbuddy/下的stats是噪声应排除"
    assert is_code_file("11-易经推理系统/.workbuddy/memory_l4/evolution/yijing_evolution.json") == False, \
        ".workbuddy/下的evolution是噪声应排除"
    assert is_code_file("11-易经推理系统/.workbuddy/memory_l4/index/latest.json") == False, \
        ".workbuddy/下的index/latest是噪声应排除"

    # 2) 隐藏交易时间文件
    assert is_code_file("1-ARCHITECTURE/dreamos/cli/.trade_time.json") == False, \
        ".trade_time.json是自动状态文件应排除"
    # 更通用的 .xxx_time.json 模式
    assert is_code_file("any/.signal_time.json") == False, ".xxx_time.json应排除"

    # 3) heartbeat.json 在任意位置都应排除
    assert is_code_file("some/sub/dir/heartbeat.json") == False, "heartbeat.json任何位置应排除"

    # === 反例：真实代码不应被误伤 ===
    assert is_code_file("11-易经推理系统/scripts/memory_l4/case_registry.py") == True, \
        "scripts下的代码应保留（scripts不是.workbuddy）"
    assert is_code_file("14-V15经典马丁策略/core/v15_trader.py") == True, \
        "真实策略代码应保留"
    assert is_code_file("1-ARCHITECTURE/dreamos/capabilities/trading/execution/auto_trader.py") == True, \
        "交易执行代码应保留"

    print("✅ test_daemon_exclude_noise_files 通过")
    return True


def test_daemon_generate_change_experience():
    """daemon：从变更文件列表生成经验描述"""
    from cognitive_daemon import generate_change_experience

    changes = {
        "4-MEMORY/9-工具与接口/bayesian_memory_updater.py": "modified",
        "4-MEMORY/9-工具与接口/test.py": "added",
    }

    desc = generate_change_experience(changes)
    assert "bayesian_memory_updater.py" in desc, f"应包含变更文件名: {desc}"
    assert "modified" in desc or "修改" in desc or "变更" in desc, f"应包含变更类型: {desc}"
    assert len(desc) > 10, f"描述太短: {desc}"

    # 空变更
    desc_empty = generate_change_experience({})
    assert desc_empty is None or len(desc_empty) == 0, "空变更应返回None或空"

    print("✅ test_daemon_generate_change_experience 通过")
    return True


def test_daemon_trigger_record():
    """daemon：变更触发record到认知系统（用mock验证）"""
    from cognitive_daemon import trigger_change_record

    changes = {
        "4-MEMORY/bayesian_memory_updater.py": "modified",
        "4-MEMORY/test.py": "added",
    }

    # P1-1 后改成 get_cle() 单例，mock get_cle 而非 CognitiveLoopEntry
    with patch("cognitive_daemon.get_cle") as mock_get_cle:
        mock_cle = MagicMock()
        mock_cle.record.return_value = "VM-DAEMON-001"
        mock_get_cle.return_value = mock_cle

        result = trigger_change_record(changes, dry_run=False)

        assert mock_cle.record.called, "record()应被调用"
        assert result["memory_id"] == "VM-DAEMON-001"
        assert result["recorded"] == True

        # 验证record的参数包含变更文件信息
        call_args = mock_cle.record.call_args
        content = call_args[1].get("content", "") or (call_args[0][0] if call_args[0] else "")
        assert "bayesian" in str(content).lower(), f"record内容应包含文件名: {content}"

        print("✅ test_daemon_trigger_record 通过")
        return True


def test_daemon_dry_run():
    """daemon：dry_run模式不产生副作用"""
    from cognitive_daemon import trigger_change_record

    changes = {"test.py": "modified"}

    # P1-1 后改成 get_cle() 单例，mock get_cle
    with patch("cognitive_daemon.get_cle") as mock_get_cle:
        mock_cle = MagicMock()
        mock_get_cle.return_value = mock_cle
        result = trigger_change_record(changes, dry_run=True)

        assert not mock_cle.record.called, "dry_run不应调用record"
        assert result["dry_run"] == True

        print("✅ test_daemon_dry_run 通过")
        return True


def test_daemon_debounce():
    """daemon：防抖机制，短时间内的多次变更合并为一次"""
    from cognitive_daemon import DebounceTimer

    # 创建防抖计时器，窗口=0.3秒
    dt = DebounceTimer(window_seconds=0.3)

    # 第一次变更
    triggered1 = dt.trigger()
    assert triggered1 == False, "首次触发不应立即执行（在窗口内）"

    # 窗口内的第二次变更
    time.sleep(0.1)
    triggered2 = dt.trigger()
    assert triggered2 == False, "窗口内第二次触发不应执行"

    # 等待窗口过期
    time.sleep(0.25)
    triggered3 = dt.trigger()
    # 窗口过期后的触发应该标记为可执行
    assert triggered3 == True, "窗口过期后应标记可执行"

    print("✅ test_daemon_debounce 通过")
    return True


def test_daemon_log_file_redirect():
    """daemon P2a：--log-file 将 verbose 输出写入日志文件（而非 stdout）"""
    from cognitive_daemon import CognitiveDaemon, _setup_log_redirect
    import io

    tmpdir = tempfile.mkdtemp()
    try:
        log_path = os.path.join(tmpdir, "daemon_test.log")

        # 调用日志重定向
        prev_stdout, prev_stderr = _setup_log_redirect(log_path, verbose=True)

        # 向 stdout 打印（模拟 daemon verbose 输出）
        print("[Daemon] 测试日志行 A")
        print("[Daemon] 测试日志行 B")

        # 恢复 stdout/stderr（避免影响后续测试）
        import sys as _sys
        _sys.stdout.flush()
        _sys.stderr.flush()
        _sys.stdout = prev_stdout
        _sys.stderr = prev_stderr

        # 验证写入了日志文件
        assert os.path.exists(log_path), f"日志文件应被创建: {log_path}"
        content = Path(log_path).read_text()
        assert "测试日志行 A" in content, f"日志应包含行A，实际：{content[:500]}"
        assert "测试日志行 B" in content, f"日志应包含行B，实际：{content[:500]}"

        print("✅ test_daemon_log_file_redirect 通过")
        return True
    finally:
        # 确保恢复
        import sys as _sys2
        if not isinstance(_sys2.stdout, io.TextIOWrapper):
            # 如果测试中途失败，强制恢复
            _sys2.stdout = sys.__stdout__
            _sys2.stderr = sys.__stderr__
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_daemon_log_file_default_path():
    """daemon P2a：日志默认路径应为 <项目根>/logs/cognitive_daemon.log"""
    from cognitive_daemon import _default_log_path

    path = _default_log_path()
    # 项目根 = 4-MEMORY/9-工具与接口/../../
    expected_leaf = os.path.join("logs", "cognitive_daemon.log")
    assert path.endswith(expected_leaf) or expected_leaf in path, \
        f"默认路径应指向 logs/cognitive_daemon.log，实际：{path}"
    assert os.path.isabs(path), "默认日志路径应是绝对路径"

    print("✅ test_daemon_log_file_default_path 通过")
    return True


if __name__ == "__main__":
    print("=" * 60)
    print("🔴 TDD RED 阶段：cognitive_daemon 测试（期望失败）")
    print("=" * 60)

    tests = [
        ("test_daemon_scan_changed_files", test_daemon_scan_changed_files),
        ("test_daemon_filter_code_files", test_daemon_filter_code_files),
        ("test_daemon_exclude_noise_files", test_daemon_exclude_noise_files),
        ("test_daemon_generate_change_experience", test_daemon_generate_change_experience),
        ("test_daemon_trigger_record", test_daemon_trigger_record),
        ("test_daemon_dry_run", test_daemon_dry_run),
        ("test_daemon_debounce", test_daemon_debounce),
        ("test_daemon_log_file_default_path", test_daemon_log_file_default_path),
        ("test_daemon_log_file_redirect", test_daemon_log_file_redirect),
    ]

    passed = 0
    failed = 0
    failures = []

    for name, fn in tests:
        print(f"\n▶ 运行: {name}")
        try:
            if fn():
                passed += 1
        except Exception as ex:
            failed += 1
            failures.append((name, f"{type(ex).__name__}: {ex}"))
            print(f"   ❌ {type(ex).__name__}: {ex}")

    print("\n" + "=" * 60)
    print(f"📊 结果: 通过 {passed} / {len(tests)}, 失败 {failed}")
    if failures:
        for n, r in failures:
            print(f"  - {n}: {r}")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)
