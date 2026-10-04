"""bsk 第四引擎 — 腾讯 BrowserSkill CLI 包装

四引擎架构中的线4（DSH 原生引擎）：
- 线1 脚本引擎：scenario_runner + user_simulator（YAML + Playwright）
- 线2 agent-browser 引擎：agent_browser_runner（GLM-5.2 + CLI，省 token）
- 线3 AI 引擎：ai_agent.py（Browser Use + Qwen VL）
- 线4 bsk 引擎：本模块（腾讯 BrowserSkill CLI，DSH 原生）

独特能力（agent-browser CLI 没有的）：
- Multi-session 并发（maxSessions=5）
- Multi-tab 管理 + borrow/return 借用用户标签页
- request-help 人工接管（反爬虫关键：验证码/人脸）
- emulate 设备模拟（移动端测试）
- back/forward/reload 历史导航
- console + html + observe 高级观察
- wheel + scroll-to + focus/blur/select/press 9 种交互

省 token 原理（与线2 一致）：
- bsk snapshot 输出 indented aria-snapshot with @eN refs
- GLM-5.2 读文本编排，无需外部 LLM
- bsk --json 输出结构化 JSON，便于解析

参考：
- /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/.dsh-home/profiles/web/node_modules/@wxg-prc-cpg/browser-skill-dsh-plugin/README.md
- https://github.com/Tencent/BrowserSkill
- bsk CLI v0.3.2 路径：/Users/zhangjiangtao/.local/bin/bsk
"""
from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .result_verifier import VerificationResult

logger = logging.getLogger("real_env.bsk_runner")


@dataclass
class BskStep:
    """单条 bsk 命令执行结果"""
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float = 0.0


@dataclass
class BskResult:
    """bsk 任务执行结果"""
    task: str
    passed: bool
    steps: List[BskStep] = field(default_factory=list)
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


class BskRunner:
    """腾讯 BrowserSkill CLI 包装层 — GLM-5.2 通过 Bash 编排

    用法：
        runner = BskRunner(config, session_name="form_test")
        result = runner.run_task_from_yaml({
            "name": "登录测试",
            "mode": "bsk",
            "steps": [
                {"navigate": "https://example.com/login"},
                {"snapshot": {}},
                {"fill": {"ref": "@e1", "value": "user@example.com"}},
                {"click": {"ref": "@e3"}},
                {"wait-for-navigation": {}},
            ],
            "assertions": {"url_contains": "/dashboard"},
        })

    Session 管理（独立方法，不通过 --session flag）：
        runner.start_session(name="form_test")  # bsk session start --name form_test --json
        runner.stop_session(session_id="...")   # bsk session stop <id>
        runner.list_sessions()                  # bsk session list --json
    """

    def __init__(self, config: dict, session_name: Optional[str] = None):
        """初始化 Bsk Runner。

        Args:
            config: 顶层配置字典，需含 "bsk" 段
                bsk:
                  executable: "bsk"
                  default_session: "real_env_test"
                  timeout: 120
                  json_output: true
                  auto_verify: true
            session_name: 可选，任务名（用于 bsk session start --name）
        """
        self._config = config
        self._cfg = config.get("bsk", {})
        self._executable = self._cfg.get("executable", "bsk")
        self._default_session = self._cfg.get("default_session")
        self._session_name = session_name or self._default_session
        self._timeout = self._cfg.get("timeout", 120)
        self._json_output = self._cfg.get("json_output", True)
        self._auto_verify = self._cfg.get("auto_verify", True)

    # ------------------------------------------------------------------
    # 命令拼装
    # ------------------------------------------------------------------
    def _build_command(self, args: List[str], session: Optional[str] = None) -> List[str]:
        """构建 bsk CLI 命令（executable + --json + args）。

        注意：bsk 没有 --session 全局 flag，session 通过 `bsk session start`
        子命令创建后自动成为 "current session"。本方法不注入 session 参数。
        如需 session 隔离，调用方应先调用 start_session()。

        Args:
            args: bsk 子命令参数，如 ["snapshot"]
            session: 保留参数，bsk 不支持全局 --session，忽略

        Returns:
            完整命令列表，如 ["bsk", "--json", "snapshot"]
        """
        cmd = [self._executable]
        if self._json_output:
            cmd.append("--json")
        cmd.extend(args)
        return cmd

    def _step_to_args(self, step: dict) -> List[str]:
        """把原生命令风格 YAML step 转为 bsk CLI 参数。

        YAML 格式（单键 dict，键=命令，值=参数）：
            {navigate: "url"}                    → ["navigate", "url"]
            {navigate-back: {}}                   → ["navigate-back"]
            {navigate-forward: {}}               → ["navigate-forward"]
            {reload: {}}                          → ["reload"]
            {snapshot: {}}                        → ["snapshot"]
            {observe: {}}                         → ["observe"]
            {screenshot: {path: "out.png"}}       → ["screenshot", "--path", "out.png"]
            {click: {ref: "@e1"}}                 → ["click", "@e1"]
            {hover: {ref: "@e1"}}                 → ["hover", "@e1"]
            {fill: {ref: "@e1", value: "text"}}   → ["fill", "@e1", "text"]
            {press: {key: "Enter"}}               → ["press", "Enter"]
            {select: {ref: "@e1", value: "opt"}}  → ["select", "@e1", "opt"]
            {focus: {ref: "@e1"}}                 → ["focus", "@e1"]
            {blur: {ref: "@e1"}}                   → ["blur", "@e1"]
            {scroll-to: {ref: "@e1"}}             → ["scroll-to", "@e1"]
            {wait-for-navigation: {}}            → ["wait-for-navigation"]
            {wait-ms: {ms: 500}}                  → ["wait-ms", "500"]
            {console: {}}                         → ["console"]
            {network: {}}                         → ["network"]
            {get-html: {}}                        → ["get-html"]
            {get-html: {ref: "@e1"}}              → ["get-html", "@e1"]
            {emulate: {device: "iPhone 14"}}      → ["emulate", "--device", "iPhone 14"]
            {request-help: {prompt: "..."}}       → ["request-help", "--prompt", "..."]
            {evaluate: {expression: "..."}}       → ["evaluate", "..."]
        """
        # 导航类
        if "navigate" in step:
            return ["navigate", step["navigate"]]
        if "navigate-back" in step:
            return ["navigate-back"]
        if "navigate-forward" in step:
            return ["navigate-forward"]
        if "reload" in step:
            return ["reload"]
        # 观察类
        if "snapshot" in step:
            return ["snapshot"]
        if "observe" in step:
            return ["observe"]
        if "screenshot" in step:
            args = ["screenshot"]
            sc = step["screenshot"]
            if isinstance(sc, dict) and sc.get("path"):
                args.extend(["--path", sc["path"]])
            return args
        if "console" in step:
            return ["console"]
        if "network" in step:
            return ["network"]
        if "get-html" in step:
            args = ["get-html"]
            gh = step["get-html"]
            if isinstance(gh, dict) and gh.get("ref"):
                args.append(gh["ref"])
            return args
        # 交互类
        if "click" in step:
            return ["click", step["click"]["ref"]]
        if "hover" in step:
            return ["hover", step["hover"]["ref"]]
        if "fill" in step:
            return ["fill", step["fill"]["ref"], step["fill"]["value"]]
        if "press" in step:
            return ["press", step["press"]["key"]]
        if "select" in step:
            return ["select", step["select"]["ref"], step["select"]["value"]]
        if "focus" in step:
            return ["focus", step["focus"]["ref"]]
        if "blur" in step:
            return ["blur", step["blur"]["ref"]]
        if "scroll-to" in step:
            return ["scroll-to", step["scroll-to"]["ref"]]
        # 等待类
        if "wait-for-navigation" in step:
            return ["wait-for-navigation"]
        if "wait-ms" in step:
            return ["wait-ms", str(step["wait-ms"]["ms"])]
        # 设备类（bsk 独特）
        if "emulate" in step:
            args = ["emulate"]
            em = step["emulate"]
            if isinstance(em, dict) and em.get("device"):
                args.extend(["--device", em["device"]])
            return args
        # 人工接管（bsk 独特：反爬虫关键）
        if "request-help" in step:
            args = ["request-help"]
            rh = step["request-help"]
            if isinstance(rh, dict) and rh.get("prompt"):
                args.extend(["--prompt", rh["prompt"]])
            return args
        # JS 执行
        if "evaluate" in step:
            return ["evaluate", step["evaluate"]["expression"]]
        raise ValueError(f"Unknown bsk step: {step}")

    # ------------------------------------------------------------------
    # 命令执行
    # ------------------------------------------------------------------
    def run_command(self, args: List[str], session: Optional[str] = None,
                    timeout: Optional[int] = None) -> BskStep:
        """执行单条 bsk 命令。"""
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
            return BskStep(
                command=cmd_str,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                duration_ms=duration,
            )
        except subprocess.TimeoutExpired as e:
            duration = (time.time() - start) * 1000
            logger.warning("bsk command timed out: %s", cmd_str)
            return BskStep(
                command=cmd_str,
                exit_code=-1,
                stdout="",
                stderr=f"Timeout: {e}",
                duration_ms=duration,
            )
        except FileNotFoundError as e:
            duration = (time.time() - start) * 1000
            logger.error("bsk executable not found: %s", self._executable)
            return BskStep(
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
                 callback: Optional[Any] = None) -> BskResult:
        """从 YAML steps 列表执行多步任务。

        每步执行后调用 callback（可选），GLM-5.2 可注入判断逻辑：
            def callback(step_result: BskStep) -> bool:
                # 返回 False 立即终止任务
                if "error" in step_result.stderr.lower():
                    return False
                return True

        bail-on-error：步骤 exit_code!=0 时立即停止后续步骤。
        """
        results: List[BskStep] = []
        all_passed = True
        start = time.time()

        for step in steps:
            args = self._step_to_args(step)
            step_result = self.run_command(args, session=session)
            results.append(step_result)

            if step_result.exit_code != 0:
                all_passed = False
                logger.warning(
                    "Step failed (exit=%d), bailing: %s",
                    step_result.exit_code, step_result.command,
                )
                break

            if callback is not None:
                try:
                    should_continue = callback(step_result)
                    if not should_continue:
                        logger.info("Callback signaled stop after: %s",
                                    step_result.command)
                        break
                except Exception as e:
                    logger.warning("Callback error: %s", e)

        return BskResult(
            task="bsk_task",
            passed=all_passed,
            steps=results,
            duration_ms=(time.time() - start) * 1000,
        )

    def run_task_from_yaml(self, scenario: dict) -> BskResult:
        """从 YAML 场景定义运行 bsk 任务。

        YAML 格式：
            name: 登录测试
            mode: bsk
            session: form_test
            steps:
              - navigate: https://example.com/login
              - snapshot: {}
              - fill: {ref: "@e1", value: "user@example.com"}
              - click: {ref: "@e3"}
              - wait-for-navigation: {}
            assertions:
              dom:
                - selector: ".dashboard"
                  action: exists
              url_contains: "/dashboard"
              console_no_errors: true
        """
        steps = scenario.get("steps")
        if not steps:
            return BskResult(
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

    # ------------------------------------------------------------------
    # Session 管理（bsk 独特：多 session 并发）
    # ------------------------------------------------------------------
    def start_session(self, name: Optional[str] = None) -> BskStep:
        """启动新 session：bsk session start [--name <name>] --json。

        Returns:
            BskStep，stdout 含 session id（JSON 格式）
        """
        args = ["session", "start"]
        if name or self._session_name:
            args.extend(["--name", name or self._session_name])
        return self.run_command(args)

    def stop_session(self, session_id: Optional[str] = None) -> BskStep:
        """停止 session：bsk session stop [<id>|--all]"""
        args = ["session", "stop"]
        if session_id:
            args.append(session_id)
        else:
            args.append("--all")
        return self.run_command(args)

    def list_sessions(self) -> BskStep:
        """列出 active sessions：bsk session list --json"""
        return self.run_command(["session", "list"])

    # ------------------------------------------------------------------
    # 三重验证集成
    # ------------------------------------------------------------------
    def _run_verification(self, assertions: Optional[Dict[str, Any]],
                         session: Optional[str] = None) -> VerificationResult:
        """用 bsk snapshot/observe/console/get-html/evaluate/network 验证。

        - DOM 断言：调用 snapshot，从 stdout 检查 selector
        - url_contains：调用 evaluate 'location.href'（bsk 无 get url）
        - console_no_errors：调用 console，检查 stdout 是否含 error
        """
        if not assertions:
            return VerificationResult(name="verification", passed=True)

        passed = True
        details: Dict[str, Any] = {}

        # DOM 断言
        dom_assertions = assertions.get("dom", [])
        if dom_assertions:
            snapshot_step = self.run_command(["snapshot"], session=session)
            details["snapshot_stdout"] = snapshot_step.stdout
            if snapshot_step.exit_code != 0:
                passed = False
                details["snapshot_error"] = snapshot_step.stderr
            else:
                for assertion in dom_assertions:
                    selector = assertion.get("selector", "")
                    action = assertion.get("action", "exists")
                    if action == "exists":
                        needle = selector.lstrip(".#")
                        if needle not in snapshot_step.stdout:
                            passed = False
                            details[f"dom_missing:{selector}"] = True

        # url_contains 断言（用 evaluate 替代）
        url_contains = assertions.get("url_contains")
        if url_contains:
            eval_step = self.run_command(
                ["evaluate", "location.href"], session=session,
            )
            details["url"] = eval_step.stdout
            if eval_step.exit_code != 0 or url_contains not in eval_step.stdout:
                passed = False
                details["url_contains_failed"] = url_contains

        # console_no_errors 断言（bsk 独特）
        if assertions.get("console_no_errors"):
            console_step = self.run_command(["console"], session=session)
            details["console_stdout"] = console_step.stdout
            if console_step.exit_code != 0:
                passed = False
                details["console_error"] = console_step.stderr
            else:
                # 检查 stdout 是否含 error 级别日志
                if '"error"' in console_step.stdout.lower() or '"level":"error"' in console_step.stdout.lower():
                    passed = False
                    details["console_has_errors"] = True

        return VerificationResult(
            name="verification",
            passed=passed,
            details=details,
        )
