# -*- coding: utf-8 -*-
"""
index_publisher.py — 报告落盘与 41 索引登记（P1-4）
====================================================
职责（PLAN P1-4）：
- 报告 JSON 落盘到 `<base_dir>/reports/<eval_id>.json`（41 索引按目录段 `reports`
  识别为 report 类型，见 41-文件索引系统/core/indexer.py）
- 返回 `file://` URI 供 41 检索与人工核对
- 41 索引更新钩子：可注入 scan/刷新动作，异常 fail-open（不阻断评测）

不可变语义：同 eval_id 同内容可重放；内容不同即拒（证据不可变）。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

logger = logging.getLogger(__name__)

MODULE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_DIR = MODULE_ROOT / "artifacts"


class PublisherError(Exception):
    """报告发布失败：缺 eval_id / 同 eval_id 内容不一致等。"""


@dataclass(frozen=True)
class PublishedReport:
    """发布结果：URI 与磁盘路径、内容哈希。"""

    uri: str
    path: Path
    sha256: str


class ReportPublisher(Protocol):
    def publish(self, report: dict[str, Any]) -> PublishedReport: ...


class FileReportPublisher:
    """文件发布器：`reports/` 目录约定 + 41 索引钩子（fail-open）。"""

    def __init__(
        self,
        base_dir: str | Path = DEFAULT_BASE_DIR,
        hook: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._reports_dir = Path(base_dir) / "reports"
        self._hook = hook
        self._hook_errors = 0

    @property
    def hook_errors(self) -> int:
        return self._hook_errors

    @property
    def reports_dir(self) -> Path:
        return self._reports_dir

    def publish(self, report: dict[str, Any]) -> PublishedReport:
        if not isinstance(report, dict) or not report.get("eval_id"):
            raise PublisherError("报告缺少 eval_id，无法发布")

        eval_id = str(report["eval_id"])
        content = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        digest = _sha256(content)

        self._reports_dir.mkdir(parents=True, exist_ok=True)
        path = self._reports_dir / f"{eval_id}.json"

        if path.exists():
            if _sha256(path.read_text(encoding="utf-8")) != digest:
                raise PublisherError(
                    f"报告内容与已归档版本不一致，拒绝覆盖: {eval_id}（证据不可变）"
                )
            return PublishedReport(
                uri=f"file://{path.resolve()}", path=path.resolve(), sha256=digest
            )

        _atomic_write(path, content)
        published = PublishedReport(
            uri=f"file://{path.resolve()}", path=path.resolve(), sha256=digest
        )
        logger.info("report published eval_id=%s uri=%s", eval_id, published.uri)
        self._notify_index(published, report)
        return published

    # ---------- 41 索引钩子 ----------

    def _notify_index(self, published: PublishedReport, report: dict[str, Any]) -> None:
        if self._hook is None:
            return
        try:
            self._hook(published.uri, report)
        except Exception as exc:  # noqa: BLE001 — 索引失败不得阻断评测发布（fail-open）
            self._hook_errors += 1
            logger.warning("41 索引登记失败（fail-open）uri=%s: %s", published.uri, exc)


def _sha256(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write(path: Path, content: str) -> None:
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, path)
