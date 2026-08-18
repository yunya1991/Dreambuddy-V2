#!/usr/bin/env python3
"""
千问 (Qwen) LLM 客户端 — Dream OS 大模型驱动底层封装

三层配置（Provider / Model / Protocol）：
  - Provider: 阿里云 DashScope（百炼平台），千问 = 阿里云/通义千问（非百度）
  - Model:    qwen-max（可通过 env QWEN_MODEL 覆盖）
  - Protocol: OpenAI 兼容层（/compatible-mode/v1/chat/completions）

核心职责：
  - 提供统一的 chat_completion() 接口
  - API key 从环境变量读取，禁止硬编码
  - 内置重试 + 超时 + 错误处理
  - 作为 llm_bridge.py 的 provider 之一，也作为 llm_driver.py 的底层引擎

接入位置：
  - 16-调控系统/core/llm_bridge.py（新增 qwen provider）
  - 11-易经推理系统/scripts/memory_l4/self_evolution_engine.py（llm_client slot）
"""

import json
import os
import time
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── 环境配置加载 ──────────────────────────────────────────────────────────

_BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _load_env() -> Dict[str, str]:
    """从多个 .env 文件加载配置（与 llm_bridge.py 一致的加载策略）"""
    config = {}
    env_files = [
        _BASE_DIR / "6-TRADING" / "scripts" / ".env",
        _BASE_DIR / "16-调控系统" / ".env",
        _BASE_DIR / ".env",
        Path(os.path.expanduser("~/.workbuddy/.env")),
    ]
    for ef in env_files:
        if ef.exists():
            try:
                with open(ef, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            config[k.strip()] = v.strip().strip('"').strip("'")
            except Exception:
                pass
    # os.environ 优先级最高
    for k, v in os.environ.items():
        if k.startswith(("QWEN", "DASHSCOPE")):
            config[k] = v
    return config


_env = _load_env()

# ── 三层配置 ──────────────────────────────────────────────────────────────

# Provider: 阿里云 DashScope（百炼平台）
QWEN_API_KEY: str = _env.get("QWEN_API_KEY", "")
QWEN_BASE_URL: str = _env.get(
    "QWEN_BASE_URL",
    # sk-sp- (Token Plan) → token-plan 端点；sk- (标准) → dashscope 端点
    "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
)

# Model: 千问 3.8 MAX（可通过 env 覆盖为其他千问型号）
QWEN_MODEL: str = _env.get("QWEN_MODEL", "qwen3.8-max")

# Protocol: OpenAI 兼容层
QWEN_PROTOCOL: str = "openai-compatible"


@dataclass
class QwenResult:
    """千问调用结果"""
    success: bool
    content: str = ""
    model: str = ""
    tokens_input: int = 0
    tokens_output: int = 0
    latency_ms: float = 0.0
    error: str = ""
    raw: Optional[Dict[str, Any]] = None


def is_available() -> bool:
    """检查千问是否可用（API key 已配置）"""
    return bool(QWEN_API_KEY)


def chat_completion(
    messages: List[Dict[str, str]],
    model: str = "",
    temperature: float = 0.3,
    max_tokens: int = 2000,
    timeout: int = 30,
    retries: int = 2,
) -> QwenResult:
    """
    调用千问 chat/completions 接口（OpenAI 兼容协议）

    Args:
        messages: [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
        model: 模型名，空则用默认 QWEN_MODEL
        temperature: 温度
        max_tokens: 最大输出 token
        timeout: 超时秒
        retries: 失败重试次数

    Returns:
        QwenResult
    """
    if not QWEN_API_KEY:
        return QwenResult(success=False, error="QWEN_API_KEY 未配置")

    used_model = model or QWEN_MODEL
    start = time.time()

    for attempt in range(retries + 1):
        try:
            import http.client
            import ssl
            from urllib.parse import urlparse

            payload = {
                "model": used_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            data = json.dumps(payload).encode("utf-8")

            parsed = urlparse(QWEN_BASE_URL)
            host = parsed.hostname
            path = f"{parsed.path.rstrip('/')}/chat/completions"

            # 北京端点需要更宽松的 SSL 上下文
            ctx = ssl.create_default_context()
            ctx.check_hostname = True
            ctx.verify_mode = ssl.CERT_REQUIRED

            conn = http.client.HTTPSConnection(
                host, parsed.port or 443, timeout=timeout, context=ctx,
            )
            conn.request(
                "POST", path, body=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {QWEN_API_KEY}",
                    "Content-Length": str(len(data)),
                },
            )
            resp = conn.getresponse()
            resp_body = resp.read().decode("utf-8")
            conn.close()

            body = json.loads(resp_body)

            content = (
                body.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            usage = body.get("usage", {})
            latency = (time.time() - start) * 1000

            return QwenResult(
                success=True,
                content=content,
                model=used_model,
                tokens_input=usage.get("prompt_tokens", 0),
                tokens_output=usage.get("completion_tokens", 0),
                latency_ms=round(latency, 1),
                raw=body,
            )

        except Exception as e:
            err = str(e)
            # SSL 间歇性断连时，最后一次尝试用 curl fallback
            if attempt == retries and "SSL" in err:
                curl_result = _curl_fallback(
                    used_model, messages, temperature, max_tokens, timeout,
                )
                if curl_result.success:
                    return curl_result
            if attempt < retries:
                wait = 2 ** attempt
                logger.warning(f"[Qwen] 调用失败(attempt {attempt+1}), {wait}s后重试: {err}")
                time.sleep(wait)
            else:
                latency = (time.time() - start) * 1000
                return QwenResult(
                    success=False,
                    error=err,
                    model=used_model,
                    latency_ms=round(latency, 1),
                )

    return QwenResult(success=False, error="unreachable")


def _curl_fallback(
    model: str,
    messages: List[Dict[str, str]],
    temperature: float,
    max_tokens: int,
    timeout: int,
) -> QwenResult:
    """
    curl fallback — 当 Python http.client/urllib 出现 SSL 间歇性断连时，
    用 subprocess curl 发送请求（curl 的 SSL 实现更稳定）。

    北京 token-plan 端点偶发 SSL UNEXPECTED_EOF，curl 不受影响。
    """
    import subprocess
    start = time.time()

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    })

    url = f"{QWEN_BASE_URL.rstrip('/')}/chat/completions"
    try:
        proc = subprocess.run(
            [
                "curl", "-s", "--connect-timeout", "10",
                "--max-time", str(timeout),
                "-X", "POST", url,
                "-H", "Content-Type: application/json",
                "-H", f"Authorization: Bearer {QWEN_API_KEY}",
                "-d", payload,
            ],
            capture_output=True, text=True, timeout=timeout + 10,
        )
        if proc.returncode != 0:
            return QwenResult(success=False, error=f"curl failed: {proc.stderr[:200]}")

        body = json.loads(proc.stdout)
        content = (
            body.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        usage = body.get("usage", {})
        latency = (time.time() - start) * 1000

        logger.info(f"[Qwen] curl fallback 成功, latency={latency:.0f}ms")
        return QwenResult(
            success=True,
            content=content,
            model=model,
            tokens_input=usage.get("prompt_tokens", 0),
            tokens_output=usage.get("completion_tokens", 0),
            latency_ms=round(latency, 1),
            raw=body,
        )
    except Exception as e:
        return QwenResult(success=False, error=f"curl fallback error: {e}")


def call(
    prompt: str,
    system_prompt: str = "",
    max_tokens: int = 2000,
    temperature: float = 0.3,
    purpose: str = "",
) -> str:
    """
    简化调用接口 — 兼容 self_evolution_engine 的 llm_client 签名

    用法:
        # 在 self_evolution_engine 中
        engine = SelfEvolutionEngine(llm_client=qwen_client.call)

    Args:
        prompt: 用户提示词
        system_prompt: 系统提示词（可选）
        max_tokens: 最大输出 token
        temperature: 温度
        purpose: 调用用途标记（用于日志/配额，不影响调用）

    Returns:
        模型回复文本（失败返回空字符串）
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    result = chat_completion(
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    if result.success:
        logger.info(
            f"[Qwen] purpose={purpose} model={result.model} "
            f"tokens={result.tokens_input}+{result.tokens_output} "
            f"latency={result.latency_ms}ms"
        )
        return result.content
    else:
        logger.error(f"[Qwen] purpose={purpose} 调用失败: {result.error}")
        return ""


def get_config_info() -> Dict[str, Any]:
    """返回当前配置信息（用于调试，不暴露完整 key）"""
    return {
        "provider": "阿里云 DashScope（百炼平台）",
        "model": QWEN_MODEL,
        "protocol": QWEN_PROTOCOL,
        "base_url": QWEN_BASE_URL,
        "api_key_configured": bool(QWEN_API_KEY),
        "api_key_preview": f"{QWEN_API_KEY[:8]}..." if QWEN_API_KEY else "(empty)",
    }
