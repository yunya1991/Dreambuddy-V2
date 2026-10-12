"""P8: 认知闭环 + 训练进化 — L4 自进化集成
=====================================================
C-Drive 执行结果反馈到认知系统，驱动贝叶斯更新 + 蒸馏 + L4 自进化。

闭环链路:
  1. record(content=执行经验, quality_level=B, tags="C-Drive,训练进化")
  2. TAG_HOOKS: "hermes反思" → should_trigger_hermes → dream-self-iteration-workflow
  3. verify(memory_id, success) → 贝叶斯置信度更新 → 蒸馏

hermes 反思频率限制（防反思风暴）:
  - 每日最大 10 次
  - 两次间隔至少 5 分钟
  - 案例价值 >= 0.6 才触发
  - 降级策略: 配额用尽仍 record+verify 但跳过 self-iteration

关联:
  - SPEC: 35-广义认知系统协作模块/SPEC-CDrive-CognitiveSystem-Integration.md §2.5
  - 认知 MCP: mcp_cognitive (record/verify)
  - L4 自进化: dream-self-iteration-workflow
"""
import time
from datetime import datetime
from typing import Any, Callable, Dict, Optional

# ============================================================
# 频率限制参数（对齐 SPEC §2.5.2）
# ============================================================

MAX_DAILY_HERMES = 10           # 每日最大 hermes 触发次数
MIN_INTERVAL_SECONDS = 300      # 两次 hermes 间最小间隔（5 分钟）
CASE_VALUE_THRESHOLD = 0.6      # 案例价值评分阈值


# ============================================================
# HermesFrequencyLimiter — hermes 反思频率限制器
# ============================================================

class HermesFrequencyLimiter:
    """hermes 反思频率限制器（防止反思风暴）。

    hermes 反思（dream-self-iteration-workflow）是重资源操作（LLM token + skill-creator），
    不应对每次 C-Drive 执行都触发，需设频率上限。

    规则:
      1. 每日次数未超上限 (MAX_DAILY_HERMES=10)
      2. 距上次触发间隔 >= MIN_INTERVAL_SECONDS (300秒=5分钟)
      3. 案例价值评分 >= CASE_VALUE_THRESHOLD (0.6)
    """

    def __init__(self):
        self._daily_count: int = 0
        self._last_hermes_ts: float = 0.0
        self._date_key: str = datetime.now().strftime("%Y-%m-%d")

    def should_trigger_hermes(self, case_value_score: float) -> bool:
        """判断是否应触发 hermes 反思。

        Args:
            case_value_score: 案例价值评分 (0.0-1.0)

        Returns:
            True 如果应触发 hermes 反思
        """
        self._reset_if_new_day()
        if self._daily_count >= MAX_DAILY_HERMES:
            return False
        now = time.time()
        if now - self._last_hermes_ts < MIN_INTERVAL_SECONDS:
            return False
        if case_value_score < CASE_VALUE_THRESHOLD:
            return False
        return True

    def record_hermes_trigger(self):
        """记录一次 hermes 触发。"""
        self._daily_count += 1
        self._last_hermes_ts = time.time()

    def _reset_if_new_day(self):
        """新日重置计数。"""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._date_key:
            self._date_key = today
            self._daily_count = 0


# ============================================================
# 模块级单例（共享频率限制器）
# ============================================================

_global_limiter: Optional[HermesFrequencyLimiter] = None


def _get_limiter() -> HermesFrequencyLimiter:
    """获取全局频率限制器单例。"""
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = HermesFrequencyLimiter()
    return _global_limiter


# ============================================================
# 默认 record/verify 实现（调用 MCP 认知工具）
# ============================================================

def _default_record(content: str, tags: str, quality_level: str = "B") -> Dict[str, Any]:
    """默认 record 实现 — 调用 mcp_cognitive.record。

    FAIL-OPEN: 失败时返回空 dict，不抛异常。
    """
    try:
        # 延迟导入避免循环依赖
        from run_mcp import run_mcp  # type: ignore
        result = run_mcp(
            server_name="mcp_cognitive",
            tool_name="record",
            args={"content": content, "quality_level": quality_level, "tags": tags},
        )
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


def _default_verify(memory_id: str, success: bool) -> Dict[str, Any]:
    """默认 verify 实现 — 调用 mcp_cognitive.verify。

    FAIL-OPEN: 失败时返回空 dict，不抛异常。
    """
    try:
        from run_mcp import run_mcp  # type: ignore
        result = run_mcp(
            server_name="mcp_cognitive",
            tool_name="verify",
            args={"memory_id": memory_id, "success": success},
        )
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


# ============================================================
# close_loop — 认知闭环主函数
# ============================================================

def close_loop(
    decision: str,
    outcome: str,
    case_value_score: float = 0.6,
    content: str = "",
    tags: str = "C-Drive,训练进化",
    record_fn: Optional[Callable] = None,
    verify_fn: Optional[Callable] = None,
    limiter: Optional[HermesFrequencyLimiter] = None,
) -> Dict[str, Any]:
    """认知闭环：record → hermes → verify。

    C-Drive 执行结果反馈到认知系统：
      1. record 写入执行经验
      2. hermes 反思（频率限制，高价值案例才触发）
      3. verify 贝叶斯置信度更新

    FAIL-OPEN: record/verify 失败不抛异常，保证 C-Drive 主流程不中断。
    降级策略: hermes 配额用尽时仍 record+verify，但跳过 self-iteration。

    Args:
        decision: C-Drive 执行的决策
        outcome: 执行结果 ("success"/"failure"/"partial")
        case_value_score: 案例价值评分 (0.0-1.0)
        content: 记录内容
        tags: 记录标签
        record_fn: 可注入的 record 函数（测试用）
        verify_fn: 可注入的 verify 函数（测试用）
        limiter: 可注入的频率限制器（测试用），None 时使用全局单例

    Returns:
        闭环结果 dict:
          - memory_id: 记录的记忆 ID（可能为 None）
          - hermes_triggered: 是否触发了 hermes 反思
          - degraded: 是否处于降级模式（hermes 未触发）
    """
    # 选择 record/verify 实现
    _record = record_fn or _default_record
    _verify = verify_fn or _default_verify

    # 1. record — 写入执行经验
    memory_id = None
    try:
        record_result = _record(
            content=content,
            quality_level="B",
            tags=tags,
        )
        if record_result and isinstance(record_result, dict):
            memory_id = record_result.get("memory_id")
    except Exception:
        # FAIL-OPEN: record 失败不中断
        memory_id = None

    # 2. hermes 反思（频率限制）
    _limiter = limiter or _get_limiter()
    hermes_triggered = False
    if _limiter.should_trigger_hermes(case_value_score):
        _limiter.record_hermes_trigger()
        hermes_triggered = True
        # dream-self-iteration-workflow 调用点（实际生产环境接入）
        # L4 自进化: hermes 反思 → trace 分析 → skill-creator
        #           参数优化 → 贝叶斯 + walk-forward
        #           案例入库 → 4维价值评估
        #           文档同步 → checksum → dream-doc-sync
    # 降级模式: hermes 未触发，仅做基础 record+verify

    # 3. verify — 贝叶斯置信度更新
    if memory_id:
        success = (outcome == "success")
        try:
            _verify(memory_id=memory_id, success=success)
        except Exception:
            # FAIL-OPEN: verify 失败不中断
            pass

    return {
        "memory_id": memory_id,
        "hermes_triggered": hermes_triggered,
        "degraded": not hermes_triggered,
    }
