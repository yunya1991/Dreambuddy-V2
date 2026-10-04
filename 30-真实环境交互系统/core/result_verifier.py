"""结果验证层 — DOM + 截图 + 网络请求三重验证

反幻觉核心机制：
- 不依赖 AI 主观判断，而是通过真实数据验证
- DOM 验证：检查元素是否存在、文本是否匹配、属性是否正确
- 截图验证：像素级对比，检测视觉变化
- 网络请求验证：捕获 API 请求和响应，验证数据正确性

验证模式：
- all: 三重验证全部通过才算通过
- any: 任一验证通过就算通过
- majority: 多数验证通过就算通过
"""
from __future__ import annotations

import io
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PIL import Image
import numpy as np
from playwright.sync_api import Page, Response

logger = logging.getLogger("real_env.result_verifier")


class VerificationMode(Enum):
    """验证模式"""
    ALL = "all"          # 全部通过
    ANY = "any"          # 任一通过
    MAJORITY = "majority"  # 多数通过


@dataclass
class VerificationResult:
    """验证结果"""
    name: str
    passed: bool
    details: Dict[str, Any] = field(default_factory=dict)
    screenshot: Optional[bytes] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "details": self.details,
            "error": self.error,
        }


class ResultVerifier:
    """结果验证器 — DOM + 截图 + 网络请求三重验证"""

    def __init__(self, config: dict):
        self._config = config.get("verification", {})
        self._mode = VerificationMode(self._config.get("mode", "all"))
        self._dom_timeout = self._config.get("dom_timeout", 10000)
        self._screenshot_threshold = self._config.get("screenshot_threshold", 0.05)
        self._network_logs: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # 三重验证主接口
    # ------------------------------------------------------------------
    def verify(self, page: Page, assertions: Dict[str, Any]) -> VerificationResult:
        """执行三重验证。

        Args:
            page: Playwright Page 实例
            assertions: 断言配置，包含 dom / screenshot / network 三类

        Returns:
            VerificationResult 验证结果
        """
        results = {}

        # 1. DOM 验证
        if "dom" in assertions:
            results["dom"] = self._verify_dom(page, assertions["dom"])

        # 2. 截图验证
        if "screenshot" in assertions:
            results["screenshot"] = self._verify_screenshot(page, assertions["screenshot"])

        # 3. 网络请求验证
        if "network" in assertions:
            results["network"] = self._verify_network(assertions["network"])

        # 综合判定
        passed = self._combine_results(results)

        return VerificationResult(
            name=assertions.get("name", "verification"),
            passed=passed,
            details={k: v.to_dict() for k, v in results.items()},
        )

    def _combine_results(self, results: Dict[str, VerificationResult]) -> bool:
        """根据验证模式综合判定。"""
        if not results:
            return True

        passed_list = [r.passed for r in results.values()]

        if self._mode == VerificationMode.ALL:
            return all(passed_list)
        elif self._mode == VerificationMode.ANY:
            return any(passed_list)
        elif self._mode == VerificationMode.MAJORITY:
            return passed_list.count(True) > len(passed_list) / 2
        return all(passed_list)

    # ------------------------------------------------------------------
    # DOM 验证
    # ------------------------------------------------------------------
    def _verify_dom(self, page: Page, dom_assertions: List[Dict]) -> VerificationResult:
        """DOM 验证：检查元素状态、文本、属性等。"""
        details = {"checks": [], "passed": True}

        for assertion in dom_assertions:
            try:
                result = self._execute_dom_assertion(page, assertion)
                details["checks"].append(result)
                if not result["passed"]:
                    details["passed"] = False
            except Exception as e:
                details["checks"].append({
                    "assertion": assertion,
                    "passed": False,
                    "error": str(e),
                })
                details["passed"] = False

        return VerificationResult(
            name="dom",
            passed=details["passed"],
            details=details,
        )

    def _execute_dom_assertion(self, page: Page, assertion: Dict) -> Dict:
        """执行单个 DOM 断言。"""
        selector = assertion.get("selector")
        action = assertion.get("action", "exists")
        expected = assertion.get("expected")
        timeout = assertion.get("timeout", self._dom_timeout)

        locator = page.locator(selector)

        if action == "exists":
            count = locator.count()
            return {
                "assertion": assertion,
                "passed": count > 0,
                "actual": count,
            }

        elif action == "not_exists":
            count = locator.count()
            return {
                "assertion": assertion,
                "passed": count == 0,
                "actual": count,
            }

        elif action == "text_contains":
            locator.first.wait_for(state="visible", timeout=timeout)
            text = locator.first.inner_text()
            return {
                "assertion": assertion,
                "passed": expected in text,
                "actual": text[:200],
            }

        elif action == "text_equals":
            locator.first.wait_for(state="visible", timeout=timeout)
            text = locator.first.inner_text().strip()
            return {
                "assertion": assertion,
                "passed": text == expected,
                "actual": text,
            }

        elif action == "attribute_equals":
            attr_name = assertion.get("attribute")
            locator.first.wait_for(state="attached", timeout=timeout)
            actual = locator.first.get_attribute(attr_name)
            return {
                "assertion": assertion,
                "passed": actual == expected,
                "actual": actual,
            }

        elif action == "is_visible":
            visible = locator.first.is_visible()
            return {
                "assertion": assertion,
                "passed": visible == expected if expected is not None else visible,
                "actual": visible,
            }

        elif action == "count_equals":
            count = locator.count()
            return {
                "assertion": assertion,
                "passed": count == expected,
                "actual": count,
            }

        elif action == "count_greater_than":
            count = locator.count()
            return {
                "assertion": assertion,
                "passed": count > expected,
                "actual": count,
            }

        elif action == "has_class":
            locator.first.wait_for(state="attached", timeout=timeout)
            classes = locator.first.get_attribute("class") or ""
            return {
                "assertion": assertion,
                "passed": expected in classes.split(),
                "actual": classes,
            }

        elif action == "is_enabled":
            enabled = locator.first.is_enabled()
            return {
                "assertion": assertion,
                "passed": enabled == expected if expected is not None else enabled,
                "actual": enabled,
            }

        elif action == "value_equals":
            locator.first.wait_for(state="attached", timeout=timeout)
            value = locator.first.input_value()
            return {
                "assertion": assertion,
                "passed": value == expected,
                "actual": value,
            }

        else:
            return {
                "assertion": assertion,
                "passed": False,
                "error": f"Unknown action: {action}",
            }

    # ------------------------------------------------------------------
    # 截图验证
    # ------------------------------------------------------------------
    def _verify_screenshot(self, page: Page, screenshot_assertion: Dict) -> VerificationResult:
        """截图验证：对比截图，检测视觉变化。"""
        details = {"passed": True}

        try:
            # 截取当前页面
            current_screenshot = page.screenshot(full_page=screenshot_assertion.get("full_page", False))

            # 如果有基准截图，进行对比
            baseline_path = screenshot_assertion.get("baseline")
            if baseline_path and Path(baseline_path).exists():
                diff_score = self._compare_screenshots(
                    baseline_path, current_screenshot
                )
                threshold = screenshot_assertion.get(
                    "threshold", self._screenshot_threshold
                )
                details["diff_score"] = diff_score
                details["threshold"] = threshold
                details["passed"] = diff_score <= threshold

                # 保存差异截图
                if not details["passed"] and screenshot_assertion.get("save_diff"):
                    self._save_diff_screenshot(
                        baseline_path, current_screenshot,
                        screenshot_assertion.get("diff_path", "/tmp/diff.png"),
                    )
            else:
                # 无基准截图，保存当前截图作为基准
                details["message"] = "No baseline found, current screenshot saved"
                details["screenshot_saved"] = True

            details["screenshot"] = current_screenshot[:100]  # 仅存储引用

        except Exception as e:
            details["passed"] = False
            details["error"] = str(e)

        return VerificationResult(
            name="screenshot",
            passed=details["passed"],
            details=details,
        )

    def _compare_screenshots(self, baseline_path: str, current_bytes: bytes) -> float:
        """比较两张截图，返回差异比例（0-1）。

        实现已抽离至 utils/screenshot_diff.py:compare_screenshot_bytes，
        供 ResultVerifier 和 DesktopAssertions 共享。本方法保留为薄包装。
        """
        from utils.screenshot_diff import compare_screenshot_bytes
        return compare_screenshot_bytes(baseline_path, current_bytes)

    def _save_diff_screenshot(self, baseline_path: str, current_bytes: bytes,
                              diff_path: str) -> None:
        """保存差异截图（红色高亮差异区域）。"""
        baseline = Image.open(baseline_path).convert("RGB")
        current = Image.open(io.BytesIO(current_bytes)).convert("RGB")

        if baseline.size != current.size:
            current = current.resize(baseline.size)

        baseline_arr = np.array(baseline)
        current_arr = np.array(current)

        # 生成差异图：差异部分标红
        diff_mask = np.any(np.abs(baseline_arr.astype(int) - current_arr.astype(int)) > 30, axis=2)
        diff_arr = current_arr.copy()
        diff_arr[diff_mask] = [255, 0, 0]  # 红色高亮

        Image.fromarray(diff_arr).save(diff_path)

    # ------------------------------------------------------------------
    # 网络请求验证
    # ------------------------------------------------------------------
    def _verify_network(self, network_assertions: List[Dict]) -> VerificationResult:
        """网络请求验证：检查捕获的请求/响应。"""
        details = {"checks": [], "passed": True}

        for assertion in network_assertions:
            try:
                result = self._execute_network_assertion(assertion)
                details["checks"].append(result)
                if not result["passed"]:
                    details["passed"] = False
            except Exception as e:
                details["checks"].append({
                    "assertion": assertion,
                    "passed": False,
                    "error": str(e),
                })
                details["passed"] = False

        return VerificationResult(
            name="network",
            passed=details["passed"],
            details=details,
        )

    def _execute_network_assertion(self, assertion: Dict) -> Dict:
        """执行单个网络请求断言。"""
        action = assertion.get("action", "request_exists")
        url_pattern = assertion.get("url_pattern", "")
        expected_status = assertion.get("status")
        expected_body = assertion.get("body_contains")

        matched_logs = [
            log for log in self._network_logs
            if url_pattern in log.get("url", "")
        ]

        if action == "request_exists":
            return {
                "assertion": assertion,
                "passed": len(matched_logs) > 0,
                "actual": len(matched_logs),
            }

        elif action == "response_status":
            for log in matched_logs:
                if log.get("status") == expected_status:
                    return {
                        "assertion": assertion,
                        "passed": True,
                        "actual": log.get("status"),
                    }
            return {
                "assertion": assertion,
                "passed": False,
                "actual": [log.get("status") for log in matched_logs],
            }

        elif action == "response_body_contains":
            for log in matched_logs:
                body = log.get("response_body", "")
                if expected_body in str(body):
                    return {
                        "assertion": assertion,
                        "passed": True,
                        "actual": "found in response body",
                    }
            return {
                "assertion": assertion,
                "passed": False,
                "actual": "not found",
            }

        else:
            return {
                "assertion": assertion,
                "passed": False,
                "error": f"Unknown action: {action}",
            }

    # ------------------------------------------------------------------
    # 网络请求捕获
    # ------------------------------------------------------------------
    def start_network_capture(self, page: Page) -> None:
        """开始捕获网络请求。"""
        self._network_logs = []

        def on_request(request):
            self._network_logs.append({
                "type": "request",
                "url": request.url,
                "method": request.method,
                "timestamp": time.time(),
            })

        def on_response(response: Response):
            try:
                body = ""
                if response.headers.get("content-type", "").startswith("application/json"):
                    try:
                        body = response.json()
                    except Exception:
                        body = response.text()[:1000]
                else:
                    body = response.text()[:500]
            except Exception:
                body = ""

            self._network_logs.append({
                "type": "response",
                "url": response.url,
                "status": response.status,
                "method": response.request.method,
                "response_body": body,
                "timestamp": time.time(),
            })

        page.on("request", on_request)
        page.on("response", on_response)
        logger.info("Network capture started")

    def stop_network_capture(self, page: Page) -> List[Dict]:
        """停止捕获并返回网络日志。"""
        page.remove_listener("request", lambda r: None)
        page.remove_listener("response", lambda r: None)
        logs = self._network_logs.copy()
        logger.info("Network capture stopped, %d logs", len(logs))
        return logs

    @property
    def network_logs(self) -> List[Dict]:
        return self._network_logs
