# -*- coding: utf-8 -*-
"""
routes.py — 评测系统 HTTP API（P0-6）
=====================================
职责（PLAN P0-6 验收 / SPEC §13.1/§13.2）：
- POST   /api/v1/eval/submit      受理（Idempotency-Key 强制 → 202）
- GET    /api/v1/eval/{eval_id}   查询（状态 + 已出分报告字段，§13.2）
- GET    /api/v1/eval             列表（submitter/category/verdict/from/to/limit）
- DELETE /api/v1/eval/{eval_id}   取消（仅 queued/running；否则 409）

错误映射（§13.1 受理即拒）：
- MissingIdempotencyKeyError / RequestValidationError / CategoryMismatchError → 400
- 未知 eval_id → 404；不可取消状态 → 409

影子模式说明：
- gate.shadow=true（config/categories.yaml）时仅受理与出分，不触发拦截回调；
  本层不做拦截决策，拦截动作属 P3 部署卡点（§13.3/§13.4）。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from core.gateway import (
    CATEGORIES,
    CategoriesConfig,
    CategoryMismatchError,
    Gateway,
    MissingIdempotencyKeyError,
    RequestValidationError,
)
from core.registry import ThresholdRegistry
from core.reporter import Reporter
from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from storage.repo import EvalRepo, InMemoryRepo, parse_zulu, zulu

logger = logging.getLogger(__name__)

VERDICTS = ("PASS", "BLOCK", "INCONCLUSIVE")

API_PREFIX = "/api/v1/eval"


def create_app(
    repo: EvalRepo | None = None,
    gateway: Gateway | None = None,
    reporter: Reporter | None = None,
) -> FastAPI:
    """应用工厂：默认内存装配（本地空跑/单测）；生产注入 PgRepo 装配。"""
    if repo is None:
        repo = InMemoryRepo()
    if gateway is None:
        gateway = Gateway(store=repo, categories=CategoriesConfig.load())
    if reporter is None:
        reporter = Reporter(repo=repo, thresholds=ThresholdRegistry.load())

    app = FastAPI(title="45-评测系统", version="1.0.0")
    app.state.repo = repo
    app.state.gateway = gateway
    app.state.reporter = reporter

    # ---------- 错误映射 ----------

    @app.exception_handler(MissingIdempotencyKeyError)
    async def _missing_key(_req: Request, exc: MissingIdempotencyKeyError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def _invalid_request(_req: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(CategoryMismatchError)
    async def _mismatch(_req: Request, exc: CategoryMismatchError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    # ---------- 提交（§13.1） ----------

    @app.post(f"{API_PREFIX}/submit", status_code=202)
    def submit(
        payload: dict[str, Any],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        result = gateway.submit(payload, idempotency_key)
        return {
            "eval_id": result.eval_id,
            "status": result.status,
            "spec_hash": result.spec_hash,
        }

    # ---------- 查询（§13.2） ----------

    @app.get(f"{API_PREFIX}/{{eval_id}}")
    def get_eval(eval_id: str) -> JSONResponse:
        request = repo.get_request(eval_id)
        if request is None:
            return JSONResponse(status_code=404, content={"detail": f"未知 eval_id: {eval_id}"})
        report = repo.get_report(eval_id)
        body: dict[str, Any] = {
            "eval_id": eval_id,
            "status": request.status,
            "verdict": report["verdict"] if report else None,
            "score": report["score"] if report else None,
            "n": report["n"] if report else None,
            "ci": report["ci"] if report else None,
            "evidence_uri": report["evidence"]["uri"] if report else None,
            "block_reasons": report["block_reasons"] if report else [],
            "sla": report["sla"] if report else None,
            "run_spec_hash": report["spec_hash"] if report else request.spec_hash,
        }
        return JSONResponse(status_code=200, content=body)

    @app.get(API_PREFIX)
    def list_evals(
        submitter: str | None = Query(default=None),
        category: str | None = Query(default=None),
        verdict: str | None = Query(default=None),
        from_: str | None = Query(default=None, alias="from"),
        to: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> JSONResponse:
        if category is not None and category not in CATEGORIES:
            return JSONResponse(
                status_code=400,
                content={"detail": f"未知 category: {category!r}（须为 {CATEGORIES}）"},
            )
        if verdict is not None and verdict not in VERDICTS:
            return JSONResponse(
                status_code=400,
                content={"detail": f"未知 verdict: {verdict!r}（须为 {VERDICTS}）"},
            )
        from_dt, err = _parse_dt("from", from_)
        if err:
            return err
        to_dt, err = _parse_dt("to", to)
        if err:
            return err
        rows = repo.list_requests(
            submitter=submitter,
            category=category,
            verdict=verdict,
            from_dt=from_dt,
            to_dt=to_dt,
            limit=limit,
        )
        items = []
        for row in rows:
            item = dict(row)
            created = item.get("created_at")
            if isinstance(created, datetime):
                item["created_at"] = zulu(created)
            items.append(item)
        return JSONResponse(status_code=200, content={"items": items, "count": len(items)})

    # ---------- 取消（§13.2） ----------

    @app.delete(f"{API_PREFIX}/{{eval_id}}")
    def cancel_eval(eval_id: str) -> JSONResponse:
        request = repo.get_request(eval_id)
        if request is None:
            return JSONResponse(status_code=404, content={"detail": f"未知 eval_id: {eval_id}"})
        if request.status not in ("queued", "running"):
            return JSONResponse(
                status_code=409,
                content={
                    "detail": (
                        f"eval_id {eval_id} 当前状态 {request.status}，"
                        "仅 queued/running 可取消（§13.2 已判定不可撤销）"
                    )
                },
            )
        repo.update_status(eval_id, "cancelled")
        logger.info("eval cancelled eval_id=%s prev_status=%s", eval_id, request.status)
        return JSONResponse(status_code=200, content={"eval_id": eval_id, "status": "cancelled"})

    return app


def _parse_dt(name: str, value: str | None) -> tuple[datetime | None, JSONResponse | None]:
    """ISO 时间解析；非法 → (None, 400)。"""
    if value is None:
        return None, None
    try:
        return parse_zulu(value), None
    except ValueError:
        return None, JSONResponse(
            status_code=400,
            content={"detail": f"参数 {name} 非法 ISO 时间: {value!r}"},
        )
