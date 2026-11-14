# -*- coding: utf-8 -*-
"""调研族方法编号表（X/O/P/Q/SC）：只提供元数据，不在此登记/实现。

来源：
  - docs/RESEARCH-INSTITUTIONAL-L1-METHODS.md §2（X 12 / O 15 / P 14 / Q 16）
  - docs/RESEARCH-SCIENTIFIC-METHODS.md §2（SC01–SC92）

实现按族分散在 `research_xo.py`（X/O）、`research_pq.py`（P/Q）、
`research_sc_a.py`（SC01–SC46）、`research_sc_b.py`（SC47–SC92），
由各模块用 `register()` 登记；本模块只保证编号/名称/层级/最小样本的口径唯一。
"""

from __future__ import annotations

from typing import Dict, Tuple

from .registry import RegistryError

_SOURCE: Dict[str, str] = {
    "X": "RESEARCH-INSTITUTIONAL-L1-METHODS.md §2.1 横截面统计",
    "O": "RESEARCH-INSTITUTIONAL-L1-METHODS.md §2.2 时间序列算子",
    "P": "RESEARCH-INSTITUTIONAL-L1-METHODS.md §2.3 风险与组合描述",
    "Q": "RESEARCH-INSTITUTIONAL-L1-METHODS.md §2.4 研究与检验协议",
    "SC": "RESEARCH-SCIENTIFIC-METHODS.md §2 科研方法族",
}

# (method_id, name, group, layer, min_n)；layer/min_n 为占位默认值，实现时按调研口径校准
_SPECS: Tuple[Tuple[str, str, str, str, int], ...] = (
    ("X01", "横截面 z-score", "X", "D1", 30),
    ("X02", "横截面百分位 rank", "X", "D1", 30),
    ("X03", "中性化（去均值）", "X", "D1", 30),
    ("X04", "分位组合排序", "X", "D1", 30),
    ("X05", "多空价差", "X", "D1", 30),
    ("X06", "横截面离散度", "X", "D1", 30),
    ("X07", "市场宽度", "X", "D1", 30),
    ("X08", "同向率", "X", "D1", 30),
    ("X09", "因子暴露回归", "X", "D3", 30),
    ("X10", "特质收益", "X", "D3", 30),
    ("X11", "因子收益（WLS）", "X", "D3", 30),
    ("X12", "横截面自相关", "X", "D1", 30),
    ("O01", "delay(x, d)", "O", "D1", 30),
    ("O02", "delta(x, d)", "O", "D1", 30),
    ("O03", "ts_sum(x, d)", "O", "D1", 30),
    ("O04", "ts_mean / ts_std", "O", "D1", 30),
    ("O05", "ts_min / ts_max", "O", "D1", 30),
    ("O06", "ts_argmax / ts_argmin", "O", "D1", 30),
    ("O07", "ts_rank(x, d)", "O", "D1", 30),
    ("O08", "ts_zscore(x, d)", "O", "D1", 30),
    ("O09", "ts_corr(x, y, d)", "O", "D1", 30),
    ("O10", "ts_cov(x, y, d)", "O", "D1", 30),
    ("O11", "decay_linear(x, d)", "O", "D1", 30),
    ("O12", "scale(x, a)", "O", "D1", 30),
    ("O13", "signedpower(x, e)", "O", "D1", 30),
    ("O14", "rank(x)", "O", "D1", 30),
    ("O15", "indneutralize(x, g)", "O", "D1", 30),
    ("P01", "实现波动率", "P", "D1", 60),
    ("P02", "波动率目标换算", "P", "D1", 60),
    ("P03", "逆波动权重", "P", "D1", 60),
    ("P04", "等风险贡献权重", "P", "D3", 60),
    ("P05", "风险贡献分解", "P", "D1", 60),
    ("P06", "协方差收缩（Ledoit-Wolf）", "P", "D3", 60),
    ("P07", "EWMA 波动/协方差", "P", "D1", 60),
    ("P08", "PCA 风险分解", "P", "D3", 60),
    ("P09", "组合 VaR（参数法）", "P", "D1", 60),
    ("P10", "组合 CVaR（历史法）", "P", "D1", 60),
    ("P11", "水下曲线", "P", "D1", 60),
    ("P12", "Brinson 归因", "P", "D1", 60),
    ("P13", "尾部相关", "P", "D2", 60),
    ("P14", "相关性稳定性", "P", "D2", 60),
    ("Q01", "IC / RankIC", "Q", "D2", 250),
    ("Q02", "ICIR", "Q", "D2", 250),
    ("Q03", "IC 衰减表", "Q", "D2", 250),
    ("Q04", "分位单调性检验", "Q", "D2", 250),
    ("Q05", "Fama-MacBeth", "Q", "D3", 250),
    ("Q06", "Newey-West t", "Q", "D2", 250),
    ("Q07", "Deflated Sharpe", "Q", "D2", 250),
    ("Q08", "子样本稳健性", "Q", "D2", 250),
    ("Q09", "参数扰动", "Q", "D2", 250),
    ("Q10", "事件窗 CAR", "Q", "D2", 250),
    ("Q11", "Patell/BMP 标准化检验", "Q", "D2", 250),
    ("Q12", "Bootstrap 置信区间", "Q", "D2", 250),
    ("Q13", "置换检验", "Q", "D2", 250),
    ("Q14", "多重比较校正", "Q", "D2", 250),
    ("Q15", "样本充分性检查", "Q", "D2", 250),
    ("Q16", "PIT 校验", "Q", "D2", 250),
    ("SC01", "统计功效", "SC", "D2", 30),
    ("SC02", "最小样本量", "SC", "D2", 30),
    ("SC03", "等效性检验 TOST", "SC", "D2", 30),
    ("SC04", "置换检验", "SC", "D2", 30),
    ("SC05", "Bootstrap 百分位区间", "SC", "D2", 30),
    ("SC06", "Bootstrap BCa 区间", "SC", "D2", 30),
    ("SC07", "Jackknife 标准误", "SC", "D2", 30),
    ("SC08", "Delta 法误差传播", "SC", "D2", 30),
    ("SC09", "GUM 不确定度合成", "SC", "D2", 30),
    ("SC10", "预测区间", "SC", "D2", 30),
    ("SC11", "容忍区间", "SC", "D2", 30),
    ("SC12", "分割共形区间", "SC", "D2", 30),
    ("SC13", "OLS", "SC", "D2", 30),
    ("SC14", "WLS", "SC", "D2", 30),
    ("SC15", "Logistic 回归", "SC", "D2", 30),
    ("SC16", "Poisson 回归", "SC", "D2", 30),
    ("SC17", "分位数回归", "SC", "D2", 30),
    ("SC18", "Huber 稳健回归", "SC", "D2", 30),
    ("SC19", "Ridge（固定 α）", "SC", "D2", 30),
    ("SC20", "多重共线性 VIF", "SC", "D2", 30),
    ("SC21", "异方差 Breusch-Pagan", "SC", "D2", 30),
    ("SC22", "异方差 White 检验", "SC", "D2", 30),
    ("SC23", "残差自相关 Durbin-Watson", "SC", "D2", 30),
    ("SC24", "影响点 Cook's D / 杠杆", "SC", "D2", 30),
    ("SC25", "单因素 ANOVA", "SC", "D2", 30),
    ("SC26", "双因素 ANOVA", "SC", "D2", 30),
    ("SC27", "ANCOVA", "SC", "D2", 30),
    ("SC28", "重复测量 ANOVA", "SC", "D2", 30),
    ("SC29", "析因设计主效应", "SC", "D2", 30),
    ("SC30", "事后多重比较", "SC", "D2", 30),
    ("SC31", "PCA", "SC", "D2", 30),
    ("SC32", "SVD", "SC", "D2", 30),
    ("SC33", "因子分析", "SC", "D2", 30),
    ("SC34", "ICA", "SC", "D2", 30),
    ("SC35", "图 Lasso（固定 α）", "SC", "D2", 30),
    ("SC36", "层次聚类", "SC", "D2", 30),
    ("SC37", "K-Means（seed=42, k 固定）", "SC", "D2", 30),
    ("SC38", "轮廓系数", "SC", "D2", 30),
    ("SC39", "FFT 频谱", "SC", "D2", 30),
    ("SC40", "Welch 功率谱", "SC", "D2", 30),
    ("SC41", "Lomb-Scargle 周期图", "SC", "D2", 30),
    ("SC42", "离散小波 DWT", "SC", "D2", 30),
    ("SC43", "小波相干", "SC", "D2", 30),
    ("SC44", "Savitzky-Golay 平滑", "SC", "D2", 30),
    ("SC45", "Butterworth 滤波", "SC", "D2", 30),
    ("SC46", "Hilbert 包络/瞬时相位", "SC", "D2", 30),
    ("SC47", "Kalman 滤波（固定 Q/R）", "SC", "D2", 30),
    ("SC48", "互谱相干", "SC", "D2", 30),
    ("SC49", "CUSUM 变点", "SC", "D2", 30),
    ("SC50", "PELT 变点", "SC", "D2", 30),
    ("SC51", "Pettitt 检验", "SC", "D2", 30),
    ("SC52", "Mann-Kendall 趋势", "SC", "D2", 30),
    ("SC53", "Sen 斜率", "SC", "D2", 30),
    ("SC54", "季节 Mann-Kendall", "SC", "D2", 30),
    ("SC55", "香农熵", "SC", "D2", 30),
    ("SC56", "互信息", "SC", "D2", 30),
    ("SC57", "传递熵", "SC", "D2", 30),
    ("SC58", "KL 散度", "SC", "D2", 30),
    ("SC59", "Lempel-Ziv 复杂度", "SC", "D2", 30),
    ("SC60", "样本熵", "SC", "D2", 30),
    ("SC61", "排列熵", "SC", "D2", 30),
    ("SC62", "DFA / Hurst", "SC", "D2", 30),
    ("SC63", "块最大值 GEV 拟合", "SC", "D2", 30),
    ("SC64", "POT / GPD 拟合", "SC", "D2", 30),
    ("SC65", "重现水平", "SC", "D2", 30),
    ("SC66", "Hill 尾指数", "SC", "D2", 30),
    ("SC67", "Moran's I", "SC", "D2", 30),
    ("SC68", "Geary's C", "SC", "D2", 30),
    ("SC69", "半变异函数", "SC", "D2", 30),
    ("SC70", "普通 Kriging", "SC", "D2", 30),
    ("SC71", "网络中心性", "SC", "D2", 30),
    ("SC72", "社区发现", "SC", "D2", 30),
    ("SC73", "Kaplan-Meier", "SC", "D2", 30),
    ("SC74", "Log-rank 检验", "SC", "D2", 30),
    ("SC75", "Cox 比例风险", "SC", "D2", 30),
    ("SC76", "Weibull 拟合", "SC", "D2", 30),
    ("SC77", "MTBF / 失效率", "SC", "D2", 30),
    ("SC78", "控制图", "SC", "D2", 30),
    ("SC79", "固定效应 meta", "SC", "D2", 30),
    ("SC80", "随机效应 meta", "SC", "D2", 30),
    ("SC81", "异质性 I² / Q", "SC", "D2", 30),
    ("SC82", "漏斗图不对称", "SC", "D2", 30),
    ("SC83", "Trim-and-fill", "SC", "D2", 30),
    ("SC84", "缺失机制检验", "SC", "D2", 30),
    ("SC85", "KNN 插补", "SC", "D2", 30),
    ("SC86", "马氏距离离群", "SC", "D2", 30),
    ("SC87", "缺失模式矩阵", "SC", "D2", 30),
    ("SC88", "重复记录检测", "SC", "D2", 30),
    ("SC89", "一致性规则校验", "SC", "D2", 30),
    ("SC90", "PIT 时间校验", "SC", "D2", 30),
    ("SC91", "X-13 风格分解", "SC", "D2", 30),
    ("SC92", "异常点识别", "SC", "D2", 30),
)


_SPEC_BY_ID: Dict[str, Tuple[str, str, str, str, int]] = {row[0]: row for row in _SPECS}


def spec_of(method_id: str) -> Tuple[str, str, str, str, int]:
    """返回 (method_id, name, group, layer, min_n)；未收录则报错。"""
    try:
        return _SPEC_BY_ID[method_id]
    except KeyError as exc:
        raise RegistryError(f"research spec not found: {method_id!r}") from exc


def specs_of(group: str) -> Tuple[Tuple[str, str, str, str, int], ...]:
    """按族（X/O/P/Q/SC）返回全部编号行。"""
    return tuple(row for row in _SPECS if row[2] == group)
