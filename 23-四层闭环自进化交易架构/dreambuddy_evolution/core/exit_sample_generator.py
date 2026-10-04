"""离场 RL 样本生成器 — 从历史交易 backtest 扩充 (s,a,R,s') 样本

从 all_trades.jsonl 的 16 笔真实交易出发，通过：
  1. 价格轨迹模拟（entry→exit 线性插值 + 布朗运动噪声）
  2. 市场参数变异（ATR/RSI/ESS/CS/vol_ratio 在合理范围内扰动）
  3. 反事实场景（提前出场 / 延迟出场 / 不同 tier）
  4. 动作标签映射（exit_reason → action index）

生成 2000+ 条 MDP 样本，供 CQLTrainer 离线预训练。

State (8维): [upl_ratio, position_age_min, atr_pct, RSI, ESS, CS, vol_ratio, tier_index]
Action (5个): {0:hold, 1:adjust_sl_tp, 2:trailing, 3:force_close, 4:partial_close}
Reward: ExitRewardCalculator 三组件加权 R_total
"""
from __future__ import annotations

import json
import logging
import math
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# 动作枚举（与 exit_rl_policy.py 一致）
ACTION_NAMES = ["hold", "adjust_sl_tp", "trailing", "force_close", "partial_close"]
ACTION_TO_IDX = {name: i for i, name in enumerate(ACTION_NAMES)}

# exit_reason → action 映射
EXIT_REASON_TO_ACTION = {
    "signal_reverse": "force_close",
    "timeout_profit_switch": "force_close",
    "timeout_loss": "hold",  # 超时亏损 → 继续持有（优化3规则）
    "tp_hit": "trailing",
    "sl_hit": "force_close",
    "trailing_hit": "trailing",
    "partial_tp": "partial_close",
    "external_signal_reduce": "partial_close",
    "manual_close": "force_close",
    "okx_algo": "force_close",
}

# tier → tier_index 映射
TIER_TO_IDX = {"probe": 0, "standard": 1, "trend": 2}


class ExitSampleGenerator:
    """从历史交易扩充 RL 离场样本"""

    # 每笔交易生成的轨迹步数
    STEPS_PER_TRADE = 20
    # 每笔交易的反事实变体数
    VARIANTS_PER_TRADE = 7
    # 价格布朗运动波动率
    PRICE_NOISE_SCALE = 0.003
    # ATR 范围
    ATR_RANGE = (0.005, 0.04)
    # RSI 范围
    RSI_RANGE = (20.0, 80.0)
    # ESS 范围
    ESS_RANGE = (0.2, 0.9)
    # CS 范围
    CS_RANGE = (-0.5, 0.9)
    # vol_ratio 范围
    VOL_RATIO_RANGE = (0.3, 2.5)

    def __init__(
        self,
        trades_path: str = "",
        output_path: str = "",
        target_samples: int = 2000,
        seed: int = 42,
        trades_paths: List[str] | None = None,
    ):
        self.trades_path = trades_path
        self.trades_paths = trades_paths  # 多源文件路径列表（P1b）
        self.output_path = output_path
        self.target_samples = target_samples
        self._rng = random.Random(seed)
        self._np_rng = np.random.RandomState(seed)

    def load_trades(self) -> List[Dict[str, Any]]:
        """加载历史交易"""
        trades = []
        with open(self.trades_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    trades.append(json.loads(line))
        logger.info("加载 %d 笔历史交易", len(trades))
        return trades

    def _load_trades_multi(self) -> List[Dict[str, Any]]:
        """P1b: 从多个源文件加载交易，按 (coin, entry_time, exit_time, direction) 去重。

        每条交易标记 meta_source = "real" | "backtest"（基于 source_system 字段）。
        FAIL-OPEN: 单文件加载失败 → 跳过该文件，继续加载其他文件。
        """
        if not self.trades_paths:
            return self.load_trades()

        all_trades: List[Dict[str, Any]] = []
        seen: set = set()
        for path in self.trades_paths:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            trade = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        # 去重键
                        key = (
                            str(trade.get("coin", "")),
                            str(trade.get("entry_time", "")),
                            str(trade.get("exit_time", "")),
                            str(trade.get("direction", "")),
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        # 标记来源
                        src = trade.get("source_system", "")
                        trade["meta_source"] = "backtest" if src == "backtest" else "real"
                        all_trades.append(trade)
                logger.info("加载 %s: %d 笔", path, len([t for t in all_trades if t.get("meta_source") in ("real", "backtest")]))
            except Exception as e:
                logger.warning("[FO] load trades fail %s: %s", path, e)
                continue
        logger.info("多源合并: 共 %d 笔交易", len(all_trades))
        return all_trades

    def _simulate_price_path(
        self, entry_price: float, exit_price: float, n_steps: int, noise_scale: float = 0.003
    ) -> np.ndarray:
        """模拟 entry→exit 价格轨迹（线性插值 + 布朗运动）"""
        # 线性插值
        linear = np.linspace(entry_price, exit_price, n_steps)
        # 布朗运动噪声
        noise = np.cumsum(self._np_rng.normal(0, entry_price * noise_scale, n_steps))
        # 去除漂移（使噪声均值为 0）
        noise = noise - np.linspace(noise[0], noise[-1], n_steps)
        return linear + noise * 0.3  # 噪声权重 30%

    def _compute_state(
        self,
        upl_ratio: float,
        position_age_min: float,
        atr_pct: float,
        rsi: float,
        ess: float,
        cs: float,
        vol_ratio: float,
        tier: str,
    ) -> np.ndarray:
        """构造 8 维状态向量"""
        tier_idx = float(TIER_TO_IDX.get(tier, 1))
        return np.array(
            [upl_ratio, position_age_min, atr_pct, rsi, ess, cs, vol_ratio, tier_idx],
            dtype=np.float32,
        )

    def _compute_reward(
        self, upl_ratio: float, cs: float, sl_in_range: bool,
        tp_pct_target: float = 0.06, sl_pct_target: float = 0.03,
    ) -> float:
        """三组件奖励 R_total = 0.4*R_trend + 0.3*R_risk + 0.3*R_pnl"""
        # R_trend
        if cs >= 0.7:
            r_trend = 1.0
        elif cs <= -0.2:
            r_trend = -1.0
        else:
            r_trend = 0.0
        # R_risk
        r_risk = 0.5 if sl_in_range else -0.5
        # R_pnl
        if upl_ratio >= tp_pct_target:
            r_pnl = 1.0
        elif upl_ratio <= -sl_pct_target:
            r_pnl = -1.0
        else:
            r_pnl = upl_ratio / tp_pct_target
        return 0.4 * r_trend + 0.3 * r_risk + 0.3 * r_pnl

    def _determine_action(
        self, step: int, total_steps: int, exit_reason: str, upl_ratio: float,
        position_age_min: float, tier: str,
    ) -> str:
        """根据轨迹位置和交易信息确定动作标签"""
        is_last = step >= total_steps - 1
        if is_last:
            # 终端动作：根据 exit_reason 映射
            action_name = EXIT_REASON_TO_ACTION.get(exit_reason, "force_close")
            return action_name

        # 中间步：根据盈亏和时间决定动作
        # 亏损超时 → hold（优化3：亏损继续持有）
        if position_age_min > 29 * 60 and upl_ratio < -0.02:
            return "hold"
        # 盈利 >1R → partial_close
        if upl_ratio >= 0.03:
            if self._rng.random() < 0.3:
                return "partial_close"
        # 盈利 >3% 且未到终点 → trailing
        if upl_ratio >= 0.03 and tier == "trend":
            if self._rng.random() < 0.2:
                return "trailing"
        # 盈利 >1% → adjust_sl_tp（保本位）
        if upl_ratio >= 0.01 and self._rng.random() < 0.15:
            return "adjust_sl_tp"
        # 默认 hold
        return "hold"

    def _generate_trajectory(
        self, trade: Dict[str, Any], variant_idx: int,
    ) -> List[Dict[str, Any]]:
        """从单笔交易生成一条轨迹的多个 MDP 样本"""
        samples: List[Dict[str, Any]] = []
        entry_price = float(trade.get("entry_price", 0) or 0)
        exit_price = float(trade.get("exit_price", 0) or entry_price)
        if entry_price <= 0:
            return samples

        exit_reason = str(trade.get("exit_reason", "manual_close"))
        pnl_pct = float(trade.get("pnl_pct", 0) or 0)
        confidence = float(trade.get("confidence", 0.5) or 0.5)

        # 反事实变体：修改 exit_price 和 exit_reason
        n_steps = self.STEPS_PER_TRADE
        if variant_idx == 0:
            # 原始轨迹
            final_price = exit_price
            final_reason = exit_reason
        elif variant_idx == 1:
            # 提前止盈（exit_price 提高 2%）
            direction = 1 if exit_price >= entry_price else -1
            final_price = entry_price * (1 + direction * abs(pnl_pct) * 1.2)
            final_reason = "tp_hit"
        elif variant_idx == 2:
            # 提前止损（亏损 3%）
            direction = 1 if exit_price >= entry_price else -1
            final_price = entry_price * (1 - direction * 0.03)
            final_reason = "sl_hit"
        elif variant_idx == 3:
            # 延迟出场（价格继续有利方向 1%）
            direction = 1 if exit_price >= entry_price else -1
            final_price = exit_price * (1 + direction * 0.01)
            final_reason = "trailing_hit"
        elif variant_idx == 4:
            # 超时亏损场景
            final_price = entry_price * (1 - 0.015)
            final_reason = "timeout_loss"
        elif variant_idx == 5:
            # 信号反转场景
            direction = 1 if exit_price >= entry_price else -1
            final_price = entry_price * (1 - direction * 0.02)
            final_reason = "signal_reverse"
        else:
            # 高波动场景（trailing 触发）
            direction = 1 if exit_price >= entry_price else -1
            final_price = entry_price * (1 + direction * 0.05)
            final_reason = "trailing_hit"

        # 模拟价格路径
        noise_scale = self.PRICE_NOISE_SCALE * (1.0 + variant_idx * 0.1)
        price_path = self._simulate_price_path(entry_price, final_price, n_steps, noise_scale)

        # 市场参数基线（从 trade 的 market_snapshot 读取或用默认值）
        snap = trade.get("market_snapshot", {}) or {}
        base_atr = float(snap.get("volatility", 0.02) or 0.02)
        base_vol_ratio = 1.0

        # tier：优先使用 trade 自带的 tier 字段，否则随机选择（权重：standard 60%, probe 20%, trend 20%）
        tier = trade.get("tier") or self._rng.choices(
            ["probe", "standard", "trend"], weights=[2, 6, 2]
        )[0]

        # 持仓时长（从交易时间计算）
        entry_time_str = trade.get("entry_time", "")
        exit_time_str = trade.get("exit_time", "")
        try:
            et = entry_time_str.replace("Z", "+00:00")
            xt = exit_time_str.replace("Z", "+00:00")
            entry_dt = datetime.fromisoformat(et)
            exit_dt = datetime.fromisoformat(xt)
            total_age_min = max(60.0, (exit_dt - entry_dt).total_seconds() / 60.0)
        except Exception:
            total_age_min = 600.0  # 默认 10h

        # 生成轨迹样本
        for step in range(n_steps):
            current_price = float(price_path[step])
            next_price = float(price_path[min(step + 1, n_steps - 1)])

            # 计算盈亏
            direction = trade.get("direction", "long")
            if direction == "long":
                upl_ratio = (current_price - entry_price) / entry_price
                next_upl_ratio = (next_price - entry_price) / entry_price
            else:
                upl_ratio = (entry_price - current_price) / entry_price
                next_upl_ratio = (entry_price - next_price) / entry_price

            position_age_min = total_age_min * (step + 1) / n_steps
            next_age_min = total_age_min * (step + 2) / n_steps

            # 市场参数扰动
            atr_pct = float(
                self._np_rng.uniform(
                    max(self.ATR_RANGE[0], base_atr * 0.5),
                    min(self.ATR_RANGE[1], base_atr * 2.0),
                )
            )
            rsi = float(self._np_rng.uniform(*self.RSI_RANGE))
            ess = float(self._np_rng.uniform(*self.ESS_RANGE))
            cs = float(self._np_rng.uniform(*self.CS_RANGE))
            vol_ratio = float(self._np_rng.uniform(*self.VOL_RATIO_RANGE))

            # 构造状态
            state = self._compute_state(
                upl_ratio, position_age_min, atr_pct, rsi, ess, cs, vol_ratio, tier
            )
            next_state = self._compute_state(
                next_upl_ratio, next_age_min, atr_pct, rsi, ess, cs, vol_ratio, tier
            )

            # 确定动作
            action_name = self._determine_action(
                step, n_steps, final_reason, upl_ratio, position_age_min, tier
            )
            action_idx = ACTION_TO_IDX.get(action_name, 0)

            # 奖励
            sl_in_range = abs(upl_ratio) <= 0.06
            tp_target = {"probe": 0.10, "standard": 0.06, "trend": 0.04}.get(tier, 0.06)
            sl_target = {"probe": 0.05, "standard": 0.03, "trend": 0.02}.get(tier, 0.03)
            reward = self._compute_reward(
                upl_ratio, cs, sl_in_range, tp_target, sl_target
            )

            # 终端样本 reward 包含实际 pnl
            is_done = step >= n_steps - 1
            if is_done:
                reward += pnl_pct * 5.0  # 终端奖励加权

            samples.append({
                "state": state.tolist(),
                "action": action_idx,
                "reward": round(reward, 6),
                "next_state": next_state.tolist(),
                "done": is_done,
                "meta": {
                    "trade_id": trade.get("trade_id", ""),
                    "variant": variant_idx,
                    "step": step,
                    "tier": tier,
                    "upl_ratio": round(upl_ratio, 6),
                    "action_name": action_name,
                },
            })

        return samples

    def generate(self) -> int:
        """生成扩充样本并写入文件

        P1b: 支持多源交易（trades_paths）、meta_source 标记、sample_weight（real=1.0/backtest=0.3）、
        大样本量时流式写入避免内存爆炸。
        """
        trades = self._load_trades_multi() if self.trades_paths else self.load_trades()
        if not trades:
            logger.error("无历史交易可生成样本")
            return 0

        all_samples: List[Dict[str, Any]] = []
        n_variants = self.VARIANTS_PER_TRADE
        use_streaming = self.target_samples > 100_000

        output = Path(self.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        written = 0
        action_dist = {name: 0 for name in ACTION_NAMES}

        def _flush(samples_buf: List[Dict[str, Any]]) -> None:
            nonlocal written
            with open(output, "a", encoding="utf-8") as f:
                for s in samples_buf:
                    f.write(json.dumps(s, ensure_ascii=False) + "\n")
                    written += 1
            samples_buf.clear()

        # 流式模式：先清空输出文件
        if use_streaming:
            open(output, "w").close()
            buf: List[Dict[str, Any]] = []

        for trade in trades:
            meta_source = trade.get("meta_source", "real")
            sample_weight = 0.3 if meta_source == "backtest" else 1.0
            for v in range(n_variants):
                traj = self._generate_trajectory(trade, v)
                for s in traj:
                    s["meta"]["meta_source"] = meta_source
                    s["meta"]["sample_weight"] = sample_weight
                    action_dist[ACTION_NAMES[s["action"]]] += 1
                    if use_streaming:
                        buf.append(s)
                        if len(buf) >= 10000:
                            _flush(buf)
                        if written >= self.target_samples:
                            break
                    else:
                        all_samples.append(s)
                if use_streaming and written >= self.target_samples:
                    break
            if use_streaming and written >= self.target_samples:
                break

        if use_streaming:
            if buf:
                _flush(buf)
            count = written
        else:
            # 不足 target 时补充
            while len(all_samples) < self.target_samples:
                trade = self._rng.choice(trades)
                v = self._rng.randint(0, n_variants - 1)
                traj = self._generate_trajectory(trade, v)
                meta_source = trade.get("meta_source", "real")
                sample_weight = 0.3 if meta_source == "backtest" else 1.0
                for s in traj[:5]:
                    s["meta"]["meta_source"] = meta_source
                    s["meta"]["sample_weight"] = sample_weight
                    action_dist[ACTION_NAMES[s["action"]]] += 1
                    all_samples.append(s)

            if len(all_samples) > self.target_samples:
                all_samples = all_samples[: self.target_samples]

            with open(output, "w", encoding="utf-8") as f:
                for s in all_samples:
                    f.write(json.dumps(s, ensure_ascii=False) + "\n")
            count = len(all_samples)

        logger.info("生成 %d 条样本 → %s", count, self.output_path)
        logger.info("动作分布: %s", action_dist)
        return count


def main():
    """CLI 入口：生成 RL 离场样本

    用法:
      python -m dreambuddy_evolution.core.exit_sample_generator [target] [trades_path]
      python -m dreambuddy_evolution.core.exit_sample_generator --trades-paths a.jsonl,b.jsonl --target 500000
    """
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
    )

    # 默认路径
    project_root = Path(__file__).resolve().parents[3]
    default_trades = str(
        project_root
        / "11-易经推理系统"
        / ".workbuddy"
        / "memory_l4"
        / "stats"
        / "all_trades.jsonl"
    )
    default_output = str(
        Path(__file__).resolve().parents[1]
        / "data"
        / "exit_rl_samples.jsonl"
    )

    parser = argparse.ArgumentParser(description="生成 RL 离场样本")
    parser.add_argument("target", nargs="?", type=int, default=2000, help="目标样本数")
    parser.add_argument("trades_path", nargs="?", type=str, default=default_trades, help="交易文件路径")
    parser.add_argument("--output", type=str, default=default_output, help="输出路径")
    parser.add_argument("--trades-paths", type=str, default=None, help="多源路径（逗号分隔）")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    args = parser.parse_args()

    trades_paths = None
    if args.trades_paths:
        trades_paths = [p.strip() for p in args.trades_paths.split(",") if p.strip()]

    gen = ExitSampleGenerator(
        trades_path=args.trades_path if not trades_paths else "",
        output_path=args.output,
        target_samples=args.target,
        seed=args.seed,
        trades_paths=trades_paths,
    )
    count = gen.generate()
    print(f"生成 {count} 条样本 → {args.output}")


if __name__ == "__main__":
    main()
