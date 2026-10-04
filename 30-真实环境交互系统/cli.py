"""CLI 入口 — 真实环境交互系统命令行工具

用法：
    # 连接已运行的 Chrome 并运行场景
    python cli.py run --scenario scenarios/examples/frontend_smoke.yaml --mode connect

    # 启动独立 Chrome 并运行场景
    python cli.py run --scenario scenarios/examples/frontend_smoke.yaml --mode launch

    # 批量运行场景
    python cli.py run-batch --scenarios scenarios/examples/ --mode launch

    # 检查 Chrome CDP 连接状态
    python cli.py check
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from core.browser_connector import BrowserConnector, BrowserMode
from core.user_simulator import UserSimulator
from core.result_verifier import ResultVerifier
from core.scenario_runner import ScenarioRunner
from core.report_generator import ReportGenerator
from core.ai_agent import AIAgentRunner
from core.llm_factory import validate_llm_config
from core.agent_browser_runner import AgentBrowserRunner
from core.bsk_runner import BskRunner
from core.computer_use_runner import ComputerUseRunner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("real_env.cli")


def load_config(config_path: str = "config.yaml") -> dict:
    """加载配置文件。"""
    path = Path(config_path)
    if not path.exists():
        path = Path(__file__).parent / "config.yaml"

    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def cmd_run(args):
    """运行单个场景。"""
    config = load_config(args.config)
    connector = BrowserConnector(config)
    simulator = UserSimulator(config)
    verifier = ResultVerifier(config)
    runner = ScenarioRunner(config, simulator, verifier)
    reporter = ReportGenerator(config)

    try:
        # 连接浏览器（CLI 的 connect 映射到 CONNECT_CDP）
        mode_map = {
            "playwright_chromium": BrowserMode.PLAYWRIGHT_CHROMIUM,
            "connect": BrowserMode.CONNECT_CDP,
            "launch_headed": BrowserMode.LAUNCH_HEADED,
            "launch_headless": BrowserMode.LAUNCH_HEADLESS,
        }
        mode = mode_map[args.mode]
        browser = connector.connect(mode=mode, cdp_url=args.cdp_url)
        context = connector.new_context()
        page = connector.new_page()

        # 运行场景
        result = runner.run_from_file(page, args.scenario)

        # 生成报告
        if args.report:
            report_path = reporter.generate([result])
            logger.info("Report saved to: %s", report_path)

        # 输出结果
        status = "PASSED" if result.passed else "FAILED"
        print(f"\n{'='*60}")
        print(f"Scenario: {result.name}")
        print(f"Status: {status}")
        print(f"Duration: {result.duration_ms:.0f}ms")
        print(f"Steps: {sum(1 for s in result.steps if s.passed)}/{len(result.steps)} passed")
        print(f"{'='*60}")

        for step in result.steps:
            symbol = "✓" if step.passed else "✗"
            print(f"  {symbol} {step.name} [{step.action}] {step.duration_ms:.0f}ms")
            if step.error:
                print(f"    Error: {step.error}")

        return 0 if result.passed else 1

    finally:
        connector.close()


def cmd_run_batch(args):
    """批量运行场景。"""
    config = load_config(args.config)
    connector = BrowserConnector(config)
    simulator = UserSimulator(config)
    verifier = ResultVerifier(config)
    runner = ScenarioRunner(config, simulator, verifier)
    reporter = ReportGenerator(config)

    try:
        mode_map = {
            "playwright_chromium": BrowserMode.PLAYWRIGHT_CHROMIUM,
            "connect": BrowserMode.CONNECT_CDP,
            "launch_headed": BrowserMode.LAUNCH_HEADED,
            "launch_headless": BrowserMode.LAUNCH_HEADLESS,
        }
        mode = mode_map[args.mode]
        browser = connector.connect(mode=mode, cdp_url=args.cdp_url)
        context = connector.new_context()
        page = connector.new_page()

        # 收集场景文件
        scenario_path = Path(args.scenarios)
        if scenario_path.is_dir():
            scenario_files = sorted(scenario_path.glob("*.yaml"))
        else:
            scenario_files = [scenario_path]

        logger.info("Found %d scenarios", len(scenario_files))

        results = runner.run_batch(page, [str(f) for f in scenario_files])

        # 生成报告
        if args.report:
            report_path = reporter.generate(results)
            logger.info("Report saved to: %s", report_path)

        # 输出汇总
        passed = sum(1 for r in results if r.passed)
        print(f"\n{'='*60}")
        print(f"Batch Run Summary")
        print(f"Total: {len(results)}, Passed: {passed}, Failed: {len(results) - passed}")
        print(f"{'='*60}")

        for r in results:
            symbol = "✓" if r.passed else "✗"
            print(f"  {symbol} {r.name} ({r.duration_ms:.0f}ms)")

        return 0 if passed == len(results) else 1

    finally:
        connector.close()


def cmd_check(args):
    """检查 Chrome CDP 连接状态。"""
    config = load_config(args.config)
    port = config.get("browser", {}).get("cdp_port", 9222)

    if BrowserConnector.is_chrome_running(port):
        print(f"✓ Chrome is running with CDP on port {port}")
        print(f"  CDP URL: http://localhost:{port}")
        return 0
    else:
        print(f"✗ Chrome is not running with CDP on port {port}")
        print(f"  Start Chrome with: --remote-debugging-port={port}")
        return 1


def cmd_launch(args):
    """启动独立 Chrome（带 CDP）。"""
    config = load_config(args.config)
    connector = BrowserConnector(config)

    try:
        browser = connector.connect(mode=BrowserMode.LAUNCH_HEADED)
        print(f"✓ Chrome launched and connected")
        print(f"  CDP URL: {connector.get_cdp_url()}")
        print(f"  Press Ctrl+C to stop...")

        # 保持运行
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping Chrome...")
    finally:
        connector.close()


def cmd_ai_run(args):
    """运行 AI 驱动的语义化场景（Browser Use Agent）。

    用法：
        python cli.py ai-run --scenario scenarios/examples/ai_semantic_task.yaml
        python cli.py ai-run --task "打开 example.com 并报告标题"
    """
    import asyncio

    config = load_config(args.config)

    # 校验 LLM 配置
    is_valid, msg = validate_llm_config(config)
    if not is_valid:
        logger.error("LLM 配置错误: %s", msg)
        logger.error(
            "请配置 .env 文件，设置对应的 API key 环境变量。"
            "Qwen: ALIBABA_CLOUD; OpenAI: OPENAI_API_KEY; Anthropic: ANTHROPIC_API_KEY"
        )
        return 1
    logger.info("LLM 配置: %s", msg)

    # 创建 Browser Use Browser（复用系统 Chrome 或 Playwright Chromium）
    connector = BrowserConnector(config)
    try:
        bu_browser = connector.get_browser_use_browser()
    except ImportError as e:
        logger.error("browser-use 未安装: %s. 请运行: pip install browser-use", e)
        return 1

    # 创建 AI Agent Runner
    runner = AIAgentRunner(config, browser_use_browser=bu_browser)

    # 加载场景或直接用 --task
    if args.task:
        scenario = {"task": args.task, "assertions": None}
    elif args.scenario:
        scenario = load_scenario(args.scenario)
    else:
        logger.error("必须提供 --scenario 或 --task")
        return 1

    # 运行
    try:
        result = asyncio.run(runner.run_task_from_yaml(scenario))
    except Exception as e:
        logger.error("AI Agent 运行失败: %s", e)
        return 1
    finally:
        connector.close_browser_use()

    # 输出结果
    print("\n" + "=" * 60)
    print(f"任务: {result.task[:80]}...")
    print(f"结果: {'PASSED' if result.passed else 'FAILED'}")
    print(f"耗时: {result.duration_ms:.0f}ms")
    print(f"步骤数: {len(result.steps)}")
    if result.final_result:
        print(f"\nAgent 最终输出:\n{result.final_result}")
    if result.verification:
        print(f"\n三重验证:\n{result.verification.to_dict()}")
    if result.error:
        print(f"\n错误: {result.error}")
    print("=" * 60)

    # 生成报告（可选）
    if args.report:
        report_gen = ReportGenerator(config)
        report_path = report_gen.generate_ai_report(result)
        logger.info("报告已生成: %s", report_path)

    return 0 if result.passed else 1


def cmd_agent_browser_run(args):
    """运行 agent-browser 引擎场景（线2：GLM-5.2 + CLI，省 token）。

    用法：
        python cli.py agent-browser-run --scenario scenarios/examples/agent_browser_form.yaml
        python cli.py agent-browser-run --session my_sess --scenario ...
    """
    config = load_config(args.config)

    # 校验 agent-browser 可执行文件是否在 PATH
    import shutil
    executable = config.get("agent_browser", {}).get("executable", "agent-browser")
    if not shutil.which(executable):
        logger.error(
            "agent-browser 未安装或不在 PATH。安装方式：npm install -g agent-browser"
            "（已安装路径：/opt/homebrew/bin/agent-browser）"
        )
        return 1

    # 创建 Runner
    runner = AgentBrowserRunner(config, session_name=args.session)

    # 加载场景
    if not args.scenario:
        logger.error("必须提供 --scenario <yaml 路径>")
        return 1
    scenario = load_scenario(args.scenario)

    if scenario.get("mode") != "agent_browser":
        logger.warning(
            "场景 mode != 'agent_browser'（实际=%s），仍按 agent_browser 引擎执行",
            scenario.get("mode"),
        )

    # 运行
    result = runner.run_task_from_yaml(scenario)

    # 输出结果
    print("\n" + "=" * 60)
    print(f"场景: {scenario.get('name', 'unnamed')}")
    print(f"模式: agent_browser (线2)")
    print(f"结果: {'PASSED' if result.passed else 'FAILED'}")
    print(f"耗时: {result.duration_ms:.0f}ms")
    print(f"步骤数: {len(result.steps)}")
    for i, step in enumerate(result.steps, 1):
        symbol = "✓" if step.exit_code == 0 else "✗"
        print(f"  {symbol} step{i}: exit={step.exit_code} "
              f"({step.duration_ms:.0f}ms) {step.command[:80]}")
        if step.stderr:
            print(f"    stderr: {step.stderr[:200]}")
    if result.verification:
        print(f"\n三重验证: {result.verification.to_dict()}")
    if result.error:
        print(f"\n错误: {result.error}")
    print("=" * 60)

    return 0 if result.passed else 1


def cmd_bsk_run(args):
    """运行 bsk 引擎场景（线4：腾讯 BrowserSkill CLI，DSH 原生）。

    用法：
        python cli.py bsk-run --scenario scenarios/examples/bsk_form.yaml
        python cli.py bsk-run --session my_task --scenario ...
    """
    config = load_config(args.config)

    # 校验 bsk 可执行文件是否在 PATH
    import shutil
    executable = config.get("bsk", {}).get("executable", "bsk")
    if not shutil.which(executable):
        logger.error(
            "bsk 未安装或不在 PATH。安装方式：参考 https://github.com/Tencent/BrowserSkill"
            "（已安装路径：/Users/zhangjiangtao/.local/bin/bsk）"
        )
        return 1

    # 创建 Runner
    runner = BskRunner(config, session_name=args.session)

    # 加载场景
    if not args.scenario:
        logger.error("必须提供 --scenario <yaml 路径>")
        return 1
    scenario = load_scenario(args.scenario)

    if scenario.get("mode") != "bsk":
        logger.warning(
            "场景 mode != 'bsk'（实际=%s），仍按 bsk 引擎执行",
            scenario.get("mode"),
        )

    # 运行
    result = runner.run_task_from_yaml(scenario)

    # 输出结果
    print("\n" + "=" * 60)
    print(f"场景: {scenario.get('name', 'unnamed')}")
    print(f"模式: bsk (线4 腾讯 BrowserSkill)")
    print(f"结果: {'PASSED' if result.passed else 'FAILED'}")
    print(f"耗时: {result.duration_ms:.0f}ms")
    print(f"步骤数: {len(result.steps)}")
    for i, step in enumerate(result.steps, 1):
        symbol = "✓" if step.exit_code == 0 else "✗"
        print(f"  {symbol} step{i}: exit={step.exit_code} "
              f"({step.duration_ms:.0f}ms) {step.command[:80]}")
        if step.stderr:
            print(f"    stderr: {step.stderr[:200]}")
    if result.verification:
        print(f"\n三重验证: {result.verification.to_dict()}")
    if result.error:
        print(f"\n错误: {result.error}")
    print("=" * 60)

    return 0 if result.passed else 1


def cmd_computer_use_run(args):
    """运行线5 computer_use 引擎场景（模式 A：trae 电脑控制插件）。

    用法：
        python cli.py computer-use-run --scenario scenarios/examples/computer_use_cross_app.yaml
        python cli.py computer-use-run --scenario ... --plan-only

    说明：模式 A 必须由 trae 主对话介入执行，本命令仅生成 JSON plan。
    """
    import json as _json

    config = load_config(args.config)
    runner = ComputerUseRunner(config)

    if not args.scenario:
        logger.error("必须提供 --scenario <yaml 路径>")
        return 1
    scenario = load_scenario(args.scenario)

    if scenario.get("mode") != "computer_use":
        logger.warning(
            "场景 mode != 'computer_use'（实际=%s），仍按 computer_use 引擎执行",
            scenario.get("mode"),
        )

    # 强制 plan_only=True（模式 A 物理限制：Python 无法 spawn trae subagent）
    result = runner.run_task_from_yaml(scenario, plan_only=True)

    # 输出 JSON plan（供 trae 主对话读入并逐条喂给 Agent(subagent_type=computer_use)）
    print("\n" + "=" * 60)
    print(f"场景: {scenario.get('name', 'unnamed')}")
    print(f"模式: computer_use (线5 trae 电脑控制插件)")
    print(f"结果: {'PLAN_READY' if result.passed else 'FAILED'}")
    print(f"步骤数: {len(result.plan)}")
    print("\n--- PLAN JSON（喂给 trae 主对话）---")
    print(_json.dumps({
        "task": scenario.get("name", ""),
        "subagent_type": config.get("computer_use", {}).get("subagent_type", "computer_use"),
        "plan": result.plan,
        "assertions": scenario.get("assertions", []),
    }, ensure_ascii=False, indent=2))
    print("\n--- 执行说明 ---")
    print("将上述 plan 中的每条 prompt 依次通过 Agent(subagent_type=computer_use) 调用执行。")
    print("执行完后用 parse_step_response 解析响应，再用 _run_verification 收尾。")
    print("=" * 60)

    if result.error:
        print(f"\n错误: {result.error}")
    return 0 if result.passed else 1


def cmd_desktop_run(args):
    """运行线5 desktop_native 引擎场景（模式 B：纯 Python pyautogui + osascript）。

    用法：
        python cli.py desktop-run --scenario scenarios/examples/computer_use_cross_app.yaml
    """
    config = load_config(args.config)
    runner = ComputerUseRunner(config)

    if not args.scenario:
        logger.error("必须提供 --scenario <yaml 路径>")
        return 1
    scenario = load_scenario(args.scenario)

    if scenario.get("mode") != "desktop_native":
        logger.warning(
            "场景 mode != 'desktop_native'（实际=%s），仍按 desktop_native 引擎执行",
            scenario.get("mode"),
        )

    # 校验 pyautogui 是否可用（仅当步骤需要时）
    needs_pyautogui = any(
        any(k in s for k in ("click_image", "type_text", "press_key", "screenshot"))
        for s in scenario.get("steps", [])
    )
    if needs_pyautogui:
        try:
            import pyautogui  # noqa: F401
        except ImportError:
            logger.error(
                "pyautogui 未安装。请运行: pip install pyautogui"
            )
            return 1

    result = runner.run_task_from_yaml(scenario)

    print("\n" + "=" * 60)
    print(f"场景: {scenario.get('name', 'unnamed')}")
    print(f"模式: desktop_native (线5 纯 Python 桌面控制)")
    print(f"结果: {'PASSED' if result.passed else 'FAILED'}")
    print(f"耗时: {result.duration_ms:.0f}ms")
    print(f"步骤数: {len(result.steps)}")
    for i, step in enumerate(result.steps, 1):
        symbol = "✓" if step.success else "✗"
        print(f"  {symbol} step{i}: {list(step.step.keys())[0] if step.step else '?'}"
              f" ({step.duration_ms:.0f}ms)"
              f" output={step.output[:80] if step.output else ''}")
        if step.error:
            print(f"    error: {step.error[:200]}")
    if result.verification:
        print(f"\n桌面验证: {result.verification.to_dict()}")
    if result.error:
        print(f"\n错误: {result.error}")
    print("=" * 60)

    return 0 if result.passed else 1


def load_scenario(path: str) -> dict:
    """加载 YAML 场景文件。"""
    p = Path(path)
    if not p.exists():
        # 尝试相对 cli.py 的路径
        p = Path(__file__).parent / path
    if not p.exists():
        raise FileNotFoundError(f"Scenario not found: {path}")
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(
        description="30-真实环境交互系统 — 真实浏览器环境测试工具"
    )
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # run 子命令
    run_parser = subparsers.add_parser("run", help="运行单个场景")
    run_parser.add_argument("--scenario", required=True, help="场景文件路径")
    run_parser.add_argument(
        "--mode", default="playwright_chromium",
        choices=["playwright_chromium", "connect", "launch_headed", "launch_headless"],
        help="浏览器模式: playwright_chromium(沙箱内可用,默认) | connect(连接真实Chrome) | launch_headed | launch_headless",
    )
    run_parser.add_argument("--cdp-url", help="CDP 连接地址（仅 connect 模式）")
    run_parser.add_argument("--report", action="store_true", help="生成报告")
    run_parser.set_defaults(func=cmd_run)

    # run-batch 子命令
    batch_parser = subparsers.add_parser("run-batch", help="批量运行场景")
    batch_parser.add_argument("--scenarios", required=True, help="场景目录或文件")
    batch_parser.add_argument(
        "--mode", default="playwright_chromium",
        choices=["playwright_chromium", "connect", "launch_headed", "launch_headless"],
    )
    batch_parser.add_argument("--cdp-url", help="CDP 连接地址")
    batch_parser.add_argument("--report", action="store_true", help="生成报告")
    batch_parser.set_defaults(func=cmd_run_batch)

    # check 子命令
    check_parser = subparsers.add_parser("check", help="检查 Chrome CDP 状态")
    check_parser.set_defaults(func=cmd_check)

    # launch 子命令
    launch_parser = subparsers.add_parser("launch", help="启动独立 Chrome")
    launch_parser.set_defaults(func=cmd_launch)

    # ai-run 子命令 — AI 驱动的语义化测试（Browser Use Agent）
    ai_run_parser = subparsers.add_parser(
        "ai-run",
        help="运行 AI 驱动的语义化场景（Browser Use Agent）"
    )
    ai_run_parser.add_argument(
        "--scenario", help="AI 场景 YAML 文件路径（含 task 和 assertions）"
    )
    ai_run_parser.add_argument(
        "--task", help="直接传入自然语言任务（覆盖 --scenario 的 task）"
    )
    ai_run_parser.add_argument(
        "--browser-mode",
        default="from_system_chrome",
        choices=["from_system_chrome", "playwright_chromium", "connect_cdp"],
        help="Browser Use Browser 模式"
    )
    ai_run_parser.add_argument("--report", action="store_true", help="生成报告")
    ai_run_parser.set_defaults(func=cmd_ai_run)

    # agent-browser-run 子命令 — agent-browser CLI 引擎（线2，省 token）
    ab_run_parser = subparsers.add_parser(
        "agent-browser-run",
        help="运行 agent-browser 引擎场景（GLM-5.2 + CLI，省 token）"
    )
    ab_run_parser.add_argument(
        "--scenario", required=True,
        help="agent-browser 场景 YAML 文件路径（原生命令风格）",
    )
    ab_run_parser.add_argument(
        "--session", help="覆盖 config 中的 default_session",
    )
    ab_run_parser.add_argument("--report", action="store_true", help="生成报告")
    ab_run_parser.set_defaults(func=cmd_agent_browser_run)

    # bsk-run 子命令 — 腾讯 BrowserSkill CLI 引擎（线4，DSH 原生）
    bsk_run_parser = subparsers.add_parser(
        "bsk-run",
        help="运行 bsk 引擎场景（腾讯 BrowserSkill CLI，DSH 原生）"
    )
    bsk_run_parser.add_argument(
        "--scenario", required=True,
        help="bsk 场景 YAML 文件路径（原生命令风格）",
    )
    bsk_run_parser.add_argument(
        "--session", help="覆盖 config 中的 default_session（用作 bsk session start --name）",
    )
    bsk_run_parser.add_argument("--report", action="store_true", help="生成报告")
    bsk_run_parser.set_defaults(func=cmd_bsk_run)

    # computer-use-run 子命令 — 线5 trae 电脑控制插件（模式 A，plan-only）
    cu_run_parser = subparsers.add_parser(
        "computer-use-run",
        help="运行线5 computer_use 引擎场景（trae 电脑控制插件，仅生成 plan）"
    )
    cu_run_parser.add_argument(
        "--scenario", required=True,
        help="computer_use 场景 YAML 文件路径（自然语言 prompt 风格）",
    )
    cu_run_parser.add_argument(
        "--plan-only", action="store_true", default=True,
        help="仅生成 plan（模式 A 物理限制：必须由 trae 主对话介入执行）",
    )
    cu_run_parser.set_defaults(func=cmd_computer_use_run)

    # desktop-run 子命令 — 线5 桌面原生（模式 B，纯 Python）
    desktop_run_parser = subparsers.add_parser(
        "desktop-run",
        help="运行线5 desktop_native 引擎场景（纯 Python pyautogui + osascript）"
    )
    desktop_run_parser.add_argument(
        "--scenario", required=True,
        help="desktop_native 场景 YAML 文件路径",
    )
    desktop_run_parser.add_argument("--report", action="store_true", help="生成报告")
    desktop_run_parser.set_defaults(func=cmd_desktop_run)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
