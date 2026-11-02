# -*- coding: utf-8 -*-
"""
server.py — 45-评测系统 生产启动入口
====================================
职责：
- 从环境变量 EVAL_PG_DSN 装配 PgRepo（生产存储，fail-closed：未设置即拒绝启动）
- 装配 Runner + E3Executor：受理即入队，后台线程执行真实评测（E3 + 专项评测器）
- 启动时恢复滞留 queued 任务（服务重启不丢任务）
- 由 systemd 服务 eval-api.service 以 uvicorn 拉起
用法：
    EVAL_PG_DSN=postgresql://... uvicorn api.server:app --host 127.0.0.1 --port 8790
"""
from __future__ import annotations
import logging
import os
import sys

MODULE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if MODULE_ROOT not in sys.path:
    sys.path.insert(0, MODULE_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

from api.routes import create_app  # noqa: E402


def _build_app():
    dsn = os.environ.get("EVAL_PG_DSN")
    if not dsn:
        raise SystemExit(
            "[eval-api] EVAL_PG_DSN 未设置：生产模式必须装配 PgRepo（fail-closed），拒绝以内存模式上线"
        )
    from core.registry import ThresholdRegistry
    from core.reporter import Reporter
    from core.runner import Runner
    from evaluators.executor import E3Executor, requeue_pending
    from storage.repo import PgRepo

    repo = PgRepo(dsn)
    reporter = Reporter(repo=repo, thresholds=ThresholdRegistry.load())
    executor = E3Executor(repo=repo, reporter=reporter)
    runner = Runner(repo=repo, reporter=reporter, executor=executor)

    # runner 随应用工厂注入：受理路由闭包持有该实例，受理成功即入队
    app = create_app(repo=repo, reporter=reporter, runner=runner)
    app.state.dsn_configured = True

    # 恢复滞留任务并启动后台执行线程
    requeue_pending(repo, runner)
    runner.start()

    @app.on_event("shutdown")
    def _stop_runner() -> None:  # pragma: no cover
        runner.stop()

    return app


app = _build_app()
