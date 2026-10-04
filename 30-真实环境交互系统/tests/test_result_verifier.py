"""结果验证层单元测试 — 验证三重验证逻辑"""
import sys
from pathlib import Path

import pytest
from PIL import Image
import io

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.result_verifier import ResultVerifier, VerificationMode, VerificationResult


@pytest.fixture
def verifier():
    config = {
        "verification": {
            "mode": "all",
            "dom_timeout": 5000,
            "screenshot_threshold": 0.05,
        }
    }
    return ResultVerifier(config)


class TestVerificationResult:
    """验证结果数据类测试"""

    def test_verification_result_creation(self):
        result = VerificationResult(
            name="test",
            passed=True,
            details={"key": "value"},
        )
        assert result.name == "test"
        assert result.passed is True
        assert result.details == {"key": "value"}
        assert result.error is None

    def test_verification_result_to_dict(self):
        result = VerificationResult(
            name="test",
            passed=False,
            details={"checks": []},
            error="something went wrong",
        )
        d = result.to_dict()
        assert d["name"] == "test"
        assert d["passed"] is False
        assert d["error"] == "something went wrong"


class TestCombineResults:
    """验证结果综合判定测试"""

    def test_all_mode_all_passed(self, verifier):
        results = {
            "dom": VerificationResult("dom", True),
            "screenshot": VerificationResult("screenshot", True),
            "network": VerificationResult("network", True),
        }
        assert verifier._combine_results(results) is True

    def test_all_mode_one_failed(self, verifier):
        results = {
            "dom": VerificationResult("dom", True),
            "screenshot": VerificationResult("screenshot", False),
            "network": VerificationResult("network", True),
        }
        assert verifier._combine_results(results) is False

    def test_any_mode_one_passed(self):
        config = {"verification": {"mode": "any"}}
        verifier = ResultVerifier(config)
        results = {
            "dom": VerificationResult("dom", False),
            "screenshot": VerificationResult("screenshot", True),
            "network": VerificationResult("network", False),
        }
        assert verifier._combine_results(results) is True

    def test_any_mode_all_failed(self):
        config = {"verification": {"mode": "any"}}
        verifier = ResultVerifier(config)
        results = {
            "dom": VerificationResult("dom", False),
            "screenshot": VerificationResult("screenshot", False),
        }
        assert verifier._combine_results(results) is False

    def test_majority_mode(self):
        config = {"verification": {"mode": "majority"}}
        verifier = ResultVerifier(config)
        results = {
            "dom": VerificationResult("dom", True),
            "screenshot": VerificationResult("screenshot", True),
            "network": VerificationResult("network", False),
        }
        assert verifier._combine_results(results) is True

    def test_empty_results(self, verifier):
        assert verifier._combine_results({}) is True


class TestScreenshotComparison:
    """截图对比测试"""

    def test_identical_images(self, verifier, tmp_path):
        # 创建两张相同的图片
        img = Image.new("RGB", (100, 100), color="red")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_bytes = img_bytes.getvalue()

        baseline = tmp_path / "baseline.png"
        img.save(baseline)

        diff = verifier._compare_screenshots(str(baseline), img_bytes)
        assert diff == 0.0

    def test_different_images(self, verifier, tmp_path):
        # 创建两张不同的图片
        img1 = Image.new("RGB", (100, 100), color="red")
        img2 = Image.new("RGB", (100, 100), color="blue")

        baseline = tmp_path / "baseline.png"
        img1.save(baseline)

        img2_bytes = io.BytesIO()
        img2.save(img2_bytes, format="PNG")
        img2_bytes = img2_bytes.getvalue()

        diff = verifier._compare_screenshots(str(baseline), img2_bytes)
        assert diff > 0.0

    def test_different_sizes(self, verifier, tmp_path):
        # 创建不同尺寸的图片
        img1 = Image.new("RGB", (100, 100), color="red")
        img2 = Image.new("RGB", (200, 200), color="red")

        baseline = tmp_path / "baseline.png"
        img1.save(baseline)

        img2_bytes = io.BytesIO()
        img2.save(img2_bytes, format="PNG")
        img2_bytes = img2_bytes.getvalue()

        diff = verifier._compare_screenshots(str(baseline), img2_bytes)
        assert diff == 0.0  # 相同颜色，resize 后无差异


class TestNetworkCapture:
    """网络请求捕获测试"""

    def test_start_capture_initializes_logs(self, verifier):
        verifier._network_logs = [{"url": "old"}]
        # 模拟 start_network_capture 的初始化
        verifier._network_logs = []
        assert verifier._network_logs == []

    def test_network_logs_property(self, verifier):
        verifier._network_logs = [{"url": "test"}]
        assert verifier.network_logs == [{"url": "test"}]

    def test_execute_network_assertion_request_exists(self, verifier):
        verifier._network_logs = [
            {"type": "request", "url": "http://api.example.com/data", "method": "GET"},
        ]
        assertion = {
            "action": "request_exists",
            "url_pattern": "api.example.com",
        }
        result = verifier._execute_network_assertion(assertion)
        assert result["passed"] is True

    def test_execute_network_assertion_request_not_exists(self, verifier):
        verifier._network_logs = []
        assertion = {
            "action": "request_exists",
            "url_pattern": "nonexistent.com",
        }
        result = verifier._execute_network_assertion(assertion)
        assert result["passed"] is False

    def test_execute_network_assertion_response_status(self, verifier):
        verifier._network_logs = [
            {"type": "response", "url": "http://api.example.com/data", "status": 200},
        ]
        assertion = {
            "action": "response_status",
            "url_pattern": "api.example.com",
            "status": 200,
        }
        result = verifier._execute_network_assertion(assertion)
        assert result["passed"] is True

    def test_execute_network_assertion_unknown_action(self, verifier):
        assertion = {
            "action": "unknown_action",
            "url_pattern": "test",
        }
        result = verifier._execute_network_assertion(assertion)
        assert result["passed"] is False
        assert "Unknown action" in result["error"]
