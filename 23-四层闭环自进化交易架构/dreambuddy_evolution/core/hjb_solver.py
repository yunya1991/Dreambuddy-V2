"""
Phase 2.6: HJB/变分法最优路径求解器（L3 路径计算层增强）
SPEC-AGI升级蓝图.md §4.2.6

核心哲学: 最优路径求解 — 万物皆数，最小阻力路径.
  1. HJBPathSolver — 离散化 HJB PDE，逆向动态规划求值函数 V(p,t) + 最优策略 π*(p,t)
  2. VariationalPathOptimizer — 蒙特卡洛路径集合上做欧拉-拉格朗日梯度下降

HJB 方程:
  ∂V/∂t + min_u { L(s,u) + ∇V·f(s,u) } = 0
  离散化: V(p,t) = min_u { L(p,u)·dt + Σ_{p'} P(p→p'|u)·V(p',t+dt) }

变分法:
  S[γ] = Σ_i L(γ_i, Δγ_i) → min
  欧拉-拉格朗日: ∂L/∂γ - d/dt(∂L/∂γ') = 0
  梯度下降: γ_{k+1} = γ_k - η·∇S

降级链 (HC-AGI-17):
  HJBPathSolver → VariationalPathOptimizer → PathIntegralEngine.find_least_resistance_path

HC-AGI-15: 价格网格≥32, 时间网格≥16
HC-AGI-16: 收敛阈值 1e-6 持续≥3轮
HC-AGI-17: 异常强制降级到 argmin（不可跳过）
"""
from __future__ import annotations

import logging
import math

import numpy as np

logger = logging.getLogger(__name__)


class HJBPathSolver:
    """HJB PDE 离散化求解器.

    V(p,t) = min_u { L(p,u)·dt + Σ_{p'} P(p→p'|u)·V(p',t+dt) }

    状态空间: 价格 p ∈ [p_min, p_max] × 时间 t ∈ [0, T]
    策略空间: u ∈ {long, short, wait}
    终端条件: V(p, T) = 0
    """

    MIN_PRICE_GRID = 32   # HC-AGI-15
    MIN_TIME_GRID = 16    # HC-AGI-15
    CONVERGENCE_TOL = 1e-6   # HC-AGI-16
    CONVERGENCE_ROUNDS = 3  # HC-AGI-16

    def __init__(
        self,
        n_price_bins: int = 64,
        n_time_bins: int = 32,
        alpha: float = 0.4,   # 成本权重（对齐 PathIntegralEngine）
        beta: float = 0.3,    # 风险权重
        gamma: float = 0.3,   # 不确定性权重
        n_sigma: float = 3.0,  # 价格网格 ±nσ
    ) -> None:
        self.n_price_bins = max(n_price_bins, self.MIN_PRICE_GRID)
        self.n_time_bins = max(n_time_bins, self.MIN_TIME_GRID)
        self.alpha = float(alpha)
        self.beta = float(beta)
        self.gamma = float(gamma)
        self.n_sigma = float(n_sigma)

    # ------------------------------------------------------------------
    # 网格构造
    # ------------------------------------------------------------------
    def build_grid(
        self,
        start_price: float,
        volatility: float,
        horizon: int,
    ) -> dict:
        """构建价格-时间状态网格.

        价格范围: [start_price × exp(-nσ·√horizon), start_price × exp(nσ·√horizon)]
        时间范围: [0, horizon]，等距分 n_time_bins 段
        """
        if volatility <= 0 or not math.isfinite(volatility):
            volatility = 0.02
        # 防止极端波动率导致 math.exp 溢出（低价币收益率可能>1000%）
        # 5.0 = 500% 每期，已远超合理交易波动范围
        volatility = min(volatility, 5.0)
        if start_price <= 0 or not math.isfinite(start_price):
            start_price = 100.0

        sigma_total = self.n_sigma * volatility * math.sqrt(max(horizon, 1))
        # 防止 math.exp 溢出: exp(709)≈8.2e307 是 float64 上限
        # 实际交易中 ±50 已覆盖 exp(50)≈5e21 倍价格范围，远超合理范围
        sigma_total = min(sigma_total, 50.0)
        p_min = start_price * math.exp(-sigma_total)
        p_max = start_price * math.exp(sigma_total)

        price_grid = np.linspace(p_min, p_max, self.n_price_bins)
        time_grid = np.linspace(0, horizon, self.n_time_bins + 1)
        dp = float(price_grid[1] - price_grid[0]) if len(price_grid) > 1 else 1.0
        dt = float(time_grid[1] - time_grid[0]) if len(time_grid) > 1 else 1.0

        return {
            "price_grid": price_grid,
            "time_grid": time_grid,
            "dp": dp,
            "dt": dt,
            "p_min": p_min,
            "p_max": p_max,
        }

    # ------------------------------------------------------------------
    # Lagrangian
    # ------------------------------------------------------------------
    def lagrangian(
        self,
        price: float,
        action: str,
        r_vector: dict | None = None,
        primary_contradiction: dict | None = None,
    ) -> float:
        """计算瞬时 Lagrangian L(p, u), 可选矛盾强度调制.

        对齐 level0_path_cost.py 的 R_up/R_down/R_smooth·R_reflexivity:
          long:  L = α·R_up
          short: L = α·R_down
          wait:  L = γ·R_smooth·R_reflexivity

        矛盾论 §矛盾主要方面: 主要矛盾方向阻力降低, 次要方向阻力升高
          action 对齐 primary_direction: L × (1 - 0.3×strength)
          action 逆向 primary_direction: L × (1 + 0.5×strength)

        FAIL-OPEN: r_vector 缺失/NaN → 0.50 兜底
        HC-AGI-19: 调制后 L >= 0.001
        """
        if r_vector is None:
            r_vector = {}

        def _get(key: str, default: float = 0.50) -> float:
            v = r_vector.get(key, default)
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = default
            if math.isnan(v) or math.isinf(v):
                v = default
            return max(0.01, v)

        R_up = _get("R_up")
        R_down = _get("R_down")
        R_smooth = _get("R_smooth")
        R_refl = _get("R_reflexivity")

        if action == "long":
            L = self.alpha * R_up
        elif action == "short":
            L = self.beta * R_down
        elif action == "wait":
            L = self.gamma * R_smooth * R_refl
        else:
            L = 0.0

        # 矛盾强度调制 (Phase 3.3)
        if primary_contradiction is not None:
            try:
                pc_dir = str(primary_contradiction.get("direction", "neutral"))
                pc_strength = float(primary_contradiction.get("strength", 0.0))
                pc_strength = max(0.0, min(1.0, pc_strength))  # 截断 [0,1]

                if pc_dir != "neutral" and pc_strength >= 0.01:
                    action_dir = {"long": "long", "short": "short"}.get(action, "neutral")
                    if action_dir == pc_dir:
                        # 对齐主要矛盾: 阻力降低（阻力最小路径哲学）
                        L = L * (1.0 - 0.3 * pc_strength)
                    else:
                        # 逆向主要矛盾: 阻力升高（重心原则）
                        L = L * (1.0 + 0.5 * pc_strength)
            except (TypeError, ValueError):
                pass  # FAIL-OPEN: 调制异常不阻塞

        return float(max(0.001, L))  # HC-AGI-19: L >= 0.001

    # ------------------------------------------------------------------
    # 转移概率
    # ------------------------------------------------------------------
    def _transition_probabilities(
        self,
        price_idx: int,
        grid: dict,
        drift: float,
        volatility: float,
        dt: float,
        reflexivity_fuel: dict | None = None,
    ) -> np.ndarray:
        """计算从 price_idx 出发的 GBM 转移概率（高斯窗 ±2σ）.

        GBM: dS = μS dt + σS dW
        离散: ln(S'/S) ~ N((μ-σ²/2)dt, σ²dt)

        Args:
            reflexivity_fuel: 反身性燃料偏移参数，格式:
                {"type": "leverage"|"mechanism"|"sentiment", "intensity": 0~1, "direction": -1|+1}
                - leverage: σ ↑↑ (2.0 × intensity)
                - mechanism: μ 偏移 (K × direction, K=0.02 × intensity)
                - sentiment: σ ↑ (0.5 × intensity)
                None 或 unknown type → 回退标准 GBM（FAIL-OPEN）

        返回归一化概率向量，长度 = n_price_bins
        """
        n = self.n_price_bins
        price_grid = grid["price_grid"]
        dp = grid["dp"]

        if price_idx < 0 or price_idx >= n:
            probs = np.zeros(n)
            probs[max(0, min(n - 1, price_idx))] = 1.0
            return probs

        p_current = price_grid[price_idx]
        if p_current <= 0 or volatility <= 0 or dt <= 0:
            probs = np.zeros(n)
            probs[price_idx] = 1.0
            return probs

        # 反身性燃料偏移（FAIL-OPEN: 异常回退标准GBM）
        eff_drift = drift
        eff_vol = volatility
        if reflexivity_fuel is not None:
            try:
                fuel_type = str(reflexivity_fuel.get("type", ""))
                intensity = float(reflexivity_fuel.get("intensity", 0.0))
                # intensity clip [0, 1]
                intensity = max(0.0, min(1.0, intensity))

                if fuel_type == "leverage":
                    # σ ↑↑ (2.0 × intensity)，上限 5× 原始
                    eff_vol = min(volatility * (1.0 + 2.0 * intensity), volatility * 5.0)
                elif fuel_type == "mechanism":
                    # μ 偏移 (K × direction, K=0.02 × intensity)
                    direction = float(reflexivity_fuel.get("direction", 0))
                    eff_drift = drift + 0.02 * intensity * direction
                elif fuel_type == "sentiment":
                    # σ ↑ (0.5 × intensity)，上限 5× 原始
                    eff_vol = min(volatility * (1.0 + 0.5 * intensity), volatility * 5.0)
                # unknown type → 回退标准GBM（eff_drift/eff_vol 不变）
            except Exception:
                pass  # FAIL-OPEN: 燃料偏移异常回退标准GBM

        mu_log = (eff_drift - 0.5 * eff_vol ** 2) * dt
        sigma_log = eff_vol * math.sqrt(dt)

        # 对数收益率到各格点
        log_returns = np.log(np.maximum(price_grid / p_current, 1e-12))

        # 高斯密度权重（±2σ 截断）
        probs = np.exp(-0.5 * ((log_returns - mu_log) / max(sigma_log, 1e-12)) ** 2)
        mask = np.abs(log_returns - mu_log) <= 2.0 * sigma_log
        probs = probs * mask

        total = float(np.sum(probs))
        if total > 0:
            probs = probs / total
        else:
            probs = np.zeros(n)
            probs[price_idx] = 1.0

        return probs

    # ------------------------------------------------------------------
    # 逆向动态规划
    # ------------------------------------------------------------------
    def _value_iteration(
        self,
        grid: dict,
        r_vector: dict | None,
        drift: float,
        volatility: float,
        primary_contradiction: dict | None = None,
        reflexivity_fuel: dict | None = None,
        shift_points: list | None = None,
    ) -> tuple[np.ndarray, np.ndarray, bool]:
        """逆向动态规划主循环（迭代值迭代 + HC-AGI-16 收敛检查）.

        算法:
          1. 终端条件 V[:, -1] = 0
          2. 外层迭代: 重复逆向 DP 直到 V 收敛
          3. 逆向时间迭代 t = T-1 → 0:
               V[p, t] = min_u { L(p,u)·dt + Σ_{p'} P(p→p'|u)·V[p', t+1] }
               π*[p, t] = argmin_u

        HC-AGI-16: 连续 CONVERGENCE_ROUNDS 轮 max|ΔV| < CONVERGENCE_TOL
          max|ΔV| = max_p |V_new[p] - V_old[p]|  — 迭代间值函数变化量（非绝对值）

        有限时域逆向DP为精确解，首轮即得V*；后续轮次验证V稳定（ΔV→0）。

        Args:
            primary_contradiction: Phase 3.3 矛盾强度调制参数，传入 lagrangian()

        Returns:
            (V, policy, converged)
        """
        n_p = self.n_price_bins
        n_t = self.n_time_bins + 1
        dt = grid["dt"]

        V = np.zeros((n_p, n_t), dtype=np.float64)
        policy = np.zeros((n_p, n_t), dtype=np.int64)  # 0=wait, 1=long, 2=short

        actions = [("wait", 0), ("long", 1), ("short", 2)]

        # HC-AGI-16: 外层迭代收敛检查
        max_iterations = 50
        convergence_history: list[float] = []
        converged = False

        for iteration in range(max_iterations):
            V_old = V.copy()

            # 逆向时间迭代（单遍逆向 DP）
            for t in range(n_t - 2, -1, -1):
                V_next = V[:, t + 1]  # 当前迭代中已更新的 t+1 列

                # §18 质变驱动：检查 t 时刻是否需要切换 primary
                current_primary = primary_contradiction
                if shift_points:
                    try:
                        for sp_t, sp_primary in shift_points:
                            if sp_t == t and sp_primary is not None:
                                current_primary = sp_primary
                                break
                    except (TypeError, ValueError):
                        pass  # FAIL-OPEN: shift_points 格式错误→不切换

                for p_idx in range(n_p):
                    best_cost = math.inf
                    best_action_code = 0

                    for action_name, action_code in actions:
                        L = self.lagrangian(
                            float(grid["price_grid"][p_idx]),
                            action_name,
                            r_vector,
                            primary_contradiction=current_primary,
                        )

                        # 转移概率
                        # long: drift > 0; short: drift < 0; wait: drift = 0
                        if action_name == "long":
                            eff_drift = abs(drift) + volatility * 0.5  # 上行偏向
                        elif action_name == "short":
                            eff_drift = -abs(drift) - volatility * 0.5  # 下行偏向
                        else:
                            eff_drift = 0.0

                        probs = self._transition_probabilities(
                            p_idx, grid, eff_drift, volatility, dt,
                            reflexivity_fuel=reflexivity_fuel,
                        )

                        expected_future = float(np.dot(probs, V_next))
                        cost = L * dt + expected_future

                        if cost < best_cost:
                            best_cost = cost
                            best_action_code = action_code

                    V[p_idx, t] = best_cost
                    policy[p_idx, t] = best_action_code

            # HC-AGI-16: max|ΔV| = max|V_new - V_old|（迭代间变化量，非绝对值）
            max_delta_v = float(np.max(np.abs(V - V_old)))
            convergence_history.append(max_delta_v)

            # 连续 CONVERGENCE_ROUNDS 轮 max|ΔV| < CONVERGENCE_TOL
            if len(convergence_history) >= self.CONVERGENCE_ROUNDS:
                recent = convergence_history[-self.CONVERGENCE_ROUNDS:]
                if all(d < self.CONVERGENCE_TOL for d in recent):
                    converged = True
                    break

        return V, policy, converged

    # ------------------------------------------------------------------
    # 最优路径回溯
    # ------------------------------------------------------------------
    def _trace_optimal_path(
        self,
        value_function: np.ndarray,
        policy: np.ndarray,
        grid: dict,
        start_price: float,
    ) -> tuple[np.ndarray, list[str]]:
        """从 start_price 正向回溯最优路径."""
        n_t = self.n_time_bins + 1
        price_grid = grid["price_grid"]

        # 找到最接近 start_price 的格点
        start_idx = int(np.argmin(np.abs(price_grid - start_price)))

        optimal_path = np.zeros(n_t, dtype=np.float64)
        optimal_path[0] = price_grid[start_idx]

        action_map = {0: "wait", 1: "long", 2: "short"}
        actions: list[str] = []

        current_idx = start_idx
        for t in range(n_t):
            action_code = int(policy[current_idx, t])
            actions.append(action_map.get(action_code, "wait"))

            if t < n_t - 1:
                # 根据 action 和转移概率选择下一格点
                if action_code == 1:  # long → 上行
                    next_idx = min(current_idx + 1, self.n_price_bins - 1)
                elif action_code == 2:  # short → 下行
                    next_idx = max(current_idx - 1, 0)
                else:  # wait → 维持
                    next_idx = current_idx
                optimal_path[t + 1] = price_grid[next_idx]
                current_idx = next_idx

        return optimal_path, actions

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------
    def solve(
        self,
        start_price: float,
        horizon: int,
        volatility: float,
        drift: float = 0.0,
        r_vector: dict | None = None,
        primary_contradiction: dict | None = None,
        reflexivity_fuel: dict | None = None,
        shift_points: list | None = None,
    ) -> dict:
        """逆向动态规划求解 HJB PDE.

        Args:
            primary_contradiction: Phase 3.3 矛盾强度调制参数
            reflexivity_fuel: §14 反身性燃料偏移转移概率参数
            shift_points: §18 质变驱动路径切换点列表 [(t_shift, new_primary), ...]

        Returns:
            {
                "value_function": np.ndarray,   # shape (n_price_bins, n_time_bins+1)
                "policy": np.ndarray,           # shape 同上, 0=wait/1=long/2=short
                "price_grid": np.ndarray,
                "time_grid": np.ndarray,
                "optimal_path": np.ndarray,      # 从 start_price 正向回溯
                "optimal_actions": list[str],
                "total_cost": float,            # V(start_price, 0)
                "converged": bool,
                "backend": "hjb",
            }
        """
        grid = self.build_grid(start_price, volatility, horizon)
        V, policy, converged = self._value_iteration(
            grid, r_vector, drift, volatility,
            primary_contradiction=primary_contradiction,
            reflexivity_fuel=reflexivity_fuel,
            shift_points=shift_points,
        )
        optimal_path, optimal_actions = self._trace_optimal_path(
            V, policy, grid, start_price
        )

        # V(start_price, 0)
        start_idx = int(np.argmin(np.abs(grid["price_grid"] - start_price)))
        total_cost = float(V[start_idx, 0])

        # 安全检查
        if not np.all(np.isfinite(V)):
            raise ValueError("[HJB] 值函数含 NaN/Inf")

        return {
            "value_function": V,
            "policy": policy,
            "price_grid": grid["price_grid"],
            "time_grid": grid["time_grid"],
            "optimal_path": optimal_path,
            "optimal_actions": optimal_actions,
            "total_cost": max(0.0, total_cost),
            "converged": converged,  # HC-AGI-16: 基于 max|ΔV| 的迭代收敛标志
            "backend": "hjb",
        }


class VariationalPathOptimizer:
    """变分法路径优化器: 欧拉-拉格朗日梯度下降.

    作用量: S[γ] = Σ_i L(γ_i, Δγ_i)
    离散梯度下降: γ_{k+1} = γ_k - η·∇S

    compute_action 严格复用 PathIntegralEngine.compute_action 公式:
      S = α·成本(Σ|diffs|/n) + β·风险(max drawdown) + γ·不确定性(RMSE to trend)
    """

    DEFAULT_LEARNING_RATE = 0.01
    MAX_ITER = 200
    CONVERGENCE_TOL = 1e-6   # HC-AGI-16
    CONVERGENCE_ROUNDS = 3    # HC-AGI-16

    def __init__(
        self,
        alpha: float = 0.4,
        beta: float = 0.3,
        gamma: float = 0.3,
        learning_rate: float = 0.01,
        max_iter: int = 200,
    ) -> None:
        self.alpha = float(alpha)
        self.beta = float(beta)
        self.gamma = float(gamma)
        self.learning_rate = float(learning_rate)
        self.max_iter = int(max_iter)

    # ------------------------------------------------------------------
    # 作用量计算（严格复用 PathIntegralEngine.compute_action 公式）
    # ------------------------------------------------------------------
    def compute_action(self, path: np.ndarray) -> float:
        """计算路径作用量 S.

        S = α·成本 + β·风险 + γ·不确定性
          成本 = 总波动 / 路径长度
          风险 = 最大回撤
          不确定性 = 路径与线性趋势的 RMSE

        与 path_integral.py:78-110 严格一致.
        """
        path = np.asarray(path, dtype=np.float64).ravel()
        n = len(path)
        if n < 2:
            return 0.0

        # 成本: 总波动 / 长度
        diffs = np.diff(path)
        cost = float(np.sum(np.abs(diffs)) / max(n - 1, 1))

        # 风险: 最大回撤
        running_max = np.maximum.accumulate(path)
        drawdowns = (running_max - path) / np.maximum(running_max, 1e-12)
        risk = float(np.max(drawdowns))

        # 不确定性: RMSE to linear trend
        t = np.arange(n, dtype=np.float64)
        if n > 2:
            coeffs = np.polyfit(t, path, 1)
            trend = np.polyval(coeffs, t)
            uncertainty = float(np.sqrt(np.mean((path - trend) ** 2)))
        else:
            uncertainty = 0.0

        action = self.alpha * cost + self.beta * risk + self.gamma * uncertainty
        return float(max(0.0, action))

    # ------------------------------------------------------------------
    # 数值梯度（中心差分）
    # ------------------------------------------------------------------
    def compute_action_gradient(self, path: np.ndarray) -> np.ndarray:
        """中心差分计算 ∇S/∂γ_i.

        ∂S/∂γ_i ≈ (S(γ + ε·e_i) - S(γ - ε·e_i)) / (2ε)
        ε = max(1e-5, 1e-3·|γ_i|)
        """
        path = np.asarray(path, dtype=np.float64).ravel()
        n = len(path)
        grad = np.zeros(n, dtype=np.float64)

        for i in range(n):
            eps = max(1e-5, 1e-3 * abs(path[i]))
            path_plus = path.copy()
            path_minus = path.copy()
            path_plus[i] += eps
            path_minus[i] -= eps
            s_plus = self.compute_action(path_plus)
            s_minus = self.compute_action(path_minus)
            grad[i] = (s_plus - s_minus) / (2.0 * eps)

        # 防止梯度爆炸
        grad = np.clip(grad, -10.0, 10.0)
        return grad

    # ------------------------------------------------------------------
    # 梯度下降优化
    # ------------------------------------------------------------------
    def optimize(
        self,
        initial_path: np.ndarray | list[np.ndarray],
        n_paths: int = 1,
    ) -> dict:
        """对初始路径做梯度下降优化.

        若 initial_path 是 list，则对每条路径分别优化，返回总作用量最小者.
        HC-AGI-16: 连续 CONVERGENCE_ROUNDS 轮 |ΔS/S| < CONVERGENCE_TOL 视为收敛.

        Returns:
            {
                "optimal_path": np.ndarray,
                "total_action": float,
                "n_iter": int,
                "converged": bool,
                "backend": "variational",
                "initial_action": float,
            }
        """
        # 处理多路径输入
        if isinstance(initial_path, (list, tuple)) and len(initial_path) > 0 and isinstance(initial_path[0], np.ndarray):
            paths_list = list(initial_path)
        else:
            paths_list = [np.asarray(initial_path, dtype=np.float64).ravel()]

        best_result = None
        for path in paths_list:
            result = self._optimize_single(path)
            if best_result is None or result["total_action"] < best_result["total_action"]:
                best_result = result

        return best_result

    def _optimize_single(self, initial_path: np.ndarray) -> dict:
        """对单条路径做梯度下降."""
        gamma = np.asarray(initial_path, dtype=np.float64).ravel().copy()
        start_point = float(gamma[0]) if len(gamma) > 0 else 100.0
        p_min = float(np.min(gamma)) if len(gamma) > 0 else start_point * 0.9
        p_max = float(np.max(gamma)) if len(gamma) > 0 else start_point * 1.1

        initial_action = self.compute_action(gamma)
        action_history: list[float] = [initial_action]

        for k in range(self.max_iter):
            grad = self.compute_action_gradient(gamma)
            gamma = gamma - self.learning_rate * grad

            # 起点 anchoring
            if len(gamma) > 0:
                gamma[0] = start_point

            # 价格边界
            gamma = np.clip(gamma, p_min, p_max)

            s_new = self.compute_action(gamma)
            action_history.append(s_new)

            # HC-AGI-16 收敛检查
            if len(action_history) >= self.CONVERGENCE_ROUNDS + 1:
                recent = action_history[-self.CONVERGENCE_ROUNDS:]
                deltas = [
                    abs(recent[i] - recent[i - 1]) / max(abs(recent[i - 1]), 1e-12)
                    for i in range(1, len(recent))
                ]
                if all(d < self.CONVERGENCE_TOL for d in deltas):
                    return {
                        "optimal_path": gamma,
                        "total_action": float(s_new),
                        "n_iter": k + 1,
                        "converged": True,
                        "backend": "variational",
                        "initial_action": float(initial_action),
                    }

        converged = False
        if len(action_history) >= self.CONVERGENCE_ROUNDS + 1:
            recent = action_history[-self.CONVERGENCE_ROUNDS:]
            deltas = [
                abs(recent[i] - recent[i - 1]) / max(abs(recent[i - 1]), 1e-12)
                for i in range(1, len(recent))
            ]
            converged = all(d < self.CONVERGENCE_TOL for d in deltas)

        final_action = float(action_history[-1])
        return {
            "optimal_path": gamma,
            "total_action": final_action,
            "n_iter": self.max_iter,
            "converged": converged,
            "backend": "variational",
            "initial_action": float(initial_action),
        }


# ----------------------------------------------------------------------
# 统一入口：三级降级链（HC-AGI-17）
# ----------------------------------------------------------------------
def solve_optimal_path(
    start_price: float,
    horizon: int,
    volatility: float,
    drift: float = 0.0,
    r_vector: dict | None = None,
    monte_carlo_paths: list[np.ndarray] | None = None,
    alpha: float = 0.4,
    beta: float = 0.3,
    gamma: float = 0.3,
    primary_contradiction: dict | None = None,
    reflexivity_fuel: dict | None = None,
    shift_points: list | None = None,
) -> dict:
    """统一入口：HJB → 变分法 → argmin 三级降级链.

    优先级:
      1. HJBPathSolver.solve() — 全局最优（值函数）
      2. VariationalPathOptimizer.optimize(monte_carlo_paths) — 局部连续优化
      3. PathIntegralEngine.find_least_resistance_path(monte_carlo_paths) — argmin 兜底

    HC-AGI-17: 异常强制降级，不可跳过.

    Args:
        primary_contradiction: Phase 3.3 矛盾强度调制参数，传入 HJB lagrangian.
                               None 时等价旧行为（向后兼容）.
        reflexivity_fuel: §14 反身性燃料偏移转移概率参数，传入 HJB _transition_probabilities.
        shift_points: §18 质变驱动路径切换点列表 [(t_shift, new_primary), ...].

    Returns:
        {
            "optimal_path": np.ndarray,
            "total_cost": float,
            "backend": "hjb" | "variational" | "argmin",
            "converged": bool,
            "fallback_chain": list[str],
        }
    """
    fallback_chain: list[str] = []

    # ------------------------------------------------------------------
    # Level 1: HJB PDE 求解器
    # ------------------------------------------------------------------
    try:
        from dreambuddy_evolution.agi_config import get_switch
        if get_switch("enable_hjb_solver", True):
            if math.isnan(volatility) or math.isinf(volatility) or volatility <= 0:
                raise ValueError(f"[HJB] volatility 无效: {volatility}")

            solver = HJBPathSolver(alpha=alpha, beta=beta, gamma=gamma)
            hjb_result = solver.solve(
                start_price=start_price,
                horizon=horizon,
                volatility=volatility,
                drift=drift,
                r_vector=r_vector,
                primary_contradiction=primary_contradiction,
                reflexivity_fuel=reflexivity_fuel,
                shift_points=shift_points,
            )
            fallback_chain.append("hjb")
            return {
                "optimal_path": hjb_result["optimal_path"],
                "total_cost": hjb_result["total_cost"],
                "backend": "hjb",
                "converged": hjb_result["converged"],
                "fallback_chain": fallback_chain,
                "value_function": hjb_result["value_function"],
                "policy": hjb_result["policy"],
            }
    except Exception as e:
        logger.warning("[FO-AGI-17] HJB 求解降级: %s", e)
        fallback_chain.append("hjb_fail")

    # ------------------------------------------------------------------
    # Level 2: 变分法路径优化器
    # ------------------------------------------------------------------
    try:
        from dreambuddy_evolution.agi_config import get_switch
        if get_switch("enable_variational_opt", True) and monte_carlo_paths:
            opt = VariationalPathOptimizer(alpha=alpha, beta=beta, gamma=gamma)
            var_result = opt.optimize(monte_carlo_paths)
            fallback_chain.append("variational")
            return {
                "optimal_path": var_result["optimal_path"],
                "total_cost": var_result["total_action"],
                "backend": "variational",
                "converged": var_result["converged"],
                "fallback_chain": fallback_chain,
                "value_function": None,
                "policy": None,
            }
    except Exception as e:
        logger.warning("[FO-AGI-17] 变分法降级: %s", e)
        fallback_chain.append("variational_fail")

    # ------------------------------------------------------------------
    # Level 3: argmin 兜底（PathIntegralEngine）
    # ------------------------------------------------------------------
    try:
        from dreambuddy_evolution.core.path_integral import PathIntegralEngine
        pe = PathIntegralEngine(alpha=alpha, beta=beta, gamma=gamma)

        if monte_carlo_paths and len(monte_carlo_paths) > 0:
            best_idx, best_action = pe.find_least_resistance_path(monte_carlo_paths)
            optimal_path = monte_carlo_paths[best_idx]
            total_cost = float(best_action)
        else:
            # 无路径时用 HJB 的网格中点
            optimal_path = np.array([start_price])
            total_cost = 0.0

        fallback_chain.append("argmin")
        return {
            "optimal_path": optimal_path,
            "total_cost": total_cost,
            "backend": "argmin",
            "converged": True,
            "fallback_chain": fallback_chain,
            "value_function": None,
            "policy": None,
        }
    except Exception as e:
        logger.error("[FO-AGI-17] argmin 也失败: %s", e)
        fallback_chain.append("argmin_fail")

        # Level 4: 最简兜底
        if monte_carlo_paths and len(monte_carlo_paths) > 0:
            optimal_path = monte_carlo_paths[0]
        else:
            optimal_path = np.array([start_price])

        return {
            "optimal_path": optimal_path,
            "total_cost": 0.0,
            "backend": "fallback",
            "converged": False,
            "fallback_chain": fallback_chain,
            "value_function": None,
            "policy": None,
        }
