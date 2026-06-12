#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UI-Map 项目进度自动检测与监控页面更新脚本
============================================

定期执行：
  1. 扫描 Git 变更与关键文件存在性
  2. 运行功能测试套件
  3. 生成/更新 progress-monitor.html 监控页面
  4. 启动 HTTP 服务器（如未运行）
  5. 输出简洁执行报告

使用方式：
  python3 progress_auto_update.py
  或配合 crontab 每 30 分钟执行一次：
    */30 * * * * cd /path/to/7-产物中台 && python3 progress_auto_update.py >> progress-task.log 2>&1
"""

import os
import re
import sys
import json
import shutil
import socket
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

# ====================================================================
# 路径配置（相对于脚本所在目录：7-产物中台/）
# ====================================================================
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SYSTEM_RESEARCH_DIR = SCRIPT_DIR / "系统研究索引体系"
UI_MAP_APP_DIR = SYSTEM_RESEARCH_DIR / "app" / "ui-map"
LIB_DIR = SYSTEM_RESEARCH_DIR / "lib"
DOCS_DIR = SCRIPT_DIR / "docs"
SCRIPTS_DIR = SYSTEM_RESEARCH_DIR / "scripts"

MONITOR_HTML = SCRIPT_DIR / "progress-monitor.html"
BACKUP_DIR = SCRIPT_DIR / ".monitor-backups"
PORT = 62932
SERVER_URL = f"http://127.0.0.1:{PORT}"

MAX_BACKUPS = 5


# ====================================================================
# 工具函数
# ====================================================================
def run_cmd(cmd, cwd=None, timeout=120, capture=True):
    """执行 shell 命令并返回结果"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=str(cwd) if cwd else None,
            capture_output=capture,
            text=True,
            timeout=timeout,
        )
        return result
    except subprocess.TimeoutExpired:
        class _T:
            returncode = -1
            stdout = ""
            stderr = "[timeout]"
        return _T()


def file_exists(p: Path) -> bool:
    return p.exists() and p.is_file()


def file_contains(p: Path, pattern: str) -> bool:
    if not file_exists(p):
        return False
    try:
        content = p.read_text(encoding="utf-8", errors="ignore")
        return bool(re.search(pattern, content))
    except Exception:
        return False


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


# ====================================================================
# 第 1 步：状态检测 —— Git 状态、关键文件、Task 完成度
# ====================================================================
def detect_git_state() -> dict:
    """检测 Git 变更状态"""
    state = {
        "commit_hash": "unknown",
        "commit_message": "",
        "recent_commits": [],
        "changed_files": [],
        "diff_files": [],
    }

    # 最近 5 个 commit
    r = run_cmd("git log --oneline -5", cwd=PROJECT_ROOT)
    if r.returncode == 0:
        lines = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()]
        state["recent_commits"] = lines
        if lines:
            first = lines[0]
            parts = first.split(" ", 1)
            state["commit_hash"] = parts[0]
            state["commit_message"] = parts[1] if len(parts) > 1 else ""

    # 当前 git status --short
    r = run_cmd("git status --short", cwd=PROJECT_ROOT)
    if r.returncode == 0:
        state["changed_files"] = [
            l.strip() for l in r.stdout.strip().splitlines() if l.strip()
        ]

    # 与上一个 commit 对比（如可用）
    r = run_cmd("git diff --name-only HEAD~1 2>/dev/null || true", cwd=PROJECT_ROOT)
    if r.returncode == 0:
        state["diff_files"] = [
            l.strip() for l in r.stdout.strip().splitlines() if l.strip()
        ]

    return state


def detect_task_completion(test_results: dict) -> dict:
    """根据文件存在性、内容和测试结果，判断 6 个 Task 的完成状态"""

    tasks = {}

    # —— Task 1: 壳层 view-model 与基础测试 ——
    t1_files = {
        "ui-map-scenarios.ts": file_exists(UI_MAP_APP_DIR / "ui-map-scenarios.ts"),
        "ui-map-shell-view-model.ts": file_exists(UI_MAP_APP_DIR / "ui-map-shell-view-model.ts"),
        "ui-map-shell-view-model.test.ts": file_exists(
            UI_MAP_APP_DIR / "ui-map-shell-view-model.test.ts"
        ),
    }
    t1_test_pass = test_results.get("ui-map-shell-view-model.test.ts", {}).get("passed", 0) > 0
    t1_test_all_pass = test_results.get("ui-map-shell-view-model.test.ts", {}).get("failed", 0) == 0
    tasks["task1"] = {
        "name": "Task 1 · 壳层 view-model 与基础语义",
        "description": "ui-map-scenarios.ts / ui-map-shell-view-model.ts / 对应测试文件齐备且测试通过",
        "files": t1_files,
        "completed": all(t1_files.values()) and t1_test_pass and t1_test_all_pass,
        "evidence": [
            f"文件存在: {sum(t1_files.values())}/{len(t1_files)}",
            f"测试通过: {test_results.get('ui-map-shell-view-model.test.ts', {}).get('passed', 0)}/"
            f"{test_results.get('ui-map-shell-view-model.test.ts', {}).get('total', 0)}",
        ],
    }

    # —— Task 2: 页面组件与路由入口 ——
    t2_files = {
        "UIMapModuleCard.tsx": file_exists(UI_MAP_APP_DIR / "UIMapModuleCard.tsx"),
        "UIMapShell.tsx": file_exists(UI_MAP_APP_DIR / "UIMapShell.tsx"),
        "UIMapClient.tsx": file_exists(UI_MAP_APP_DIR / "UIMapClient.tsx"),
        "page.tsx": file_exists(UI_MAP_APP_DIR / "page.tsx"),
        "page.test.ts": file_exists(UI_MAP_APP_DIR / "page.test.ts"),
    }
    t2_test_pass = test_results.get("page.test.ts", {}).get("passed", 0) > 0
    t2_test_all_pass = test_results.get("page.test.ts", {}).get("failed", 0) == 0
    tasks["task2"] = {
        "name": "Task 2 · 页面组件与路由入口",
        "description": "UIMapModuleCard / UIMapShell / UIMapClient / page.tsx / page.test.ts 齐备且测试通过",
        "files": t2_files,
        "completed": all(t2_files.values()) and t2_test_pass and t2_test_all_pass,
        "evidence": [
            f"文件存在: {sum(t2_files.values())}/{len(t2_files)}",
            f"测试通过: {test_results.get('page.test.ts', {}).get('passed', 0)}/"
            f"{test_results.get('page.test.ts', {}).get('total', 0)}",
        ],
    }

    # —— Task 3: 来源层语义增强 ——
    vm_has_source = file_contains(
        UI_MAP_APP_DIR / "ui-map-shell-view-model.ts",
        r"sourceLayer|业务来源层",
    )
    shell_has_source = file_contains(
        UI_MAP_APP_DIR / "UIMapShell.tsx",
        r"source-layer|sourceLayer|业务来源层",
    )
    tasks["task3"] = {
        "name": "Task 3 · 来源层语义增强",
        "description": "view-model 与 shell 中包含来源层语义（sourceLayer / 业务来源层）",
        "files": {
            "ui-map-shell-view-model.ts 含 sourceLayer": vm_has_source,
            "UIMapShell.tsx 含 source-layer": shell_has_source,
        },
        "completed": vm_has_source and shell_has_source,
        "evidence": [
            f"ui-map-shell-view-model.ts 含来源层: {'是' if vm_has_source else '否'}",
            f"UIMapShell.tsx 含来源层: {'是' if shell_has_source else '否'}",
        ],
    }

    # —— Task 4: 主线层与双索引语义 ——
    vm_has_mainline = file_contains(
        UI_MAP_APP_DIR / "ui-map-shell-view-model.ts",
        r"mainlineLayer|策略主线|indexFoundation",
    )
    shell_has_mainline = file_contains(
        UI_MAP_APP_DIR / "UIMapShell.tsx",
        r"mainlineLayer|统一主线层|策略主线",
    )
    tasks["task4"] = {
        "name": "Task 4 · 主线层与双索引语义",
        "description": "view-model 与 shell 中包含主线层与索引底座语义",
        "files": {
            "ui-map-shell-view-model.ts 含主线层/索引": vm_has_mainline,
            "UIMapShell.tsx 含主线层": shell_has_mainline,
        },
        "completed": vm_has_mainline and shell_has_mainline,
        "evidence": [
            f"ui-map-shell-view-model.ts 含主线层/双索引: {'是' if vm_has_mainline else '否'}",
            f"UIMapShell.tsx 含主线层: {'是' if shell_has_mainline else '否'}",
        ],
    }

    # —— Task 5: 导航入口与 ui-map 导航项 ——
    header = SYSTEM_RESEARCH_DIR / "components" / "Header.tsx"
    page_has_uimap = file_contains(UI_MAP_APP_DIR / "page.tsx", r"UIMapClient|UIMapPage|ui-map")
    header_has_uimap_nav = file_contains(header, r"ui-map|UI-Map|UIMap")
    nav_test_exists = file_exists(SYSTEM_RESEARCH_DIR / "components" / "navigation.test.ts")
    tasks["task5"] = {
        "name": "Task 5 · 导航入口与 ui-map 导航项",
        "description": "page.tsx 含 ui-map 入口，Header.tsx 含 ui-map 导航项，navigation.test.ts 覆盖",
        "files": {
            "page.tsx 含 ui-map 入口": page_has_uimap,
            "Header.tsx 含 ui-map 导航": header_has_uimap_nav,
            "navigation.test.ts 存在": nav_test_exists,
        },
        "completed": page_has_uimap and header_has_uimap_nav and nav_test_exists,
        "evidence": [
            f"page.tsx 含 ui-map 入口: {'是' if page_has_uimap else '否'}",
            f"Header.tsx 含 ui-map 导航: {'是' if header_has_uimap_nav else '否'}",
            f"navigation.test.ts 存在: {'是' if nav_test_exists else '否'}",
        ],
    }

    # —— Task 6: 压力测试脚本与自动测试文档 ——
    pressure_script = file_exists(SCRIPTS_DIR / "ui-map-pressure-check.mjs")
    docs_has_auto_test = file_contains(
        DOCS_DIR / "ENGINEERING_INDEX.md",
        r"自动测试|压力测试|pressure|test coverage",
    ) or any(
        file_contains(p, r"自动测试|压力测试|自动化测试")
        for p in list(DOCS_DIR.rglob("*.md"))[:20]
    )
    tasks["task6"] = {
        "name": "Task 6 · 压力测试脚本与自动测试文档",
        "description": "scripts/ui-map-pressure-check.mjs 存在，且文档中包含自动测试章节",
        "files": {
            "ui-map-pressure-check.mjs 存在": pressure_script,
            "文档含自动测试章节": docs_has_auto_test,
        },
        "completed": pressure_script and docs_has_auto_test,
        "evidence": [
            f"scripts/ui-map-pressure-check.mjs: {'存在' if pressure_script else '缺失'}",
            f"文档含自动测试章节: {'是' if docs_has_auto_test else '否'}",
        ],
    }

    return tasks


# ====================================================================
# 第 2 步：运行功能测试
# ====================================================================
TEST_FILES = [
    ("ui-map-shell-view-model.test.ts", UI_MAP_APP_DIR / "ui-map-shell-view-model.test.ts"),
    ("page.test.ts", UI_MAP_APP_DIR / "page.test.ts"),
    ("org-data.test.ts", LIB_DIR / "org-data.test.ts"),
    ("workspace-path-alignment.test.mjs", LIB_DIR / "workspace-path-alignment.test.mjs"),
]


def run_node_test(name: str, test_path: Path) -> dict:
    """运行单个 node:test 测试文件并解析结果"""
    result = {
        "name": name,
        "exists": file_exists(test_path),
        "total": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "failures": [],
        "output": "",
        "exit_code": None,
    }
    if not result["exists"]:
        return result

    # 使用 node --test 运行，通过 TAP 格式输出
    # 优先使用本地 node_modules/.bin/tsx，失败时回退到 npx tsx
    local_tsx = SYSTEM_RESEARCH_DIR / "node_modules" / ".bin" / "tsx"
    if local_tsx.exists():
        cmd = f'"{local_tsx}" --test "{test_path}"'
    else:
        cmd = f'npx tsx --test "{test_path}"'
    r = run_cmd(cmd, cwd=SYSTEM_RESEARCH_DIR, timeout=180)
    result["exit_code"] = r.returncode
    result["output"] = (r.stdout or "") + (r.stderr or "")

    # 解析 TAP 或简单输出（node --test 默认 TAP）
    output = result["output"]

    # 尝试多种解析方式
    # 模式 1: TAP 中 "# tests" "# pass" "# fail" "# skip"
    m = re.search(r"# tests\s+(\d+)", output)
    if m:
        result["total"] = int(m.group(1))
    m = re.search(r"# pass\s+(\d+)", output)
    if m:
        result["passed"] = int(m.group(1))
    m = re.search(r"# fail\s+(\d+)", output)
    if m:
        result["failed"] = int(m.group(1))
    m = re.search(r"# skip\s+(\d+)", output)
    if m:
        result["skipped"] = int(m.group(1))

    # 模式 2: 如果没有 TAP 信息，尝试解析 "X passed" 形式
    if result["total"] == 0 and result["passed"] == 0:
        m = re.search(r"(\d+)\s+passing|passed\s+(\d+)|(\d+)\s+passed", output)
        if m:
            val = int(m.group(1) or m.group(2) or m.group(3) or "0")
            result["passed"] = val
            result["total"] = val
        m = re.search(r"(\d+)\s+failing|failed\s+(\d+)|(\d+)\s+failed", output)
        if m:
            val = int(m.group(1) or m.group(2) or m.group(3) or "0")
            result["failed"] = val
            result["total"] = max(result["total"], result["passed"] + val)

    # 模式 3: 统计 "ok " 和 "not ok " 行
    if result["total"] == 0:
        ok_lines = len(re.findall(r"^ok \d", output, re.MULTILINE))
        not_ok_lines = len(re.findall(r"^not ok \d", output, re.MULTILINE))
        if ok_lines or not_ok_lines:
            result["passed"] = ok_lines
            result["failed"] = not_ok_lines
            result["total"] = ok_lines + not_ok_lines

    # 模式 4: tsx --test 使用 Unicode 符号 "ℹ tests 14"、"ℹ pass 14"、"ℹ fail 0"、"ℹ skipped 0"
    if result["total"] == 0:
        m = re.search(r"\u2139\s*tests\s+(\d+)", output)
        if m:
            result["total"] = int(m.group(1))
        m = re.search(r"\u2139\s*pass(?:ed)?\s+(\d+)", output)
        if m:
            result["passed"] = int(m.group(1))
        m = re.search(r"\u2139\s*fail(?:ed)?\s+(\d+)", output)
        if m:
            result["failed"] = int(m.group(1))
        m = re.search(r"\u2139\s*skip(?:ped)?\s+(\d+)", output)
        if m:
            result["skipped"] = int(m.group(1))

    # 提取失败详情（取前 10 条）
    if result["failed"] > 0:
        fail_lines = []
        for line in output.splitlines():
            if line.startswith("not ok") or "✗" in line or "FAIL" in line.upper():
                fail_lines.append(line.strip()[:120])
        result["failures"] = fail_lines[:10]

    # 如果 exit_code == 0 且 total == 0 但 output 有内容，退而求其次：
    if result["exit_code"] == 0 and result["total"] == 0 and output.strip():
        result["total"] = 1
        result["passed"] = 1

    return result


def run_all_tests() -> dict:
    """运行所有测试，返回聚合结果"""
    results = {"files": {}, "total": 0, "passed": 0, "failed": 0, "skipped": 0}

    for name, path in TEST_FILES:
        r = run_node_test(name, path)
        results["files"][name] = r
        results["total"] += r["total"]
        results["passed"] += r["passed"]
        results["failed"] += r["failed"]
        results["skipped"] += r["skipped"]

    # HTTP 页面访问测试
    http_result = {
        "name": "HTTP 监控页面访问测试",
        "status_code": None,
        "ok": False,
    }
    try:
        r = run_cmd(
            f'curl -s -o /dev/null -w "%{{http_code}}" "{SERVER_URL}/progress-monitor.html"',
            timeout=15,
        )
        if r.returncode == 0:
            code = r.stdout.strip()
            http_result["status_code"] = code
            http_result["ok"] = code.isdigit() and 200 <= int(code) < 400
    except Exception:
        pass
    results["http"] = http_result

    return results


# ====================================================================
# 第 3 步：备份 & 生成 progress-monitor.html
# ====================================================================
def backup_old_page():
    """备份旧页面，保留最近 MAX_BACKUPS 份"""
    if not MONITOR_HTML.exists():
        return
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = now_stamp()
    target = BACKUP_DIR / f"progress-monitor.html.bak.{stamp}"
    shutil.copy2(MONITOR_HTML, target)

    # 清理旧备份，最多保留 MAX_BACKUPS 份
    backups = sorted(BACKUP_DIR.glob("progress-monitor.html.bak.*"), reverse=True)
    for old in backups[MAX_BACKUPS:]:
        try:
            old.unlink()
        except Exception:
            pass


def render_html(git_state: dict, tasks: dict, test_results: dict) -> str:
    """生成完整的监控页面 HTML"""
    now = now_iso()
    commit_hash = git_state["commit_hash"]
    commit_msg = git_state["commit_message"]

    # —— 统计 ——
    completed = sum(1 for t in tasks.values() if t["completed"])
    total = len(tasks)
    progress_pct = int(completed / total * 100) if total else 0

    test_total = test_results["total"]
    test_passed = test_results["passed"]
    test_failed = test_results["failed"]
    test_rate = int(test_passed / test_total * 100) if test_total else 100

    # —— 最近变更文件（取前 10 条）——
    recent_changes = git_state["changed_files"][:10]
    diff_files = git_state["diff_files"][:10]

    # —— Task 卡片 ——
    task_cards = []
    for key in ["task1", "task2", "task3", "task4", "task5", "task6"]:
        t = tasks[key]
        status_class = "done" if t["completed"] else "pending"
        status_text = "已完成" if t["completed"] else "进行中"
        status_icon = "✓" if t["completed"] else "◯"

        ok_span = '<span class="ok">✓</span>'
        no_span = '<span class="no">✗</span>'
        evidence_html = "".join(
            f'<div class="evidence-line">{ok_span if v else no_span} {k}</div>'
            for k, v in t["files"].items()
        )
        task_cards.append(
            f"""
            <div class="task-card task-{status_class}">
                <div class="task-header">
                    <span class="task-icon">{status_icon}</span>
                    <div class="task-title-wrap">
                        <div class="task-name">{t["name"]}</div>
                        <div class="task-desc">{t["description"]}</div>
                    </div>
                    <span class="task-status status-{status_class}">{status_text}</span>
                </div>
                <div class="task-evidence">{evidence_html}</div>
            </div>
            """
        )

    # —— 测试结果卡片 ——
    test_cards = []
    for fname, fres in test_results["files"].items():
        if not fres["exists"]:
            status = "missing"
            status_text = "文件缺失"
        elif fres["failed"] > 0:
            status = "fail"
            status_text = f"{fres['failed']} 失败"
        elif fres["passed"] > 0:
            status = "pass"
            status_text = f"{fres['passed']}/{fres['total']} 通过"
        else:
            status = "warn"
            status_text = "未解析到测试"

        failure_html = ""
        if fres["failures"]:
            failure_html = (
                '<div class="failures">'
                + "".join(f'<div class="failure">✗ {f}</div>' for f in fres["failures"][:5])
                + "</div>"
            )

        test_cards.append(
            f"""
            <div class="test-card test-{status}">
                <div class="test-name">{fname}</div>
                <div class="test-meta">
                    <span>总计 {fres["total"]}</span>
                    <span class="pass-num">通过 {fres["passed"]}</span>
                    <span class="fail-num">失败 {fres["failed"]}</span>
                </div>
                <div class="test-status">{status_text}</div>
                {failure_html}
            </div>
            """
        )

    # —— 本轮运行日志 ——
    log_lines = [
        f"[{now}] 启动自动检测",
        f"[{now}] Git HEAD: {commit_hash} {commit_msg}",
        f"[{now}] 变更文件数: {len(git_state['changed_files'])} (工作区) / {len(git_state['diff_files'])} (HEAD~1 对比)",
        f"[{now}] 运行 {len(TEST_FILES)} 个测试文件, 共 {test_total} 个测试, 通过 {test_passed}, 失败 {test_failed}",
        f"[{now}] HTTP 服务器: {'可达' if test_results.get('http', {}).get('ok') else '不可达，已尝试重启'}",
        f"[{now}] Task 完成度: {completed}/{total} ({progress_pct}%)",
    ]
    log_html = "".join(f'<div class="log-line">{l}</div>' for l in log_lines)

    # —— 最近 commits ——
    commits_html = "".join(
        f'<div class="commit-line">{c}</div>' for c in git_state["recent_commits"][:5]
    )

    # —— 变更文件 ——
    if recent_changes:
        changed_html = "".join(f'<div class="file-line">{f}</div>' for f in recent_changes)
    else:
        changed_html = '<div class="file-line empty">本轮未检测到工作区变更</div>'

    if diff_files:
        diff_html = "".join(f'<div class="file-line">{f}</div>' for f in diff_files)
    else:
        diff_html = '<div class="file-line empty">无 HEAD~1 差异（或只有一个 commit）</div>'

    test_alert = ""
    if test_failed > 0:
        test_alert = f'<div class="alert-fail">⚠ 有 {test_failed} 个测试失败，请关注上方红色卡片</div>'

    # —— 组装完整 HTML ——
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>UI-Map 项目进度监控 · {now}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
    margin: 0; padding: 0;
    background: #0f172a;
    color: #e2e8f0;
    line-height: 1.6;
  }}
  .container {{ max-width: 1200px; margin: 0 auto; padding: 32px 24px; }}
  header {{
    background: linear-gradient(135deg, #1e3a8a 0%, #312e81 100%);
    padding: 32px; border-radius: 16px; margin-bottom: 24px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
  }}
  h1 {{ margin: 0 0 8px 0; font-size: 28px; }}
  .subtitle {{ color: #94a3b8; font-size: 14px; }}
  .meta-row {{ display: flex; flex-wrap: wrap; gap: 16px; margin-top: 16px; font-size: 13px; color: #cbd5e1; }}
  .meta-item {{ background: rgba(255,255,255,0.08); padding: 6px 12px; border-radius: 20px; }}

  .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px; }}
  .stat-card {{
    background: #1e293b; padding: 20px; border-radius: 12px; border: 1px solid #334155;
  }}
  .stat-label {{ font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }}
  .stat-value {{ font-size: 32px; font-weight: bold; margin: 8px 0; }}
  .stat-detail {{ font-size: 13px; color: #cbd5e1; }}
  .pass {{ color: #4ade80; }}
  .fail {{ color: #f87171; }}
  .pct {{ color: #60a5fa; }}

  .progress-wrap {{ background: #1e293b; padding: 20px; border-radius: 12px; margin-bottom: 24px; border: 1px solid #334155; }}
  .progress-bar-wrap {{ background: #334155; height: 14px; border-radius: 7px; overflow: hidden; margin-top: 12px; }}
  .progress-bar {{
    height: 100%;
    background: linear-gradient(90deg, #22c55e 0%, #16a34a 100%);
    width: {progress_pct}%;
    transition: width 0.3s;
  }}

  section {{ margin-bottom: 32px; }}
  h2 {{ font-size: 20px; margin: 0 0 16px 0; color: #f1f5f9; border-left: 4px solid #3b82f6; padding-left: 12px; }}

  .task-card {{
    background: #1e293b; border-radius: 12px; padding: 20px; margin-bottom: 12px;
    border-left: 4px solid #475569; border-top: 1px solid #334155;
    border-right: 1px solid #334155; border-bottom: 1px solid #334155;
  }}
  .task-done {{ border-left-color: #22c55e; }}
  .task-pending {{ border-left-color: #f59e0b; background: #1e293b; }}
  .task-header {{ display: flex; align-items: flex-start; gap: 12px; }}
  .task-icon {{ font-size: 20px; width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }}
  .task-done .task-icon {{ background: rgba(34,197,94,0.2); color: #4ade80; }}
  .task-pending .task-icon {{ background: rgba(245,158,11,0.2); color: #fbbf24; }}
  .task-title-wrap {{ flex: 1; }}
  .task-name {{ font-size: 16px; font-weight: 600; color: #f1f5f9; }}
  .task-desc {{ font-size: 13px; color: #94a3b8; margin-top: 4px; }}
  .task-status {{ font-size: 12px; padding: 4px 10px; border-radius: 20px; flex-shrink: 0; }}
  .status-done {{ background: rgba(34,197,94,0.2); color: #4ade80; }}
  .status-pending {{ background: rgba(245,158,11,0.2); color: #fbbf24; }}
  .task-evidence {{ margin-top: 12px; padding-top: 12px; border-top: 1px dashed #334155; }}
  .evidence-line {{ font-size: 12px; color: #cbd5e1; margin: 4px 0; font-family: "SF Mono", Consolas, monospace; }}
  .ok {{ color: #4ade80; margin-right: 6px; }}
  .no {{ color: #f87171; margin-right: 6px; }}

  .test-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }}
  .test-card {{
    background: #1e293b; border-radius: 12px; padding: 16px;
    border: 1px solid #334155; border-left: 4px solid #475569;
  }}
  .test-pass {{ border-left-color: #22c55e; }}
  .test-fail {{ border-left-color: #ef4444; background: #2c1810; }}
  .test-missing {{ border-left-color: #64748b; opacity: 0.7; }}
  .test-warn {{ border-left-color: #f59e0b; }}
  .test-name {{ font-family: "SF Mono", Consolas, monospace; font-size: 13px; color: #e2e8f0; }}
  .test-meta {{ margin-top: 8px; font-size: 11px; color: #94a3b8; display: flex; gap: 12px; }}
  .pass-num {{ color: #4ade80; }}
  .fail-num {{ color: #f87171; }}
  .test-status {{ margin-top: 8px; font-size: 13px; font-weight: 600; }}
  .test-pass .test-status {{ color: #4ade80; }}
  .test-fail .test-status {{ color: #f87171; }}
  .failures {{ margin-top: 8px; }}
  .failure {{ font-size: 11px; color: #fca5a5; font-family: monospace; padding: 4px 0; border-bottom: 1px dashed #334155; }}

  .alert-fail {{
    background: rgba(239,68,68,0.15); border: 1px solid #ef4444;
    color: #fca5a5; padding: 12px 16px; border-radius: 8px;
    margin-bottom: 16px; font-size: 14px;
  }}

  .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  @media (max-width: 768px) {{ .two-col {{ grid-template-columns: 1fr; }} }}

  .panel {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 16px; }}
  .panel-title {{ font-size: 14px; color: #94a3b8; margin-bottom: 12px; font-weight: 600; }}
  .file-line, .commit-line, .log-line {{
    font-size: 12px; color: #cbd5e1; padding: 6px 8px;
    border-bottom: 1px dashed #334155; font-family: "SF Mono", Consolas, monospace;
  }}
  .file-line.empty {{ color: #64748b; font-style: italic; }}
  .commit-line:last-child, .file-line:last-child, .log-line:last-child {{ border-bottom: none; }}

  footer {{
    margin-top: 32px; padding: 24px; text-align: center;
    color: #64748b; font-size: 12px;
    border-top: 1px solid #334155;
  }}
  footer .commit {{ font-family: "SF Mono", Consolas, monospace; color: #94a3b8; }}
</style>
</head>
<body>
<div class="container">

  <header>
    <h1>🔍 UI-Map 项目进度监控</h1>
    <div class="subtitle">自动扫描 · 测试验证 · 页面更新 · 每 30 分钟刷新</div>
    <div class="meta-row">
      <span class="meta-item">🕐 最后更新：{now}</span>
      <span class="meta-item">📌 Git：<span class="commit">{commit_hash}</span></span>
      <span class="meta-item">📊 进度：{progress_pct}%</span>
      <span class="meta-item">🧪 测试通过率：{test_rate}%</span>
    </div>
  </header>

  <section>
    <h2>📊 测试报告</h2>
    {test_alert}
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-label">测试总数</div>
        <div class="stat-value">{test_total}</div>
        <div class="stat-detail">覆盖 {len(TEST_FILES)} 个测试文件</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">通过</div>
        <div class="stat-value pass">{test_passed}</div>
        <div class="stat-detail">占比 <span class="pct">{test_rate}%</span></div>
      </div>
      <div class="stat-card">
        <div class="stat-label">失败</div>
        <div class="stat-value fail">{test_failed}</div>
        <div class="stat-detail">失败的测试需关注</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">HTTP 页面</div>
        <div class="stat-value {'pass' if test_results.get('http', {}).get('ok') else 'fail'}">{'✓' if test_results.get('http', {}).get('ok') else '✗'}</div>
        <div class="stat-detail">{SERVER_URL}/progress-monitor.html · {test_results.get('http', {}).get('status_code') or 'N/A'}</div>
      </div>
    </div>
    <div class="test-grid">
      {''.join(test_cards)}
    </div>
  </section>

  <section>
    <h2>🎯 整体进度</h2>
    <div class="progress-wrap">
      <div style="display:flex;justify-content:space-between;align-items:baseline;">
        <div>
          <div style="font-size: 14px; color: #cbd5e1;">已完成 Task</div>
          <div style="font-size: 28px; font-weight: bold; color: #4ade80;">{completed} / {total}</div>
        </div>
        <div style="font-size: 36px; font-weight: bold; color: #60a5fa;">{progress_pct}%</div>
      </div>
      <div class="progress-bar-wrap">
        <div class="progress-bar"></div>
      </div>
    </div>
  </section>

  <section>
    <h2>✅ Task 完成状态</h2>
    {''.join(task_cards)}
  </section>

  <section class="two-col">
    <div class="panel">
      <div class="panel-title">📝 本轮检测到的工作区变更</div>
      {changed_html}
    </div>
    <div class="panel">
      <div class="panel-title">🔄 与 HEAD~1 差异</div>
      {diff_html}
    </div>
  </section>

  <section class="two-col">
    <div class="panel">
      <div class="panel-title">📜 最近 commits</div>
      {commits_html}
    </div>
    <div class="panel">
      <div class="panel-title">📋 本轮运行日志</div>
      {log_html}
    </div>
  </section>

  <footer>
    本次检查基于 commit：<span class="commit">{commit_hash}</span> · {commit_msg}<br>
    页面由 progress_auto_update.py 自动生成 · {now}
  </footer>
</div>
</body>
</html>
"""


def write_html(html: str):
    """写入 HTML 页面"""
    MONITOR_HTML.write_text(html, encoding="utf-8")


# ====================================================================
# 第 4 步：HTTP 服务器自愈
# ====================================================================
def is_port_open(host="127.0.0.1", port=PORT) -> bool:
    """检查端口是否可连接"""
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def ensure_http_server():
    """确保 HTTP 服务器运行"""
    status = {"was_running": False, "started": False, "verified": False}

    if is_port_open():
        # 再用 curl 验证
        r = run_cmd(f'curl -s -o /dev/null -w "%{{http_code}}" "{SERVER_URL}/"', timeout=5)
        if r.returncode == 0 and r.stdout.strip().isdigit():
            code = int(r.stdout.strip())
            if 200 <= code < 500:
                status["was_running"] = True
                status["verified"] = True
                return status

    # 启动服务器（后台运行）
    try:
        # 关闭可能的僵尸进程
        run_cmd(
            f"lsof -ti:{PORT} | xargs kill -9 2>/dev/null; sleep 1",
            timeout=5,
        )
    except Exception:
        pass

    # 用 subprocess 启动（不阻塞）
    try:
        log_file = open(SCRIPT_DIR / "http-server.log", "a", encoding="utf-8")
        subprocess.Popen(
            ["python3", "-m", "http.server", str(PORT), "--bind", "0.0.0.0"],
            cwd=str(SCRIPT_DIR),
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )
        status["started"] = True
    except Exception:
        pass

    # 等几秒再验证
    import time
    for _ in range(8):
        time.sleep(1)
        if is_port_open():
            r = run_cmd(f'curl -s -o /dev/null -w "%{{http_code}}" "{SERVER_URL}/progress-monitor.html"', timeout=5)
            if r.returncode == 0 and r.stdout.strip().isdigit():
                code = int(r.stdout.strip())
                if 200 <= code < 400:
                    status["verified"] = True
                    break

    return status


# ====================================================================
# 第 5 步：输出执行报告
# ====================================================================
def print_report(git_state: dict, tasks: dict, test_results: dict, server_status: dict):
    """打印控制台执行报告"""
    now = now_iso()
    next_run = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M")

    completed = sum(1 for t in tasks.values() if t["completed"])
    total = len(tasks)
    progress_pct = int(completed / total * 100) if total else 0

    test_total = test_results["total"]
    test_passed = test_results["passed"]
    test_failed = test_results["failed"]
    test_rate = int(test_passed / test_total * 100) if test_total else 100

    print("=" * 62)
    print(f"=== 定时任务执行报告 [{now}] ===")
    print("=" * 62)

    print()
    print("📊 项目进度:")
    print(f"  - 已完成 Task: {completed}/{total}")
    print(f"  - 整体进度: {progress_pct}%")
    print(f"  - 最新 commit: {git_state['commit_hash']} {git_state['commit_message']}")

    print()
    print("✅ 功能测试:")
    print(f"  - 通过: {test_passed}")
    print(f"  - 失败: {test_failed}")
    print(f"  - 测试通过率: {test_rate}%")

    # 失败详情
    for fname, fres in test_results["files"].items():
        if fres.get("failed", 0) > 0 and fres.get("failures"):
            print(f"  · {fname}: {fres['failures'][0]}")

    print()
    print("📄 监控页面:")
    print(f"  - 地址: {SERVER_URL}/progress-monitor.html")
    print(f"  - 状态: {'已更新（HTTP 服务器运行中）' if server_status['verified'] else '已更新（HTTP 可能需要检查）'}")
    print(f"  - 服务器: {'已在运行' if server_status['was_running'] else '已新启动'}")

    print()
    print("🔍 本轮检测到的变更:")
    changes = git_state["changed_files"][:6]
    if changes:
        for f in changes:
            print(f"  - {f}")
        if len(git_state["changed_files"]) > 6:
            print(f"  ... 共 {len(git_state['changed_files'])} 项")
    else:
        print("  - 本轮无工作区变更")

    print()
    print(f"⏱ 下次运行: {next_run}")
    print("=" * 62)


# ====================================================================
# 主流程
# ====================================================================
def main():
    # 1. Git 状态
    git_state = detect_git_state()

    # 2. 运行测试（先探测服务器，再跑测试，最后更新页面后再探测一次）
    test_results = run_all_tests()

    # 3. 检测 Task 完成状态
    tasks = detect_task_completion(test_results)

    # 4. 生成 HTML（先备份）
    backup_old_page()
    html = render_html(git_state, tasks, test_results)
    write_html(html)

    # 5. 确保 HTTP 服务器运行（页面写入后再启动/验证）
    server_status = ensure_http_server()
    # 启动后再次确认 HTTP 测试结果
    test_results["http"]["ok"] = server_status["verified"]
    test_results["http"]["status_code"] = "200" if server_status["verified"] else (
        test_results["http"].get("status_code") or "N/A"
    )

    # 6. 输出报告
    print_report(git_state, tasks, test_results, server_status)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[中断] 用户取消执行")
        sys.exit(130)
    except Exception as e:
        print(f"[错误] 执行异常: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
