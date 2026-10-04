"""线5 computer_use 引擎 — trae 电脑控制插件（双模式）

五引擎架构中的线5（跨应用桌面引擎）：
- 线1 脚本引擎：scenario_runner + user_simulator（YAML + Playwright）
- 线2 agent-browser 引擎：agent_browser_runner（GLM-5.2 + CLI，省 token）
- 线3 AI 引擎：ai_agent.py（Browser Use + Qwen VL）
- 线4 bsk 引擎：bsk_runner（腾讯 BrowserSkill CLI，DSH 原生）
- 线5 computer_use 引擎：本模块（trae 电脑控制 / 桌面原生）

双模式（用户决策：A+B 混合）：
- 模式 A `mode: computer_use`：trae 主对话通过 Agent(subagent_type=computer_use) 介入执行
  Python 退化为「计划生成器+结果聚合器+验证器」
  CLI: `python cli.py computer-use-run --scenario <yaml>` 仅打印 JSON plan
- 模式 B `mode: desktop_native`：30 系统自实现桌面控制（pyautogui + osascript）
  保持与线1-4 一致的 Python 控制流，CI 可用
  CLI: `python cli.py desktop-run --scenario <yaml>` 直接执行

关键物理限制：trae 电脑控制插件无 CLI 可执行文件（plugin.json 仅声明 interface），
只能由 trae 主对话通过 Agent 工具调用，Python 无法直接 spawn subagent。
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .result_verifier import VerificationResult
from utils.desktop_assertions import DesktopAssertions

logger = logging.getLogger("real_env.computer_use_runner")


# ----------------------------------------------------------------------
# 数据类
# ----------------------------------------------------------------------
@dataclass
class ComputerUseStep:
    """单步执行结果（双模式共用）"""
    step: dict
    mode: str  # "computer_use" | "desktop_native"
    success: bool
    output: str = ""  # 模式 A：subagent 文本响应；模式 B：pyautogui/osascript stdout
    screenshot_path: Optional[str] = None
    error: Optional[str] = None
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "mode": self.mode,
            "success": self.success,
            "output": self.output,
            "screenshot_path": self.screenshot_path,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


@dataclass
class ComputerUseResult:
    """computer_use 任务执行结果"""
    task: str
    passed: bool
    mode: str
    steps: List[ComputerUseStep] = field(default_factory=list)
    plan: List[dict] = field(default_factory=list)  # 模式 A 的 prompt 计划
    duration_ms: float = 0.0
    verification: Optional[VerificationResult] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "passed": self.passed,
            "mode": self.mode,
            "steps": [s.to_dict() for s in self.steps],
            "plan": self.plan,
            "duration_ms": self.duration_ms,
            "verification": self.verification.to_dict() if self.verification else None,
            "error": self.error,
        }


# ----------------------------------------------------------------------
# Runner
# ----------------------------------------------------------------------
class ComputerUseRunner:
    """线5 computer_use 引擎 — 双模式桌面控制

    用法（模式 A — trae 介入）:
        runner = ComputerUseRunner(config)
        result = runner.run_task_from_yaml({
            "name": "跨应用测试",
            "mode": "computer_use",
            "steps": [{"activate": {"app": "Google Chrome"}}, ...],
            "assertions": [{"file_exists": {"path": "~/.workbuddy/x.json"}}],
        }, plan_only=True)
        # result.plan 是自然语言 prompt 列表，由 trae 主对话喂给 Agent(computer_use)

    用法（模式 B — 纯 Python）:
        runner = ComputerUseRunner(config)
        result = runner.run_task_from_yaml({
            "name": "跨应用测试",
            "mode": "desktop_native",
            "steps": [{"open_app": {"name": "Google Chrome"}}, ...],
        })  # 直接 pyautogui/osascript 执行
    """

    def __init__(self, config: dict, session_name: Optional[str] = None):
        """初始化。

        Args:
            config: 顶层配置字典，需含 "computer_use" 和 "desktop_native" 段
            session_name: 保留参数，当前未使用（线5 不区分 session）
        """
        self._config = config
        self._cu_cfg = config.get("computer_use", {})
        self._dn_cfg = config.get("desktop_native", {})
        self._session_name = session_name
        self._auto_verify = self._cu_cfg.get("auto_verify", True)
        self._screenshot_dir = self._cu_cfg.get(
            "screenshot_dir", "/tmp/cu_screenshots"
        )
        self._visual_threshold = self._cu_cfg.get("visual_threshold", 0.05)
        self._subagent_type = self._cu_cfg.get("subagent_type", "computer_use")
        self._step_timeout = self._cu_cfg.get("step_timeout", 60)
        self._pyautogui_confidence = self._dn_cfg.get("pyautogui_confidence", 0.8)
        self._osascript_path = self._dn_cfg.get("osascript_path", "/usr/bin/osascript")
        Path(self._screenshot_dir).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 模式 A：build_plan + parse_step_response
    # ------------------------------------------------------------------
    def build_plan(self, yaml_dict: dict) -> List[dict]:
        """从 YAML 生成自然语言 prompt 计划（模式 A）。

        每条 prompt 是一个 dict，含：
            - step_index: int
            - action: str  # activate/click/type/screenshot/open_app/...
            - prompt: str  # 喂给 computer_use subagent 的自然语言指令
            - expect: Optional[str]  # 期望状态，让 subagent 自检
        """
        default_app = yaml_dict.get("default_app")
        steps = yaml_dict.get("steps", [])
        plan: List[dict] = []

        for idx, step in enumerate(steps, 1):
            prompt = self._step_to_prompt(step, default_app)
            plan.append({
                "step_index": idx,
                "action": list(step.keys())[0] if step else "unknown",
                "prompt": prompt,
                "expect": self._extract_expect(step),
                "raw_step": step,
            })
        return plan

    def _step_to_prompt(self, step: dict, default_app: Optional[str]) -> str:
        """单步 YAML → 自然语言 prompt。"""
        if not step:
            return "(empty step)"
        key = list(step.keys())[0]
        val = step[key]

        if key == "activate":
            app = val.get("app") if isinstance(val, dict) else val
            return f"激活应用「{app}」（如果尚未打开则启动它，等窗口出现）"

        if key == "click":
            target = val.get("target") if isinstance(val, dict) else str(val)
            return f"在当前应用中点击「{target}」（如果找不到，报告失败原因）"

        if key == "type":
            target = val.get("target") if isinstance(val, dict) else None
            text = val.get("text", "") if isinstance(val, dict) else str(val)
            if target:
                return f"先定位「{target}」输入框，然后输入文本：{text}"
            return f"在当前焦点位置输入文本：{text}"

        if key == "screenshot":
            path = val.get("path") if isinstance(val, dict) else None
            if path:
                return f"截取当前屏幕，保存到：{path}"
            return "截取当前屏幕"

        if key == "open_app":
            name = val.get("name") if isinstance(val, dict) else str(val)
            return f"打开应用「{name}」（如果已打开则切到它，等窗口出现）"

        if key == "press_key":
            key_name = val.get("key") if isinstance(val, dict) else str(val)
            return f"按下键盘：{key_name}"

        if key == "wait":
            ms = val.get("ms", 1000) if isinstance(val, dict) else 1000
            return f"等待 {ms} 毫秒"

        # 未知 step，回退到原始 YAML 描述
        return f"执行以下操作（原始 YAML）：{step}"

    @staticmethod
    def _extract_expect(step: dict) -> Optional[str]:
        if not step:
            return None
        val = list(step.values())[0]
        if isinstance(val, dict) and "expect" in val:
            return str(val["expect"])
        return None

    def parse_step_response(self, raw_text: str, step: dict) -> ComputerUseStep:
        """解析 trae subagent 文本响应 → ComputerUseStep。

        宽松解析：寻找关键字段（success/screenshot_path/error），取不到时返回 success=False。
        """
        text = raw_text or ""
        lowered = text.lower()
        # 简单启发式判断
        success = (
            "success" in lowered and "fail" not in lowered
        ) or (
            "completed" in lowered and "error" not in lowered
        ) or (
            "done" in lowered and not lowered.startswith("error")
        )
        # 截图路径：找 /tmp 或绝对路径
        screenshot_path = None
        for token in text.split():
            if token.startswith(("/tmp/", "/Users/", "~/")):
                screenshot_path = token.rstrip(",.;")
                break

        return ComputerUseStep(
            step=step,
            mode="computer_use",
            success=success,
            output=text,
            screenshot_path=screenshot_path,
            error=None if success else "parse_fail_or_subagent_reported_failure",
            duration_ms=0.0,
        )

    # ------------------------------------------------------------------
    # 模式 B：纯 Python 桌面执行
    # ------------------------------------------------------------------
    def _step_to_native(self, step: dict) -> ComputerUseStep:
        """模式 B：用 pyautogui/osascript 直接执行单步。"""
        start = time.time()
        try:
            return self._exec_native_step(step)
        except Exception as e:
            return ComputerUseStep(
                step=step,
                mode="desktop_native",
                success=False,
                error=f"native step error: {e}",
                duration_ms=(time.time() - start) * 1000,
            )

    def _exec_native_step(self, step: dict) -> ComputerUseStep:
        """执行单条 native step。延迟 import pyautogui 以避免未装时崩溃。"""
        start = time.time()
        if not step:
            return ComputerUseStep(
                step=step, mode="desktop_native", success=False,
                error="empty step", duration_ms=0,
            )
        key = list(step.keys())[0]
        val = step[key]

        if key == "open_app" or key == "activate":
            name = val.get("name") if isinstance(val, dict) else str(val)
            # macOS: open -a <AppName>
            import subprocess
            r = subprocess.run(["open", "-a", name], capture_output=True, text=True, timeout=15)
            return ComputerUseStep(
                step=step, mode="desktop_native",
                success=(r.returncode == 0),
                output=r.stdout,
                error=r.stderr if r.returncode != 0 else None,
                duration_ms=(time.time() - start) * 1000,
            )

        if key == "screenshot":
            path = val.get("path") if isinstance(val, dict) else None
            try:
                import pyautogui
            except ImportError as e:
                return ComputerUseStep(
                    step=step, mode="desktop_native", success=False,
                    error=f"pyautogui not installed: {e}",
                    duration_ms=(time.time() - start) * 1000,
                )
            img = pyautogui.screenshot()
            save_path = path or os.path.join(
                self._screenshot_dir, f"step_{int(time.time()*1000)}.png"
            )
            img.save(save_path)
            return ComputerUseStep(
                step=step, mode="desktop_native", success=True,
                output=save_path, screenshot_path=save_path,
                duration_ms=(time.time() - start) * 1000,
            )

        if key == "click_image":
            image = val.get("image") if isinstance(val, dict) else None
            confidence = val.get("confidence", self._pyautogui_confidence) if isinstance(val, dict) else self._pyautogui_confidence
            if not image:
                return ComputerUseStep(
                    step=step, mode="desktop_native", success=False,
                    error="click_image requires 'image' param",
                    duration_ms=(time.time() - start) * 1000,
                )
            try:
                import pyautogui
            except ImportError as e:
                return ComputerUseStep(
                    step=step, mode="desktop_native", success=False,
                    error=f"pyautogui not installed: {e}",
                    duration_ms=(time.time() - start) * 1000,
                )
            try:
                # pyautogui locateOnScreen 需要 confidence 参数（需 opencv）
                location = None
                try:
                    location = pyautogui.locateOnScreen(image, confidence=confidence)
                except Exception:
                    # 退到无 confidence 模式
                    location = pyautogui.locateOnScreen(image)
                if location is None:
                    return ComputerUseStep(
                        step=step, mode="desktop_native", success=False,
                        error=f"image not found on screen: {image}",
                        duration_ms=(time.time() - start) * 1000,
                    )
                center = pyautogui.center(location)
                pyautogui.click(center)
                return ComputerUseStep(
                    step=step, mode="desktop_native", success=True,
                    output=f"clicked at {center}",
                    duration_ms=(time.time() - start) * 1000,
                )
            except Exception as e:
                return ComputerUseStep(
                    step=step, mode="desktop_native", success=False,
                    error=f"click_image error: {e}",
                    duration_ms=(time.time() - start) * 1000,
                )

        if key == "type_text":
            text = val.get("text", "") if isinstance(val, dict) else str(val)
            try:
                import pyautogui
            except ImportError as e:
                return ComputerUseStep(
                    step=step, mode="desktop_native", success=False,
                    error=f"pyautogui not installed: {e}",
                    duration_ms=(time.time() - start) * 1000,
                )
            pyautogui.typewrite(text, interval=0.02) if all(ord(c) < 128 for c in text) else pyautogui.write(text)
            return ComputerUseStep(
                step=step, mode="desktop_native", success=True,
                output=f"typed {len(text)} chars",
                duration_ms=(time.time() - start) * 1000,
            )

        if key == "press_key":
            key_name = val.get("key") if isinstance(val, dict) else str(val)
            try:
                import pyautogui
            except ImportError as e:
                return ComputerUseStep(
                    step=step, mode="desktop_native", success=False,
                    error=f"pyautogui not installed: {e}",
                    duration_ms=(time.time() - start) * 1000,
                )
            pyautogui.press(key_name)
            return ComputerUseStep(
                step=step, mode="desktop_native", success=True,
                output=f"pressed {key_name}",
                duration_ms=(time.time() - start) * 1000,
            )

        if key == "wait":
            ms = val.get("ms", 1000) if isinstance(val, dict) else 1000
            time.sleep(ms / 1000.0)
            return ComputerUseStep(
                step=step, mode="desktop_native", success=True,
                output=f"waited {ms}ms",
                duration_ms=float(ms),
            )

        return ComputerUseStep(
            step=step, mode="desktop_native", success=False,
            error=f"unknown native step: {key}",
            duration_ms=(time.time() - start) * 1000,
        )

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def run_task_from_yaml(self, scenario: dict,
                           plan_only: Optional[bool] = None) -> ComputerUseResult:
        """从 YAML 场景运行任务。

        Args:
            scenario: 场景字典
            plan_only: 强制 plan_only 模式（仅模式 A 有效）
                - 模式 A：plan_only=True 仅生成 plan；plan_only=False 报错（需 trae 介入）
                - 模式 B：plan_only 忽略，直接执行
        """
        start = time.time()
        name = scenario.get("name", "")
        mode = scenario.get("mode", "computer_use")
        steps = scenario.get("steps", [])

        if not steps:
            return ComputerUseResult(
                task=name, passed=False, mode=mode,
                error="Scenario must contain 'steps'",
                duration_ms=0,
            )

        # 模式 A — plan_only
        if mode == "computer_use":
            plan = self.build_plan(scenario)
            # 决定是否仅生成 plan
            force_plan = plan_only if plan_only is not None else self._cu_cfg.get("plan_only", False)
            if force_plan:
                return ComputerUseResult(
                    task=name, passed=True, mode=mode,
                    plan=plan, duration_ms=(time.time() - start) * 1000,
                )
            # 模式 A 不支持纯 Python 执行（无 trae CLI）
            return ComputerUseResult(
                task=name, passed=False, mode=mode,
                plan=plan,
                error=(
                    "模式 A (computer_use) 必须由 trae 主对话介入执行："
                    "请将上述 plan 中的 prompt 依次通过 Agent(subagent_type=computer_use) "
                    "调用执行，再用 parse_step_response + _run_verification 收尾。"
                ),
                duration_ms=(time.time() - start) * 1000,
            )

        # 模式 B — 直接执行
        if mode == "desktop_native":
            executed_steps: List[ComputerUseStep] = []
            all_passed = True
            for step in steps:
                step_result = self._step_to_native(step)
                executed_steps.append(step_result)
                if not step_result.success:
                    all_passed = False
                    logger.warning(
                        "desktop_native step failed, bailing: %s",
                        step_result.error,
                    )
                    break

            result = ComputerUseResult(
                task=name, passed=all_passed, mode=mode,
                steps=executed_steps,
                duration_ms=(time.time() - start) * 1000,
            )

            # 验证
            if self._auto_verify and scenario.get("assertions"):
                result.verification = self._run_verification(
                    scenario["assertions"], executed_steps,
                )
                result.passed = result.passed and result.verification.passed

            return result

        return ComputerUseResult(
            task=name, passed=False, mode=mode,
            error=f"unknown mode: {mode} (expected: computer_use | desktop_native)",
            duration_ms=(time.time() - start) * 1000,
        )

    # ------------------------------------------------------------------
    # 验证集成
    # ------------------------------------------------------------------
    def _run_verification(self, assertions: List[dict],
                          steps: List[ComputerUseStep]) -> VerificationResult:
        """调度 DesktopAssertions 静态方法。

        assertions 是 dict 列表，每个 dict 单键，键=断言类型，值=参数。
        """
        if not assertions:
            return VerificationResult(name="verification", passed=True)

        passed = True
        details: Dict[str, Any] = {}
        # 收集 subagent 文本响应供 terminal_contains 用
        subagent_text = "\n".join(s.output for s in steps if s.mode == "computer_use")

        for idx, assertion in enumerate(assertions):
            if not assertion:
                continue
            atype = list(assertion.keys())[0]
            params = assertion[atype] or {}

            if atype == "file_exists":
                r = DesktopAssertions.file_exists(params.get("path", ""))
            elif atype == "file_contains":
                r = DesktopAssertions.file_contains(
                    params.get("path", ""), params.get("text", ""),
                )
            elif atype == "file_size_gt":
                r = DesktopAssertions.file_size_gt(
                    params.get("path", ""), params.get("size", 0),
                )
            elif atype == "terminal_contains":
                # 模式 A 搜 subagent 文本；模式 B 走 osascript
                if subagent_text:
                    r = DesktopAssertions.terminal_contains(
                        params.get("text", ""), subagent_response=subagent_text,
                    )
                else:
                    r = DesktopAssertions.terminal_contains(
                        params.get("text", ""), osascript_path=self._osascript_path,
                    )
            elif atype == "ui_visual_match":
                r = DesktopAssertions.ui_visual_match(
                    current_path=params.get("current", params.get("current_path", "")),
                    baseline_path=params.get("baseline", params.get("baseline_path", "")),
                    threshold=params.get("threshold", self._visual_threshold),
                )
            else:
                r = VerificationResult(
                    name=atype, passed=False,
                    details={"assertion": assertion},
                    error=f"unknown assertion type: {atype}",
                )

            details[f"assertion_{idx}_{atype}"] = r.to_dict()
            if not r.passed:
                passed = False

        return VerificationResult(
            name="verification", passed=passed, details=details,
        )
