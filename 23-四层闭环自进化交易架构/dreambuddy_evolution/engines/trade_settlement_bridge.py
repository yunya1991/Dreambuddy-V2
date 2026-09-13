"""
TradeSettlementBridge (P2-S4 紧耦合流平仓反思回路)
蓝图: 四层闭环进化架构-最小阻力路径总览.md §1.7 + §1.13.6

职责:
- store_snapshot(symbol, snapshot) — JSON 持久化 pre_trade_snapshot
- retrieve_snapshot(symbol) — 检索并删除（消费后清除，防重复反思）
- _reconstruct_snapshot_from_trade(trade_rec) — 降级重建（无持久化 snapshot 时）
- on_trade_settled(trade_rec) — 平仓回调: 检索 snapshot → ReflectionEngine measure→reflect→learn→feedback

FAIL-OPEN: 所有异常 try/except，不阻断交易，crash → 返回空 ESS delta
"""
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 默认 JSON 持久化路径
_DEFAULT_SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "gene_data"
_SNAPSHOT_FILE = "evolution_snapshots.json"


class TradeSettlementBridge:
    """紧耦合流平仓反思桥接器 — 连接交易结算事件与 ReflectionEngine"""

    def __init__(self, snapshot_dir: str | None = None):
        """
        snapshot_dir: JSON 持久化目录（默认 gene_data/）
        """
        self._snapshot_dir = Path(snapshot_dir) if snapshot_dir else _DEFAULT_SNAPSHOT_DIR
        self._snapshot_path = self._snapshot_dir / _SNAPSHOT_FILE

    # ==================================================================
    # Snapshot 持久化
    # ==================================================================

    def store_snapshot(self, symbol: str, snapshot: dict[str, Any]) -> None:
        """存储 pre_trade_snapshot 到 JSON 文件（symbol 为 key）"""
        try:
            self._snapshot_dir.mkdir(parents=True, exist_ok=True)
            data = self._load_all()
            data[symbol] = snapshot
            self._save_all(data)
        except Exception as e:
            logger.warning("[FO] store_snapshot crash: %s", e)

    def retrieve_snapshot(self, symbol: str) -> dict[str, Any] | None:
        """检索 snapshot 并删除（消费后清除，防重复反思）"""
        try:
            data = self._load_all()
            snapshot = data.pop(symbol, None)
            if snapshot is not None:
                self._save_all(data)
            return snapshot
        except Exception as e:
            logger.warning("[FO] retrieve_snapshot crash: %s", e)
            return None

    def _load_all(self) -> dict[str, Any]:
        """加载全部 snapshot"""
        if not self._snapshot_path.exists():
            return {}
        try:
            text = self._snapshot_path.read_text(encoding="utf-8")
            return json.loads(text) if text.strip() else {}
        except Exception:
            return {}

    def _save_all(self, data: dict[str, Any]) -> None:
        """保存全部 snapshot"""
        self._snapshot_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    # ==================================================================
    # 降级重建
    # ==================================================================

    def _reconstruct_snapshot_from_trade(self, trade_rec: Any) -> dict[str, Any]:
        """
        从 trade_rec 重建 snapshot（降级模式，无持久化 snapshot 时使用）
        缺失 level0_dstar/ess_dir → CS 计算降级（cos 项=0 中性）
        """
        try:
            direction = str(getattr(trade_rec, "direction", "")).lower()
            pnl = float(getattr(trade_rec, "pnl", 0.0))
            outcome = "TP" if pnl >= 0 else "SL"
            return {
                "symbol": self._extract_symbol(trade_rec),
                "u_open": 0.1,
                "action": direction,
                "level0_dstar": direction,  # 降级：用建仓方向作为 d*
                "ess_dir": "",               # 缺失 → cos(ess,real)=0
                "cbr_top1_outcome": outcome, # 降级：从 pnl 推断
                "cluster_id": "",
                "ess_id": "",
                "cbr_sim": 0.5,              # 中性
            }
        except Exception as e:
            logger.warning("[FO] _reconstruct_snapshot crash: %s", e)
            return {
                "symbol": "", "u_open": 0.0, "action": "WAIT",
                "level0_dstar": "WAIT", "ess_dir": "",
                "cbr_top1_outcome": "", "cluster_id": "",
                "ess_id": "", "cbr_sim": 0.5,
            }

    # ==================================================================
    # 平仓回调入口
    # ==================================================================

    def on_trade_settled(self, trade_rec: Any) -> dict[str, Any]:
        """
        平仓回调入口: 检索 snapshot（或重建）→ ReflectionEngine measure→reflect→learn→feedback

        返回: {cs, ess_delta, gmax_mult, cluster_weight_mult, anti_pattern_flag}
        FAIL-OPEN: 任何异常 → 返回空 ESS delta
        """
        try:
            if trade_rec is None:
                logger.warning("[FO] on_trade_settled: trade_rec is None")
                return self._empty_result()

            # 1. 检索 snapshot（或降级重建）
            symbol = self._extract_symbol(trade_rec)
            snapshot = self.retrieve_snapshot(symbol)
            if snapshot is None:
                snapshot = self._reconstruct_snapshot_from_trade(trade_rec)
                logger.info("[Bridge] 无持久化 snapshot，降级重建 for %s", symbol)

            # 2. 从 trade_rec 提取 outcome
            real_direction = self._infer_real_direction(trade_rec)
            real_outcome = "TP" if float(getattr(trade_rec, "pnl", 0.0)) >= 0 else "SL"
            outcome = {"real_direction": real_direction, "real_outcome": real_outcome}

            # 3. 调用 ReflectionEngine: calculate_cs → apply_reward
            from dreambuddy_evolution.engines.reflection_engine import ReflectionEngine
            engine = ReflectionEngine()
            cs = engine.calculate_cs(snapshot, outcome)
            reward = engine.apply_reward(
                cs=cs,
                outcome=real_outcome,
                cluster_id=snapshot.get("cluster_id", ""),
                ess_id=snapshot.get("ess_id", ""),
                gmax=1.0,
            )

            return {
                "cs": round(cs, 4),
                "ess_delta": reward.get("ess_delta", 0.0),
                "gmax_mult": reward.get("gmax_mult", 1.0),
                "cluster_weight_mult": reward.get("cluster_weight_mult", 1.0),
                "anti_pattern_flag": reward.get("anti_pattern_flag", False),
            }
        except Exception as e:
            logger.warning("[FO] on_trade_settled crash: %s", e)
            return self._empty_result()

        finally:
            # Fix 1: 向 ShadowRL 记录基于真实 PnL 的 reward
            # 替代 kline_event_handler 中用 quality_score 作为 reward 的做法
            _snap = locals().get("snapshot")
            if _snap is not None:
                self._record_real_pnl_reward(trade_rec, _snap)

    def _record_real_pnl_reward(self, trade_rec: Any, snapshot: dict) -> None:
        """Fix 1: 将真实 PnL 归一化后注入 ShadowRL，使矛盾反馈基于真实交易结果。

        Fix C: 过滤异常平仓（OKX 持仓消失等），不注入虚假 PnL。

        FAIL-OPEN: 任何异常不阻断交易。
        """
        try:
            from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline
            pipe = EvolutionPipeline._instance
            if pipe is None or not hasattr(pipe, "shadow_rl"):
                return

            # Fix C: 过滤异常平仓 — exit_reason 含"持仓消失"/"position_disappeared" 或 pnl=-100 且无正常 exit
            _exit_reason = str(getattr(trade_rec, "exit_reason", "") or "").lower()
            _pnl_raw = float(getattr(trade_rec, "pnl", 0.0) or 0.0)
            if "持仓消失" in _exit_reason or "position_disappear" in _exit_reason:
                logger.debug("[FixC] 跳过异常平仓(持仓消失): %s", _exit_reason)
                return
            if _pnl_raw == -100.0 and ("消失" in _exit_reason or "disappear" in _exit_reason
                                        or not _exit_reason):
                logger.debug("[FixC] 跳过疑似异常平仓(pnl=-100): %s", _exit_reason)
                return

            import math
            _pnl_pct = float(getattr(trade_rec, "pnl_pct", 0.0) or 0.0)
            # tanh 归一化: ±2% 波动 → ±0.96, ±0.5% → ±0.24
            _reward = math.tanh(_pnl_pct / 0.02)

            _symbol = self._extract_symbol(trade_rec)
            _action = str(snapshot.get("action", "")).lower() or \
                      str(getattr(trade_rec, "direction", "")).lower() or "wait"

            pipe.shadow_rl.record(
                symbol=_symbol,
                state=snapshot,
                action=_action,
                reward=_reward,
                next_state=None,
            )
        except Exception:
            pass  # FAIL-OPEN

    # ==================================================================
    # 辅助方法
    # ==================================================================

    def _extract_symbol(self, trade_rec: Any) -> str:
        """从 trade_rec 提取 symbol（inst_id → coin）"""
        try:
            inst_id = str(getattr(trade_rec, "inst_id", "") or "")
            # BTC-USDT-SWAP → BTC
            if "-" in inst_id:
                return inst_id.split("-")[0]
            return inst_id or "UNKNOWN"
        except Exception:
            return "UNKNOWN"

    def _infer_real_direction(self, trade_rec: Any) -> str:
        """从 entry→exit 价格变化推断实际方向"""
        try:
            entry = float(getattr(trade_rec, "entry_price", 0.0))
            exit_p = float(getattr(trade_rec, "exit_price", 0.0))
            if exit_p > entry:
                return "long"
            elif exit_p < entry:
                return "short"
            return "wait"
        except Exception:
            return "wait"

    # ==================================================================
    # outcome 标签提取（Phase 3 GREEN + 入场侧 REDUCE_WEIGHT）
    # ==================================================================

    @staticmethod
    def _extract_outcome_from_reason(
        reason: str,
        okx_algo_triggered: bool = False,
        pnl: float = 0.0,
        pos_side: str = "long",
        weight_reduce_factor: float = 1.0,
    ) -> str:
        """从平仓 reason 字符串提取 outcome 标签

        覆盖：
        - evolution_sltp + OKX algo → TP_algo / SL_algo
        - evolution_exit:adjust_sl_tp → ADJUST
        - evolution_exit:trailing → TRAILING
        - evolution_exit:force_close:signal_reverse → FORCE_REVERSE
        - evolution_exit:force_close:timeout → FORCE_TIMEOUT
        - weight_reduce_factor < 1.0 + pnl 正 → REDUCE_WEIGHT_PREMATURE
        - weight_reduce_factor < 1.0 + pnl 负 → REDUCE_WEIGHT_CORRECT
        - fallback: pnl≥0 → TP, pnl<0 → SL
        """
        reason_lower = str(reason).lower()

        # 1. 入场侧 REDUCE_WEIGHT 优先判定（weight_reduce_factor < 1.0 表示被 BCRM 软权重削减）
        if weight_reduce_factor < 1.0:
            if float(pnl) >= 0:
                return "REDUCE_WEIGHT_PREMATURE"
            else:
                return "REDUCE_WEIGHT_CORRECT"

        # 2. OKX algo 触达 → TP_algo / SL_algo
        if okx_algo_triggered and "evolution_sltp" in reason_lower:
            return "TP_algo" if float(pnl) >= 0 else "SL_algo"

        # 3. evolution_exit 离场动作分类
        if "force_close" in reason_lower:
            if "signal_reverse" in reason_lower:
                return "FORCE_REVERSE"
            if "timeout" in reason_lower:
                return "FORCE_TIMEOUT"
            # 其他 force_close（含 okx_algo_triggered 但非 evolution_sltp）
            if okx_algo_triggered:
                return "TP_algo" if float(pnl) >= 0 else "SL_algo"
            return "FORCE_REVERSE"  # 默认归入信号反转
        if "external_signal_reduce" in reason_lower:
            return "PARTIAL_REDUCE"
        if "trailing" in reason_lower:
            return "TRAILING"
        if "adjust_sl_tp" in reason_lower:
            return "ADJUST"

        # 4. fallback: 按 pnl 正负推断
        return "TP" if float(pnl) >= 0 else "SL"

    @staticmethod
    def _empty_result() -> dict[str, Any]:
        """FAIL-OPEN 空结果"""
        return {
            "cs": 0.0,
            "ess_delta": 0.0,
            "gmax_mult": 1.0,
            "cluster_weight_mult": 1.0,
            "anti_pattern_flag": False,
        }
