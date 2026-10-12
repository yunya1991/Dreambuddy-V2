"""
Phase 3 P0-4 FAIL-OPEN 登记制 — TDD 测试套件
覆盖: safe_call 三层分层 + ring buffer mmap + cognitive_enabled fallback

蓝图:
- L1: 现有 try/except 保留（热路径 FAIL-OPEN 不破坏）
- L2: safe_call(fn, fallback, *args) 装饰器，登记异常到 ring buffer
- L3: cognitive_enabled 关闭时，safe_call 降级为纯 try/except

硬约束: 692 基线零回归 + safe_call 不破坏现有热路径 FAIL-OPEN 语义
"""
import os
import struct
from pathlib import Path

import pytest

# ---- path inject ----
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in os.environ.get("PYTHONPATH", ""):
    os.environ["PYTHONPATH"] = REPO.as_posix() + os.pathsep + os.environ.get("PYTHONPATH", "")
if str(REPO) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(REPO))


# ==============================================================================
# TR-SC-01: safe_call 模块可导入 (RED: ModuleNotFoundError)
# ==============================================================================
class TestSafeCallModuleContract:
    """safe_call 模块契约: 导入 + 基本签名"""

    def test_TR_SC_01_module_importable(self):
        """safe_call 模块可从 dreambuddy_evolution.core.safe_call 导入"""
        from dreambuddy_evolution.core.safe_call import safe_call  # noqa: F401
        assert callable(safe_call)

    def test_TR_SC_02_safe_call_signature(self):
        """safe_call 签名: (fn, fallback, *args, **kwargs) -> 任一返回值"""
        from dreambuddy_evolution.core.safe_call import safe_call
        import inspect
        sig = inspect.signature(safe_call)
        params = list(sig.parameters.keys())
        # 必须有 fn + fallback 参数 (位置参数)
        assert "fn" in params, f"safe_call 缺少 fn 参数: {params}"
        assert "fallback" in params, f"safe_call 缺少 fallback 参数: {params}"

    def test_TR_SC_03_ring_buffer_class_exists(self):
        """ErrorRingBuffer 类可导入, 用于 mmap 持久化"""
        from dreambuddy_evolution.core.safe_call import ErrorRingBuffer  # noqa: F401
        assert ErrorRingBuffer is not None


# ==============================================================================
# TR-SC-02: safe_call 三层分层语义 (L1/L2/L3)
# ==============================================================================
class TestSafeCallLayers:
    """safe_call 三层分层: L1 保留 / L2 登记 / L3 fallback"""

    def test_TR_SC_04_L1_normal_returns_value(self):
        """L1: fn 正常执行时, 返回 fn 的返回值, 不登记"""
        from dreambuddy_evolution.core.safe_call import safe_call
        def good_fn(x): return x * 2
        result = safe_call(good_fn, fallback=-1, x=21)
        assert result == 42

    def test_TR_SC_05_L2_exception_returns_fallback_and_registers(self):
        """L2: fn 抛异常时, 返回 fallback, 并登记到 ring buffer"""
        from dreambuddy_evolution.core.safe_call import safe_call, get_ring_buffer
        from dreambuddy_evolution.agi_config import set_switch, get_switch
        original = get_switch("enable_cognitive_record")
        try:
            set_switch("enable_cognitive_record", True)
            buf = get_ring_buffer()
            buf.clear()
            def bad_fn(x): raise ValueError("boom_L2_test")
            result = safe_call(bad_fn, fallback=-1, x=10)
            assert result == -1
            entries = buf.read_all()
            assert len(entries) >= 1, "L2 未登记异常"
            last = entries[-1]
            assert "boom_L2_test" in last.get("error", "") or \
                   "ValueError" in last.get("error_type", "")
        finally:
            set_switch("enable_cognitive_record", original)

    def test_TR_SC_06_L2_registers_module_name(self):
        """L2: 登记包含 module 字段 (调用方模块名)"""
        from dreambuddy_evolution.core.safe_call import safe_call, get_ring_buffer
        from dreambuddy_evolution.agi_config import set_switch, get_switch
        original = get_switch("enable_cognitive_record")
        try:
            set_switch("enable_cognitive_record", True)
            buf = get_ring_buffer()
            buf.clear()
            def boom(): raise RuntimeError("test_module_marker")
            safe_call(boom, fallback=None)
            entries = buf.read_all()
            assert len(entries) >= 1, "L2 未登记"
            last = entries[-1]
            assert "module" in last
            assert last["module"], "module 字段为空"
        finally:
            set_switch("enable_cognitive_record", original)

    def test_TR_SC_07_L3_cognitive_disabled_fallback_only(self):
        """L3: cognitive_enabled=False 时, safe_call 不登记, 仅返回 fallback"""
        from dreambuddy_evolution.core import safe_call as sc_module
        # 临时禁用 cognitive
        from dreambuddy_evolution.agi_config import set_switch, get_switch
        original = get_switch("enable_cognitive_record")
        try:
            set_switch("enable_cognitive_record", False)
            buf_before = sc_module.get_ring_buffer().read_all()
            def boom(): raise RuntimeError("L3_no_register_test")
            result = sc_module.safe_call(boom, fallback="default")
            assert result == "default"
            buf_after = sc_module.get_ring_buffer().read_all()
            # L3 关闭时, 不新增登记
            assert len(buf_after) == len(buf_before), \
                "cognitive_enabled=False 时仍登记, 违反 L3 语义"
        finally:
            set_switch("enable_cognitive_record", original)

    def test_TR_SC_08_L3_cognitive_enabled_registers(self):
        """L3: cognitive_enabled=True 时, safe_call 登记 (恢复 L2 行为)"""
        from dreambuddy_evolution.core import safe_call as sc_module
        from dreambuddy_evolution.agi_config import set_switch, get_switch
        original = get_switch("enable_cognitive_record")
        try:
            set_switch("enable_cognitive_record", True)
            buf_before = sc_module.get_ring_buffer().read_all()
            def boom(): raise RuntimeError("L3_register_test")
            sc_module.safe_call(boom, fallback="default")
            buf_after = sc_module.get_ring_buffer().read_all()
            assert len(buf_after) > len(buf_before), \
                "cognitive_enabled=True 时未登记, 违反 L3 语义"
        finally:
            set_switch("enable_cognitive_record", original)


# ==============================================================================
# TR-SC-03: ring buffer mmap 持久化
# ==============================================================================
class TestRingBufferMmap:
    """ring buffer mmap: 固定 64KB 文件, 环形写入, 进程重启可读"""

    def test_TR_SC_09_ring_buffer_path(self):
        """ring buffer 文件路径: dreambuddy_evolution/data/error_ring.bin"""
        from dreambuddy_evolution.core.safe_call import get_ring_buffer
        buf = get_ring_buffer()
        assert buf.path.name == "error_ring.bin"
        assert "data" in buf.path.parts
        assert "dreambuddy_evolution" in buf.path.parts

    def test_TR_SC_10_ring_buffer_size_64kb(self):
        """ring buffer 文件大小: 64KB (65536 bytes)"""
        from dreambuddy_evolution.core.safe_call import get_ring_buffer
        buf = get_ring_buffer()
        # 文件存在时, 大小应为 64KB
        buf.ensure_created()
        if buf.path.exists():
            assert buf.path.stat().st_size == 64 * 1024, \
                f"ring buffer 文件大小应为 64KB, 实际: {buf.path.stat().st_size}"

    def test_TR_SC_11_ring_buffer_overwrite_oldest(self):
        """满则覆盖最旧: 写入超过容量后, 最旧的被覆盖"""
        from dreambuddy_evolution.core.safe_call import get_ring_buffer
        buf = get_ring_buffer()
        buf.clear()
        # body 65528 bytes / 单条 ~75 bytes, 1000 条 ≈ 75KB > 64KB → 必触发覆盖
        for i in range(1000):
            buf.append({
                "timestamp": 1700000000 + i,
                "module": f"test_mod_{i}",
                "error": f"error_{i}",
            })
        entries = buf.read_all()
        # 最旧的 error_0 应已被覆盖
        first_kept = entries[0] if entries else {}
        assert "error_0" not in first_kept.get("error", ""), \
            "ring buffer 未触发覆盖, 最旧条目仍存在"

    def test_TR_SC_12_ring_buffer_persists_across_instances(self):
        """进程重启可读: 新实例读取旧实例写入的数据"""
        from dreambuddy_evolution.core.safe_call import ErrorRingBuffer
        buf1 = ErrorRingBuffer()
        buf1.ensure_created()
        buf1.clear()
        buf1.append({
            "timestamp": 1700000000,
            "module": "persist_test",
            "error": "persistent_entry",
        })
        # 模拟重启: 新实例
        buf2 = ErrorRingBuffer()
        entries = buf2.read_all()
        assert any("persistent_entry" in e.get("error", "") for e in entries), \
            "ring buffer 跨实例不可读, 违反持久化语义"

    def test_TR_SC_13_ring_buffer_entry_signature(self):
        """登记条目签名: timestamp + module + error_hash (核心3字段)"""
        from dreambuddy_evolution.core.safe_call import safe_call, get_ring_buffer
        from dreambuddy_evolution.agi_config import set_switch, get_switch
        original = get_switch("enable_cognitive_record")
        try:
            set_switch("enable_cognitive_record", True)
            buf = get_ring_buffer()
            buf.clear()
            def boom(): raise ValueError("signature_test_marker")
            safe_call(boom, fallback=None)
            entries = buf.read_all()
            last = entries[-1] if entries else {}
            assert "timestamp" in last, f"缺少 timestamp 字段: {last}"
            assert "module" in last, f"缺少 module 字段: {last}"
            # error_hash 或 error/error_type 任一存在
            assert any(k in last for k in ("error_hash", "error", "error_type")), \
                f"缺少 error 签名字段: {last}"
        finally:
            set_switch("enable_cognitive_record", original)


# ==============================================================================
# TR-SC-04: cognitive_record 开关 (agi_config)
# ==============================================================================
class TestCognitiveRecordSwitch:
    """agi_config 中 enable_cognitive_record 开关"""

    def test_TR_SC_14_switch_exists_in_agi_config(self):
        """enable_cognitive_record 开关在 agi_config.AGI_SWITCHES 中"""
        from dreambuddy_evolution.agi_config import AGI_SWITCHES
        assert "enable_cognitive_record" in AGI_SWITCHES, \
            "agi_config 缺少 enable_cognitive_record 开关"

    def test_TR_SC_15_switch_default_false(self):
        """enable_cognitive_record 默认 False (Phase 3 解冻前关闭)"""
        from dreambuddy_evolution.agi_config import get_switch
        # 不被环境变量影响 (清空环境变量)
        import os
        old = os.environ.pop("ENABLE_COGNITIVE_RECORD", None)
        try:
            assert get_switch("enable_cognitive_record") is False, \
                "enable_cognitive_record 默认应为 False"
        finally:
            if old is not None:
                os.environ["ENABLE_COGNITIVE_RECORD"] = old

    def test_TR_SC_16_is_enabled_checks_agi_core(self):
        """is_enabled('enable_cognitive_record') 受 enable_agi_core 总开关约束"""
        from dreambuddy_evolution.agi_config import is_enabled, set_switch
        original_core = is_enabled("enable_agi_core")
        original_cog = is_enabled("enable_cognitive_record")
        try:
            set_switch("enable_agi_core", False)
            set_switch("enable_cognitive_record", True)
            # AGI 总开关关闭时, 子开关也应关闭
            assert is_enabled("enable_cognitive_record") is False, \
                "enable_agi_core=False 时 enable_cognitive_record 仍为 True, 违反总开关约束"
            set_switch("enable_agi_core", True)
            assert is_enabled("enable_cognitive_record") is True
        finally:
            set_switch("enable_agi_core", original_core)
            set_switch("enable_cognitive_record", original_cog)
