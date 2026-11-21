"""小红书适配器：爆款侦察 + 图文发布，两条通道共用同一 App。

- mode 缺省 / "post"：选素材 → 填标题正文 → 停在「发笔记」按钮前。
- mode="scout"：按赛道关键词浏览信息流，读前 N 篇爆款，可选点赞/收藏。

红线：
- 默认只填好内容并停在发布前，人工核对后自行点发布；
- 仅当上游显式传入 publish_authorized（用户明确说"发出去"）才允许点发布；
- 不刷量、不控评、不搬运他人内容；侦察互动只做点赞/收藏，且单次不超过 limit。
"""

from __future__ import annotations

import re

from .base import BasePhoneAdapter, build_step, validate_steps

MAX_TITLE = 20
MAX_BODY = 1000
MAX_SCOUT = 8
# 赛道偏窄，按「泛金融 / 经济 / 时事 + AI Agent / 数据服务」扩圈
DEFAULT_TRACKS = ("财经", "经济", "时事", "AI Agent", "数据服务")


class XiaohongshuPhone(BasePhoneAdapter):
    NAME = "xiaohongshu"
    APP = "com.xingin.xhs"

    def describe(self, job: dict) -> dict:
        mode = str(job.get("mode") or "post").strip().lower()
        if mode == "scout":
            return self._scout(job)
        return self._post(job)

    def _post(self, job: dict) -> dict:
        note = job.get("note") or {}
        title = str(note.get("title") or job.get("title") or "").strip()[:MAX_TITLE]
        body = str(note.get("body") or job.get("body") or "").strip()[:MAX_BODY]
        topics = [str(item).strip().lstrip("#") for item in (note.get("topics") or job.get("topics") or [])]
        topics = [item for item in topics if item][:6]
        materials = [str(item) for item in (note.get("images") or job.get("images") or []) if item]
        steps = validate_steps(
            [
                build_step("open_app", app=self.APP),
                build_step("select_material", count=max(1, len(materials) or 1)),
                build_step("compose_note", title=title, topic_count=len(topics)),
                build_step("stop", reason="await_publish_confirm"),
            ]
        )
        return {
            "job_id": job.get("_id"),
            "adapter": self.NAME,
            "app": self.APP,
            "mode": "post",
            "title": title,
            "body": body,
            "topics": topics,
            "images": materials,
            # 发布授权：默认 False；仅用户明确说"发出去/直接发布"时由上游置 True
            "publish_authorized": bool(job.get("publish_authorized")),
            "steps": steps,
            "stop_before": "publish",
        }

    def _scout(self, job: dict) -> dict:
        tracks = job.get("track") or job.get("keywords") or list(DEFAULT_TRACKS)
        if isinstance(tracks, str):
            # 只按分隔符切，保留 "AI Agent" 这类带空格的赛道名
            tracks = re.split(r"[,，、;；]+", tracks)
        tracks = [str(item).strip() for item in tracks if str(item).strip()][:5] or list(DEFAULT_TRACKS)
        try:
            limit = int(job.get("limit") or 3)
        except (TypeError, ValueError):
            limit = 3
        limit = max(1, min(MAX_SCOUT, limit))
        interact = bool(job.get("interact"))
        steps = [
            build_step("open_app", app=self.APP),
            build_step("browse_feed", keywords=",".join(tracks), limit=limit),
            build_step("read_note", index=0),
            build_step("save_material", tag="xhs_scout"),
        ]
        if interact:
            # 互动硬上限 5：只点赞/收藏，不评论
            steps.append(build_step("interact_post", actions="like,collect", limit=min(limit, 5)))
        steps.append(build_step("stop", reason="scout_done"))
        return {
            "job_id": job.get("_id"),
            "adapter": self.NAME,
            "app": self.APP,
            "mode": "scout",
            "track": tracks,
            "limit": limit,
            "interact": interact,
            "exec_timeout_ms": int(job.get("exec_timeout_ms") or 420000),
            "steps": validate_steps(steps),
            "stop_before": "",
        }
