"""
L3 ShadowRLTracker (§二 L3 高频探索层 · MVP 骨架)
蓝图: 四层闭环进化架构-最小阻力路径总览.md §二

Phase 3: ShadowRLTrainer 激活（gmax变异 + Thompson sampling + V(s)回流）
样本≥2000自动激活（HC-AGI-01，非PR评审）.

优化（B+C+D 方案）：
  - C: 有效样本计数（reward≠0），激活与训练只看有效样本
  - D: JSONL 持久化，重启不丢失
"""
import json
import logging
import numpy as np
from collections import deque
from pathlib import Path
from typing import Any

from dreambuddy_evolution.core.shadow_rl_trainer import ShadowRLTrainer

logger = logging.getLogger(__name__)


class ShadowRLTracker:
    """
    L3 影子 RL 追踪器.
    MVP: 记录样本 + 计算 Sharpe.
    Phase 3: 有效样本≥2000自动激活 ShadowRLTrainer（gmax变异 + Thompson采样）.

    C方案: _effective_count 只计 reward≠0 的样本，激活与训练均使用有效样本
    D方案: persist_path 指定 JSONL 落盘路径，load_from_disk 启动加载
    """

    def __init__(self, max_samples: int = 10000, persist_path: str | Path | None = None):
        self._samples: deque = deque(maxlen=max_samples)
        self._phase3_activated = False
        # C方案: 有效样本计数（reward≠0）
        self._effective_count: int = 0
        # D方案: JSONL 持久化路径
        self._persist_path: Path | None = Path(persist_path) if persist_path else None
        # Phase 3 训练器（gmax变异 + Thompson采样 + 策略训练）
        self.trainer: ShadowRLTrainer = ShadowRLTrainer()

    def record(
        self,
        symbol: str,
        state: dict[str, Any],
        action: str,
        reward: float,
        next_state: dict[str, Any] | None = None,
    ) -> None:
        """记录一条 (s, a, R, s') 样本，并检查是否触发Phase3自动激活.

        C方案: reward≠0 的样本计入 _effective_count，激活阈值只看有效样本
        D方案: 若 persist_path 已设置，追加写入 JSONL（FAIL-OPEN）
        """
        _reward = float(reward) if reward is not None and not (isinstance(reward, float) and (reward != reward)) else 0.0
        sample = {
            "symbol": symbol,
            "state": dict(state) if state else {},
            "action": action,
            "reward": _reward,
            "next_state": dict(next_state) if next_state else {},
        }
        self._samples.append(sample)

        # C方案: 有效样本计数（reward≠0）
        if _reward != 0.0:
            self._effective_count += 1

        # HC-AGI-01: 有效样本≥2000自动激活Phase3（非PR评审）
        if not self._phase3_activated and self._effective_count >= self.trainer.MIN_SAMPLES:
            from dreambuddy_evolution.agi_config import is_enabled
            if is_enabled("enable_shadow_rl_phase3"):
                self.trainer.maybe_activate(self._effective_count)
                self._phase3_activated = True
                # C方案: 训练只传有效样本（reward≠0），防 baseline 被 0 污染
                effective_samples = [s for s in self._samples if s["reward"] != 0.0]
                try:
                    self.trainer.train_policy(effective_samples)
                except Exception as e:
                    logger.warning("[FO] ShadowRL train_policy crash(FAIL-OPEN): %s", e)

        # D方案: JSONL 落盘（FAIL-OPEN，不阻断热路径）
        if self._persist_path:
            try:
                self._persist_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._persist_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(sample, default=str, ensure_ascii=False) + "\n")
            except Exception as e:
                logger.debug("[FO] shadow_rl persist crash: %s", e)

    def sample_count(self) -> int:
        """总样本数（含 reward=0 占位样本）。保持原语义，兼容前端展示。"""
        return len(self._samples)

    def effective_sample_count(self) -> int:
        """C方案: 有效样本数（reward≠0）。激活阈值与训练数据量的真实指标。"""
        return self._effective_count

    def get_stats(self) -> dict[str, Any]:
        """计算 Sharpe + 样本统计。C方案: 新增 effective_sample_count 字段."""
        if not self._samples:
            return {"sharpe": 0.0, "sample_count": 0, "effective_sample_count": 0,
                    "mean_reward": 0.0, "std_reward": 0.0}
        rewards = np.array([s["reward"] for s in self._samples], dtype=np.float64)
        mean_r = float(np.mean(rewards))
        std_r = float(np.std(rewards, ddof=1)) if len(rewards) > 1 else 0.0
        sharpe = mean_r / (std_r + 1e-9) if std_r > 0 else 0.0
        return {
            "sharpe": round(sharpe, 6),
            "sample_count": len(self._samples),
            "effective_sample_count": self._effective_count,
            "mean_reward": round(mean_r, 6),
            "std_reward": round(std_r, 6),
        }

    def is_phase3_activated(self) -> bool:
        return self._phase3_activated

    def activate_phase3(self) -> None:
        """手动激活Phase3（同时激活内部trainer）."""
        self._phase3_activated = True
        self.trainer.maybe_activate(self.trainer.MIN_SAMPLES)

    def load_from_disk(self) -> None:
        """D方案: 启动时加载历史样本到 deque。只加载最后 max_samples 行。

        - 落盘文件保留全量历史（审计用途）
        - load 只取尾部 maxlen 行入 deque，deque maxlen 自然截断最旧
        - effective_count 同步重建
        """
        if not self._persist_path or not self._persist_path.exists():
            return
        try:
            lines = self._persist_path.read_text(encoding="utf-8").splitlines()
            maxlen = self._samples.maxlen
            tail = lines[-maxlen:] if maxlen else lines
            loaded = 0
            for line in tail:
                try:
                    sample = json.loads(line)
                    self._samples.append(sample)
                    if float(sample.get("reward", 0.0)) != 0.0:
                        self._effective_count += 1
                    loaded += 1
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
            logger.info("[ShadowRL] 从磁盘加载 %d 条样本（有效 %d）",
                        loaded, self._effective_count)
            # 加载后若有效样本已达阈值，同步激活状态（不触发训练，训练由实盘事件驱动）
            if not self._phase3_activated and self._effective_count >= self.trainer.MIN_SAMPLES:
                self.trainer.maybe_activate(self._effective_count)
                self._phase3_activated = True
                logger.info("[ShadowRL] 加载后有效样本 %d >= %d，Phase3 已激活",
                            self._effective_count, self.trainer.MIN_SAMPLES)
        except Exception as e:
            logger.warning("[FO] shadow_rl load_from_disk crash: %s", e)
