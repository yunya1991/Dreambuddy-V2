"""抖音适配器：图文发布（P0）+ 爆款侦察，两条通道共用同一 App。

- mode 缺省 / "post"：选相册素材 → 填描述（标题+正文+话题）→ 停在「发布」按钮前。
- mode="scout"：按赛道关键词搜索，读前 N 条视频卡片标题与互动量，可选点赞。

红线：
- 默认只填好内容并停在发布前，人工核对后自行点发布；
- 仅当上游显式传入 publish_authorized（用户明确说"发出去"）才允许点发布；
- 侦察只读卡片 + 点赞，不下载他人视频、不搬运、不评论；
- 每日发布条数由上游控制（默认 ≤2），避免账号风控。
"""

from __future__ import annotations

import re

from .base import BasePhoneAdapter, build_step, validate_steps

MAX_TITLE = 55       # 抖音描述首行展示长度，超出会被折叠
MAX_BODY = 800       # 描述总长控制在 1000 字内、留出话题空间
MAX_TOPICS = 5
MAX_IMAGES = 9       # 图文默认控制在 9 张内，顺序即相册时间倒序
MAX_SCOUT = 8
DEFAULT_TRACKS = ("财经", "经济", "时事", "AI Agent", "数据服务")


class DouyinPhone(BasePhoneAdapter):
    NAME = "douyin"
    APP = "com.ss.android.ugc.aweme"

    def describe(self, job: dict) -> dict:
        mode = str(job.get("mode") or "post").strip().lower()
        if mode == "scout":
            return self._scout(job)
        return self._post(job)

    def _post(self, job: dict) -> dict:
        note = job.get("note") or {}
        title = str(note.get("title") or job.get("title") or "").strip()[:MAX_TITLE]
        body = str(note.get("body") or job.get("body") or "").strip()[:MAX_BODY]
        topics: list[str] = []
        for item in note.get("topics") or job.get("topics") or []:
            word = str(item).strip().lstrip("#").strip()
            if word and word not in topics:
                topics.append(word)
        topics = topics[:MAX_TOPICS]
        images = [str(item) for item in (note.get("images") or job.get("images") or []) if item][:MAX_IMAGES]
        media = "video" if str(job.get("media") or note.get("media") or "image").lower() == "video" else "image"
        steps = validate_steps(
            [
                build_step("open_app", app=self.APP),
                build_step("select_material", count=max(1, len(images) or 1)),
                build_step("compose_note", title=title, topic_count=len(topics)),
                build_step("stop", reason="await_publish_confirm"),
            ]
        )
        return {
            "job_id": job.get("_id"),
            "adapter": self.NAME,
            "app": self.APP,
            "mode": "post",
            "media": media,
            "title": title,
            "body": body,
            "topics": topics,
            "images": images,
            # 发布授权：默认 False；仅用户明确说"发出去/直接发布"时由上游置 True
            "publish_authorized": bool(job.get("publish_authorized")),
            "exec_timeout_ms": int(job.get("exec_timeout_ms") or 300000),
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
            build_step("save_material", tag="douyin_scout"),
        ]
        if interact:
            # 互动硬上限 5：只点赞，不评论、不下载
            steps.append(build_step("interact_post", actions="like", limit=min(limit, 5)))
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
