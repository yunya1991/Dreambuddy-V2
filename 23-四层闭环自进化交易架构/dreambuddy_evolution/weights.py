"""
default_weights.py — 蓝图附录 C R-1 集中权重 & 阈值档边界
----------------------------------------------------------------
唯一权威源（硬约束：零散落硬编码）。所有 4 组权重比 + 阈值档边界 + FAIL-OPEN 降级常量必须从此文件 import，
不得在各引擎内部硬编码（R-1评审要求）。
版本: WEIGHTS_VERSION = "1.0-MVP"
----------------------------------------------------------------
权重来源先验（蓝图附录C）：
  ESS       4:4:2  Livermore 中央点把握(H) + Wyckoff 供需结构(S) + Schluter 样本收敛(N辅助) → H:S 平权 8成，N 2成
  R_REFL    4:3:3  Soros 反身性启动 corr>liq通道 ≈ sent羊群 → 启动最高4，通道/羊群平权
  CS        0.4:0.3:0.3 解析Level0(无过拟合) > ESS_top(统计) ≈ CBR_top(案例检索) → Level0最高40%，两者平权30%
  CM        4:3:3  美林时钟(4-6年长周期) > 蓄水池(月度) ≈ CrossVal(即期) → 周期越长权重越高
FAIL-OPEN 降级值（蓝图附录 A C-3 ε=0.01硬约束）：
  RI        = 0.29  严格 < RI档首边界 0.30（ε=0.01，5个标准差安全裕度 蓝图附录A证明）
  CMScore   = 0.45  严格在中性档(0.35, 0.55)内部，不触发±boost（等价baseline）
  R_5dim    = 0.50  5 维阻力向量统一中性兜底值
"""

from __future__ import annotations

# -------- 版本号（MVP交付基线，TR-W-SENS-17 精确等于"1.0-MVP"）------------------
WEIGHTS_VERSION: str = "1.0-MVP"

# -------- 4 组权重比（蓝图附录 C R-1 三祖师经验域贝叶斯先验）--------------------
WEIGHTS: dict = {
    "ESS": {
        "H": 0.4,          # 把握度：Livermore 中央点 Hox级权重
        "S": 0.4,          # 结构性：Wyckoff 供需累积/派发 S 级
        "N_ratio": 0.2,    # 样本量校正：Schluter gmax 收敛辅助 2成
        "N_scale": 500,    # N=500 时 sqrt(N/500)=1，clamp上限
    },
    "R_REFL": {
        "corr": 0.4,       # 价格-市值相关性（索罗斯反身性第一因启动）
        "liq": 0.3,        # 流动性（反馈环持续通道保障）
        "sent": 0.3,       # 情绪（FinBERT + 社交，羊群效应放大器）
    },
    "CS": {
        "Level0": 0.4,     # 解析计算 Level0（无训练偏差，可重复可解释 → 最高）
        "ESS_top": 0.3,    # ESS 统计最优（历史样本过拟合风险中等）
        "CBR_top": 0.3,    # CBR 历史案例匹配（同统计类，平权）
    },
    "CM": {
        "ML": 0.4,         # 美林时钟 4象限（年/季度周期，最长线=权重最高）
        "Reservoir": 0.3,  # 蓄水池资金流（月度节奏）
        "CrossVal": 0.3,   # 三war_state信号交叉一致性（秒到分钟即期，最短=权重最低）
    },
    # -------- 阈值档边界（FO-OPEN降级<首档，ε≥0.005约束）------------------------
    #   任何修改必须同步检查 FALLBACK_VALUES 对应的常量！（CI断言 TR-W-SENS-19/20）
    "BOUNDARIES": {
        # 涟漪扩散 §0.7 4 档（附录A：降级RI=0.29 < 0.30 ε=0.01）
        "RI": [0.30, 0.55, 0.75],
        # 跨市场CMScore §0.8.5 5 档（附录A：降级CM=0.45 ∈(0.35,0.55)中性）
        "CMScore": [0.15, 0.35, 0.55, 0.75],
        # ScaleClassifier §0.6 Quantum档 MVP豁免κ（统一κ=0规则例外）
        "SCALE_KAPPA_QUANTUM": 0.15,
        # Reservoir 缩放校正（评审R-2b: 3.0→150，99分位0.6%→tanh(0.9)=0.72）
        "CM_RESERVOIR_SCALE_M2": 150,
        # TypeTransfer 拉黑双条件（§1.6.4 R-3形式化）：失败率≥67% AND ≥3笔
        "TYPE_TRANSFER_BAN_RATE": 0.67,
        "TYPE_TRANSFER_BAN_COUNT": 3,
        # 冷备 + 滑窗常量
        "COLD_BACKUP_DAYS": 30,
        "WINDOW_7D_HOURS": 168,
    },
}


# -------- FAIL-OPEN 降级值（蓝图附录A C-3 统一语义=等价baseline，绝不触发动作档）---
# 规则：所有降级值必须严格落在"无动作档"内，有 0.005 ≤ ε ≤ 0.020 安全裕度
FALLBACK_VALUES: dict[str, float] = {
    # RippleEngine 涟漪（§0.7.3 + 附录A RI=0.29 < 0.30 ε=0.01）
    "RI": 0.29,
    # CrossMarket（§0.8.5 + 附录A CM=0.45∈中性档(0.35,0.55) ε≥0.10）
    "CMScore": 0.45,
    # ResistanceVector 5 维（A模块 FO-1：单维NaN→0.5，附录 A R_up/R_down/... 同值）
    "R_up": 0.50,
    "R_down": 0.50,
    "R_smooth": 0.50,
    "R_flow": 0.50,
    "R_reflexivity": 0.50,
    # SentimentEngine L1降级（FO-1 USE_FINBERT=0 55/45扣0.15后的sent默认=0.5）
    "SENTIMENT_L1": 0.50,
}


# -------- 类型安全导出（防止直接赋值修改；若需修改需走权重Sobol校准PR + CI冒烟）----
__all__ = [
    "WEIGHTS_VERSION",
    "WEIGHTS",
    "FALLBACK_VALUES",
]
