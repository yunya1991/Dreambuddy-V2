"""Phase C 渐进上线管理器 —— α blend 的渐进式上线

Spec: 2026-08-19-morph-cycle-dynamic-correction-design.md §五 Phase C
Plan: 2026-08-20-phase-c-alpha-blend-plan.md §T_C6

设计原则：
  • α 从 0 渐进提升至 target（ALPHA_BLEND_MAX=0.5）
  • 步长 ALPHA_BLEND_STEP=0.1
  • promote 提升 α；rollback 降低 α（不下穿 0）
  • 状态持久化到 JSON 文件，重启可恢复
  • α 达到 target 后 is_complete=True

用法：
    mgr = RolloutManager(state_path=Path("rollout.json"))
    mgr.load()
    if report.passed:
        mgr.promote()
    else:
        mgr.rollback()
    mgr.save()
    status = mgr.get_status()
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# 确保可导入 bcrm2
_THIS = Path(__file__).resolve()
_MEMORY_L4 = _THIS.parent.parent.parent
if str(_MEMORY_L4) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_MEMORY_L4))

from bcrm2.parameter_mapper import ALPHA_BLEND_MAX, ALPHA_BLEND_STEP

logger = logging.getLogger(__name__)


class RolloutManager:
    """α blend 渐进上线管理器。

    管理从 α=0 到 α=target 的渐进上线过程。
    每次评估周期根据 AB 影子对比结果调用 promote/rollback。
    """

    def __init__(
        self,
        state_path: Optional[Path] = None,
        target_alpha: float = ALPHA_BLEND_MAX,
        step: float = ALPHA_BLEND_STEP,
    ):
        self.state_path = state_path or Path("rollout_state.json")
        self.target_alpha = float(target_alpha)
        self.step = float(step)
        self.current_alpha: float = 0.0
        self.history: List[Dict[str, Any]] = []
        self.is_complete: bool = False
        # ── H3-FMA 渐进上线字段 ─────────────────────────────────────
        # FMA 5态差异化过滤：默认 False（回测整体更优），
        # 当 shadow 样本 ≥ fma_min_samples 且 FMA=ON 模拟胜率 - FMA=OFF 实际胜率 ≥ fma_required_delta 时，
        # 自动从 False → True（晋升）。若后续胜率差回落 < delta - 0.01 回滚 → False。
        self.fma_enabled: bool = False
        self.fma_min_samples: int = 60                     # 样本门槛：用户要求 ≥60 条
        self.fma_required_delta: float = 0.05              # 胜率差门槛：≥+5%（用户要求）
        self.fma_rollback_delta: float = 0.04              # 回滚门槛：<+4% 就回滚（防止hysteresis震荡）
        self.fma_last_checked_at: Optional[str] = None     # ISO 时间戳
        self.fma_history: List[Dict[str, Any]] = []        # 每次评估的历史
        # 尝试加载已有状态
        self.load()

    # ============================================================
    # 核心操作
    # ============================================================

    def promote(self) -> float:
        """提升 α（步长 step，不超过 target）。"""
        old = self.current_alpha
        self.current_alpha = round(min(self.current_alpha + self.step, self.target_alpha), 4)
        if self.current_alpha >= self.target_alpha:
            self.is_complete = True
        self._record_history("promote", old, self.current_alpha)
        logger.info(f"[Rollout] promote: {old:.2f} → {self.current_alpha:.2f}")
        return self.current_alpha

    def rollback(self) -> float:
        """降低 α（步长 step，不下穿 0）。"""
        old = self.current_alpha
        self.current_alpha = round(max(self.current_alpha - self.step, 0.0), 4)
        self.is_complete = False
        self._record_history("rollback", old, self.current_alpha)
        logger.info(f"[Rollout] rollback: {old:.2f} → {self.current_alpha:.2f}")
        return self.current_alpha

    def set_alpha(self, alpha: float) -> float:
        """直接设置 α（受 [0, target] 约束）。"""
        old = self.current_alpha
        self.current_alpha = round(max(0.0, min(alpha, self.target_alpha)), 4)
        self.is_complete = self.current_alpha >= self.target_alpha
        self._record_history("set", old, self.current_alpha)
        return self.current_alpha

    # ============================================================
    # 状态持久化
    # ============================================================

    def save(self) -> Path:
        """保存状态到 JSON 文件。"""
        data = {
            "current_alpha": self.current_alpha,
            "target_alpha": self.target_alpha,
            "step": self.step,
            "is_complete": self.is_complete,
            "updated_at": datetime.now().isoformat(),
            "history": self.history,
            # ── H3-FMA 渐进状态 ──────────────────────────────────────
            "fma_enabled": self.fma_enabled,
            "fma_min_samples": self.fma_min_samples,
            "fma_required_delta": self.fma_required_delta,
            "fma_rollback_delta": self.fma_rollback_delta,
            "fma_last_checked_at": self.fma_last_checked_at,
            "fma_history": self.fma_history,
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"[Rollout] 状态已保存: {self.state_path} (FMA={'ON' if self.fma_enabled else 'OFF'})")
        return self.state_path

    def load(self) -> bool:
        """从 JSON 文件加载状态。"""
        if not self.state_path.exists():
            return False
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.current_alpha = float(data.get("current_alpha", 0.0))
            self.target_alpha = float(data.get("target_alpha", self.target_alpha))
            self.step = float(data.get("step", self.step))
            self.is_complete = bool(data.get("is_complete", False))
            self.history = data.get("history", [])
            # ── H3-FMA 渐进状态（缺省值 fallback 保持 False）
            self.fma_enabled = bool(data.get("fma_enabled", False))
            self.fma_min_samples = int(data.get("fma_min_samples", 60))
            self.fma_required_delta = float(data.get("fma_required_delta", 0.05))
            self.fma_rollback_delta = float(data.get("fma_rollback_delta", 0.04))
            self.fma_last_checked_at = data.get("fma_last_checked_at")
            self.fma_history = data.get("fma_history", []) or []
            logger.info(
                f"[Rollout] 状态已加载: α={self.current_alpha:.2f} "
                f"FMA={'ON' if self.fma_enabled else 'OFF'}(min_samples={self.fma_min_samples},delta={self.fma_required_delta:.0%})"
            )
            return True
        except Exception as e:
            logger.warning(f"[Rollout] 状态加载失败，使用默认值: {e}")
            return False

    # ============================================================
    # 查询
    # ============================================================

    def get_status(self) -> Dict[str, Any]:
        """返回完整状态。"""
        return {
            "current_alpha": self.current_alpha,
            "target_alpha": self.target_alpha,
            "step": self.step,
            "is_complete": self.is_complete,
            "history_length": len(self.history),
            "history": self.history,
            # ── H3-FMA 渐进状态 ──────────────────────────────────────
            "fma_enabled": self.fma_enabled,
            "fma_min_samples": self.fma_min_samples,
            "fma_required_delta": self.fma_required_delta,
            "fma_rollback_delta": self.fma_rollback_delta,
            "fma_last_checked_at": self.fma_last_checked_at,
            "fma_history_length": len(self.fma_history),
            "fma_history": self.fma_history[-30:],  # 最多输出最近 30 条，避免 JSON 过大
        }

    # ============================================================
    # H3-FMA 渐进：自动评估 & 切换
    # ============================================================

    def evaluate_fma_toggle(self, shadow_records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """评估 FMA=ON 是否优于 FMA=OFF，并自动晋升/回滚。

        评估逻辑（无真实 PNL 时，用「实际置信度 > 阈值」作为"虚拟胜出"信号；
        胜 = 置信度通过阈值且方向≠HOLD → 视作通过信号，未来结合真实 PNL 再替换）：

            off_total = 实际交易有 direction 且非 HOLD 的条数
            off_pass  = actual_confidence >= actual_threshold (FMA=OFF 实际开仓通过)
            on_total  = fma_on_allowed == True 且 direction != HOLD 的条数
            on_pass   = fma_on_allowed == True 且 actual_confidence >= fma_on_eff_threshold

            win_rate_off = off_pass / off_total
            win_rate_on  = on_pass  / on_total
            delta = win_rate_on - win_rate_off

        晋升 (False→True):  n >= min_samples 且 delta >= required_delta
        回滚 (True →False):  n >= min_samples 且 delta <  rollback_delta（带hysteresis）
        否则：保持不变

        返回: {
            "triggered": bool,          # 是否触发了本次评估（样本不足则不触发）
            "action": "PROMOTE|ROLLBACK|KEEP",
            "prev_enabled": bool,
            "new_enabled": bool,
            "n_records": int,
            "off_total": int, "off_pass": int, "win_rate_off": float,
            "on_total":  int, "on_pass":  int, "win_rate_on":  float,
            "delta": float,
            "reason": str,
        }
        """
        from datetime import datetime
        now_iso = datetime.now().isoformat()

        # 1. 统计有效样本
        off_total = off_pass = 0
        on_total = on_pass = 0
        for r in (shadow_records or []):
            direction = r.get("actual_direction")
            if not direction or direction == "HOLD":
                continue
            actual_conf = r.get("actual_confidence")
            actual_thr = r.get("actual_threshold")
            if actual_conf is None or actual_thr is None:
                continue
            # FMA=OFF（当前实际使用的）统计
            off_total += 1
            if float(actual_conf) >= float(actual_thr):
                off_pass += 1
            # FMA=ON（影子决策）统计
            fma_allow = r.get("fma_on_allowed")
            fma_thr = r.get("fma_on_eff_threshold")
            if isinstance(fma_allow, bool) and fma_allow and fma_thr is not None:
                on_total += 1
                if float(actual_conf) >= float(fma_thr):
                    on_pass += 1

        n_records = len(shadow_records or [])
        win_rate_off = round(off_pass / max(off_total, 1), 4)
        win_rate_on  = round(on_pass  / max(on_total,  1), 4)
        # 只要一组有样本就计算 delta（缺样本的一侧视作 0）
        delta = round(win_rate_on - win_rate_off, 4)

        # 2. 评估门槛
        min_samples = self.fma_min_samples
        need_eval = bool(off_total >= min_samples)

        prev = self.fma_enabled
        action = "SKIP"
        reason = ""
        if not need_eval:
            reason = f"样本不足：FMA_OFF有效样本={off_total}/{min_samples}（fma_on样本={on_total}）"
        else:
            if not prev:
                # 当前 False → 评估晋升
                if delta >= self.fma_required_delta:
                    self.fma_enabled = True
                    action = "PROMOTE"
                    reason = (
                        f"FMA=ON 胜率 {win_rate_on:.2%} vs FMA=OFF {win_rate_off:.2%}，"
                        f"Δ={delta:+.2%} ≥ 要求 {self.fma_required_delta:+.0%}，自动开启 5 态差异化过滤"
                    )
                else:
                    action = "KEEP"
                    reason = (
                        f"FMA=ON 胜率 {win_rate_on:.2%} vs FMA=OFF {win_rate_off:.2%}，"
                        f"Δ={delta:+.2%} < 晋升阈值 {self.fma_required_delta:+.0%}，保持默认双均线"
                    )
            else:
                # 当前 True → 评估回滚（hysteresis：rollback < required - 0.01）
                if delta < self.fma_rollback_delta:
                    self.fma_enabled = False
                    action = "ROLLBACK"
                    reason = (
                        f"FMA=ON 胜率 {win_rate_on:.2%} vs FMA=OFF {win_rate_off:.2%}，"
                        f"Δ={delta:+.2%} < 回滚阈值 {self.fma_rollback_delta:+.0%}，自动关闭 5 态差异化过滤"
                    )
                else:
                    action = "KEEP"
                    reason = (
                        f"FMA=ON 胜率 {win_rate_on:.2%} vs FMA=OFF {win_rate_off:.2%}，"
                        f"Δ={delta:+.2%} ≥ 回滚阈值 {self.fma_rollback_delta:+.0%}，继续保持开启"
                    )

        self.fma_last_checked_at = now_iso
        result = {
            "triggered": need_eval,
            "action": action,
            "prev_enabled": bool(prev),
            "new_enabled": bool(self.fma_enabled),
            "n_records": int(n_records),
            "shadow_off_total": int(off_total),
            "shadow_off_pass":  int(off_pass),
            "win_rate_off": win_rate_off,
            "shadow_on_total": int(on_total),
            "shadow_on_pass":  int(on_pass),
            "win_rate_on":  win_rate_on,
            "delta": delta,
            "reason": reason or "n/a",
        }
        self.fma_history.append({
            "checked_at": now_iso,
            **result,
        })
        # history 控制最多保留 500 条
        if len(self.fma_history) > 500:
            self.fma_history = self.fma_history[-500:]
        if need_eval:
            logger.info(
                f"[Rollout][FMA评估] {action} | Δ={delta:+.2%} "
                f"(ON {win_rate_on:.2%} n={on_total} vs OFF {win_rate_off:.2%} n={off_total}) → {reason}"
            )
        else:
            logger.debug(f"[Rollout][FMA评估] 不触发：{reason}")
        return result

    # ============================================================
    # FMA 手动开关（供 data_server API / CLI 手动 override）
    # ============================================================

    def set_fma_enabled(self, enabled: bool, reason: str = "手动切换") -> bool:
        """手动切换 FMA 开关（写入 history + 返回是否发生变更）。"""
        prev = self.fma_enabled
        self.fma_enabled = bool(enabled)
        self.fma_history.append({
            "checked_at": datetime.now().isoformat(),
            "triggered": True,
            "action": "MANUAL_ON" if self.fma_enabled else "MANUAL_OFF",
            "prev_enabled": prev,
            "new_enabled": self.fma_enabled,
            "reason": reason,
        })
        changed = (prev != self.fma_enabled)
        if changed:
            logger.info(f"[Rollout][FMA手动切换] {'ON' if prev else 'OFF'} → {'ON' if self.fma_enabled else 'OFF'} | {reason}")
        return changed

    # ============================================================
    # 内部
    # ============================================================

    def _record_history(self, action: str, old_alpha: float, new_alpha: float):
        """记录 α 变化历史。"""
        self.history.append({
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "old_alpha": round(old_alpha, 4),
            "new_alpha": round(new_alpha, 4),
        })


# ================================================================
# CLI 入口
# ================================================================
def main():
    import argparse
    p = argparse.ArgumentParser(description="Phase C 渐进上线管理器 + FMA 自动渐进")
    p.add_argument("--state", default="rollout_state.json", help="状态文件路径")
    p.add_argument("--action", choices=["status", "promote", "rollback", "save",
                                         "fma_status", "fma_on", "fma_off", "fma_eval"],
                   default="status")
    p.add_argument("--alpha", type=float, default=None, help="直接设置 α 值")
    p.add_argument("--reason", default="CLI手动触发", help="FMA 切换的原因说明")
    args = p.parse_args()

    mgr = RolloutManager(state_path=Path(args.state))

    if args.action == "promote":
        mgr.promote()
        mgr.save()
    elif args.action == "rollback":
        mgr.rollback()
        mgr.save()
    elif args.action == "save":
        mgr.save()
    elif args.alpha is not None:
        mgr.set_alpha(args.alpha)
        mgr.save()
    elif args.action == "fma_on":
        mgr.set_fma_enabled(True, reason=args.reason)
        mgr.save()
    elif args.action == "fma_off":
        mgr.set_fma_enabled(False, reason=args.reason)
        mgr.save()
    elif args.action == "fma_eval":
        # 从 bcrm2 storage 拉 7 天 shadow log 做一次评估
        try:
            _THIS = Path(__file__).resolve()
            _MEMORY_L4 = _THIS.parent.parent.parent
            import sys
            if str(_MEMORY_L4) not in sys.path:
                sys.path.insert(0, str(_MEMORY_L4))
            from bcrm2.run_evolution_pipeline import get_storage
            storage = get_storage()
            all_records: List[Any] = []
            for sym in ["BTC", "SOL", "XAU", "XAG", "NVDA", "GOOGL", "AMZN", "MU",
                        "SNDK", "SPCX", "OKB", "HYPE", "PUMP", "UNI", "SKHYNIX", "ETH"]:
                all_records.extend(storage.get_shadow_log(sym, days=7))
            result = mgr.evaluate_fma_toggle(all_records)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            mgr.save()
        except Exception as e:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            return

    status = mgr.get_status()
    print(json.dumps(status, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
