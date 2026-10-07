"""
L4 BellmanVTracker (§二 L4 最优目标层 · MVP 骨架)
蓝图: 四层闭环进化架构-最小阻力路径总览.md §二, §1.5.1

V(s) ← V(s) + α·(R + γ·V(s') - V(s))  (TD(0) 时序差分更新)
MVP: 纯 numpy 值迭代 + ESS 回馈 ±0.02 硬约束 (§1.6.3)
Phase 3: Bellman 完整 + 摩擦力建模
Phase 3.3: 状态空间扩展 (symbol, regime) 二维 V 值
D2: 持久化（save/load + persist_path 自动恢复 + 每 N 次更新自动保存）
"""
import json
from pathlib import Path
from typing import Any


class BellmanVTracker:
    """
    L4 价值函数追踪器.
    MVP: TD(0) 简化版 + ESS 调整量输出.
    Phase 3.3: 支持 (symbol, regime) 二维状态空间.
    D2: 持久化（save/load + persist_path 自动恢复）.
    """

    def __init__(self, alpha: float = 0.1, gamma: float = 0.95,
                 ess_max: float = 0.02, ess_min: float = -0.02,
                 persist_path: str | Path | None = None,
                 save_every: int = 100):
        # 一维: per-symbol V 值（向后兼容）
        self._v: dict[str, float] = {}
        # 二维: per-symbol×regime V 值
        self._v_regime: dict[tuple[str, str], float] = {}
        self._alpha = float(alpha)
        self._gamma = float(gamma)
        self._ess_max = float(ess_max)
        self._ess_min = float(ess_min)
        # 持久化配置
        self._persist_path = Path(persist_path) if persist_path else None
        self._save_every = int(save_every)
        self._update_count = 0
        # 构造时自动恢复
        if self._persist_path is not None and self._persist_path.exists():
            self.load(self._persist_path)

    def get_v(self, symbol: str, regime: str | None = None) -> float:
        """获取 V 值. regime=None 时退化为一维（向后兼容）."""
        if regime is None:
            return self._v.get(symbol, 0.0)
        return self._v_regime.get((symbol, regime), self._v.get(symbol, 0.0))

    def td_update(self, symbol: str, reward: float,
                  next_symbol: str = "",
                  regime: str | None = None,
                  next_regime: str | None = None) -> float:
        """
        V(s) ← V(s) + α·(R + γ·V(s') - V(s))
        regime=None 时退化为一维 TD 更新（向后兼容）.
        regime 提供 时更新二维 (symbol, regime) V 值.
        返回更新后的 V(s).
        """
        if regime is None:
            # 一维模式（向后兼容）
            v_s = self._v.get(symbol, 0.0)
            v_sp = self._v.get(next_symbol, 0.0) if next_symbol else 0.0
            td_target = reward + self._gamma * v_sp
            td_error = td_target - v_s
            v_new = v_s + self._alpha * td_error
            self._v[symbol] = v_new
            self._maybe_auto_save()
            return v_new
        else:
            # 二维模式: (symbol, regime)
            key = (symbol, regime)
            next_key = (next_symbol, next_regime) if next_symbol and next_regime else None
            v_s = self._v_regime.get(key, self._v.get(symbol, 0.0))
            v_sp = self._v_regime.get(next_key, 0.0) if next_key else 0.0
            td_target = reward + self._gamma * v_sp
            td_error = td_target - v_s
            v_new = v_s + self._alpha * td_error
            self._v_regime[key] = v_new
            # 同时更新一维（保持兼容性）
            self._v[symbol] = v_new
            self._maybe_auto_save()
            return v_new

    def get_ess_adjustment(self, symbol: str, regime: str | None = None) -> float:
        """
        V(s) → ESS 调整量 (§1.6.3 硬约束 ±0.02).
        正 V → 正调整（策略有效），负 V → 负调整（策略无效）.
        """
        v = self.get_v(symbol, regime)
        # 线性映射: V > 0 → +ess（上限 ess_max），V < 0 → -ess（下限 ess_min）
        # 归一化: 假设 |V| ≤ 0.2 对应满 ess
        normalized = max(-1.0, min(1.0, v / 0.2))
        if normalized >= 0:
            return round(normalized * self._ess_max, 6)
        else:
            return round(normalized * abs(self._ess_min), 6)

    def get_all_v(self) -> dict[str, float]:
        return dict(self._v)

    def get_all_v_regime(self) -> dict[tuple[str, str], float]:
        """获取二维 V 值表."""
        return dict(self._v_regime)

    # ------------------------------------------------------------------ D2 持久化
    def save(self, path: str | Path | None = None) -> bool:
        """保存 V 值到 JSON 文件.

        FAIL-OPEN: 保存失败返回 False，不影响内存 V 值.
        """
        target = Path(path) if path else self._persist_path
        if target is None:
            return False
        try:
            data = {
                "v": {k: float(v) for k, v in self._v.items()},
                "v_regime": {f"{k[0]}||{k[1]}": float(v) for k, v in self._v_regime.items()},
                "alpha": self._alpha,
                "gamma": self._gamma,
            }
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            return True
        except Exception:
            return False  # FAIL-OPEN

    def load(self, path: str | Path | None = None) -> bool:
        """从 JSON 文件加载 V 值.

        FAIL-OPEN: 加载失败/文件不存在/数据损坏 → 保持空 dict，不抛异常.
        """
        target = Path(path) if path else self._persist_path
        if target is None or not target.exists():
            return False
        try:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return False
            self._v = {str(k): float(v) for k, v in data.get("v", {}).items()}
            self._v_regime = {}
            for k, v in data.get("v_regime", {}).items():
                if "||" in k:
                    sym, reg = k.split("||", 1)
                    self._v_regime[(sym, reg)] = float(v)
            return True
        except Exception:
            self._v = {}
            self._v_regime = {}
            return False  # FAIL-OPEN: 损坏 → 空开始

    def _maybe_auto_save(self) -> None:
        """每 save_every 次更新自动持久化（HC-DS4-09）."""
        self._update_count += 1
        if self._persist_path is None:
            return
        if self._update_count % self._save_every == 0:
            self.save()
