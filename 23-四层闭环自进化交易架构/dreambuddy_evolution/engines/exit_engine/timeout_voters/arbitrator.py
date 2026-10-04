"""TimeoutVoteArbitrator — 软投票仲裁层 + 贝叶斯权重持久化

四方案各出一票（force_close/hold/adjust_sl_tp），按历史胜率加权；
冷启动期 4H 均等权重 0.25；贝叶斯升级到 ≥30 样本后启用真实胜率权重。

仲裁规则（用户确认 2026-09-15）：
  - ≥2 票同向 force_close + 加权胜率 > 0.5 → force_close
  - 否则取最高置信的 hold/adjust_sl_tp
  - 四 voter 全 None → 返回 None（落回后续规则3b/4/5/6）

FAIL-OPEN：权重加载异常 → 均等权重 0.25；持久化异常 → 跳过不阻塞
"""
from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from dreambuddy_evolution.engines.exit_engine.exit_decision import ExitDecision
from dreambuddy_evolution.engines.exit_engine.timeout_voters.base_voter import (
    TimeoutVoter,
    VoteTicket,
)
from dreambuddy_evolution.engines.exit_engine.timeout_voters.voters_a_d import (
    ATRStandardVoter_B,
    MurphyDecayVoter_D,
    VCPVoter_A,
    WyckoffSupportVoter_C,
)

logger = logging.getLogger(__name__)


class TimeoutVoteArbitrator:
    """软投票仲裁层

    被 EvolutionExitEngine._check_timeout_soft_vote() 调用，取代原规则3a 固定阈值强平。

    冷启动期设计（复用 BCRM_REDUCE_COOLDOWN_SEC 同源，4H）：
      - 首次 arbitrate() 调用时间戳记为 _cold_start_ts
      - 4H 内四权重均等 0.25
      - 4H 后若某 voter 样本数 ≥30 触发贝叶斯升级

    贝叶斯升级路径：
      冷启动期(0-4H)           → 均等权重 0.25 × 4
      样本积累期(4H-30样本/voter) → 均等权重 0.25 × 4（但开始 record_outcome）
      贝叶斯升级(≥30样本/voter)  → 真实胜率权重，归一化到四票和=1.0
    """

    # 冷启动期 4H（复用 BCRM_REDUCE_COOLDOWN_SEC 同源设计）
    COLD_START_SEC: int = 4 * 3600
    # 贝叶斯升级阈值 ≥30 样本/voter
    BAYESIAN_MIN_SAMPLES: int = 30
    # 冷启动均等权重
    COLD_START_WEIGHT: float = 0.25
    # 仲裁规则阈值
    ARBITRATION_FORCE_CLOSE_VOTES: int = 2  # ≥2 票
    ARBITRATION_WEIGHTED_WIN_RATE: float = 0.5  # 加权胜率 > 0.5

    def __init__(
        self,
        persist_path: Optional[Path] = None,
        log_fn: Optional[Callable[[str, str], None]] = None,
    ):
        """
        Args:
            persist_path: JSONL 持久化路径（None=不持久化）
            log_fn: 日志回调 fn(msg, level)
        """
        # 四 voter 实例
        self._voters: List[TimeoutVoter] = [
            VCPVoter_A(),
            ATRStandardVoter_B(),
            WyckoffSupportVoter_C(),
            MurphyDecayVoter_D(),
        ]
        self._voter_map: Dict[str, TimeoutVoter] = {v.voter_id: v for v in self._voters}

        # 权重存储 voter_id → weight
        self._weight_store: Dict[str, float] = {v.voter_id: self.COLD_START_WEIGHT for v in self._voters}
        # 样本存储 voter_id → list[(was_correct: bool, ...)]
        self._sample_store: Dict[str, List[dict]] = defaultdict(list)
        # 冷启动时间戳（首次 arbitrate 调用）
        self._cold_start_ts: float = 0.0

        self._persist_path: Optional[Path] = persist_path
        self._log_fn = log_fn or (lambda msg, level="INFO": None)

        # 启动时从磁盘加载历史样本
        if self._persist_path:
            self.load_from_disk()

    def arbitrate(self, ctx: Dict[str, Any]) -> Optional[ExitDecision]:
        """主入口：收集四票 → 加权 → 仲裁 → 返回 ExitDecision 或 None

        Returns:
            ExitDecision 或 None（None=落回后续规则3b/4/5/6）

        FAIL-OPEN：四 voter 全 None → 返回 None
        """
        try:
            # 首次调用记录冷启动时间戳
            if self._cold_start_ts == 0.0:
                self._cold_start_ts = time.time()

            # 1. 收集四票（各自 FAIL-OPEN）
            tickets: List[VoteTicket] = []
            for voter in self._voters:
                ticket = voter.evaluate(ctx)
                if ticket is not None:
                    tickets.append(ticket)

            # 四 voter 全 None → 返回 None（落回后续规则）
            if not tickets:
                self._log(
                    "[SoftVote] 四 voter 全 FAIL-OPEN → 返回 None，落回后续规则",
                    "DEBUG",
                )
                return None

            # 2. 加载权重
            weights = self._load_weights()

            # 3. 仲裁
            return self._arbitrate(tickets, weights)
        except Exception as exc:
            self._log(
                f"[SoftVote] arbitrate crash (FAIL-OPEN): {exc}",
                "WARN",
            )
            return None

    def _arbitrate(
        self, tickets: List[VoteTicket], weights: Dict[str, float]
    ) -> Optional[ExitDecision]:
        """加权仲裁

        规则：
          - ≥2 票 force_close + 加权胜率>0.5 → force_close
          - 否则取最高置信的 hold/adjust_sl_tp
        """
        # 按动作分组
        force_close_tickets = [t for t in tickets if t.action == "force_close"]
        hold_tickets = [t for t in tickets if t.action == "hold"]
        adjust_tickets = [t for t in tickets if t.action == "adjust_sl_tp"]

        # 计算 force_close 加权胜率
        total_weight = sum(weights.values()) or 1.0
        force_close_weight = sum(
            weights.get(t.voter_id, 0.0) for t in force_close_tickets
        )
        weighted_win_rate = force_close_weight / total_weight

        # ≥2 票 force_close + 加权胜率>0.5 → force_close
        if (
            len(force_close_tickets) >= self.ARBITRATION_FORCE_CLOSE_VOTES
            and weighted_win_rate > self.ARBITRATION_WEIGHTED_WIN_RATE
        ):
            # 取 force_close 中最高置信者
            best = max(force_close_tickets, key=lambda t: t.confidence)
            reason_parts = [f"soft_vote:force_close_{len(force_close_tickets)}votes_wrate_{weighted_win_rate:.2f}"]
            reason_parts.append(best.reason)
            return ExitDecision(
                action="force_close",
                reason="|".join(reason_parts),
                confidence=best.confidence,
            )

        # 否则取最高置信的 hold/adjust_sl_tp
        candidates = hold_tickets + adjust_tickets
        if not candidates:
            # 无 hold/adjust_sl_tp 候选（全 force_close 但未达阈值）→ 返回 None 落回后续
            return None

        best = max(candidates, key=lambda t: t.confidence)
        # 如果是 adjust_sl_tp，传播 sl_px
        sl_px = best.sl_px if best.action == "adjust_sl_tp" else 0.0
        tp_px = best.tp_px if best.action == "adjust_sl_tp" else 0.0

        reason_parts = [
            f"soft_vote:{best.action}_conf_{best.confidence:.2f}",
            f"force_close_votes_{len(force_close_tickets)}_wrate_{weighted_win_rate:.2f}",
            best.reason,
        ]
        return ExitDecision(
            action=best.action,
            reason="|".join(reason_parts),
            sl_px=sl_px,
            tp_px=tp_px,
            confidence=best.confidence,
        )

    def record_outcome(
        self,
        voter_id: str,
        was_correct: bool,
        symbol: str,
        action: str,
    ) -> None:
        """交易结算后回填结果，≥30 样本触发贝叶斯升级

        Args:
            voter_id: "A"/"B"/"C"/"D"
            was_correct: 该 voter 的投票是否正确（基于后续价格走势判断）
            symbol: 交易标的
            action: 该 voter 投票的 action

        FAIL-OPEN：持久化异常 → 跳过不阻塞
        """
        try:
            sample = {
                "voter_id": voter_id,
                "was_correct": bool(was_correct),
                "symbol": symbol,
                "action": action,
                "timestamp": time.time(),
            }
            self._sample_store[voter_id].append(sample)

            # 持久化（FAIL-OPEN）
            if self._persist_path:
                try:
                    self._persist_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(self._persist_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(sample, ensure_ascii=False) + "\n")
                except Exception as e:
                    logger.debug("[FO] soft_vote persist crash: %s", e)

            # 检查贝叶斯升级
            self._maybe_upgrade_weights()
        except Exception as e:
            logger.debug("[FO] soft_vote record_outcome crash: %s", e)

    def _maybe_upgrade_weights(self) -> None:
        """检查是否所有 voter 都达 ≥30 样本，触发权重重算"""
        try:
            # 检查冷启动期是否已过
            if self._cold_start_ts > 0:
                elapsed = time.time() - self._cold_start_ts
                if elapsed < self.COLD_START_SEC:
                    return  # 仍在冷启动期

            # 检查是否所有 voter 都达阈值
            all_ready = all(
                len(self._sample_store.get(v.voter_id, [])) >= self.BAYESIAN_MIN_SAMPLES
                for v in self._voters
            )
            if not all_ready:
                # 部分达阈值也触发部分升级（按各自样本量）
                for v in self._voters:
                    if len(self._sample_store.get(v.voter_id, [])) >= self.BAYESIAN_MIN_SAMPLES:
                        # 单 voter 达阈值，重算权重
                        self._recalculate_weights()
                        return
                return

            # 全部达阈值，重算权重
            self._recalculate_weights()
        except Exception as e:
            logger.debug("[FO] soft_vote upgrade check crash: %s", e)

    def _recalculate_weights(self) -> None:
        """根据真实胜率重算权重

        权重 = voter_win_rate / sum(all_voter_win_rates)，归一化到四票和=1.0
        """
        try:
            win_rates: Dict[str, float] = {}
            for v in self._voters:
                samples = self._sample_store.get(v.voter_id, [])
                if not samples:
                    win_rates[v.voter_id] = 0.0
                    continue
                wins = sum(1 for s in samples if s.get("was_correct", False))
                win_rates[v.voter_id] = wins / len(samples) if samples else 0.0

            total_win_rate = sum(win_rates.values())
            if total_win_rate <= 0:
                # 全部胜率为0，回退均等
                for v in self._voters:
                    self._weight_store[v.voter_id] = self.COLD_START_WEIGHT
                return

            # 归一化
            for v in self._voters:
                self._weight_store[v.voter_id] = win_rates[v.voter_id] / total_win_rate

            self._log(
                f"[SoftVote] 贝叶斯权重升级: {self._weight_store}",
                "INFO",
            )
        except Exception as e:
            logger.debug("[FO] soft_vote weight recalc crash: %s", e)

    def _load_weights(self) -> Dict[str, float]:
        """加载权重：冷启动均等 0.25 / 贝叶斯真实胜率

        FAIL-OPEN：任何异常 → 均等权重
        """
        try:
            # 检查冷启动期
            if self._cold_start_ts > 0:
                elapsed = time.time() - self._cold_start_ts
                if elapsed < self.COLD_START_SEC:
                    # 冷启动期 → 均等
                    return {v.voter_id: self.COLD_START_WEIGHT for v in self._voters}

            # 检查是否有足够样本
            has_samples = any(
                len(self._sample_store.get(v.voter_id, [])) >= self.BAYESIAN_MIN_SAMPLES
                for v in self._voters
            )
            if not has_samples:
                # 无足够样本 → 均等
                return {v.voter_id: self.COLD_START_WEIGHT for v in self._voters}

            # 有样本 → 返回真实权重
            return dict(self._weight_store)
        except Exception:
            return {v.voter_id: self.COLD_START_WEIGHT for v in self._voters}

    def load_from_disk(self) -> None:
        """启动时从磁盘加载历史样本

        FAIL-OPEN：任何异常 → 跳过，使用默认均等权重
        """
        if not self._persist_path or not self._persist_path.exists():
            return
        try:
            lines = self._persist_path.read_text(encoding="utf-8").splitlines()
            loaded = 0
            for line in lines:
                try:
                    sample = json.loads(line)
                    voter_id = sample.get("voter_id", "")
                    if voter_id:
                        self._sample_store[voter_id].append(sample)
                        loaded += 1
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
            self._log(
                f"[SoftVote] 从磁盘加载 {loaded} 条样本",
                "INFO",
            )
            # 加载后检查是否触发贝叶斯升级
            self._maybe_upgrade_weights()
        except Exception as e:
            logger.warning("[FO] soft_vote load_from_disk crash: %s", e)

    def _log(self, msg: str, level: str = "INFO") -> None:
        try:
            self._log_fn(msg, level)
        except Exception:
            pass
