"""P8: 认知闭环 + 训练进化测试。

测试 cognitive_loop 模块的 HermesFrequencyLimiter + record/verify 闭环。
RED 阶段：assert ModuleNotFoundError / ImportError
GREEN 阶段：实现 cognitive_loop.py 使测试通过
"""
import os
import sys
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ============================================================
# 1. 模块导入测试 (RED: ModuleNotFoundError)
# ============================================================

class TestModuleImport:
    """验证 cognitive_loop 模块可导入"""

    def test_import_hermes_frequency_limiter(self):
        from core.cognitive_loop import HermesFrequencyLimiter
        assert HermesFrequencyLimiter is not None

    def test_import_close_loop(self):
        from core.cognitive_loop import close_loop
        assert callable(close_loop)

    def test_module_constants(self):
        from core.cognitive_loop import (
            MAX_DAILY_HERMES,
            MIN_INTERVAL_SECONDS,
            CASE_VALUE_THRESHOLD,
        )
        assert MAX_DAILY_HERMES == 10
        assert MIN_INTERVAL_SECONDS == 300
        assert CASE_VALUE_THRESHOLD == 0.6


# ============================================================
# 2. HermesFrequencyLimiter — should_trigger_hermes
# ============================================================

class TestShouldTriggerHermes:
    """hermes 触发条件测试"""

    def test_trigger_when_all_conditions_met(self):
        """所有条件满足 → 触发"""
        from core.cognitive_loop import HermesFrequencyLimiter
        limiter = HermesFrequencyLimiter()
        assert limiter.should_trigger_hermes(0.8) is True

    def test_no_trigger_when_daily_exceeded(self):
        """每日次数超上限 → 不触发"""
        from core.cognitive_loop import HermesFrequencyLimiter, MAX_DAILY_HERMES
        limiter = HermesFrequencyLimiter()
        limiter._daily_count = MAX_DAILY_HERMES
        assert limiter.should_trigger_hermes(0.8) is False

    def test_no_trigger_when_interval_too_short(self):
        """间隔不足 → 不触发"""
        from core.cognitive_loop import HermesFrequencyLimiter, MIN_INTERVAL_SECONDS
        limiter = HermesFrequencyLimiter()
        limiter._last_hermes_ts = time.time()  # 刚触发过
        assert limiter.should_trigger_hermes(0.8) is False

    def test_no_trigger_when_case_value_low(self):
        """案例价值 < 0.6 → 不触发"""
        from core.cognitive_loop import HermesFrequencyLimiter
        limiter = HermesFrequencyLimiter()
        assert limiter.should_trigger_hermes(0.5) is False

    def test_trigger_when_interval_sufficient(self):
        """间隔足够 → 触发"""
        from core.cognitive_loop import HermesFrequencyLimiter
        limiter = HermesFrequencyLimiter()
        limiter._last_hermes_ts = time.time() - 301  # 5 分钟前
        assert limiter.should_trigger_hermes(0.7) is True

    def test_case_value_boundary(self):
        """case_value == 0.6 边界 → 触发（>= 0.6）"""
        from core.cognitive_loop import HermesFrequencyLimiter
        limiter = HermesFrequencyLimiter()
        assert limiter.should_trigger_hermes(0.6) is True


# ============================================================
# 3. HermesFrequencyLimiter — record_hermes_trigger
# ============================================================

class TestRecordHermesTrigger:
    """记录 hermes 触发测试"""

    def test_record_increments_count(self):
        from core.cognitive_loop import HermesFrequencyLimiter
        limiter = HermesFrequencyLimiter()
        assert limiter._daily_count == 0
        limiter.record_hermes_trigger()
        assert limiter._daily_count == 1
        limiter.record_hermes_trigger()
        assert limiter._daily_count == 2

    def test_record_updates_timestamp(self):
        from core.cognitive_loop import HermesFrequencyLimiter
        limiter = HermesFrequencyLimiter()
        old_ts = limiter._last_hermes_ts
        time.sleep(0.01)
        limiter.record_hermes_trigger()
        assert limiter._last_hermes_ts > old_ts


# ============================================================
# 4. HermesFrequencyLimiter — 新日重置
# ============================================================

class TestNewDayReset:
    """新日重置测试"""

    def test_reset_on_new_day(self):
        from core.cognitive_loop import HermesFrequencyLimiter
        limiter = HermesFrequencyLimiter()
        limiter._daily_count = 8
        limiter._date_key = "2025-01-01"  # 旧日期
        limiter._reset_if_new_day()
        assert limiter._daily_count == 0
        assert limiter._date_key == datetime.now().strftime("%Y-%m-%d")

    def test_no_reset_same_day(self):
        from core.cognitive_loop import HermesFrequencyLimiter
        limiter = HermesFrequencyLimiter()
        limiter._daily_count = 5
        limiter._date_key = datetime.now().strftime("%Y-%m-%d")
        limiter._reset_if_new_day()
        assert limiter._daily_count == 5  # 不重置


# ============================================================
# 5. close_loop — record + verify 闭环
# ============================================================

class TestCloseLoop:
    """close_loop 认知闭环测试"""

    def test_close_loop_records_and_verifies(self):
        """close_loop 调用 record + verify"""
        from core.cognitive_loop import close_loop

        mock_record = MagicMock(return_value={"memory_id": "VM-test-123"})
        mock_verify = MagicMock(return_value={"success": True})

        result = close_loop(
            decision="CONTINUE",
            outcome="success",
            case_value_score=0.8,
            content="test experience",
            tags="C-Drive,训练进化",
            record_fn=mock_record,
            verify_fn=mock_verify,
        )

        mock_record.assert_called_once()
        mock_verify.assert_called_once()
        assert result["memory_id"] == "VM-test-123"

    def test_close_loop_hermes_triggered(self):
        """高价值案例 → hermes 触发"""
        from core.cognitive_loop import close_loop, HermesFrequencyLimiter

        mock_record = MagicMock(return_value={"memory_id": "VM-test-456"})
        mock_verify = MagicMock(return_value={"success": True})
        fresh_limiter = HermesFrequencyLimiter()

        result = close_loop(
            decision="CONTINUE",
            outcome="success",
            case_value_score=0.8,
            content="test experience",
            record_fn=mock_record,
            verify_fn=mock_verify,
            limiter=fresh_limiter,
        )

        assert result["hermes_triggered"] is True
        assert result["degraded"] is False

    def test_close_loop_degraded_mode(self):
        """低价值案例 → hermes 不触发，降级模式"""
        from core.cognitive_loop import close_loop

        mock_record = MagicMock(return_value={"memory_id": "VM-test-789"})
        mock_verify = MagicMock(return_value={"success": True})

        result = close_loop(
            decision="CONTINUE",
            outcome="success",
            case_value_score=0.3,  # 低价值 → 不触发 hermes
            content="low value case",
            record_fn=mock_record,
            verify_fn=mock_verify,
        )

        assert result["hermes_triggered"] is False
        assert result["degraded"] is True
        # 降级模式仍 record + verify
        mock_record.assert_called_once()
        mock_verify.assert_called_once()

    def test_close_loop_success_verify_true(self):
        """outcome=success → verify(success=True)"""
        from core.cognitive_loop import close_loop

        mock_record = MagicMock(return_value={"memory_id": "VM-succ"})
        mock_verify = MagicMock(return_value={"success": True})

        close_loop(
            decision="CONTINUE",
            outcome="success",
            case_value_score=0.7,
            record_fn=mock_record,
            verify_fn=mock_verify,
        )

        mock_verify.assert_called_once()
        call_args = mock_verify.call_args
        assert call_args[1]["success"] is True or call_args[0][1] is True

    def test_close_loop_failure_verify_false(self):
        """outcome=failure → verify(success=False)"""
        from core.cognitive_loop import close_loop

        mock_record = MagicMock(return_value={"memory_id": "VM-fail"})
        mock_verify = MagicMock(return_value={"success": False})

        close_loop(
            decision="REDO",
            outcome="failure",
            case_value_score=0.7,
            record_fn=mock_record,
            verify_fn=mock_verify,
        )

        mock_verify.assert_called_once()
        call_args = mock_verify.call_args
        assert call_args[1]["success"] is False or (
            len(call_args[0]) > 1 and call_args[0][1] is False
        )

    def test_close_loop_no_memory_id_skips_verify(self):
        """record 返回无 memory_id → 跳过 verify"""
        from core.cognitive_loop import close_loop

        mock_record = MagicMock(return_value={})  # 无 memory_id
        mock_verify = MagicMock()

        result = close_loop(
            decision="CONTINUE",
            outcome="success",
            case_value_score=0.8,
            record_fn=mock_record,
            verify_fn=mock_verify,
        )

        mock_record.assert_called_once()
        mock_verify.assert_not_called()
        assert result["memory_id"] is None

    def test_close_loop_record_with_quality_b(self):
        """record 调用使用 quality_level=B"""
        from core.cognitive_loop import close_loop

        mock_record = MagicMock(return_value={"memory_id": "VM-q"})
        mock_verify = MagicMock()

        close_loop(
            decision="CONTINUE",
            outcome="success",
            case_value_score=0.7,
            content="quality test",
            record_fn=mock_record,
            verify_fn=mock_verify,
        )

        call_args = mock_record.call_args
        # quality_level 应该是 B
        assert call_args[1].get("quality_level") == "B" or "B" in str(call_args)


# ============================================================
# 6. close_loop — FAIL-OPEN 机制
# ============================================================

class TestFailOpen:
    """record/verify 失败时 FAIL-OPEN"""

    def test_record_failure_does_not_raise(self):
        """record 失败 → 不抛异常，FAIL-OPEN"""
        from core.cognitive_loop import close_loop

        mock_record = MagicMock(side_effect=Exception("record failed"))
        mock_verify = MagicMock()

        # 不应抛异常
        result = close_loop(
            decision="CONTINUE",
            outcome="success",
            case_value_score=0.7,
            record_fn=mock_record,
            verify_fn=mock_verify,
        )
        assert result["memory_id"] is None

    def test_verify_failure_does_not_raise(self):
        """verify 失败 → 不抛异常，FAIL-OPEN"""
        from core.cognitive_loop import close_loop

        mock_record = MagicMock(return_value={"memory_id": "VM-err"})
        mock_verify = MagicMock(side_effect=Exception("verify failed"))

        result = close_loop(
            decision="CONTINUE",
            outcome="success",
            case_value_score=0.7,
            record_fn=mock_record,
            verify_fn=mock_verify,
        )
        assert result["memory_id"] == "VM-err"
