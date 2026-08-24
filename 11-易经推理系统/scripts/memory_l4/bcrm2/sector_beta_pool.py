"""Phase 1 · v4_layer1 模块：SectorBetaPool（5 板块龙头相对 BTC 的β/α/相关系数）

输出列（15 列）5×(β,α,correl)：
  defi_beta_252d,  defi_alpha_60d,  defi_correl_btc_60d,
  ai_beta_252d,    ai_alpha_60d,    ai_correl_btc_60d,
  rwa_beta_252d,   rwa_alpha_60d,   rwa_correl_btc_60d,
  meme_beta_252d,  meme_alpha_60d,  meme_correl_btc_60d,
  l2_beta_252d,    l2_alpha_60d,    l2_correl_btc_60d,
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd


SECTORS: Dict[str, tuple[str, ...]] = {
    "defi":  ("UNI", "AAVE", "COMP", "LINK"),
    "ai":    ("FET", "AGIX", "RNDR", "AR"),
    "rwa":   ("ONDO", "SYN", "PROP", "TRAC"),
    "meme":  ("PEPE", "DOGE", "SHIB", "WIF"),
    "l2":    ("OP",  "ARB",  "STRK", "IMX"),
}


def _rolling_beta(rp: pd.Series, rb: pd.Series, window: int) -> pd.Series:
    """滚动 252d β = Cov(rp,rb)/Var(rb)"""
    cov = rp.rolling(window, min_periods=max(20, window // 6)).cov(rb)
    var = rb.rolling(window, min_periods=max(20, window // 6)).var()
    return cov / var.replace(0, np.nan)


def _rolling_corr(rp: pd.Series, rb: pd.Series, window: int) -> pd.Series:
    return rp.rolling(window, min_periods=max(10, window // 10)).corr(rb)


class SectorBetaPool:
    """
    参数：
      coins_closes: {symbol: pd.Series(时间对齐的 close)}。典型：
        coins_closes["BTC"] = BTC 的 close Series
        coins_closes["UNI"], coins_closes["AAVE"], ... 各龙头
      若 coins_closes 缺失或 BTC 缺失 → 所有 15 列输出 NaN（但列名仍保证存在）。
    """

    COLUMNS = [
        f"{s}_{metric}" for s in SECTORS.keys()
        for metric in ("beta_252d", "alpha_60d", "correl_btc_60d")
    ]

    def compute(
        self,
        df: pd.DataFrame,
        coins_closes: Optional[Dict[str, pd.Series]] = None,
    ) -> pd.DataFrame:
        out = pd.DataFrame(index=df.index)
        idx = df.index
        btc_close = None
        if coins_closes:
            for k in ("BTC", "BTCUSDT", "BTC-USDT"):
                if k in coins_closes:
                    btc_close = coins_closes[k].reindex(idx).ffill().astype(float)
                    break
        # 没拿到 BTC ref → 全 NaN
        if btc_close is None or not coins_closes:
            for col in self.COLUMNS:
                out[col] = np.nan
            return out

        btc_ret = np.log(btc_close / btc_close.shift(1))

        for sector, symbols in SECTORS.items():
            # 板块 4 个龙头等权合成价格（缺失的龙头自动用剩余龙头等权替代；全缺则 NaN）
            panel: list[pd.Series] = []
            for s in symbols:
                if s in coins_closes:
                    cs = coins_closes[s].reindex(idx).ffill().astype(float)
                    # 标准化到第一天=1.0，避免价格量纲影响等权
                    first_valid = cs.first_valid_index()
                    if first_valid is not None and cs.loc[first_valid] > 0:
                        cs = cs / cs.loc[first_valid]
                    panel.append(cs)
            if not panel:
                out[f"{sector}_beta_252d"] = np.nan
                out[f"{sector}_alpha_60d"] = np.nan
                out[f"{sector}_correl_btc_60d"] = np.nan
                continue
            pclose = pd.concat(panel, axis=1).mean(axis=1, skipna=True)
            pret = np.log(pclose / pclose.shift(1))
            beta = _rolling_beta(pret, btc_ret, 252)
            correl = _rolling_corr(pret, btc_ret, 60)
            # 60 日 α：平均每日超额（简单均值，简化）
            excess = pret - beta * btc_ret
            alpha = excess.rolling(60, min_periods=10).mean()
            out[f"{sector}_beta_252d"] = beta
            out[f"{sector}_alpha_60d"] = alpha
            out[f"{sector}_correl_btc_60d"] = correl
        return out


# ============================================================
# FeatureRegistry 注册
# ============================================================
from bcrm2.feature_registry import FeatureRegistry  # noqa: E402

FeatureRegistry.register(name="sector_beta_pool", factory=SectorBetaPool)
