"""场景运行引擎 — 解析并执行 YAML 定义的测试场景

场景定义格式（YAML）：
```yaml
name: 前端冒烟测试
description: 测试前端核心页面是否正常加载
steps:
  - name: 打开首页
    action: navigate
    url: http://localhost:3000
    verify:
      dom:
        - selector: "body"
          action: exists
  - name: 点击登录按钮
    action: click
    selector: "button:has-text('登录')"
  - name: 验证登录表单
    action: verify
    assertions:
      dom:
        - selector: "input[type='email']"
          action: exists
```

支持的 action：
- navigate: 导航到 URL
- click: 点击元素
- type: 输入文本
- select: 选择下拉选项
- scroll: 滚动
- hover: 悬停
- wait: 等待
- verify: 执行验证
- screenshot: 截图
- assert: 自定义断言
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests  # 用于 _call_dreamos_intent_route（HC-7 FAIL-OPEN）
import yaml
from playwright.sync_api import Page

from .result_verifier import ResultVerifier, VerificationResult
from .user_simulator import UserSimulator

logger = logging.getLogger("real_env.scenario_runner")


@dataclass
class StepResult:
    """步骤执行结果"""
    name: str
    action: str
    passed: bool
    duration_ms: float
    error: Optional[str] = None
    screenshot: Optional[bytes] = None
    verification: Optional[VerificationResult] = None


@dataclass
class ScenarioResult:
    """场景执行结果"""
    name: str
    description: str
    passed: bool
    steps: List[StepResult] = field(default_factory=list)
    duration_ms: float = 0.0
    error: Optional[str] = None
    # Trade 页 UI 验证结果（S 层徽章 / 链路追踪）
    trade_ui: Optional[dict] = None


class ScenarioRunner:
    """场景运行引擎 — 解析并执行测试场景"""

    def __init__(self, config: dict, user_simulator: UserSimulator,
                 result_verifier: ResultVerifier, pipeline=None):
        self._config = config
        self._simulator = user_simulator
        self._verifier = result_verifier
        self._scenario_cfg = config.get("scenarios", {})
        self._pipeline = pipeline  # 可选 IntentSamplePipeline（向后兼容）

    # ------------------------------------------------------------------
    # 场景加载
    # ------------------------------------------------------------------
    def load_scenario(self, scenario_path: str) -> Dict:
        """从 YAML 文件加载场景定义。"""
        path = Path(scenario_path)
        if not path.exists():
            raise FileNotFoundError(f"Scenario file not found: {scenario_path}")

        with open(path, "r", encoding="utf-8") as f:
            scenario = yaml.safe_load(f)

        if not isinstance(scenario, dict):
            raise ValueError(f"Invalid scenario format: {scenario_path}")

        if "steps" not in scenario:
            raise ValueError(f"Scenario must contain 'steps': {scenario_path}")

        return scenario

    # ------------------------------------------------------------------
    # 场景执行
    # ------------------------------------------------------------------
    def run(self, page: Page, scenario: Dict) -> ScenarioResult:
        """执行场景。

        Args:
            page: Playwright Page 实例
            scenario: 场景定义字典

        Returns:
            ScenarioResult 执行结果
        """
        name = scenario.get("name", "unnamed")
        description = scenario.get("description", "")
        steps = scenario.get("steps", [])
        timeout = scenario.get("timeout", self._scenario_cfg.get("default_timeout", 120))
        retry_count = scenario.get("retry", self._scenario_cfg.get("retry_count", 1))

        logger.info("Running scenario: %s (%d steps)", name, len(steps))

        result = ScenarioResult(
            name=name,
            description=description,
            passed=False,
        )

        start_time = time.time()

        # 在场景开始时启动网络捕获（确保能捕获 navigate 等步骤的请求）
        self._verifier.start_network_capture(page)

        for attempt in range(retry_count + 1):
            if attempt > 0:
                logger.info("Retry attempt %d/%d for scenario: %s", attempt, retry_count, name)

            step_results = []
            all_passed = True

            for step in steps:
                step_result = self._execute_step(page, step)
                step_results.append(step_result)

                if not step_result.passed:
                    all_passed = False
                    # 检查是否继续执行（fail_fast）
                    if step.get("fail_fast", True):
                        logger.warning(
                            "Step '%s' failed, stopping scenario (fail_fast=true)",
                            step.get("name"),
                        )
                        break

            result.steps = step_results
            result.passed = all_passed

            if all_passed:
                break

            # 如果所有步骤都执行完但有失败，且还有重试次数
            if attempt < retry_count:
                time.sleep(1)  # 重试前等待

        result.duration_ms = (time.time() - start_time) * 1000

        if result.passed:
            logger.info("Scenario '%s' PASSED (%.0fms)", name, result.duration_ms)
        else:
            logger.error("Scenario '%s' FAILED (%.0fms)", name, result.duration_ms)

        # === 新增：意图训练钩子（spec §3.2, SD-5）===
        if scenario.get("intent_training") and self._pipeline:
            try:
                self._capture_intent_sample(scenario, page, result)
            except Exception as e:
                logger.warning("IntentSample capture failed (FAIL-OPEN): %s", e)

        # === 新增：Trade 页 UI 断言（S 层徽章 / 链路追踪）===
        if "/dashboard/trade" in str(scenario.get("steps", [{}])[0].get("url", "")):
            try:
                result.trade_ui = self._verify_trade_page_ui(page)
            except Exception as e:
                logger.warning("Trade UI verify failed (FAIL-OPEN): %s", e)
                result.trade_ui = {"error": str(e), "passed": None}

        return result

    def run_from_file(self, page: Page, scenario_path: str) -> ScenarioResult:
        """从文件加载并执行场景。"""
        scenario = self.load_scenario(scenario_path)
        return self.run(page, scenario)

    # ------------------------------------------------------------------
    # 步骤执行
    # ------------------------------------------------------------------
    def _execute_step(self, page: Page, step: Dict) -> StepResult:
        """执行单个步骤。"""
        name = step.get("name", "unnamed")
        action = step.get("action", "")
        start_time = time.time()

        logger.info("Step: %s [%s]", name, action)

        try:
            if action == "navigate":
                self._step_navigate(page, step)
            elif action == "click":
                self._step_click(page, step)
            elif action == "type":
                self._step_type(page, step)
            elif action == "select":
                self._step_select(page, step)
            elif action == "scroll":
                self._step_scroll(page, step)
            elif action == "hover":
                self._step_hover(page, step)
            elif action == "wait":
                self._step_wait(page, step)
            elif action == "verify":
                return self._step_verify(page, step, start_time)
            elif action == "screenshot":
                self._step_screenshot(page, step)
            elif action == "assert":
                return self._step_assert(page, step, start_time)
            elif action == "javascript":
                self._step_javascript(page, step)
            else:
                raise ValueError(f"Unknown action: {action}")

            duration = (time.time() - start_time) * 1000
            return StepResult(
                name=name,
                action=action,
                passed=True,
                duration_ms=duration,
            )

        except Exception as e:
            duration = (time.time() - start_time) * 1000
            logger.error("Step '%s' failed: %s", name, str(e))
            return StepResult(
                name=name,
                action=action,
                passed=False,
                duration_ms=duration,
                error=str(e),
            )

    def _step_navigate(self, page: Page, step: Dict) -> None:
        """导航到 URL。"""
        url = step["url"]
        wait_until = step.get("wait_until", "networkidle")
        timeout = step.get("timeout", 30000)
        page.goto(url, wait_until=wait_until, timeout=timeout)
        logger.info("Navigated to: %s", url)

    def _step_click(self, page: Page, step: Dict) -> None:
        """点击元素。"""
        selector = step["selector"]
        locator = page.locator(selector)
        locator.wait_for(state="visible", timeout=step.get("timeout", 10000))

        if step.get("human", True):
            self._simulator.human_click(page, locator)
        else:
            locator.click()

    def _step_type(self, page: Page, step: Dict) -> None:
        """输入文本。"""
        selector = step["selector"]
        text = step["text"]
        locator = page.locator(selector)
        locator.wait_for(state="visible", timeout=step.get("timeout", 10000))

        if step.get("human", True):
            self._simulator.human_type(locator, text)
        else:
            locator.fill(text)

    def _step_select(self, page: Page, step: Dict) -> None:
        """选择下拉选项。"""
        selector = step["selector"]
        value = step.get("value")
        label = step.get("label")
        locator = page.locator(selector)

        if value:
            locator.select_option(value=value)
        elif label:
            locator.select_option(label=label)

    def _step_scroll(self, page: Page, step: Dict) -> None:
        """滚动页面。"""
        direction = step.get("direction", "down")
        distance = step.get("distance")

        if step.get("human", True):
            self._simulator.human_scroll(page, direction=direction, distance=distance)
        else:
            if direction == "down":
                page.mouse.wheel(0, distance or 300)
            elif direction == "up":
                page.mouse.wheel(0, -(distance or 300))

    def _step_hover(self, page: Page, step: Dict) -> None:
        """悬停元素。"""
        selector = step["selector"]
        locator = page.locator(selector)
        locator.wait_for(state="visible", timeout=step.get("timeout", 10000))

        if step.get("human", True):
            self._simulator.human_hover(page, locator)
        else:
            locator.hover()

    def _step_wait(self, page: Page, step: Dict) -> None:
        """等待。"""
        if "selector" in step:
            state = step.get("state", "visible")
            page.locator(step["selector"]).wait_for(
                state=state, timeout=step.get("timeout", 10000)
            )
        elif "ms" in step:
            time.sleep(step["ms"] / 1000.0)
        elif "seconds" in step:
            time.sleep(step["seconds"])

    def _step_verify(self, page: Page, step: Dict, start_time: float) -> StepResult:
        """执行验证步骤。"""
        assertions = step.get("assertions", {})
        assertions["name"] = step.get("name", "verify")

        # 网络捕获已在场景开始时启动，直接使用已捕获的日志
        verification = self._verifier.verify(page, assertions)

        duration = (time.time() - start_time) * 1000
        return StepResult(
            name=step.get("name", "verify"),
            action="verify",
            passed=verification.passed,
            duration_ms=duration,
            verification=verification,
        )

    def _step_screenshot(self, page: Page, step: Dict) -> None:
        """截图。"""
        path = step.get("path")
        full_page = step.get("full_page", False)
        page.screenshot(path=path, full_page=full_page)
        logger.info("Screenshot saved: %s", path)

    def _step_assert(self, page: Page, step: Dict, start_time: float) -> StepResult:
        """自定义断言。"""
        expression = step.get("expression", "")
        # 在浏览器中执行 JavaScript 断言
        result = page.evaluate(expression)
        passed = bool(result)

        duration = (time.time() - start_time) * 1000
        return StepResult(
            name=step.get("name", "assert"),
            action="assert",
            passed=passed,
            duration_ms=duration,
        )

    def _step_javascript(self, page: Page, step: Dict) -> None:
        """执行 JavaScript。"""
        expression = step.get("expression", "")
        page.evaluate(expression)

    # ------------------------------------------------------------------
    # 批量执行
    # ------------------------------------------------------------------
    def run_batch(self, page: Page, scenario_paths: List[str]) -> List[ScenarioResult]:
        """批量执行多个场景。"""
        results = []
        for path in scenario_paths:
            try:
                result = self.run_from_file(page, path)
                results.append(result)
            except Exception as e:
                logger.error("Failed to run scenario %s: %s", path, e)
                results.append(ScenarioResult(
                    name=path,
                    description="",
                    passed=False,
                    error=str(e),
                ))
        return results

    # ------------------------------------------------------------------
    # 意图训练钩子（spec §3.2, SD-5）
    # ------------------------------------------------------------------
    def _capture_intent_sample(self, scenario: Dict, page: Page, result: ScenarioResult) -> None:
        """从 YAML 场景 + 执行结果构建 IntentSample 并落盘

        意图识别优先级：
        1. DreamOS /api/v1/intent/route（真实意图识别）
        2. UI S 层感知意图徽章（DreamOS 不可用时的降级，前端已识别的意图）
        """
        user_input = self._extract_user_input(scenario)
        sample = self._build_intent_sample(scenario, result, user_input=user_input)
        recognizer_output = self._call_dreamos_intent_route(user_input)

        # FAIL-OPEN 降级：DreamOS 不可用时，用前端 S 层徽章展示的意图
        if not recognizer_output.get("predicted_intent"):
            s_layer_intent = self._extract_s_layer_intent(page)
            if s_layer_intent:
                recognizer_output = {
                    "predicted_intent": s_layer_intent,
                    "confidence": recognizer_output.get("confidence", 0.8),
                    "level": "ui_s_layer",
                }
                logger.info("DreamOS 降级，使用 UI S 层意图: %s", s_layer_intent)

        sample.recognizer_output = recognizer_output
        sample.human_label = self._auto_label(
            recognizer_output, scenario["intent_training"]["gold_intent"]
        )
        self._pipeline.ingest(sample)

    def _extract_s_layer_intent(self, page: Page) -> Optional[str]:
        """从 Trade 页 S 层感知意图徽章提取意图值

        结构: div.flex.items-center.justify-between.mb-3 > div:last-child
              > span("感知层:") + span.inline-flex(意图值)

        若徽章显示"执行中"（任务未完成），轮询等待最多 20 秒
        直至出现真实意图值。
        """
        import time
        max_wait = 20
        poll_interval = 2
        elapsed = 0
        last_intent = None

        while elapsed <= max_wait:
            try:
                intent = page.evaluate("""
                    () => {
                        const header = document.querySelector('div.flex.items-center.justify-between.mb-3');
                        if (!header) return null;
                        const rightDiv = header.querySelector(':scope > div:last-child');
                        if (!rightDiv) return null;
                        const spans = rightDiv.querySelectorAll('span');
                        for (let i = 0; i < spans.length; i++) {
                            if (spans[i].textContent?.trim() === '感知层:') {
                                const badge = spans[i + 1];
                                if (badge) return badge.textContent?.trim() || null;
                            }
                        }
                        const badge = rightDiv.querySelector('span.inline-flex');
                        return badge ? badge.textContent?.trim() : null;
                    }
                """)
                last_intent = intent
                # 任务执行中显示"执行中"，需等待 done 事件设置真实意图
                if intent and intent != "执行中" and intent != "识别中":
                    return intent
            except Exception as e:
                logger.warning("提取 S 层意图失败: %s", e)

            time.sleep(poll_interval)
            elapsed += poll_interval

        return last_intent

    def _build_intent_sample(self, scenario: Dict, result: ScenarioResult,
                            user_input: str) -> IntentSample:
        """从 YAML scenario 构建 IntentSample（recognizer_output 待后续填充）"""
        import uuid
        from datetime import datetime, timezone
        from .intent_sample_pipeline import IntentSample

        it = scenario["intent_training"]
        return IntentSample(
            sample_id=str(uuid.uuid4()),
            input={
                "user_query": user_input,
                "scenario_id": it["scenario_id"],
                "market_features": it.get("market_features", {}),
            },
            gold={"gold_chain": "C", "gold_intent": it["gold_intent"]},
            recognizer_output={},
            human_label={},
            dataset_split=it.get("split", "train"),
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def _call_dreamos_intent_route(self, user_input: str) -> dict:
        """调用 DreamOS /intent/route（HC-7 FAIL-OPEN）"""
        import requests
        try:
            resp = requests.post(
                "http://localhost:8000/api/v1/intent/route",
                json={"text": user_input},
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "predicted_intent": data.get("predicted_intent"),
                    "confidence": data.get("confidence", 0.0),
                    "level": data.get("level", "remote"),
                }
            logger.warning("DreamOS /intent/route status=%s, 降级", resp.status_code)
            return {"predicted_intent": None, "confidence": 0.0, "level": "failopen"}
        except Exception as e:
            logger.warning("DreamOS /intent/route 不可用，降级: %s", e)
            return {"predicted_intent": None, "confidence": 0.0, "level": "failopen"}

    def _auto_label(self, recognizer_output: dict, gold_intent: str) -> dict:
        """自动对照 gold_intent 生成 human_label"""
        predicted = recognizer_output.get("predicted_intent")
        confirmed = predicted == gold_intent
        return {
            "confirmed": confirmed,
            "corrected_intent": None if confirmed else gold_intent,
        }

    def _extract_user_input(self, scenario: Dict) -> str:
        """从 scenario.steps 提取第一个 type 步骤的 text（用户问法）"""
        for step in scenario.get("steps", []):
            if step.get("action") == "type" and step.get("text"):
                return step["text"]
        return ""

    # ------------------------------------------------------------------
    # Trade 页 UI 断言（spec: /dashboard/trade 意图识别验证）
    # ------------------------------------------------------------------
    def _verify_trade_page_ui(self, page: Page) -> dict:
        """验证 Trade 页 S 层意图徽章 + 链路追踪状态

        Returns:
            {
                "s_layer_intent": str | None,    # 感知层意图值
                "s_layer_visible": bool,         # 徽章是否展示
                "chain_active": bool,            # 链路追踪是否有活跃链路
                "chain_text": str,               # 链路追踪区域文本
                "passed": bool | None            # 综合是否通过（徽章非空）
            }
        """
        result = {
            "s_layer_intent": None,
            "s_layer_visible": False,
            "chain_active": False,
            "chain_text": "",
            "passed": None,
        }

        try:
            # 1. S 层感知意图徽章
            # 结构: div.flex.items-center.justify-between.mb-3 > div:last-child > span.inline-flex
            s_layer = page.evaluate("""
                () => {
                    const header = document.querySelector('div.flex.items-center.justify-between.mb-3');
                    if (!header) return null;
                    const rightDiv = header.querySelector(':scope > div:last-child');
                    if (!rightDiv) return null;
                    // 找包含 "感知层:" 的 span 后面的 badge
                    const spans = rightDiv.querySelectorAll('span');
                    for (let i = 0; i < spans.length; i++) {
                        if (spans[i].textContent?.trim() === '感知层:') {
                            const badge = spans[i + 1];
                            if (badge) return badge.textContent?.trim() || null;
                        }
                    }
                    // 备选：直接取最后一个 inline-flex span
                    const badge = rightDiv.querySelector('span.inline-flex');
                    return badge ? badge.textContent?.trim() : null;
                }
            """)
            if s_layer:
                result["s_layer_intent"] = s_layer
                result["s_layer_visible"] = True

            # 2. 链路追踪状态
            chain_text = page.evaluate("""
                () => {
                    const headings = Array.from(document.querySelectorAll('h3'));
                    const chainHeading = headings.find(h => h.textContent?.includes('链路追踪'));
                    if (!chainHeading) return '';
                    // 取 heading 父容器的文本
                    const container = chainHeading.closest('div') || chainHeading.parentElement;
                    return container ? container.textContent?.slice(0, 200) : '';
                }
            """)
            result["chain_text"] = chain_text or ""
            result["chain_active"] = "暂无活跃链路" not in result["chain_text"] and bool(result["chain_text"])

            # 综合判定：S 层徽章展示即通过（链路追踪非必须，market_query 可能无链路）
            result["passed"] = result["s_layer_visible"]

        except Exception as e:
            logger.warning("Trade UI verification error: %s", e)
            result["error"] = str(e)

        return result
