"""资讯采集适配器：从手机端财经 App 读取文章正文并保存素材。

定位：小红书图文的"选题原料"入口。
- 只读取公开文章与截图，不点赞/不评论/不转发。
- 平台差异只在本文件：源包名、首页入口提示。
- count>1 时连续采集多篇（每篇读完回列表再开下一篇）。
"""

from __future__ import annotations

from .base import BasePhoneAdapter, build_step, validate_steps

SOURCES = {
    "wallstreetcn": {"app": "com.wallstreetcn.news", "name": "华尔街见闻"},
    "sina": {"app": "cn.com.sina.finance", "name": "新浪财经"},
}
DEFAULT_SOURCE = "wallstreetcn"
MAX_COUNT = 5


class NewsPhone(BasePhoneAdapter):
    NAME = "news"
    APP = SOURCES[DEFAULT_SOURCE]["app"]

    def describe(self, job: dict) -> dict:
        target = job.get("target") or {}
        source = str(job.get("source") or target.get("source") or target.get("target_id") or "").strip()
        if source not in SOURCES:
            source = DEFAULT_SOURCE
        try:
            count = int(job.get("count") or 1)
        except (TypeError, ValueError):
            count = 1
        count = max(1, min(MAX_COUNT, count))
        focus = str(job.get("focus") or "").strip()[:60]
        steps = [build_step("open_app", app=SOURCES[source]["app"])]
        if focus:
            # 千问推荐的今日选题：进 App 后先搜它，再读结果
            steps.append(build_step("search", value=focus))
        steps += [
            build_step("read_article", source=source, limit=count),
            build_step("save_material", tag="article"),
            build_step("stop", reason="article_collected"),
        ]
        steps = validate_steps(steps)
        return {
            "job_id": job.get("_id"),
            "adapter": self.NAME,
            "app": SOURCES[source]["app"],
            "source": source,
            "source_name": SOURCES[source]["name"],
            "count": count,
            "focus": focus,
            "exec_timeout_ms": int(job.get("exec_timeout_ms") or max(180000, count * 90000)),
            "steps": steps,
            "stop_before": "share",
        }
