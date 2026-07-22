#!/usr/bin/env python3
"""笔记本自动捕获钩子 v1.0 — 将任务完成自动记入笔记本

用法:
  # 记录一个完成项
  python3 notebook_hook.py done "A1修复" "产出59KB报告" "cron/4d2530120c32/2026-06-15_01-06-55.md"

  # 更新NOTEBOOK.md的最近完成列表
  python3 notebook_hook.py sync

角色定位: Layer 3 — 自动捕获 hooks
  每次 cron 任务完成 / 三链阶段切换后调用, 零手工录入。
  与 agentmemory 的 PostToolUse hook 同类但更轻量 (纯文件操作)。
"""

import argparse
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

# ── 路径 ──────────────────────────────────────────────
BASE = Path.home() / "archives" / "Dreambuddy-V2-main"
NOTEBOOK = BASE / "0-NOTEBOOK"
NOTEBOOK_L1 = NOTEBOOK / "NOTEBOOK.md"
DONE_DIR = NOTEBOOK / "2-DONE"
TODO_DIR = NOTEBOOK / "0-TODO"
ACTIVE_DIR = NOTEBOOK / "1-ACTIVE"


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _short_path(path: str) -> str:
    """简化绝对路径为相对路径"""
    if "Dreambuddy-V2" in path:
        return path.split("Dreambuddy-V2/")[-1]
    return path


def cmd_done(title: str, summary: str, output: str = ""):
    """记录一个完成项到 2-DONE/"""
    date = _now_str()
    safe_title = re.sub(r"[^\w\-]", "_", title)[:40]
    filename = f"{date}-{safe_title}.md"
    filepath = DONE_DIR / filename

    content = f"""# [{date}] {title}

## 做了什么
{summary}

## 产出
- {_short_path(output) if output else "无"}
"""
    DONE_DIR.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")
    print(f"✅ 已记录完成项: {filepath.name}")


def cmd_todo_add(title: str, description: str, priority: str = "P2"):
    """添加一个待办项到 0-TODO/"""
    date = _now_str()
    safe_title = re.sub(r"[^\w\-]", "_", title)[:40]
    filename = f"{date}-{safe_title}.md"
    filepath = TODO_DIR / filename

    content = f"""# 待办: {title}

## 来源
- 识别于: {date}

## 描述
{description}

## 优先级
{priority}
"""
    TODO_DIR.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")
    print(f"📋 已添加待办: {filepath.name}")


def cmd_active_set(phase: str, title: str):
    """设置活跃链到 1-ACTIVE/"""
    date = _now_str()
    filename = f"{phase}-{title}.md"
    filepath = ACTIVE_DIR / filename

    content = f"""# [{date}] {phase} — {title}

## 阶段
{phase}

## 状态
进行中
"""
    ACTIVE_DIR.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")
    print(f"🔄 已设置活跃链: {filepath.name}")


def cmd_active_done(phase: str, title: str):
    exact = ACTIVE_DIR / f"{phase}-{title}.md"
    if exact.exists():
        src = exact
    else:
        candidates = [f for f in ACTIVE_DIR.glob(f"{phase}-*.md")
                      if f.name != "README.md" and (title.lower() in f.stem.lower())]
        if not candidates:
            candidates = sorted(ACTIVE_DIR.glob(f"{phase}-*.md"),
                                key=lambda p: p.stat().st_mtime, reverse=True)
            candidates = [f for f in candidates if f.name != "README.md"]
        if not candidates:
            print(f"Warning: no active chain found for {phase}-{title}")
            return
        src = candidates[0]
    dst = DONE_DIR / f"{_now_str()}-{src.name}"
    shutil.move(str(src), str(dst))
    print(f"Done: {dst.name}")


def cmd_sync():
    """同步 NOTEBOOK.md 的最新完成和待办列表"""
    if not NOTEBOOK_L1.exists():
        print(f"⚠️ NOTEBOOK.md 不存在，跳过同步")
        return

    content = NOTEBOOK_L1.read_text(encoding="utf-8")

    # 更新 "✅ 最近完成" 部分 - 从 2-DONE/ 读取最新的5个
    done_files = sorted(DONE_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    entries = []
    for f in done_files[:8]:  # 读前8个，排除README
        if f.name == "README.md":
            continue
        text = f.read_text(encoding="utf-8").split("\n")
        title_line = ""
        summary = ""
        for line in text:
            if line.startswith("# [") and "]" in line:
                title_line = line.strip("# ").strip()
            if line.startswith("## 做了什么"):
                # get next non-empty line
                idx = text.index(line)
                for l in text[idx + 1:]:
                    if l.strip():
                        summary = l.strip()[:50]
                        break
                break
        entries.append(f"| {title_line} | {summary}")

    # 替换最近完成区域（兼容新旧格式）
    # 新格式: "## ✅ 已完成" (步进式), 旧格式: "## ✅ 最近完成（Top-5）"
    done_header_new = "## ✅ 已完成"
    done_header_old = "## ✅ 最近完成（Top-5）"
    next_header = "## 📖 快速引用"
    
    done_start = content.find(done_header_new)
    done_is_new = True
    if done_start < 0:
        done_start = content.find(done_header_old)
        done_is_new = False
    next_start = content.find(next_header)
    
    if done_start > 0 and next_start > 0:
        if done_is_new:
            new_done_section = f"""## ✅ 已完成

| 步 | 完成项 |
|:---:|---|
"""
        else:
            new_done_section = f"""## ✅ 最近完成（Top-5）
| 日期 | 完成项 |
|:---:|---|
"""
        for e in entries[:5]:
            new_done_section += f"{e}\n"
        
        content = content[:done_start] + new_done_section + "\n" + content[next_start:]
        NOTEBOOK_L1.write_text(content, encoding="utf-8")
        print(f"✅ NOTEBOOK.md 已同步 ({len(entries)} 项)")


def main():
    parser = argparse.ArgumentParser(description="笔记本自动捕获钩子")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("done", help="记录完成项")
    p.add_argument("title")
    p.add_argument("summary")
    p.add_argument("output", nargs="?", default="")

    p = sub.add_parser("todo", help="添加待办项")
    p.add_argument("title")
    p.add_argument("description")
    p.add_argument("-p", "--priority", default="P2")

    p = sub.add_parser("active", help="设置活跃链")
    p.add_argument("phase")
    p.add_argument("title")

    p = sub.add_parser("finish", help="完成活跃链")
    p.add_argument("phase")
    p.add_argument("title")

    p = sub.add_parser("sync", help="同步NOTEBOOK.md")

    args = parser.parse_args()
    
    if args.cmd == "done":
        cmd_done(args.title, args.summary, args.output or "")
    elif args.cmd == "todo":
        cmd_todo_add(args.title, args.description, args.priority)
    elif args.cmd == "active":
        cmd_active_set(args.phase, args.title)
    elif args.cmd == "finish":
        cmd_active_done(args.phase, args.title)
    elif args.cmd == "sync":
        cmd_sync()


if __name__ == "__main__":
    main()
