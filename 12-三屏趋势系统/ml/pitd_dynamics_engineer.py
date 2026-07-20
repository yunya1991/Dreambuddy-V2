"""PITD Phase 2: 动力学层 (Dynamics)

基于Phase 1运动学量，引入质量、力、动量、动能及动量传递效率。

核心物理量：
- 质量 m(t): 稳定币总市值标准化（主方案）/ 标准化成交量（备选）
- 合力 F(t) = m×a - μ×m×σ   （驱动力 - 摩擦力）
- 动量 P(t) = m×v
- 动能 E_k(t) = ½×m×v²
- 动量传递效率 η = corr(v_W, v_D) × |v_W|/(|v_W|+|v_D|)

理论1验证：趋势强时大周期驱动小周期（η高→顺势；η低→小周期独立）

文件: ml/pitd_dynamics_engineer.py
"""

import os
import json
import time
import numpy as np
import pandas as pd
from typing import List, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class DynamicsEngineer:
    """动力学层特征工程

    用法:
        engineer = DynamicsEngineer(mass_mode='stablecoin_mcap')
        features = engineer.extract_series(prices, kinematics_features)
    """

    FEATURE_NAMES: List[str] = [
        # 基础动力学量 (4维)
        "dyn_force_net",            # 合力 F = m×a - μ×m×σ
        "dyn_momentum",             # 动量 P = m×v
        "dyn_kinetic_energy",       # 动能 E_k = ½×m×v²
        "dyn_mass",                 # 质量m（流动性环境）
        # 周线动力学 (2维)
        "dyn_force_W",              # 周线合力
        "dyn_momentum_W",           # 周线动量
        # 动量传递效率 (3维) — 理论1核心
        "dyn_coupling_eta",         # 大小周期动量传递效率
        "dyn_force_ratio_WD",       # 大小周期力比 |F_W|/|F_D|
        "dyn_friction_ratio",       # 摩擦力占比 μ×m×σ/(m×|a|+ε)
    ]

    def __init__(
        self,
        mass_mode: str = "stablecoin_mcap",
        friction_coef: float = 0.1,
        coupling_window: int = 20,
        stablecoin_cache_path: Optional[str] = None,
    ):
        """初始化动力学特征工程

        参数:
            mass_mode: 质量定义模式
                - 'stablecoin_mcap': 稳定币总市值标准化（主方案）
                - 'volume_normalized': 标准化成交量 Volume/Volume_MA（备选）
                - 'constant': 恒定质量m=1.0（退化模式）
            friction_coef: 摩擦系数μ，默认0.1
            coupling_window: 动量传递效率计算窗口，默认20日
            stablecoin_cache_path: 稳定币市值数据缓存路径
        """
        self.mass_mode = mass_mode
        self.friction_coef = friction_coef
        self.coupling_window = coupling_window
        self.stablecoin_cache_path = stablecoin_cache_path or os.path.join(
            BASE_DIR, "data/historical/stablecoin_mcap.json"
        )
        self._stablecoin_data = None  # 懒加载

    def get_feature_names(self) -> List[str]:
        return self.FEATURE_NAMES.copy()

    def _fetch_stablecoin_mcap(self) -> Optional[pd.DataFrame]:
        """通过DefiLlama API获取稳定币总市值历史数据

        API: https://stablecoins.llama.fi/stablecoincharts/all
        返回: DataFrame(index=date, columns=['total_mcap']) 或 None
        """
        if self._stablecoin_data is not None:
            return self._stablecoin_data

        # 先尝试读缓存
        if os.path.exists(self.stablecoin_cache_path):
            try:
                with open(self.stablecoin_cache_path) as f:
                    data = json.load(f)
                df = pd.DataFrame(data)
                df["date"] = pd.to_datetime(df["date"], unit="s")
                df = df.set_index("date").sort_index()
                self._stablecoin_data = df
                print("  [Dynamics] 稳定币市值数据从缓存加载: {}条".format(len(df)))
                return df
            except Exception as e:
                print("  [Dynamics] 缓存读取失败: {}".format(e))

        # 尝试API获取
        print("  [Dynamics] 尝试从DefiLlama获取稳定币市值数据...")
        try:
            url = "https://stablecoins.llama.fi/stablecoincharts/all"
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=30) as resp:
                raw = json.loads(resp.read().decode())

            records = []
            for item in raw:
                ts = item.get("date")
                mcap = item.get("totalCirculating", {}).get("peggedUSD")
                if ts and mcap:
                    records.append({"date": ts, "total_mcap": float(mcap)})

            if not records:
                print("  [Dynamics] DefiLlama返回空数据")
                return None

            df = pd.DataFrame(records)
            df["date"] = pd.to_datetime(df["date"], unit="s")
            df = df.set_index("date").sort_index()
            df = df[~df.index.duplicated(keep="last")]

            # 保存缓存
            os.makedirs(os.path.dirname(self.stablecoin_cache_path), exist_ok=True)
            df_reset = df.reset_index()
            df_reset["date"] = df_reset["date"].astype(np.int64) // 10**9
            with open(self.stablecoin_cache_path, "w") as f:
                json.dump(df_reset.to_dict("records"), f)

            print("  [Dynamics] DefiLlama获取成功: {}条, 范围 {} ~ {}".format(
                len(df), df.index[0].date(), df.index[-1].date()))
            self._stablecoin_data = df
            return df

        except (URLError, json.JSONDecodeError, KeyError, Exception) as e:
            print("  [Dynamics] DefiLlama API失败: {}".format(e))
            return None

    def _compute_mass(self, prices: pd.DataFrame) -> np.ndarray:
        """计算质量m(t)"""
        n = len(prices)

        if self.mass_mode == "constant":
            return np.ones(n)

        if self.mass_mode == "volume_normalized":
            vol = prices["volume"].values.astype(float)
            vol_ma = pd.Series(vol).rolling(window=20, min_periods=1).mean().values
            mass = vol / (vol_ma + 1e-10)
            # 裁剪极端值
            return np.clip(mass, 0.1, 10.0)

        if self.mass_mode == "stablecoin_mcap":
            sc_data = self._fetch_stablecoin_mcap()
            if sc_data is None:
                # 回退到volume_normalized
                print("  [Dynamics] 稳定币数据不可用，回退到volume_normalized")
                vol = prices["volume"].values.astype(float)
                vol_ma = pd.Series(vol).rolling(window=20, min_periods=1).mean().values
                mass = vol / (vol_ma + 1e-10)
                return np.clip(mass, 0.1, 10.0)

            # 对齐稳定币市值到价格时间轴
            sc_mcap = sc_data["total_mcap"].reindex(prices.index, method="ffill")
            # 前向填充仍为NaN的用向后填充
            sc_mcap = sc_mcap.fillna(method="bfill")
            if sc_mcap.isna().any():
                # 如果全NaN，回退
                print("  [Dynamics] 稳定币数据对齐失败，回退到volume_normalized")
                vol = prices["volume"].values.astype(float)
                vol_ma = pd.Series(vol).rolling(window=20, min_periods=1).mean().values
                mass = vol / (vol_ma + 1e-10)
                return np.clip(mass, 0.1, 10.0)

            mcap_values = sc_mcap.values
            mcap_ma = pd.Series(mcap_values).rolling(window=20, min_periods=1).mean().values
            mass = mcap_values / (mcap_ma + 1e-10)
            return np.clip(mass, 0.1, 10.0)

        return np.ones(n)

    def extract_series(
        self,
        prices: pd.DataFrame,
        kinematics_features: pd.DataFrame,
    ) -> pd.DataFrame:
        """批量计算动力学特征

        参数:
            prices: 日线OHLCV
            kinematics_features: Phase 1运动学特征（需包含v_D/a_D/v_W/a_W）

        返回:
            DataFrame, 9维动力学特征
        """
        n = len(prices)
        result = pd.DataFrame(index=prices.index, columns=self.FEATURE_NAMES, dtype=float)

        # 计算质量
        mass = self._compute_mass(prices)

        # 获取运动学量
        v_D = kinematics_features["kin_velocity_D"].values
        a_D = kinematics_features["kin_acceleration_D"].values
        v_W = kinematics_features["kin_velocity_W"].values
        a_W = kinematics_features["kin_acceleration_W"].values

        # 波动幅度（温度）σ = ATR/P
        high = prices["high"].values
        low = prices["low"].values
        close = prices["close"].values
        tr = np.maximum(
            high - low,
            np.maximum(
                np.abs(high - np.roll(close, 1)),
                np.abs(low - np.roll(close, 1)),
            ),
        )
        tr[0] = high[0] - low[0]
        atr = pd.Series(tr).rolling(window=14, min_periods=1).mean().values
        sigma = atr / (close + 1e-10)

        # === 基础动力学量 ===
        eps = 1e-10

        # 合力 F = m×a - μ×m×σ
        force_net = mass * a_D - self.friction_coef * mass * sigma
        result["dyn_force_net"] = force_net

        # 动量 P = m×v
        result["dyn_momentum"] = mass * v_D

        # 动能 E_k = ½×m×v²
        result["dyn_kinetic_energy"] = 0.5 * mass * v_D ** 2

        # 质量m
        result["dyn_mass"] = mass

        # === 周线动力学 ===
        result["dyn_force_W"] = mass * a_W - self.friction_coef * mass * sigma
        result["dyn_momentum_W"] = mass * v_W

        # === 动量传递效率 η ===
        # η = corr(v_W, v_D, window) × |v_W| / (|v_W| + |v_D| + ε)
        v_W_s = pd.Series(v_W, index=prices.index)
        v_D_s = pd.Series(v_D, index=prices.index)
        rolling_corr = v_W_s.rolling(window=self.coupling_window, min_periods=5).corr(v_D_s)
        speed_ratio = np.abs(v_W) / (np.abs(v_W) + np.abs(v_D) + eps)
        coupling_eta = rolling_corr.values * speed_ratio
        # η可能在[-1, 1]，取绝对值表示耦合强度
        result["dyn_coupling_eta"] = np.abs(coupling_eta)

        # 大小周期力比 |F_W|/|F_D|
        force_W = mass * a_W - self.friction_coef * mass * sigma
        force_D = mass * a_D - self.friction_coef * mass * sigma
        result["dyn_force_ratio_WD"] = np.abs(force_W) / (np.abs(force_D) + eps)

        # 摩擦力占比
        friction = self.friction_coef * mass * sigma
        driver = mass * np.abs(a_D) + eps
        result["dyn_friction_ratio"] = friction / driver

        # 处理NaN和Inf
        result = result.fillna(0.0).replace([np.inf, -np.inf], 0.0)
        return result

    def physics_sanity_check(
        self,
        prices: pd.DataFrame,
        kinematics_features: pd.DataFrame,
    ) -> dict:
        """物理意义检验"""
        feats = self.extract_series(prices, kinematics_features)
        mass = feats["dyn_mass"].values
        eta = feats["dyn_coupling_eta"].values

        # 检验1: 质量m>0且变化
        mass_positive = (mass > 0).mean()
        mass_cv = float(np.std(mass) / (np.mean(mass) + 1e-10))  # 变异系数

        # 检验2: 动量方向与速度方向一致 sign(P)==sign(v)
        v_D = kinematics_features["kin_velocity_D"].values
        P = feats["dyn_momentum"].values
        momentum_sign_ok = ((np.sign(P) == np.sign(v_D)) | (np.abs(v_D) < 1e-8)).mean()

        # 检验3: 动能非负
        E_k = feats["dyn_kinetic_energy"].values
        kinetic_nonneg = (E_k >= 0).mean()

        # 检验4: η在[0,1]范围
        eta_in_range = ((eta >= 0) & (eta <= 1)).mean()

        # 检验5: 强趋势时η高（|v_W|大时η应高）
        v_W = kinematics_features["kin_velocity_W"].values
        strong_trend_mask = np.abs(v_W) > np.percentile(np.abs(v_W), 70)
        weak_trend_mask = np.abs(v_W) < np.percentile(np.abs(v_W), 30)
        eta_strong = eta[strong_trend_mask].mean() if strong_trend_mask.sum() > 0 else 0
        eta_weak = eta[weak_trend_mask].mean() if weak_trend_mask.sum() > 0 else 0
        eta_ratio = eta_strong / (eta_weak + 1e-10)

        return {
            "mass_mode": self.mass_mode,
            "mass_positive_rate": float(mass_positive),
            "mass_cv": float(mass_cv),
            "momentum_sign_correct": float(momentum_sign_ok),
            "kinetic_energy_nonneg": float(kinetic_nonneg),
            "eta_in_range": float(eta_in_range),
            "eta_strong_trend": float(eta_strong),
            "eta_weak_trend": float(eta_weak),
            "eta_strong_weak_ratio": float(eta_ratio),
            "mass_range": (float(mass.min()), float(mass.max())),
            "eta_range": (float(eta.min()), float(eta.max())),
            "verdict": "✅ 物理意义合理" if (
                mass_positive > 0.99 and momentum_sign_ok > 0.95
                and kinetic_nonneg > 0.99 and eta_in_range > 0.95
            ) else "⚠️ 需检查",
        }
