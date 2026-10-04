"""agent-browser 第三引擎 — GLM-5.2 通过 Bash 编排 agent-browser CLI

三引擎架构中的线2（省 token 引擎）：
- 线1 脚本引擎：scenario_runner + user_simulator（YAML 驱动，确定性）
- 线2 agent-browser 引擎：本模块（GLM-5.2 通过 Bash 调用 CLI，零 LLM token）
- 线3 AI 引擎：ai_agent.py（Browser Use + Qwen VL）

省 token 原理：
- snapshot -i 输出结构化 DOM 文本（@e1 [input type="email"]）
- GLM-5.2 读文本比 Qwen VL 读截图省 ~10× tokens
- 所有 LLM 编排在 TRAE 主对话中完成（GLM-5.2 自身），无需调用外部 LLM

原生命令风格 YAML（与 agent-browser CLI 1:1 映射）：
    steps:
      - open: https://example.com/login
      - snapshot: {interactive: true}
      - fill: {ref: "@e1", value: "user@example.com"}
      - click: {ref: "@e3"}
      - wait: {load: networkidle}

反幻觉设计：
- GLM-5.2 编排每步后可注入判断（callback hook）
- _run_verification 用 agent-browser snapshot/screenshot/network 做三重验证
- 不依赖 LLM 主观判断，所有断言基于真实 CLI 输出

参考：/Users/zhangjiangtao/.trae-cn/skills/agent-browser/SKILL.md
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .result_verifier import VerificationResult

logger = logging.getLogger("real_env.agent_browser_runner")


@dataclass
class AgentBrowserStep:
    """单条 agent-browser 命令执行结果"""
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float = 0.0


@dataclass
class AgentBrowserResult:
    """agent-browser 任务执行结果"""
    task: str
    passed: bool
    steps: List[AgentBrowserStep] = field(default_factory=list)
    duration_ms: float = 0.0
    verification: Optional[VerificationResult] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "passed": self.passed,
            "steps": [
                {
                    "command": s.command,
                    "exit_code": s.exit_code,
                    "stdout": s.stdout,
                    "stderr": s.stderr,
                    "duration_ms": s.duration_ms,
                }
                for s in self.steps
            ],
            "duration_ms": self.duration_ms,
            "verification": self.verification.to_dict() if self.verification else None,
            "error": self.error,
        }


class AgentBrowserRunner:
    """agent-browser CLI 包装层 — GLM-5.2 通过 Bash 编排

    用法：
        runner = AgentBrowserRunner(config, session_name="form_test")
        result = runner.run_task_from_yaml({
            "name": "登录测试",
            "mode": "agent_browser",
            "steps": [
                {"open": "https://example.com/login"},
                {"snapshot": {"interactive": True}},
                {"fill": {"ref": "@e1", "value": "user@example.com"}},
                {"click": {"ref": "@e3"}},
            ],
            "assertions": {"url_contains": "/dashboard"},
        })
    """

    def __init__(self, config: dict, session_name: Optional[str] = None):
        """初始化 agent-browser Runner。

        Args:
            config: 顶层配置字典，需含 "agent_browser" 段
                agent_browser:
                  executable: "agent-browser"  # 默认 PATH
                  default_session: "real_env_test"
                  timeout: 30
                  headless: true
                  auto_verify: true
            session_name: 可选，覆盖 config 中的 default_session
        """
        self._config = config
        self._cfg = config.get("agent_browser", {})
        self._executable = self._cfg.get("executable", "agent-browser")
        self._default_session = self._cfg.get("default_session")
        self._session_name = session_name or self._default_session
        self._timeout = self._cfg.get("timeout", 30)
        self._headless = self._cfg.get("headless", True)
        self._auto_verify = self._cfg.get("auto_verify", True)

    # ------------------------------------------------------------------
    # 命令拼装
    # ------------------------------------------------------------------
    def _build_command(self, args: List[str], session: Optional[str] = None) -> List[str]:
        """构建 agent-browser CLI 命令（executable + session + args）。

        Args:
            args: agent-browser 子命令参数，如 ["snapshot", "-i"]
            session: 可选 session 名（覆盖默认）

        Returns:
            完整命令列表，如 ["agent-browser", "--session-name", "test", "snapshot", "-i"]
        """
        cmd = [self._executable]
        effective_session = session or self._session_name
        if effective_session:
            cmd.extend(["--session-name", effective_session])
        cmd.extend(args)
        return cmd

    def _step_to_args(self, step: dict) -> List[str]:
        """把原生命令风格 YAML step 转为 agent-browser CLI 参数。

        YAML 格式（单键 dict，键=命令，值=参数）：
            {open: "url"}                        → ["open", "url"]
            {snapshot: {interactive: true}}      → ["snapshot", "-i"]
            {click: {ref: "@e1"}}                → ["click", "@e1"]
            {fill: {ref: "@e1", value: "text"}}  → ["fill", "@e1", "text"]
            {wait: {load: "networkidle"}}        → ["wait", "--load", "networkidle"]
            {wait: {text: "Welcome"}}            → ["wait", "--text", "Welcome"]
            {wait: {selector: "#x", state: "hidden"}} → ["wait", "#x", "--state", "hidden"]
            {screenshot: "out.png"}              → ["screenshot", "out.png"]
            {get: "url"}                         → ["get", "url"]
            {get: {what: "text", ref: "@e1"}}    → ["get", "text", "@e1"]
        """
        if "open" in step:
            return ["open", step["open"]]
        if "snapshot" in step:
            args = ["snapshot"]
            if step["snapshot"].get("interactive"):
                args.append("-i")
            return args
        if "click" in step:
            return ["click", step["click"]["ref"]]
        if "fill" in step:
            return ["fill", step["fill"]["ref"], step["fill"]["value"]]
        if "wait" in step:
            args = ["wait"]
            w = step["wait"]
            if "load" in w:
                args.extend(["--load", w["load"]])
            if "text" in w:
                args.extend(["--text", w["text"]])
            if "selector" in w:
                args.append(w["selector"])
                if "state" in w:
                    args.extend(["--state", w["state"]])
            return args
        if "screenshot" in step:
            return ["screenshot", step["screenshot"]]
        if "get" in step:
            args = ["get"]
            if isinstance(step["get"], dict):
                args.append(step["get"].get("what", "url"))
                if "ref" in step["get"]:
                    args.append(step["get"]["ref"])
            else:
                args.append(step["get"])
            return args
        raise ValueError(f"Unknown agent-browser step: {step}")

    # ------------------------------------------------------------------
    # 命令执行
    # ------------------------------------------------------------------
    def run_command(self, args: List[str], session: Optional[str] = None,
                    timeout: Optional[int] = None) -> AgentBrowserStep:
        """执行单条 agent-browser 命令。

        Args:
            args: agent-browser 子命令参数
            session: 可选 session 名（覆盖默认）
            timeout: 可选超时（秒），默认用 self._timeout

        Returns:
            AgentBrowserStep 含 exit_code/stdout/stderr
        """
        cmd = self._build_command(args, session)
        cmd_str = " ".join(cmd)
        start = time.time()
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout or self._timeout,
            )
            duration = (time.time() - start) * 1000
            return AgentBrowserStep(
                command=cmd_str,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                duration_ms=duration,
            )
        except subprocess.TimeoutExpired as e:
            duration = (time.time() - start) * 1000
            logger.warning("agent-browser command timed out: %s", cmd_str)
            return AgentBrowserStep(
                command=cmd_str,
                exit_code=-1,
                stdout="",
                stderr=f"Timeout: {e}",
                duration_ms=duration,
            )
        except FileNotFoundError as e:
            duration = (time.time() - start) * 1000
            logger.error("agent-browser executable not found: %s", self._executable)
            return AgentBrowserStep(
                command=cmd_str,
                exit_code=-2,
                stdout="",
                stderr=f"Executable not found: {e}",
                duration_ms=duration,
            )

    # ------------------------------------------------------------------
    # 多步任务执行
    # ------------------------------------------------------------------
    def run_task(self, steps: List[dict],
                 session: Optional[str] = None,
                 callback: Optional[Any] = None) -> AgentBrowserResult:
        """从 YAML steps 列表执行多步任务。

        每步执行后调用 callback（可选），GLM-5.2 可注入判断逻辑：
            def callback(step_result: AgentBrowserStep) -> bool:
                # 返回 False 立即终止任务
                if "error" in step_result.stderr.lower():
                    return False
                return True

        bail-on-error：步骤 exit_code!=0 时立即停止后续步骤。

        Args:
            steps: YAML step 列表（原生命令风格）
            session: 可选 session 名
            callback: 可选回调，每步后调用

        Returns:
            AgentBrowserResult
        """
        results: List[AgentBrowserStep] = []
        all_passed = True
        start = time.time()

        for step in steps:
            args = self._step_to_args(step)
            step_result = self.run_command(args, session=session)
            results.append(step_result)

            # bail-on-error：exit_code != 0 立即停止
            if step_result.exit_code != 0:
                all_passed = False
                logger.warning(
                    "Step failed (exit=%d), bailing: %s",
                    step_result.exit_code, step_result.command,
                )
                break

            # callback hook：GLM-5.2 可注入判断
            if callback is not None:
                try:
                    should_continue = callback(step_result)
                    if not should_continue:
                        logger.info("Callback signaled stop after: %s",
                                    step_result.command)
                        break
                except Exception as e:
                    logger.warning("Callback error: %s", e)

        return AgentBrowserResult(
            task="agent_browser_task",
            passed=all_passed,
            steps=results,
            duration_ms=(time.time() - start) * 1000,
        )

    def run_task_from_yaml(self, scenario: dict) -> AgentBrowserResult:
        """从 YAML 场景定义运行 agent-browser 任务。

        YAML 格式：
            name: 登录测试
            mode: agent_browser
            session: form_test
            steps:
              - open: https://example.com/login
              - snapshot: {interactive: true}
              - fill: {ref: "@e1", value: "user@example.com"}
              - click: {ref: "@e3"}
              - wait: {load: networkidle}
            assertions:
              dom:
                - selector: ".dashboard"
                  action: exists
              url_contains: "/dashboard"
        """
        steps = scenario.get("steps")
        if not steps:
            return AgentBrowserResult(
                task=scenario.get("name", ""),
                passed=False,
                steps=[],
                duration_ms=0,
                error="Scenario must contain 'steps'",
            )

        session = scenario.get("session")
        result = self.run_task(steps, session=session)

        # 可选验证
        if self._auto_verify and scenario.get("assertions"):
            verification = self._run_verification(scenario["assertions"], session)
            result.verification = verification
            result.passed = result.passed and verification.passed

        return result

    def run_batch(self, steps: List[list],
                  session: Optional[str] = None) -> AgentBrowserResult:
        """batch 模式：通过 stdin 传 JSON 数组一次性执行。

        Args:
            steps: 命令参数列表的列表，如
                [["open", "url"], ["snapshot", "-i"]]
            session: 可选 session 名

        Returns:
            AgentBrowserResult（steps 只含 1 个 batch 调用结果）
        """
        batch_input = json.dumps(steps)
        cmd = self._build_command(["batch", "--json"], session)
        cmd_str = " ".join(cmd)
        start = time.time()

        try:
            result = subprocess.run(
                cmd,
                input=batch_input,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
            duration = (time.time() - start) * 1000
            step = AgentBrowserStep(
                command=cmd_str,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                duration_ms=duration,
            )
            return AgentBrowserResult(
                task="batch",
                passed=result.returncode == 0,
                steps=[step],
                duration_ms=duration,
            )
        except subprocess.TimeoutExpired as e:
            duration = (time.time() - start) * 1000
            step = AgentBrowserStep(
                command=cmd_str,
                exit_code=-1,
                stdout="",
                stderr=f"Timeout: {e}",
                duration_ms=duration,
            )
            return AgentBrowserResult(
                task="batch",
                passed=False,
                steps=[step],
                duration_ms=duration,
                error=f"Batch timed out: {e}",
            )

    # ------------------------------------------------------------------
    # 三重验证集成
    # ------------------------------------------------------------------
    def _run_verification(self, assertions: Optional[Dict[str, Any]],
                         session: Optional[str] = None) -> VerificationResult:
        """用 agent-browser snapshot/screenshot/network 做三重验证。

        - DOM 断言：调用 `snapshot -i`，从 stdout 文本检查 selector
        - url_contains：调用 `get url`，从 stdout 检查 URL
        - screenshot 断言：调用 `diff screenshot --baseline <path>`（未实现）
        - 网络断言：调用 `network requests`（未实现）

        Args:
            assertions: 断言字典
                dom: [{selector: ".x", action: "exists"}]
                url_contains: "/path"
            session: 可选 session 名

        Returns:
            VerificationResult
        """
        if not assertions:
            return VerificationResult(name="verification", passed=True)

        passed = True
        details: Dict[str, Any] = {}

        # DOM 断言：snapshot -i 输出 @e1 [div class='dashboard'] 文本
        dom_assertions = assertions.get("dom", [])
        if dom_assertions:
            snapshot_step = self.run_command(["snapshot", "-i"], session=session)
            details["snapshot_stdout"] = snapshot_step.stdout
            if snapshot_step.exit_code != 0:
                passed = False
                details["snapshot_error"] = snapshot_step.stderr
            else:
                for assertion in dom_assertions:
                    selector = assertion.get("selector", "")
                    action = assertion.get("action", "exists")
                    if action == "exists":
                        # snapshot -i 输出形如：@e1 [div class='dashboard']
                        # selector 如 ".dashboard" → 去掉前缀 . 或 # 后检查出现
                        needle = selector.lstrip(".#")
                        if needle not in snapshot_step.stdout:
                            passed = False
                            details[f"dom_missing:{selector}"] = True

        # url_contains 断言：get url 输出当前 URL
        url_contains = assertions.get("url_contains")
        if url_contains:
            url_step = self.run_command(["get", "url"], session=session)
            details["url"] = url_step.stdout
            if url_step.exit_code != 0 or url_contains not in url_step.stdout:
                passed = False
                details["url_contains_failed"] = url_contains

        return VerificationResult(
            name="verification",
            passed=passed,
            details=details,
        )
