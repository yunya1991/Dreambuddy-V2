"""Desktop 断言工具集 — 跨应用验证（文件/终端/UI 视觉）

静态方法集，仿 utils/dom_assertions.py 风格。
复用 core.result_verifier.VerificationResult（引擎无关 dataclass）。

支持三类断言：
- 文件断言：file_exists / file_contains / file_size_gt
- 终端断言：terminal_contains（模式 A 搜 subagent 文本响应；模式 B 搜 osascript 读终端）
- UI 视觉断言：ui_visual_match（文件 vs 文件，复用 utils.screenshot_diff）
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

from core.result_verifier import VerificationResult
from utils.screenshot_diff import compare_screenshot_paths


class DesktopAssertions:
    """桌面/跨应用断言静态方法集。"""

    # ------------------------------------------------------------------
    # 文件断言
    # ------------------------------------------------------------------
    @staticmethod
    def file_exists(path: str) -> VerificationResult:
        expanded = os.path.expanduser(path)
        exists = Path(expanded).exists()
        return VerificationResult(
            name="file_exists",
            passed=exists,
            details={"path": expanded, "exists": exists},
            error=None if exists else f"file not found: {expanded}",
        )

    @staticmethod
    def file_contains(path: str, text: str) -> VerificationResult:
        expanded = os.path.expanduser(path)
        if not Path(expanded).exists():
            return VerificationResult(
                name="file_contains",
                passed=False,
                details={"path": expanded},
                error=f"file not found: {expanded}",
            )
        try:
            with open(expanded, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            found = text in content
            return VerificationResult(
                name="file_contains",
                passed=found,
                details={
                    "path": expanded,
                    "needle": text,
                    "snippet": content[max(0, content.find(text) - 20):content.find(text) + len(text) + 20] if found else None,
                },
                error=None if found else f"text not found in {expanded}",
            )
        except Exception as e:
            return VerificationResult(
                name="file_contains",
                passed=False,
                details={"path": expanded},
                error=f"read error: {e}",
            )

    @staticmethod
    def file_size_gt(path: str, size: int) -> VerificationResult:
        expanded = os.path.expanduser(path)
        if not Path(expanded).exists():
            return VerificationResult(
                name="file_size_gt",
                passed=False,
                details={"path": expanded},
                error=f"file not found: {expanded}",
            )
        actual = Path(expanded).stat().st_size
        return VerificationResult(
            name="file_size_gt",
            passed=actual > size,
            details={"path": expanded, "actual_size": actual, "threshold": size},
            error=None if actual > size else f"size {actual} <= {size}",
        )

    # ------------------------------------------------------------------
    # 终端断言
    # ------------------------------------------------------------------
    @staticmethod
    def terminal_contains(text: str, subagent_response: Optional[str] = None,
                           osascript_path: str = "/usr/bin/osascript") -> VerificationResult:
        """检查终端是否包含某段文本。

        模式 A（subagent_response 非 None）：直接搜 subagent 文本响应
        模式 B（subagent_response 为 None）：用 osascript 读 Terminal.app 当前输出
        """
        # 模式 A
        if subagent_response is not None:
            found = text in subagent_response
            return VerificationResult(
                name="terminal_contains",
                passed=found,
                details={
                    "mode": "computer_use_subagent",
                    "needle": text,
                    "response_len": len(subagent_response),
                },
                error=None if found else f"text not found in subagent response",
            )

        # 模式 B：osascript 读 Terminal
        # 通过 AppleScript 获取 Terminal 当前 tab 的内容
        script = (
            'tell application "Terminal"\n'
            '  if (count of windows) > 0 then\n'
            '    if (count of tabs of front window) > 0 then\n'
            '      return contents of selected tab of front window\n'
            '    end if\n'
            '  end if\n'
            '  return ""\n'
            "end tell"
        )
        try:
            result = subprocess.run(
                [osascript_path, "-e", script],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return VerificationResult(
                    name="terminal_contains",
                    passed=False,
                    details={"mode": "osascript"},
                    error=f"osascript exit {result.returncode}: {result.stderr}",
                )
            content = result.stdout or ""
            found = text in content
            return VerificationResult(
                name="terminal_contains",
                passed=found,
                details={
                    "mode": "osascript",
                    "needle": text,
                    "content_len": len(content),
                },
                error=None if found else f"text not found in Terminal output",
            )
        except Exception as e:
            return VerificationResult(
                name="terminal_contains",
                passed=False,
                details={"mode": "osascript"},
                error=f"osascript run error: {e}",
            )

    # ------------------------------------------------------------------
    # UI 视觉断言
    # ------------------------------------------------------------------
    @staticmethod
    def ui_visual_match(current_path: str, baseline_path: str,
                        threshold: float = 0.05) -> VerificationResult:
        """对比两个截图文件，返回差异是否在阈值内。"""
        cur = os.path.expanduser(current_path)
        base = os.path.expanduser(baseline_path)

        if not Path(cur).exists():
            return VerificationResult(
                name="ui_visual_match",
                passed=False,
                details={"current_path": cur},
                error=f"current screenshot not found: {cur}",
            )
        if not Path(base).exists():
            return VerificationResult(
                name="ui_visual_match",
                passed=False,
                details={"baseline_path": base},
                error=f"baseline screenshot not found: {base}",
            )

        try:
            diff = compare_screenshot_paths(base, cur)
            return VerificationResult(
                name="ui_visual_match",
                passed=diff <= threshold,
                details={
                    "diff_score": diff,
                    "threshold": threshold,
                    "current_path": cur,
                    "baseline_path": base,
                },
                error=None if diff <= threshold else f"diff {diff:.4f} > threshold {threshold}",
            )
        except Exception as e:
            return VerificationResult(
                name="ui_visual_match",
                passed=False,
                details={"current_path": cur, "baseline_path": base},
                error=f"compare error: {e}",
            )
