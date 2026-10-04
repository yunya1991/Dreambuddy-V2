"""30-真实环境交互系统 — 核心模块

真实浏览器环境交互测试系统，通过连接真实 Chrome 浏览器（CDP）或启动独立 Chrome，
模拟真实用户行为，进行前端UI测试、端到端系统测试和AI能力验证。

核心模块：
- browser_connector: 浏览器连接层（CDP连接 + 独立启动）
- user_simulator: 用户行为模拟层（真实鼠标/键盘行为）
- scenario_runner: 场景运行引擎
- result_verifier: 结果验证层（DOM+截图+网络请求三重验证）
- report_generator: 报告生成层
"""
from .browser_connector import BrowserConnector, BrowserMode
from .user_simulator import UserSimulator
from .scenario_runner import ScenarioRunner
from .result_verifier import ResultVerifier, VerificationResult
from .report_generator import ReportGenerator

__all__ = [
    "BrowserConnector",
    "BrowserMode",
    "UserSimulator",
    "ScenarioRunner",
    "ResultVerifier",
    "VerificationResult",
    "ReportGenerator",
]
