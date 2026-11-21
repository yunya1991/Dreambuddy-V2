"""手机笔记本适配器：把选题/素材/风格结论落到手机笔记本，避免长链路中途丢失。

- mode="append"：新建一条笔记写入文本（转写长文会被截断，因此调用方要分段写）。
- mode="list"：读取最近笔记标题，用于回看已记录内容。
- mode="read"：打开最近一条笔记读取正文。

平台差异只有包名与新建入口；默认小米笔记（com.miui.notes）。
"""

from __future__ import annotations

from .base import BasePhoneAdapter, build_step, validate_steps

MAX_MEMO = 3000


class NotesPhone(BasePhoneAdapter):
    NAME = "notes"
    APP = "com.miui.notes"

    def describe(self, job: dict) -> dict:
        mode = str(job.get("mode") or job.get("op") or "append").strip().lower()
        text = str(job.get("text") or "").strip()[:MAX_MEMO]
        tag = str(job.get("tag") or "").strip()[:40]
        try:
            limit = int(job.get("limit") or 5)
        except (TypeError, ValueError):
            limit = 5
        limit = max(1, min(20, limit))
        if mode == "append":
            steps = validate_steps(
                [
                    build_step("open_app", app=self.APP),
                    build_step("write_memo", text=text, tag=tag),
                    build_step("stop", reason="memo_saved"),
                ]
            )
        else:
            steps = validate_steps(
                [
                    build_step("open_app", app=self.APP),
                    build_step("read_memo", limit=limit),
                    build_step("stop", reason="memo_read"),
                ]
            )
        return {
            "job_id": job.get("_id"),
            "adapter": self.NAME,
            "app": self.APP,
            "mode": mode,
            "text": text,
            "tag": tag,
            "limit": limit,
            "exec_timeout_ms": int(job.get("exec_timeout_ms") or 120000),
            "steps": steps,
            "stop_before": "",
        }
