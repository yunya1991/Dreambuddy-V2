#!/usr/bin/env python3
"""jev_preference_judge.py — 方案D DPO偏好判定 (SPEC §6)

用 jev choice 判定逐轮策略偏好，生成 DPO 训练样本。

HC-J1: FAIL-OPEN — jev 不可用时返回空列表
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from typing import Any, Callable, Optional

logger = logging.getLogger("debate.jev_preference_judge")


@dataclass
class PreferenceSample:
    """DPO 偏好样本。"""
    topic: str
    round: int
    strategies: list[str]
    choice: str


class JevPreferenceJudge:
    """逐轮策略偏好判定。"""

    def __init__(self, jev_fn: Optional[Callable[..., dict]] = None):
        self._jev_fn = jev_fn

    def judge(
        self,
        topic: str,
        transcript: list[dict],
        strategies: list[str],
    ) -> list[PreferenceSample]:
        """判定逐轮策略偏好。

        Args:
            topic: 辩论话题
            transcript: 辩论记录
            strategies: 候选策略列表

        Returns:
            list[PreferenceSample]，每个 round 一个
        """
        if not strategies or self._jev_fn is None:
            return []

        # 提取轮次
        rounds = sorted({t.get("round") for t in transcript if "round" in t})

        # 构建 choice 问题（每轮一个）
        questions = {}
        for r in rounds:
            questions[f"r{r}"] = {
                "type": "choice",
                "instructions": f"第 {r} 轮最有效的策略是什么？",
                "criteria": {s: s for s in strategies},
            }

        state = {"topic": topic, "rounds": rounds}

        try:
            resp = self._jev_fn(state, questions)
        except Exception as e:  # noqa: BLE001 FAIL-OPEN
            logger.warning("偏好判定 jev 异常(FAIL-OPEN): %s", e)
            return []

        if not isinstance(resp, dict) or resp.get("degraded", False):
            return []

        answers = resp.get("answers", {})
        samples: list[PreferenceSample] = []
        for r in rounds:
            ans = answers.get(f"r{r}", {})
            if not isinstance(ans, dict):
                continue
            choice = str(ans.get("choice", ""))
            if choice in strategies:
                samples.append(PreferenceSample(
                    topic=topic, round=r, strategies=strategies, choice=choice))

        return samples

    @staticmethod
    def save_samples(samples: list[PreferenceSample], output_path: str) -> None:
        """将偏好样本写入 JSON 文件。"""
        data = [asdict(s) for s in samples]
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("保存 %d 条偏好样本到 %s", len(data), output_path)
