#!/usr/bin/env python3
"""DreamOS MCP Bridge — Hermes ↔ DreamOS 物理编排的 MCP 适配器（PROP-20260829-B · P1b/B2）

职责边界（用户定调公理）：
  - Hermes（大模型）决定「做什么」：意图识别后调用本桥的对应工具
  - DreamOS 决定「怎么做」：物理管道 + 模块化能力确定性执行，本桥不做任何决策
  - 本桥只做三件事：①懒启动 api_server ②HTTP 转发 ③结果结构化回流

工具均为只读分析（无下单副作用）：
  - dreamos_health          服务健康 + 预算守卫状态
  - dreamos_recognize_intent 只读意图识别（S 层）
  - dreamos_run_analysis    完整编排（S→P→E→action），自动装配实时行情
  - dreamos_list_nodes      能力节点注册表

生命周期：api_server 未运行时，本桥自动拉起（读 experiments/ab-trading/config/.env
注入 LLM 凭证），并等待健康检查通过后再转发请求。

注册方式（~/.hermes/config.yaml）：
  mcp_servers:
    dreamos:
      command: /home/ubuntu/.hermes/hermes-agent/venv/bin/python3
      args: ["/home/ubuntu/Dreambuddy-V2-main/1-ARCHITECTURE/dreamos/apps/dreamos_mcp_server.py"]
      timeout: 180
      connect_timeout: 60
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.request

from mcp.server.fastmcp import FastMCP

# ── 常量 ─────────────────────────────────────────────────────────────
DREAMOS_ROOT = "/home/ubuntu/Dreambuddy-V2-main/1-ARCHITECTURE"
ENV_FILE = "/home/ubuntu/Dreambuddy-V2-main/experiments/ab-trading/config/.env"
VENV_PYTHON = "/home/ubuntu/.hermes/hermes-agent/venv/bin/python3"
API_PORT = 8000
API_BASE = f"http://127.0.0.1:{API_PORT}"
HL_INFO_URL = "https://api.hyperliquid.xyz/info"
STARTUP_WAIT_S = 45

logging.basicConfig(level=logging.INFO, stream=__import__("sys").stderr,
                    format="[dreamos-mcp] %(message)s")
log = logging.getLogger("dreamos-mcp")

mcp = FastMCP("dreamos")


# ── 基础工具 ─────────────────────────────────────────────────────────
def _parse_env_file(path: str) -> dict:
    """解析 KEY=VALUE 格式的 .env（跳过注释，去引号）。"""
    env = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip("'\"")
    except OSError as e:
        log.warning("读取 .env 失败: %s", e)
    return env


def _http_json(method: str, path: str, payload: dict | None = None,
               timeout: int = 170) -> dict:
    url = f"{API_BASE}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _health_ok() -> bool:
    try:
        r = _http_json("GET", "/api/v1/health", timeout=3)
        return r.get("status") == "ok"
    except Exception:
        return False


def _ensure_server() -> None:
    """确保 DreamOS api_server 在运行；未运行则懒启动并等待就绪。"""
    if _health_ok():
        return
    log.info("api_server 未运行，懒启动中...")
    env = os.environ.copy()
    env.update(_parse_env_file(ENV_FILE))
    env["PYTHONPATH"] = DREAMOS_ROOT
    log_file = open("/tmp/dreamos_api_server.log", "ab")
    subprocess.Popen(
        [VENV_PYTHON, "-m", "dreamos.apps.api_server", "--port", str(API_PORT)],
        cwd=DREAMOS_ROOT, env=env, stdout=log_file, stderr=subprocess.STDOUT,
        start_new_session=True)
    deadline = time.time() + STARTUP_WAIT_S
    while time.time() < deadline:
        time.sleep(2)
        if _health_ok():
            log.info("api_server 已就绪")
            return
    raise RuntimeError(
        f"api_server 启动超时（{STARTUP_WAIT_S}s），详见 /tmp/dreamos_api_server.log")


def _fetch_live_price(symbol: str) -> float:
    """从 Hyperliquid 拉实时中间价（网络受限环境备选源）。失败返回 0。"""
    try:
        req = urllib.request.Request(
            HL_INFO_URL, data=json.dumps({"type": "allMids"}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            mids = json.loads(resp.read().decode())
        return float(mids.get(symbol.upper(), 0))
    except Exception as e:
        log.warning("Hyperliquid 行情获取失败(%s): %s", symbol, e)
        return 0.0


# ── MCP 工具 ─────────────────────────────────────────────────────────
@mcp.tool()
def dreamos_health() -> str:
    """DreamOS 服务健康状态 + 预算守卫。只读，无副作用。
    返回: health/版本 + 预算（日/月/周期余量、降级标志）。"""
    _ensure_server()
    out = {"health": _http_json("GET", "/api/v1/health", timeout=10)}
    try:
        out["budget"] = _http_json("GET", "/api/v1/budget", timeout=10)
    except Exception as e:
        out["budget_error"] = str(e)
    return json.dumps(out, ensure_ascii=False)


@mcp.tool()
def dreamos_recognize_intent(user_input: str) -> str:
    """只读意图识别（DreamOS S 层）。不做完整编排，仅返回意图类型/置信度/
    推荐物理链（base_chain/extend_nodes）。用于对话理解预检。
    Args: user_input — 用户自然语言，如「BTC 现在能做多吗？」"""
    _ensure_server()
    r = _http_json("POST", "/api/v1/intent",
                   {"user_input": user_input}, timeout=120)
    return json.dumps(r, ensure_ascii=False)


@mcp.tool()
def dreamos_run_analysis(user_input: str, symbol: str = "BTC",
                         price: float = 0.0, intent_type: str = "",
                         phase: int = 0) -> str:
    """完整 DreamOS 物理编排：意图识别→能力路由→图执行→交易分析结论。
    只读分析（无下单副作用）。自动装配实时行情：price 缺省或为 0 时，
    从 Hyperliquid 拉取 symbol 实时中间价注入（无行情意图会降级）。
    Args:
      user_input — 用户自然语言请求
      symbol — 交易对（BTC/ETH/SOL 等 Hyperliquid 符号）
      price — 可选，显式指定价格则跳过行情拉取
      intent_type — 可选，外部意图提示（DreamOS IntentType：
        TREND_FOLLOWING/MEAN_REVERSION/FUNDAMENTAL_PLAY/BREAKOUT/
        KNOWLEDGE_MATCH/UNCERTAIN）。指定后跳过 S 层内部识别（省 10-50s）。
      phase — 可选，渐进式编排档位（0=完整编排/默认，1=仅必要节点轻量首答，
        2=完整执行/深化追问）。phase=1 时可选节点延后，返回含
        deferred_nodes 与 next_step_hint，可追问深化。
    返回: action(LONG/SHORT/HOLD)/confidence/rationale + 执行轨迹
    (nodes_planned/executed/success) + tokens/latency。"""
    _ensure_server()
    if price <= 0:
        price = _fetch_live_price(symbol)
    market_data = {"symbol": symbol.upper()}
    if price > 0:
        market_data["price"] = price
    body: dict = {"user_input": user_input, "market_data": market_data}
    if intent_type:
        # 20260829-bridge S6: 正典对齐透传（与前端桥同契约）
        body["intent_hint"] = {
            "intent_type": intent_type.upper(),
            "confidence": 0.85,
            "provenance": "mcp_canon",
        }
    if phase in (1, 2):
        body["phase"] = phase
    r = _http_json("POST", "/api/v1/run", body, timeout=170)
    return json.dumps(r, ensure_ascii=False)


@mcp.tool()
def dreamos_list_nodes() -> str:
    """DreamOS 能力节点注册表（config/nodes.yaml 加载结果）：
    各节点的 name/chain/description/tags/预估 tokens 与延迟。只读。"""
    _ensure_server()
    r = _http_json("GET", "/api/v1/nodes", timeout=15)
    return json.dumps(r, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
