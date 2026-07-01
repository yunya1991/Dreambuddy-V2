#!/usr/bin/env python3
"""
WorkBuddy OS Bridge Server (Python 侧)

位置: experiments/ab-trading/bridge_server.py

架构说明:
- S链: 意图识别层（S链 + 意图识别引擎，解决用户目标 → 图架构B层）
- A链: 执行闭环（三大闭环 + 三屏交易），使用SKILL方法论
- C链: 经典量化（经典指标系统）
- F链: 基本面（资金流、情绪、新闻）

功能:
1. 模块执行接口 (/api/v1/modules/execute)
2. 注册表查询接口 (/api/v1/registry/*)
3. 健康检查接口 (/health, /api/v1/status)
4. 批量执行接口 (/api/v1/modules/batch)

基于 FastAPI，作为 Python 侧能力对外暴露的统一入口
供 TS 侧 Bridge Client 调用
"""

import os
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Any

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.modules import (
    get_module_registry,
    get_module_executor,
    ModuleResult,
    ExecutionContext,
    create_default_context,
    ModuleQueryParams,
)


# ============================================================
# Pydantic Models
# ============================================================

class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: float
    uptime: float


class StatusResponse(BaseModel):
    status: str
    modules_loaded: int
    execution_engine: str
    registry_version: str
    stats: Dict[str, Any]


class ModuleExecuteRequest(BaseModel):
    module_id: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    context: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None
    symbol: Optional[str] = None


class ModuleBatchExecuteRequest(BaseModel):
    calls: List[Dict[str, Any]]
    context: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None


class RegistryQueryRequest(BaseModel):
    chain: Optional[str] = None
    category: Optional[str] = None
    domain: Optional[str] = None
    stage: Optional[str] = None
    tag: Optional[str] = None
    security_level: Optional[str] = None
    min_accuracy: Optional[float] = None
    max_tokens: Optional[int] = None
    intent: Optional[str] = None
    market_condition: Optional[str] = None


class ModuleInfoResponse(BaseModel):
    id: str
    name: str
    description: str
    version: str
    chain: str
    category: str
    tags: List[str]
    lifecycle: Dict[str, Any]
    security_level: str
    estimated_tokens: int
    estimated_latency_ms: int
    confidence_range: List[float]
    applicable_stages: List[str]
    applicable_intents: List[str]
    market_conditions: List[str]
    historical_accuracy: float
    dependencies: List[str]
    adapter: Dict[str, Any]
    fallback: Dict[str, Any]
    domain: str
    category_name: str


# ============================================================
# FastAPI App
# ============================================================

app = FastAPI(
    title="WorkBuddy OS Bridge Server",
    description="Python侧模块服务桥接器，提供模块执行、注册表查询等接口",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_start_time = time.time()


# ============================================================
# 工具函数
# ============================================================

def _build_context(request_data: Dict, session_id: Optional[str] = None) -> ExecutionContext:
    """从请求数据构建执行上下文"""
    if request_data.get('context'):
        ctx = ExecutionContext.from_dict(request_data['context'])
        if session_id and not ctx.session_id:
            ctx.session_id = session_id
        return ctx

    sid = session_id or request_data.get('session_id') or f"session_{uuid.uuid4().hex[:12]}"
    ctx = create_default_context(sid)

    if request_data.get('symbol'):
        ctx.symbol = request_data['symbol']

    return ctx


def _module_info_to_dict(module_info) -> Dict:
    """将模块信息转换为响应字典"""
    return {
        'id': module_info.id,
        'name': module_info.name,
        'description': module_info.description,
        'version': module_info.version,
        'chain': module_info.chain,
        'category': module_info.category,
        'tags': module_info.tags,
        'lifecycle': module_info.lifecycle,
        'security_level': module_info.security_level,
        'estimated_tokens': module_info.estimated_tokens,
        'estimated_latency_ms': module_info.estimated_latency_ms,
        'confidence_range': module_info.confidence_range,
        'applicable_stages': module_info.applicable_stages,
        'applicable_intents': module_info.applicable_intents,
        'market_conditions': module_info.market_conditions,
        'historical_accuracy': module_info.historical_accuracy,
        'dependencies': module_info.dependencies,
        'adapter': module_info.adapter,
        'fallback': module_info.fallback,
        'domain': module_info.domain,
        'category_name': module_info.category_name,
    }


# ============================================================
# 健康检查
# ============================================================

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "timestamp": time.time(),
        "uptime": time.time() - _start_time,
    }


@app.get("/api/v1/status", response_model=StatusResponse)
async def get_status():
    """获取服务状态"""
    registry = get_module_registry()
    executor = get_module_executor()
    stats = registry.get_stats()
    raw = registry.get_raw()

    return {
        "status": "running",
        "modules_loaded": stats['total'],
        "execution_engine": "python",
        "registry_version": raw.get('version', 'unknown') if raw else 'unknown',
        "stats": stats,
    }


# ============================================================
# 注册表查询
# ============================================================

@app.get("/api/v1/registry/modules")
async def list_modules(
    chain: Optional[str] = None,
    category: Optional[str] = None,
    domain: Optional[str] = None,
    stage: Optional[str] = None,
    tag: Optional[str] = None,
    security_level: Optional[str] = None,
    min_accuracy: Optional[float] = None,
    max_tokens: Optional[int] = None,
    intent: Optional[str] = None,
    market_condition: Optional[str] = None,
):
    """查询模块列表（支持多条件过滤）"""
    registry = get_module_registry()

    modules = registry.query(
        chain=chain,
        category=category,
        domain=domain,
        stage=stage,
        tag=tag,
        security_level=security_level,
        min_accuracy=min_accuracy,
        max_tokens=max_tokens,
        intent=intent,
        market_condition=market_condition,
    )

    return {
        "success": True,
        "count": len(modules),
        "modules": [_module_info_to_dict(m) for m in modules],
    }


@app.post("/api/v1/registry/query")
async def query_modules(request: RegistryQueryRequest):
    """查询模块列表（POST方式，支持更复杂的查询条件）"""
    registry = get_module_registry()

    modules = registry.query(
        chain=request.chain,
        category=request.category,
        domain=request.domain,
        stage=request.stage,
        tag=request.tag,
        security_level=request.security_level,
        min_accuracy=request.min_accuracy,
        max_tokens=request.max_tokens,
        intent=request.intent,
        market_condition=request.market_condition,
    )

    return {
        "success": True,
        "count": len(modules),
        "modules": [_module_info_to_dict(m) for m in modules],
    }


@app.get("/api/v1/registry/modules/{module_id}")
async def get_module(module_id: str):
    """获取单个模块详情"""
    registry = get_module_registry()
    module = registry.get(module_id)

    if not module:
        raise HTTPException(status_code=404, detail=f"Module {module_id} not found")

    return {
        "success": True,
        "module": _module_info_to_dict(module),
    }


@app.get("/api/v1/registry/domains")
async def list_domains():
    """获取所有领域"""
    registry = get_module_registry()
    return {
        "success": True,
        "domains": registry.get_domains(),
    }


@app.get("/api/v1/registry/chains")
async def list_chains():
    """获取所有链"""
    registry = get_module_registry()
    return {
        "success": True,
        "chains": registry.get_chains(),
    }


@app.get("/api/v1/registry/stats")
async def get_registry_stats():
    """获取注册表统计信息"""
    registry = get_module_registry()
    return {
        "success": True,
        "stats": registry.get_stats(),
    }


@app.post("/api/v1/registry/reload")
async def reload_registry():
    """重新加载注册表"""
    registry = get_module_registry()
    success = registry.reload()
    stats = registry.get_stats()

    return {
        "success": success,
        "modules_loaded": stats['total'],
    }


# ============================================================
# 模块执行
# ============================================================

@app.post("/api/v1/modules/execute")
async def execute_module(request: ModuleExecuteRequest):
    """执行单个模块"""
    executor = get_module_executor()

    req_dict = request.model_dump()
    context = _build_context(req_dict, request.session_id)

    try:
        result = executor.execute(
            module_id=request.module_id,
            inputs=request.inputs,
            context=context,
        )

        return {
            "success": True,
            "result": result.to_dict(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")


@app.post("/api/v1/modules/batch")
async def execute_batch(request: ModuleBatchExecuteRequest):
    """批量执行模块"""
    executor = get_module_executor()

    req_dict = request.model_dump()
    context = _build_context(req_dict, request.session_id)

    try:
        results = executor.execute_batch(
            calls=request.calls,
            context=context,
        )

        return {
            "success": True,
            "count": len(results),
            "results": [r.to_dict() for r in results],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch execution failed: {str(e)}")


@app.get("/api/v1/modules/{module_id}/available")
async def check_module_available(module_id: str):
    """检查模块是否可用"""
    registry = get_module_registry()
    executor = get_module_executor()

    module = registry.get(module_id)
    if not module:
        raise HTTPException(status_code=404, detail=f"Module {module_id} not found")

    adapter = executor.get_adapter(module_id)
    available = adapter.is_available() if adapter else False

    return {
        "success": True,
        "module_id": module_id,
        "available": available,
        "has_adapter": adapter is not None,
    }


# ============================================================
# 执行统计
# ============================================================

@app.get("/api/v1/execution/stats")
async def get_execution_stats():
    """获取执行统计"""
    executor = get_module_executor()
    return {
        "success": True,
        "stats": executor.get_stats(),
    }


@app.post("/api/v1/execution/stats/reset")
async def reset_execution_stats():
    """重置执行统计"""
    executor = get_module_executor()
    executor.reset_stats()
    return {
        "success": True,
        "message": "Stats reset",
    }


# ============================================================
# 启动入口
# ============================================================

def main():
    """启动 Bridge Server"""
    import uvicorn

    host = os.environ.get('BRIDGE_HOST', '127.0.0.1')
    port = int(os.environ.get('BRIDGE_PORT', '8095'))

    print(f"🚀 WorkBuddy OS Bridge Server starting...")
    print(f"   Host: {host}")
    print(f"   Port: {port}")
    print(f"   Docs: http://{host}:{port}/docs")
    print()

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == '__main__':
    main()
