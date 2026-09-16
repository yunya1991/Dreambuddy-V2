#!/usr/bin/env python3
"""
A_HERMES_SKILL — Hermes 大模型 SKILL 桥接节点

双轨大脑架构（2026-08-29 确认）中 DreamOS → Hermes 的委托通道：
DreamOS 物理编排将「重 LLM 的 A 系列深度分析任务」委托给 Hermes 大模型，
由 Hermes 加载对应 dream-* SKILL 执行，本节点负责构建任务、调用并收集结论。

调用机制（已验证路径）:
    - 直调 Hermes cron.scheduler.run_job()（同步执行一个临时 LLM job）
    - job 不落盘（临时 dict）、deliver=local（不外发消息，仅本地存档）
    - execution_loop guard 只拦 managed=True 的 job，临时 job 天然穿透

SKILL 路由:
    - A0 矛盾论      → dream-contradiction-theory
    - A2 第一性原理  → dream-strategic-analysis + dream-contradiction-theory
    - A1 深度调研    → dream-strategy-research + dream-contradiction-theory
    - 默认           → dream-strategy-research + dream-contradiction-theory

约束:
    - 只读分析桥接，不触发 Hermes 侧下单/审批/系统变更
    - Hermes 超时/不可用 → 降级返回（degraded=True），不阻塞主链
    - Mock 模式（环境变量 DREAMOS_HERMES_BRIDGE=mock）: 返回桩结果，零 token，用于测试

环境变量:
    DREAMOS_HERMES_BRIDGE=mock          启用 mock 模式
    DREAMOS_HERMES_BRIDGE_TIMEOUT=240   Hermes 调用超时秒数（默认 240）
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus

logger = logging.getLogger("a_hermes_skill_bridge")

# Hermes Agent 安装目录（cron scheduler 所在）
HERMES_AGENT_DIR = "/home/ubuntu/.hermes/hermes-agent"

# SKILL 路由表: (关键词元组, SKILL 列表, 路由名)
# 按顺序匹配，首个命中生效；关键词匹配大小写不敏感
SKILL_ROUTES: List[Tuple[Tuple[str, ...], List[str], str]] = [
    (("a0", "矛盾论", "矛盾分析", "contradiction"),
     ["dream-contradiction-theory"],
     "A0矛盾论分析"),
    (("a2", "第一性原理", "first principle", "六因子"),
     ["dream-strategic-analysis", "dream-contradiction-theory"],
     "A2第一性原理分析"),
    (("a1", "深度调研", "深度分析", "调研报告", "战略研究", "深度报告"),
     ["dream-strategy-research", "dream-contradiction-theory"],
     "A1深度调研"),
]
DEFAULT_SKILLS = ["dream-strategy-research", "dream-contradiction-theory"]
DEFAULT_ROUTE = "A系列深度分析(默认)"


class AHermesSkillNode(BaseNode):
    """Hermes 大模型 SKILL 桥接节点

    将 A 系列深度分析委托给 Hermes 执行:
        DreamOS 意图路由 → 本节点 → Hermes run_job(dream-* SKILL)
        → 结构化分析结论 → NodeResult 回流物理编排

    ⚠️ 只读分析桥接，无下单副作用。
    """

    node_id = "A_HERMES_SKILL"
    name = "Hermes SKILL桥接"
    description = "委托 Hermes 大模型执行 A 系列深度分析 SKILL 并收集结论（只读桥接）"
    chain = "A"
    tags = ["hermes", "bridge", "skill", "deep-analysis", "external"]
    estimated_tokens = 0          # token 消耗在 Hermes 侧，不占 DreamOS 预算
    estimated_latency_ms = 120_000  # LLM 深度分析，分钟级

    # ── 主执行 ──────────────────────────────────────────

    def execute_core(self, state: State) -> NodeResult:
        t0 = time.time()
        user_input = self._extract_user_input(state)
        market = self._extract_market(state)
        symbol = str(market.get("coin") or market.get("symbol") or "BTC")

        # ── Mock 模式（测试/开发，零 token） ──
        if os.environ.get("DREAMOS_HERMES_BRIDGE", "").strip().lower() == "mock":
            logger.info("A_HERMES_SKILL mock 模式: symbol=%s", symbol)
            return NodeResult(
                node_id=self.node_id,
                confidence=0.5,
                direction="NEUTRAL",
                latency_ms=(time.time() - t0) * 1000,
                outputs={
                    "source": "hermes-bridge-mock",
                    "symbol": symbol,
                    "analysis": f"[MOCK] {symbol} 深度分析桩结果：桥接链路连通性测试通过。",
                    "skills": DEFAULT_SKILLS,
                },
            )

        skills, route_name = self._route_skills(user_input)
        prompt = self._build_prompt(user_input, symbol, market, route_name)

        # ── 调用 Hermes（线程隔离 + 超时保护） ──
        try:
            ok, final_response, error = self._call_hermes(prompt, skills)
        except Exception as e:  # 导入失败等结构性错误
            logger.error("A_HERMES_SKILL 调用异常: %s", e)
            return NodeResult(
                node_id=self.node_id,
                status=NodeStatus.FAILED,
                error=f"hermes_bridge_exception: {e}",
                latency_ms=(time.time() - t0) * 1000,
                outputs={"source": "hermes-bridge", "route": route_name},
            )

        latency = (time.time() - t0) * 1000

        if not ok or not (final_response or "").strip():
            logger.warning("A_HERMES_SKILL 降级: ok=%s error=%s", ok, error)
            return NodeResult(
                node_id=self.node_id,
                status=NodeStatus.DEGRADED,
                degraded=True,
                warnings=[f"Hermes 桥接不可用，深度分析跳过: {error or 'empty_response'}"],
                latency_ms=latency,
                outputs={
                    "source": "hermes-bridge",
                    "route": route_name,
                    "skills": skills,
                    "status": "degraded",
                },
            )

        direction, confidence = self._parse_conclusion(final_response)
        logger.info(
            "A_HERMES_SKILL 完成: route=%s latency=%.1fs direction=%s confidence=%.2f",
            route_name, latency / 1000, direction, confidence,
        )
        return NodeResult(
            node_id=self.node_id,
            confidence=confidence,
            direction=direction,
            latency_ms=latency,
            outputs={
                "source": "hermes-bridge",
                "route": route_name,
                "skills": skills,
                "symbol": symbol,
                "analysis": final_response[:6000],
            },
        )

    # ── 输入提取 ────────────────────────────────────────

    @staticmethod
    def _extract_user_input(state: State) -> str:
        """从 State 多路径提取用户原始输入"""
        inputs = getattr(state, "inputs", None)
        if isinstance(inputs, dict) and inputs.get("user_input"):
            return str(inputs["user_input"])
        intent = getattr(state, "intent", None) or {}
        if isinstance(intent, dict) and intent.get("user_input"):
            return str(intent["user_input"])
        extra = getattr(state, "extra", None) or {}
        if isinstance(extra, dict) and extra.get("user_input"):
            return str(extra["user_input"])
        return ""

    @staticmethod
    def _extract_market(state: State) -> Dict[str, Any]:
        """从 State 多路径提取市场数据"""
        for attr in ("market_data", "market"):
            m = getattr(state, attr, None)
            if isinstance(m, dict) and m:
                return m
        return {}

    # ── SKILL 路由 ──────────────────────────────────────

    @staticmethod
    def _route_skills(user_input: str) -> Tuple[List[str], str]:
        """按关键词路由到对应 SKILL 组合"""
        text = (user_input or "").lower()
        for keywords, skills, route_name in SKILL_ROUTES:
            if any(kw.lower() in text for kw in keywords):
                return list(skills), route_name
        return list(DEFAULT_SKILLS), DEFAULT_ROUTE

    @staticmethod
    def _build_prompt(user_input: str, symbol: str,
                      market: Dict[str, Any], route_name: str) -> str:
        """构建委托给 Hermes 的任务 prompt"""
        price = market.get("price")
        price_line = f"，当前价格: {price}" if price else ""
        task = (user_input or "").strip() or f"对 {symbol} 进行 A 系列深度分析"
        return (
            f"[DreamOS物理编排 · Hermes SKILL桥接 · {route_name}]\n"
            f"任务: {task}\n"
            f"标的: {symbol}{price_line}\n"
            f"要求: 严格按已加载 SKILL 的方法论执行深度分析，直接输出结论，不要反问。\n"
            f"输出格式（严格遵守）:\n"
            f"1) 主要矛盾/核心判断: （一段话）\n"
            f"2) 方向: LONG / SHORT / HOLD（三选一，单独一行，格式「方向: X」）\n"
            f"3) 置信度: 0-1 之间的小数（单独一行，格式「置信度: X」）\n"
            f"4) 关键依据: （不超过3条）\n"
            f"5) 风险提示: （不超过2条）\n"
        )

    # ── Hermes 调用 ─────────────────────────────────────

    def _call_hermes(self, prompt: str,
                     skills: List[str]) -> Tuple[bool, str, Optional[str]]:
        """直调 Hermes cron.scheduler.run_job 执行临时 LLM job

        线程隔离 + 超时保护：超时后 Hermes 任务可能仍在后台继续，
        本节点先降级返回，不阻塞物理编排主链。
        """
        if HERMES_AGENT_DIR not in sys.path:
            sys.path.insert(0, HERMES_AGENT_DIR)
        from cron.scheduler import run_job  # noqa: 延迟导入

        timeout_s = float(os.environ.get("DREAMOS_HERMES_BRIDGE_TIMEOUT", "240"))
        job: Dict[str, Any] = {
            "id": f"dreamos-bridge-{int(time.time())}",
            "name": "DreamOS→Hermes SKILL桥接",
            "prompt": prompt,
            "skills": skills,
            "deliver": "local",  # 不外发消息，仅本地存档
        }

        result: Dict[str, Any] = {}

        def _runner() -> None:
            try:
                ok, _doc, final_response, err = run_job(job)
                result["ok"] = bool(ok)
                result["response"] = final_response or ""
                result["error"] = err
            except Exception as e:  # noqa: BLE001
                result["ok"] = False
                result["response"] = ""
                result["error"] = f"run_job exception: {e}"

        th = threading.Thread(target=_runner, daemon=True, name="hermes-bridge")
        th.start()
        th.join(timeout_s)
        if th.is_alive():
            return False, "", f"timeout after {timeout_s:.0f}s (Hermes 任务可能仍在后台运行)"
        return result.get("ok", False), result.get("response", ""), result.get("error")

    # ── 结论解析 ────────────────────────────────────────

    @staticmethod
    def _parse_conclusion(text: str) -> Tuple[Optional[str], float]:
        """从 Hermes 输出中尽力解析方向与置信度（best-effort）"""
        direction: Optional[str] = None
        m = re.search(r"方向\s*[:：]\s*(LONG|SHORT|HOLD)", text, re.IGNORECASE)
        if m:
            direction = m.group(1).upper()

        confidence = 0.6  # 解析失败时的保守默认值
        m = re.search(r"置信度\s*[:：]\s*(0(?:\.\d+)?|1(?:\.0+)?)", text)
        if m:
            try:
                confidence = max(0.0, min(1.0, float(m.group(1))))
            except ValueError:
                pass
        return direction, confidence
