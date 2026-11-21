"""千问 App 适配器：知识咨询 + 配图生成，两条通道共用同一 App。

- mode 缺省 / "ask"：把问题交给千问，回传答案文本（排障知识库）。
- mode="image"：让千问生成配图，保存到相册后回传素材路径。
"""

from __future__ import annotations

from .base import BasePhoneAdapter

MODES = ("ask", "image")


class QianwenPhone(BasePhoneAdapter):
    NAME = "qianwen"
    APP = "com.aliyun.tongyi"

    def describe(self, job: dict) -> dict:
        mode = str(job.get("mode") or "ask").strip().lower()
        if mode not in MODES:
            mode = "ask"
        question = str(job.get("question") or job.get("prompt") or "").strip()
        return {
            "job_id": job.get("_id"),
            "adapter": self.NAME,
            "app": self.APP,
            "mode": mode,
            "question": question,
            "steps": [],
            "stop_before": "",
        }
