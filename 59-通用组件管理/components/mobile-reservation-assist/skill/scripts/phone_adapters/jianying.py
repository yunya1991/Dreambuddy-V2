"""剪映适配器：把文案生成竖版口播视频并导出到相册。

模式：text_to_video（AI 文字成片）。
- 输入：title + body（标题会作为首句进入口播）
- 流程：剪映 → 热门工具「图文成片」→ 输入文案 → 应用 → 生成视频 → 导出 1080P
- 红线：只做本地生成与导出，不涉及支付；遇会员/付费弹窗一律关闭，不购买任何套餐
"""

from __future__ import annotations

from .base import BasePhoneAdapter, build_step, validate_steps

MAX_TEXT = 2000
DEFAULT_TIMEOUT = 900  # 生成+排队+导出可能较久


class JianyingPhone(BasePhoneAdapter):
    NAME = "jianying"
    APP = "com.lemon.lv"

    def describe(self, job: dict) -> dict:
        note = job.get("note") or {}
        title = str(note.get("title") or job.get("title") or "").strip()
        body = str(note.get("body") or job.get("body") or "").strip()
        text = str(job.get("text") or "").strip()
        if not text:
            text = (title + "\n" + body).strip()
        text = text[:MAX_TEXT]
        steps = validate_steps(
            [
                build_step("open_app", app=self.APP),
                build_step("compose_note", title=title, topic_count=0),
                build_step("stop", reason="export_ready"),
            ]
        )
        return {
            "job_id": job.get("_id"),
            "adapter": self.NAME,
            "app": self.APP,
            "mode": "text_to_video",
            "title": title,
            "text": text,
            "text_chars": len(text),
            "exec_timeout_ms": int(job.get("exec_timeout_ms") or DEFAULT_TIMEOUT * 1000),
            "steps": steps,
            "stop_before": "upload",
        }
