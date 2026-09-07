#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""认知 MCP Server 一键部署脚本。

支持将 cognitive_mcp_server.py 部署到多种 AI 工具：
  --target trae      TRAE（项目级 .trae/mcp.json）
  --target claude    Claude Code（~/.claude.json）
  --target cursor    Cursor（~/.cursor/mcp.json）
  --target windsurf  Windsurf（~/.codeium/windsurf/mcp_config.json）
  --target continue  Continue.dev（~/.continue/config.json）
  --target all       以上全部

流程：
1. 检查 Python 3.8+ 与核心依赖（numpy）；
2. 解析认知系统绝对路径与 Python 解释器路径；
3. 生成目标工具的 MCP 配置（含 command/args/env）；
4. 写入对应配置文件（已存在则备份）；
5. 启动 stdio 子进程验证 server 可响应 initialize/tools/list。

用法：
    python3 install_cognitive_mcp.py --target trae
    python3 install_cognitive_mcp.py --target all --project /path/to/dreambuddy-v2
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# === 常量 ===
SCRIPT_DIR = Path(__file__).resolve().parent.parent  # 9-工具与接口/
COGNITIVE_SERVER = SCRIPT_DIR / "cognitive_mcp_server.py"
COGNITIVE_DIR = str(SCRIPT_DIR)

# 各工具配置文件路径模板（~ 展开为 home）
TOOL_CONFIGS = {
    "trae": {
        "name": "TRAE",
        "path_template": "{project}/.trae/mcp.json",
        "needs_project": True,
        "merge_strategy": "merge_mcp_servers",
    },
    "claude": {
        "name": "Claude Code",
        "path_template": "{home}/.claude.json",
        "needs_project": False,
        "merge_strategy": "merge_mcp_servers",
    },
    "cursor": {
        "name": "Cursor",
        "path_template": "{home}/.cursor/mcp.json",
        "needs_project": False,
        "merge_strategy": "merge_mcp_servers",
    },
    "windsurf": {
        "name": "Windsurf",
        "path_template": "{home}/.codeium/windsurf/mcp_config.json",
        "needs_project": False,
        "merge_strategy": "merge_mcp_servers",
    },
    "continue": {
        "name": "Continue.dev",
        "path_template": "{home}/.continue/config.json",
        "needs_project": False,
        "merge_strategy": "continue_special",
    },
}


def log(msg: str, level: str = "INFO") -> None:
    """带颜色的日志输出。"""
    colors = {"INFO": "\033[36m", "OK": "\033[32m", "WARN": "\033[33m",
              "FAIL": "\033[31m", "STEP": "\033[35m"}
    reset = "\033[0m"
    color = colors.get(level, "")
    print(f"{color}[{level}]{reset} {msg}")


# === 步骤1：环境检查 ===

def check_python() -> Tuple[str, str]:
    """检查 Python 版本，返回 (python_path, version_str)。"""
    py_path = sys.executable
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info < (3, 8):
        log(f"Python {version} 版本过低，需要 3.8+", "FAIL")
        sys.exit(1)
    log(f"Python {version} @ {py_path}", "OK")
    return py_path, version


def check_dependencies() -> bool:
    """检查核心依赖 numpy，可选依赖给出提示。"""
    required = {"numpy": "numpy"}
    optional = {
        "chromadb": "ChromaDB（向量存储，缺失时 TF-IDF 回退）",
        "whoosh": "Whoosh（BM25 关键词检索，缺失时跳过）",
        "networkx": "NetworkX（知识图谱，缺失时跳过）",
        "sklearn": "scikit-learn（TF-IDF 回退所需）",
    }
    all_ok = True
    for mod, name in required.items():
        try:
            __import__(mod)
            log(f"依赖 {name}: OK", "OK")
        except ImportError:
            log(f"依赖 {name}: 缺失（必需）", "FAIL")
            all_ok = False
    for mod, desc in optional.items():
        try:
            __import__(mod)
            log(f"可选 {desc}: OK", "OK")
        except ImportError:
            log(f"可选 {desc}: 缺失（功能降级）", "WARN")
    if not all_ok:
        log("核心依赖缺失，请运行: pip install numpy", "FAIL")
        sys.exit(1)
    return all_ok


def check_server_script() -> bool:
    """检查 cognitive_mcp_server.py 存在。"""
    if COGNITIVE_SERVER.exists():
        log(f"cognitive_mcp_server.py: {COGNITIVE_SERVER}", "OK")
        return True
    log(f"cognitive_mcp_server.py 不存在于 {SCRIPT_DIR}", "FAIL")
    sys.exit(1)


# === 步骤2：生成配置 ===

def build_mcp_config(python_path: str) -> Dict:
    """生成单个 MCP server 配置块。"""
    return {
        "command": python_path,
        "args": [str(COGNITIVE_SERVER)],
        "env": {
            "PYTHONPATH": COGNITIVE_DIR,
            "ANONYMIZED_TELEMETRY": "False",
        },
    }


def get_config_path(target: str, project: Optional[str]) -> Path:
    """获取目标工具的配置文件路径。"""
    cfg = TOOL_CONFIGS[target]
    home = str(Path.home())
    if cfg["needs_project"]:
        if not project:
            log(f"{cfg['name']} 需要指定 --project 参数", "FAIL")
            sys.exit(1)
        return Path(cfg["path_template"].format(project=project, home=home))
    return Path(cfg["path_template"].format(home=home))


def merge_config(existing: Dict, new_server: Dict) -> Dict:
    """合并 MCP 配置（通用 merge_mcp_servers 策略）。"""
    merged = dict(existing) if existing else {}
    if "mcpServers" not in merged:
        merged["mcpServers"] = {}
    merged["mcpServers"]["cognitive"] = new_server
    return merged


def merge_continue_config(existing: Dict, new_server: Dict) -> Dict:
    """Continue.dev 特殊合并：mcpServers 在 config 顶层。"""
    merged = dict(existing) if existing else {}
    if "mcpServers" not in merged:
        merged["mcpServers"] = {}
    merged["mcpServers"]["cognitive"] = new_server
    return merged


def write_config(target: str, config_path: Path, new_server: Dict) -> bool:
    """写入配置文件，已存在则先备份。"""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing: Dict = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text(encoding="utf-8"))
            backup = config_path.with_suffix(f".json.bak.{int(time.time())}")
            shutil.copy2(config_path, backup)
            log(f"已备份原配置 → {backup.name}", "INFO")
        except Exception as e:
            log(f"读取原配置失败，将覆盖: {e}", "WARN")

    strategy = TOOL_CONFIGS[target]["merge_strategy"]
    if strategy == "continue_special":
        merged = merge_continue_config(existing, new_server)
    else:
        merged = merge_config(existing, new_server)

    try:
        config_path.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        log(f"配置已写入: {config_path}", "OK")
        return True
    except Exception as e:
        log(f"写入配置失败: {e}", "FAIL")
        return False


# === 步骤3：验证 server ===

def verify_server(python_path: str) -> bool:
    """启动 stdio 子进程验证 server 响应 initialize/tools/list。"""
    log("启动 server 验证...", "STEP")
    try:
        proc = subprocess.Popen(
            [python_path, str(COGNITIVE_SERVER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True,
            env={**os.environ, "PYTHONPATH": COGNITIVE_DIR},
        )
        # initialize
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "initialize", "params": {},
        }) + "\n")
        proc.stdin.flush()
        resp1 = json.loads(proc.stdout.readline())
        server_name = resp1.get("result", {}).get("serverInfo", {}).get("name", "")
        if server_name != "cognitive-memory-server":
            log(f"initialize 失败: {resp1}", "FAIL")
            proc.stdin.close()
            proc.wait(timeout=5)
            return False
        log(f"initialize OK: {server_name}", "OK")

        # tools/list
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "id": 2,
            "method": "tools/list", "params": {},
        }) + "\n")
        proc.stdin.flush()
        resp2 = json.loads(proc.stdout.readline())
        tools = resp2.get("result", {}).get("tools", [])
        tool_names = [t["name"] for t in tools]
        expected = {"recall", "record", "verify", "stats", "health"}
        if not expected.issubset(set(tool_names)):
            log(f"工具不完整: {tool_names}", "FAIL")
            proc.stdin.close()
            proc.terminate()
            proc.wait(timeout=5)
            return False
        log(f"tools/list OK: {tool_names}", "OK")

        proc.stdin.close()
        proc.terminate()
        proc.wait(timeout=5)
        return True
    except subprocess.TimeoutExpired:
        proc.kill()
        log("server 启动超时（10s）", "FAIL")
        return False
    except Exception as e:
        log(f"验证异常: {e}", "FAIL")
        return False


# === 主流程 ===

def deploy_target(target: str, python_path: str,
                  project: Optional[str]) -> bool:
    """部署到单个目标工具。"""
    cfg = TOOL_CONFIGS[target]
    log(f"\n{'='*50}", "STEP")
    log(f"部署到 {cfg['name']}", "STEP")
    log(f"{'='*50}", "STEP")

    config_path = get_config_path(target, project)
    new_server = build_mcp_config(python_path)
    log(f"配置文件: {config_path}", "INFO")

    if not write_config(target, config_path, new_server):
        return False

    # 生成用户操作提示
    reload_hints = {
        "trae": "重启 TRAE 会话或命令面板 MCP:Reload",
        "claude": "重启 Claude Code 或 /mcp reload",
        "cursor": "重启 Cursor 或 Cmd+Shift+P → MCP: Reload",
        "windsurf": "重启 Windsurf",
        "continue": "重启 Continue.dev",
    }
    log(f"生效方式: {reload_hints.get(target, '重启工具')}", "INFO")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="认知 MCP Server 一键部署到 AI 工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 install_cognitive_mcp.py --target trae --project /path/to/dreambuddy-v2
  python3 install_cognitive_mcp.py --target claude
  python3 install_cognitive_mcp.py --target all --project /path/to/dreambuddy-v2
  python3 install_cognitive_mcp.py --list
        """,
    )
    parser.add_argument("--target", "-t",
                        choices=["trae", "claude", "cursor", "windsurf",
                                 "continue", "all"],
                        default="trae", help="目标 AI 工具")
    parser.add_argument("--project", "-p",
                        help="项目根目录（TRAE 需要）")
    parser.add_argument("--list", "-l", action="store_true",
                        help="列出支持的工具")
    parser.add_argument("--verify-only", action="store_true",
                        help="仅验证 server 不写配置")
    args = parser.parse_args()

    if args.list:
        print("支持的 AI 工具:")
        for k, v in TOOL_CONFIGS.items():
            needs = "（需要 --project）" if v["needs_project"] else ""
            print(f"  {k:10s} {v['name']}{needs}")
        return

    # 步骤1：环境检查
    log("步骤1：环境检查", "STEP")
    python_path, version = check_python()
    check_dependencies()
    check_server_script()

    # 步骤2：验证 server 可用
    log("\n步骤2：验证 server", "STEP")
    if not verify_server(python_path):
        log("server 验证失败，部署中止", "FAIL")
        sys.exit(1)

    if args.verify_only:
        log("\n仅验证模式，跳过配置写入", "INFO")
        return

    # 步骤3：部署到目标工具
    log("\n步骤3：部署配置", "STEP")
    targets = list(TOOL_CONFIGS.keys()) if args.target == "all" else [args.target]
    success = []
    failed = []
    for t in targets:
        try:
            if deploy_target(t, python_path, args.project):
                success.append(t)
            else:
                failed.append(t)
        except Exception as e:
            log(f"部署 {t} 异常: {e}", "FAIL")
            failed.append(t)

    # 总结
    log(f"\n{'='*50}", "STEP")
    log("部署总结", "STEP")
    log(f"{'='*50}", "STEP")
    if success:
        log(f"成功 ({len(success)}): {', '.join(success)}", "OK")
    if failed:
        log(f"失败 ({len(failed)}): {', '.join(failed)}", "FAIL")
    if success and not failed:
        log("\n认知 MCP Server 部署完成！重启对应 AI 工具后即可调用 "
            "recall/record/verify/stats/health 五个工具。", "OK")


if __name__ == "__main__":
    main()
