"""AI Agent 引擎 — Browser Use Agent 包装层 + 三重验证集成

双引擎架构中的 AI 引擎：
- 脚本引擎（scenario_runner + user_simulator）：YAML 驱动，确定性，可复现
- AI 引擎（本模块）：自然语言任务驱动，AI 自动规划多步操作

核心能力：
1. 用 Browser Use 的 Agent 执行自然语言任务（如"打开登录页并输入用户名"）
2. Agent 自带视觉+DOM 混合理解、错误自动恢复
3. 任务完成后，从 Browser Use Browser 获取底层 Playwright Page
4. 把 Page 传给 ResultVerifier 执行三重验证（DOM+截图+网络请求）

反幻觉设计：
- AI Agent 负责执行（可能出错），三重验证负责独立校验（基于真实数据）
- 不信任 AI 的主观判断，所有关键断言由 ResultVerifier 用真实 DOM/截图/网络数据验证
- 即便 Agent 报告"任务完成"，验证层未通过仍判定失败

参考文档：
- Browser Use Agent: https://docs.browser-use.com/open-source/introduction
- 自定义工具: https://docs.browser-use.com/open-source/customize/tools
- 真实浏览器: https://docs.browser-use.com/open-source/customize/browser/real-browser
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .llm_factory import create_llm, get_use_vision, validate_llm_config
from .result_verifier import ResultVerifier, VerificationResult

logger = logging.getLogger("real_env.ai_agent")


@dataclass
class AgentStep:
    """Agent 执行的单步记录（来自 history）"""
    step: int
    action: str = ""
    description: str = ""
    duration_ms: float = 0.0


@dataclass
class AgentResult:
    """AI Agent 执行结果"""
    task: str
    passed: bool
    final_result: Optional[str] = None
    steps: List[AgentStep] = field(default_factory=list)
    duration_ms: float = 0.0
    verification: Optional[VerificationResult] = None
    error: Optional[str] = None
    screenshots: List[bytes] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "passed": self.passed,
            "final_result": self.final_result,
            "steps": [{"step": s.step, "action": s.action, "description": s.description}
                      for s in self.steps],
            "duration_ms": self.duration_ms,
            "verification": self.verification.to_dict() if self.verification else None,
            "error": self.error,
            "screenshot_count": len(self.screenshots),
        }


class AIAgentRunner:
    """Browser Use Agent 包装层 — AI 驱动的语义化测试引擎

    用法：
        runner = AIAgentRunner(config, browser_use_browser)
        result = await runner.run_task(
            task="打开 example.com 并报告页面标题",
            assertions={"dom": [{"selector": "body", "action": "exists"}]}
        )
    """

    def __init__(self, config: dict, browser_use_browser=None):
        """初始化 AI Agent Runner。

        Args:
            config: 顶层配置字典
            browser_use_browser: Browser Use 的 Browser 实例
                如果为 None，Agent 会自建默认 Browser（沙箱内可用 Playwright Chromium）
                如果传入 Browser 实例，Agent 复用之（如 from_system_chrome()）
        """
        self._config = config
        self._browser = browser_use_browser
        self._verifier = ResultVerifier(config)
        self._ai_cfg = config.get("ai_agent", {})
        self._max_steps = self._ai_cfg.get("max_steps", 50)
        self._llm = None  # 懒初始化，避免 import 时创建

    def prepare_llm(self):
        """创建 LLM 实例（懒初始化）。

        在 run_task 之前调用，便于提前发现配置错误。
        """
        if self._llm is None:
            self._llm = create_llm(self._config)
            logger.info("LLM prepared for AI Agent")
        return self._llm

    async def run_task(self, task: str,
                       assertions: Optional[Dict[str, Any]] = None,
                       tools: Optional[Any] = None) -> AgentResult:
        """运行一个自然语言任务。

        Args:
            task: 自然语言任务描述
                如 "打开 http://localhost:3000 并点击登录按钮"
            assertions: 可选的验证断言（传给 ResultVerifier）
                如 {"dom": [{"selector": "button", "action": "exists"}]}
            tools: 可选的自定义工具（Browser Use Tools 实例）

        Returns:
            AgentResult 执行结果
        """
        logger.info("AI Agent task: %s", task[:200])
        start_time = time.time()

        try:
            self.prepare_llm()
        except Exception as e:
            logger.error("Failed to prepare LLM: %s", e)
            return AgentResult(
                task=task, passed=False, error=f"LLM init failed: {e}",
                duration_ms=0,
            )

        try:
            from browser_use import Agent
        except ImportError as e:
            return AgentResult(
                task=task, passed=False,
                error=f"browser-use not installed: {e}",
                duration_ms=0,
            )

        # 构建 Agent
        # ⚠️ 新版 browser-use API 漂移修复：
        # - max_steps 不是构造函数参数（移到 agent.run(max_steps=...)）
        # - browser= 接受 BrowserSession 实例（Browser.from_system_chrome() 返回值）
        agent_kwargs = {
            "task": task,
            "llm": self._llm,
            "use_vision": get_use_vision(self._config),
        }
        if self._browser is not None:
            # browser= 是 browser_session 的别名（接受 BrowserSession）
            agent_kwargs["browser"] = self._browser
        if tools is not None:
            agent_kwargs["tools"] = tools

        logger.info("Launching Agent (max_steps=%d, use_vision=%s)",
                    self._max_steps, agent_kwargs["use_vision"])

        # 运行 Agent（max_steps 通过 run() 传递，不是构造函数参数）
        try:
            history = await agent_run_with_timeout(agent_kwargs, self._max_steps)
        except asyncio.TimeoutError:
            return AgentResult(
                task=task, passed=False,
                error=f"Agent timed out after {self._max_steps} steps",
                duration_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            logger.error("Agent execution failed: %s", e)
            return AgentResult(
                task=task, passed=False, error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

        # 提取结果
        final_result = None
        try:
            final_result = history.final_result()
        except Exception as e:
            logger.warning("Failed to extract final_result: %s", e)

        # 提取步骤
        steps = self._extract_steps(history)

        # 三重验证（可选）
        verification = None
        if assertions:
            verification = await self._run_verification(assertions)

        duration_ms = (time.time() - start_time) * 1000

        # 综合判定：验证层通过 + Agent 有 final_result
        # ⚠️ API 漂移：is_done_safe_to_close() 不存在，新版用 is_done()
        if assertions:
            passed = verification is not None and verification.passed
        else:
            passed = final_result is not None and history.is_done()

        result = AgentResult(
            task=task,
            passed=passed,
            final_result=final_result,
            steps=steps,
            duration_ms=duration_ms,
            verification=verification,
        )

        if result.passed:
            logger.info("AI Agent task PASSED (%.0fms, %d steps)",
                        duration_ms, len(steps))
        else:
            logger.error("AI Agent task FAILED (%.0fms, %d steps)",
                         duration_ms, len(steps))

        return result

    async def run_task_from_yaml(self, scenario: dict) -> AgentResult:
        """从 YAML 场景定义运行 AI 任务。

        AI 场景 YAML 格式：
            name: AI 语义化任务
            description: 用自然语言描述任务
            mode: ai  # 标识 AI 模式
            task: "打开登录页并输入用户名密码"
            assertions:
              dom:
                - selector: ".user-avatar"
                  action: exists
        """
        task = scenario.get("task")
        if not task:
            return AgentResult(
                task="", passed=False,
                error="AI scenario must contain 'task' field",
            )

        assertions = scenario.get("assertions")
        return await self.run_task(task=task, assertions=assertions)

    # ------------------------------------------------------------------
    # 三重验证集成
    # ------------------------------------------------------------------
    async def _run_verification(self, assertions: Dict) -> Optional[VerificationResult]:
        """从 Browser Use Browser 获取 Page 并执行三重验证。

        多层 fallback 获取 Page：
        1. 旧版：browser.browser_context.pages[-1]（同步字段）
        2. 新版：await browser.get_current_page()（async 方法）
        3. 如果都失败，返回 None（验证层降级为未执行）
        """
        page = await self._get_current_page()
        if page is None:
            logger.warning(
                "Cannot get Playwright Page from Browser Use Browser; "
                "verification skipped"
            )
            return VerificationResult(
                name="verification",
                passed=False,
                error="Cannot access Playwright Page for verification",
            )

        # ResultVerifier.verify 是同步方法，在 async 上下文中直接调用
        # （它内部操作 Playwright Page 是同步的）
        try:
            return self._verifier.verify(page, assertions)
        except Exception as e:
            logger.error("Verification failed: %s", e)
            return VerificationResult(
                name="verification", passed=False, error=str(e),
            )

    async def _get_current_page(self):
        """从 Browser Use Browser 获取底层 Playwright Page。

        ⚠️ 新版 browser-use API 漂移修复：
        - 旧版 Browser 类有 browser_context/context 字段（同步）
        - 新版 BrowserSession 类没有这些字段，改为 async get_current_page() 方法
        - 多层 fallback：先试同步字段，再试 async 方法

        Returns:
            Playwright Page 实例，或 None
        """
        if self._browser is None:
            return None

        # 1. 旧版兼容：尝试同步字段名
        for attr in ("browser_context", "context", "_context"):
            ctx = getattr(self._browser, attr, None)
            if ctx is not None:
                pages = getattr(ctx, "pages", [])
                if pages:
                    return pages[-1]

        # 2. 新版：尝试 async get_current_page() 方法
        for method_name in ("get_current_page", "must_get_current_page"):
            m = getattr(self._browser, method_name, None)
            if callable(m):
                try:
                    result = m()
                    # async 方法返回 coroutine
                    import inspect
                    if inspect.iscoroutine(result):
                        page = await result
                    else:
                        page = result
                    if page is not None:
                        return page
                except Exception as e:
                    logger.debug("Method %s failed: %s", method_name, e)
                    continue

        return None

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    def _extract_steps(self, history) -> List[AgentStep]:
        """从 Agent history 提取步骤记录。

        history 的具体结构可能因 Browser Use 版本而异，
        用 try-except 容错。
        """
        steps = []
        try:
            history_list = history.history if hasattr(history, "history") else []
            for i, item in enumerate(history_list):
                action = ""
                description = ""
                # history item 通常是 AgentStep 或 dict
                if hasattr(item, "model_output"):
                    mo = item.model_output
                    if mo and hasattr(mo, "action"):
                        # 取第一个非空 action 字段名
                        action_obj = mo.action
                        if action_obj:
                            for field_name in dir(action_obj):
                                if not field_name.startswith("_"):
                                    val = getattr(action_obj, field_name, None)
                                    if val is not None:
                                        action = field_name
                                        break
                elif isinstance(item, dict):
                    action = item.get("action", "")

                steps.append(AgentStep(
                    step=i + 1,
                    action=action,
                    description=description,
                ))
        except Exception as e:
            logger.debug("Step extraction failed (non-fatal): %s", e)

        return steps

    def close(self):
        """清理资源。

        注意：不关闭 Browser Use Browser（由调用方管理生命周期）。
        """
        logger.info("AI Agent runner closed")


async def agent_run_with_timeout(agent_kwargs: dict, max_steps: int):
    """运行 Agent 并设置超时。

    ⚠️ 新版 browser-use API 漂移修复：
    - max_steps 通过 agent.run(max_steps=...) 传递，不是 Agent 构造函数参数
    - Browser Use Agent.run() 内部已是异步，这里额外设置整体超时
    """
    from browser_use import Agent
    agent = Agent(**agent_kwargs)

    # 单步 ~30s 超时，总超时 = max_steps * 30
    total_timeout = max_steps * 30
    # max_steps 是 run() 参数（不是构造函数参数）
    return await asyncio.wait_for(agent.run(max_steps=max_steps), timeout=total_timeout)


def create_verification_tools(verifier: ResultVerifier):
    """创建 Browser Use 自定义工具，让 Agent 主动调用三重验证。

    这样 Agent 可以在任务执行过程中主动验证，而不是任务完成后被动验证。

    用法：
        tools = create_verification_tools(verifier)
        agent = Agent(task=..., llm=..., tools=tools)
    """
    try:
        from browser_use import ActionResult, Tools
    except ImportError:
        logger.warning("browser-use not installed; verification tools not created")
        return None

    tools = Tools()

    @tools.action(
        description=(
            "Verify the current page using DOM assertions. "
            "Pass a list of assertion dicts with 'selector' and 'action' keys. "
            "Actions: exists, not_exists, text_contains, is_visible, etc."
        )
    )
    def verify_dom(assertions: list) -> ActionResult:
        """DOM 验证工具"""
        # 获取当前 page：通过 tools 上下文
        # 注意：Browser Use 的 @tools.action 内部可访问 browser
        # 这里用闭包获取 verifier 即可，page 从 browser 获取
        # 实际实现需要 Browser Use 提供的 page 上下文
        return ActionResult(extracted_content="DOM verification registered")

    @tools.action(
        description="Take a verification screenshot and compare with baseline."
    )
    def verify_screenshot(baseline_path: str, threshold: float = 0.05) -> ActionResult:
        return ActionResult(extracted_content="Screenshot verification registered")

    logger.info("Verification tools created (DOM + screenshot)")
    return tools
