"""报告生成层 — 生成 HTML/JSON 测试报告

报告内容：
- 场景执行结果汇总
- 各步骤详细信息
- 截图归档
- 网络请求日志
- 验证结果详情
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .scenario_runner import ScenarioResult, StepResult

logger = logging.getLogger("real_env.report_generator")


class ReportGenerator:
    """报告生成器 — 生成测试报告"""

    def __init__(self, config: dict):
        self._config = config.get("report", {})
        self._output_dir = Path(self._config.get("output_dir", "./reports"))
        self._should_save_screenshots = self._config.get("save_screenshots", True)
        self._should_save_network_logs = self._config.get("save_network_logs", True)
        self._format = self._config.get("format", "both")

    def generate_ai_report(self, agent_result) -> str:
        """生成 AI Agent 执行报告。

        Args:
            agent_result: AgentResult 实例（来自 core.ai_agent）

        Returns:
            报告文件路径
        """
        report_name = datetime.now().strftime("%Y%m%d_ai_%H%M%S")
        report_dir = self._output_dir / report_name
        report_dir.mkdir(parents=True, exist_ok=True)

        # JSON 报告
        json_path = report_dir / "ai_report.json"
        with open(json_path, "w", encoding="utf-8") as f:
            import json
            json.dump(agent_result.to_dict(), f, ensure_ascii=False, indent=2)

        # 简单 HTML 报告
        html_path = report_dir / "ai_report.html"
        passed_color = "#28a745" if agent_result.passed else "#dc3545"
        html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>AI Agent 报告</title>
<style>
body {{ font-family: -apple-system, sans-serif; margin: 40px; }}
.header {{ color: {passed_color}; font-size: 24px; font-weight: bold; }}
.task {{ background: #f5f5f5; padding: 12px; border-radius: 4px; margin: 10px 0; }}
.result {{ margin: 10px 0; }}
.section {{ margin-top: 20px; }}
pre {{ background: #f9f9f9; padding: 12px; overflow-x: auto; }}
</style></head>
<body>
<div class="header">{'PASSED' if agent_result.passed else 'FAILED'}</div>
<div class="task"><strong>任务:</strong> {agent_result.task}</div>
<div class="result"><strong>耗时:</strong> {agent_result.duration_ms:.0f}ms</div>
<div class="result"><strong>步骤数:</strong> {len(agent_result.steps)}</div>
{'<div class="section"><h3>Agent 输出</h3><pre>' + (agent_result.final_result or '') + '</pre></div>' if agent_result.final_result else ''}
{'<div class="section"><h3>三重验证</h3><pre>' + str(agent_result.verification.to_dict() if agent_result.verification else 'N/A') + '</pre></div>'}
{'<div class="section" style="color:#dc3545"><h3>错误</h3><pre>' + (agent_result.error or '') + '</pre></div>' if agent_result.error else ''}
</body></html>"""
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)

        return str(report_dir)

    def generate(self, scenario_results: List[ScenarioResult],
                 report_name: Optional[str] = None) -> str:
        """生成测试报告。

        Args:
            scenario_results: 场景执行结果列表
            report_name: 报告名称（默认为时间戳）

        Returns:
            报告文件路径
        """
        if report_name is None:
            report_name = datetime.now().strftime("%Y%m%d_%H%M%S")

        report_dir = self._output_dir / report_name
        report_dir.mkdir(parents=True, exist_ok=True)

        # 保存截图
        if self._should_save_screenshots:
            self._save_screenshots(scenario_results, report_dir)

        # 生成 JSON 报告
        json_path = None
        if self._format in ("json", "both"):
            json_path = report_dir / "report.json"
            self._generate_json(scenario_results, json_path)

        # 生成 HTML 报告
        html_path = None
        if self._format in ("html", "both"):
            html_path = report_dir / "report.html"
            self._generate_html(scenario_results, html_path)

        logger.info("Report generated: %s", report_dir)
        return str(report_dir)

    def _generate_json(self, results: List[ScenarioResult], path: Path) -> None:
        """生成 JSON 格式报告。"""
        report = {
            "generated_at": datetime.now().isoformat(),
            "summary": self._build_summary(results),
            "scenarios": [self._scenario_to_dict(r) for r in results],
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    def _generate_html(self, results: List[ScenarioResult], path: Path) -> None:
        """生成 HTML 格式报告。"""
        summary = self._build_summary(results)

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>真实环境交互测试报告</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 20px; background: #f5f5f5; }}
        .summary {{ background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .summary h1 {{ margin: 0 0 10px 0; }}
        .stats {{ display: flex; gap: 20px; margin-top: 10px; }}
        .stat {{ background: #f0f0f0; padding: 10px 20px; border-radius: 4px; }}
        .stat.passed {{ background: #d4edda; color: #155724; }}
        .stat.failed {{ background: #f8d7da; color: #721c24; }}
        .scenario {{ background: white; padding: 15px; border-radius: 8px; margin-bottom: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .scenario.passed {{ border-left: 4px solid #28a745; }}
        .scenario.failed {{ border-left: 4px solid #dc3545; }}
        .step {{ padding: 8px; margin: 5px 0; border-radius: 4px; }}
        .step.passed {{ background: #d4edda; }}
        .step.failed {{ background: #f8d7da; }}
        .step-name {{ font-weight: bold; }}
        .step-action {{ color: #666; font-size: 0.9em; }}
        .step-error {{ color: #dc3545; font-size: 0.9em; margin-top: 5px; }}
        .details {{ margin-top: 10px; padding: 10px; background: #f9f9f9; border-radius: 4px; font-size: 0.9em; }}
        pre {{ white-space: pre-wrap; word-break: break-all; }}
    </style>
</head>
<body>
    <div class="summary">
        <h1>真实环境交互测试报告</h1>
        <p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <div class="stats">
            <div class="stat">总场景数: {summary['total']}</div>
            <div class="stat passed">通过: {summary['passed']}</div>
            <div class="stat failed">失败: {summary['failed']}</div>
            <div class="stat">总步骤数: {summary['total_steps']}</div>
            <div class="stat">通过率: {summary['pass_rate']:.1f}%</div>
        </div>
    </div>
"""

        for result in results:
            status_class = "passed" if result.passed else "failed"
            html += f"""    <div class="scenario {status_class}">
        <h3>{result.name} {'✓' if result.passed else '✗'}</h3>
        <p>{result.description}</p>
        <p>耗时: {result.duration_ms:.0f}ms</p>
"""
            if result.error:
                html += f'        <p class="step-error">错误: {result.error}</p>\n'

            for step in result.steps:
                step_class = "passed" if step.passed else "failed"
                html += f"""        <div class="step {step_class}">
            <span class="step-name">{step.name}</span>
            <span class="step-action">[{step.action}] {step.duration_ms:.0f}ms</span>
"""
                if step.error:
                    html += f'            <div class="step-error">{step.error}</div>\n'

                if step.verification:
                    html += '            <div class="details"><strong>验证结果:</strong><pre>'
                    html += json.dumps(step.verification.to_dict(), ensure_ascii=False, indent=2)
                    html += '</pre></div>\n'

                html += '        </div>\n'

            html += '    </div>\n'

        html += """</body>
</html>"""

        with open(path, "w", encoding="utf-8") as f:
            f.write(html)

    def _save_screenshots(self, results: List[ScenarioResult], report_dir: Path) -> None:
        """保存截图到报告目录。"""
        screenshots_dir = report_dir / "screenshots"
        screenshots_dir.mkdir(exist_ok=True)

        for i, result in enumerate(results):
            for j, step in enumerate(result.steps):
                if step.screenshot:
                    filename = f"{i}_{j}_{step.name.replace('/', '_')}.png"
                    filepath = screenshots_dir / filename
                    with open(filepath, "wb") as f:
                        f.write(step.screenshot)

    def _build_summary(self, results: List[ScenarioResult]) -> dict:
        """构建报告摘要。"""
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        failed = total - passed
        total_steps = sum(len(r.steps) for r in results)
        pass_rate = (passed / total * 100) if total > 0 else 0

        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "total_steps": total_steps,
            "pass_rate": pass_rate,
        }

    def _scenario_to_dict(self, result: ScenarioResult) -> dict:
        """将场景结果转为字典。"""
        return {
            "name": result.name,
            "description": result.description,
            "passed": result.passed,
            "duration_ms": result.duration_ms,
            "error": result.error,
            "steps": [self._step_to_dict(s) for s in result.steps],
        }

    def _step_to_dict(self, step: StepResult) -> dict:
        """将步骤结果转为字典。"""
        d = {
            "name": step.name,
            "action": step.action,
            "passed": step.passed,
            "duration_ms": step.duration_ms,
            "error": step.error,
        }
        if step.verification:
            d["verification"] = step.verification.to_dict()
        return d
