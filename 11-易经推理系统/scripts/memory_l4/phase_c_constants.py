"""
方案 C v3.0 §二 冻结硬编码常量（非 * 参数）
=========================================
带 * 标记的参数（P3/P4/P14/P15）由 Pareto 回测季度校准，
从 runtime/phase_c_default_params.json 加载，无文件则使用本文件默认初值。
"""

# ============================================================
# P5：基线权重时间衰减半衰 = 90 天（硬编码，1 个季度）
# ============================================================
BASELINE_DECAY_HALF_LIFE_DAYS: float = 90.0

# ============================================================
# P6：BCRMContinuityObserver 滚动窗口 N = 5 笔
# ============================================================
BCRM_CONTINUITY_WINDOW_N: int = 5

# ============================================================
# P7：Score_B 公式 continuity:confidence = 60% : 40%
# ============================================================
SCORE_B_CONT_WEIGHT: float = 0.60
SCORE_B_CONF_WEIGHT: float = 0.40

# ============================================================
# P8：S（三层权重的胜率）= 50% S_BCRM + 50% S_cont
# ============================================================
S_GLOBAL_S_BCRM_WEIGHT: float = 0.50
S_GLOBAL_S_CONT_WEIGHT: float = 0.50

# ============================================================
# P10：BTC 自反 λ 惩罚上限 = 0.40 → clip ∈ [0.60, 1.0]
# ============================================================
BTC_REFLEX_PENALTY_MAX: float = 0.40
BTC_REFLEX_LAMBDA_LOW: float = 0.60
BTC_REFLEX_LAMBDA_HIGH: float = 1.0

# ============================================================
# P11：G-01 冷却熔断阈值+时长（硬编码）
# ============================================================
G01_BTC_REFLEX_COOLDOWN_PCT: float = 0.005  # 0.5% 权益损失/踏空
G01_COOLDOWN_SHORT_DAYS: int = 3            # 触发一次 → 关 3 日
G01_COOLDOWN_LONG_DAYS: int = 7             # 连续 3 日 λ≤0.70 → 关 7 日
G01_LONG_TRIGGER_CONSECUTIVE_DAYS: int = 3
G01_LONG_TRIGGER_LAMBDA_THRESH: float = 0.70

# ============================================================
# P12：G-02 组合黑天鹅熔断 3 条门槛（硬编码）
# ============================================================
G02_SAME_DIR_POSITION_COUNT: int = 5         # ① 同方向持仓 ≥ 5 笔
G02_AVG_FLOAT_LOSS_PCT: float = 0.005        # ② 15min 平均浮亏 ≥ 0.50%
G02_BTC_LAMBDA_UPPER: float = 0.75           # ③ BTC λ ≤ 0.75
G02_BLOCK_NEW_OPEN_SECONDS: int = 3600       # 暂停开新仓 1 小时
G02_SL_MULT_ADJ: float = 0.90                # SL × 0.90（微近止损）
G02_TP_MULT_ADJ: float = 1.05                # TP × 1.05（延后止盈）

# ============================================================
# P13：G-04 单日 3% 终极熔断（桥水全天候红线）
# ============================================================
G04_DAILY_DRAWDOWN_THRESHOLD: float = 0.03   # 3.0% 小数表示
G04_SHUTDOWN_HOURS: int = 24                 # 旁路 24h

# ============================================================
# P16：CBR 经典战例库高盈亏/高亏损样本对数（各 100 条 = 200）
# ============================================================
CBR_LIBRARY_HIGH_WIN: int = 100
CBR_LIBRARY_HIGH_LOSS: int = 100
CBR_LIBRARY_TOTAL: int = CBR_LIBRARY_HIGH_WIN + CBR_LIBRARY_HIGH_LOSS

# ============================================================
# P17：WinProb 样本门槛 + Brier 合格线
# ============================================================
WINPROB_G2_MIN_SAMPLES: int = 30
WINPROB_G3_MAX_BRIER: float = 0.25
WINPROB_MULT_LOW: float = 0.80
WINPROB_MULT_HIGH: float = 1.20

# ============================================================
# P9：BTC 自反触发 5 条硬门槛阈值
# ============================================================
P9_BTC_D_PE_POSITIVE: bool = True           # ① D_PE > 0
P9_BTC_CONT_MIN_GRADE: str = "ALIGN_BASIC"  # ② ≥ ALIGN_BASIC（3/5 同向）
P9_BTC_S_BTC_ONLY_MIN: float = 0.60         # ③ S_BTC_only ≥ 0.60
P9_BTC_WINDOW_FILL_RATIO: float = 0.60      # ④ n_rev ≥ 60% × N_windows
P9_BTC_24H_NO_FUSE: bool = True             # ⑤ 24h 未触发大熔断
P9_BTC_N_REV_COOLDOWN_MIN: int = 30         # n_rev 冷却 30 分钟
P9_BTC_PENALTY_DAILY_CAP: float = 0.70      # 单交易日最大惩罚上限 0.70

# ============================================================
# F1 ~ F4 冲突铁则（§五 5.3）
# ============================================================
F1_NEVER_BLOCK_FLOOR: float = 0.05           # F1 永不 BLOCK：底仓 = 5%
F2_P1_BLOCK_CAP_DEFAULT: float = 0.10        # F2：P1 BLOCK → final ≤ 10%（P14* 默认）
F3_DIVERGE_SEVERE_MULT: float = 0.70         # F3：Elder = DIVERGE_SEVERE → × 0.70
F4_BASELINE_BONUS_MULT: float = 1.20         # F4：CBR top1 家族 ≥ θ → × 1.20
F4_BASELINE_SIM_THRESHOLD: float = 0.80      # F4 触发相似度门槛（≥ 0.80）

# ============================================================
# 全局 final_pos_mult clip 上下界（P15* 默认值）
# ============================================================
FINAL_POS_MULT_CLIP_LOW: float = 0.05
FINAL_POS_MULT_CLIP_HIGH_DEFAULT: float = 1.50

# ============================================================
# 三层权重归一化硬约束：任一 ∈ [0.05, 0.80]，Σ = 1
# ============================================================
THREE_LAYER_WEIGHT_MIN: float = 0.05
THREE_LAYER_WEIGHT_MAX: float = 0.80

# ============================================================
# 三层动态权重日级重算：Δ_max（P4* 默认初值）
# ============================================================
DEFAULT_DELTA_MAX: float = 0.10
DEFAULT_WP_COLD: float = 0.45
DEFAULT_WE_COLD: float = 0.30
DEFAULT_WB_COLD: float = 0.25

# ============================================================
# §十 10.2 Fail-open 默认值（L2 ~ L6 降级）
# ============================================================
# L2：三层动态权重 fail-open → 冷启动权重 45:30:25
FAILOPEN_WP: float = 0.45
FAILOPEN_WE: float = 0.30
FAILOPEN_WB: float = 0.25

# L3：ElasticGate3L Score 异常 → 0.10（中性 10%）
FAILOPEN_ELASTIC_MULT: float = 0.10

# L4：BTC 自反闸门异常 → λ = 1.0（零影响）
FAILOPEN_BTC_REFLEX_LAMBDA: float = 1.0

# L5：WinProb 异常 → 1.0（零影响）
FAILOPEN_WINPROB_MULT: float = 1.0

# Elder-ray fail-open：NEUTRAL 档位 0.65
FAILOPEN_ELDER_GRADE: str = "NEUTRAL"
FAILOPEN_ELDER_SCORE: float = 0.65

# BCRMContinuityObserver fail-open：NEUTRAL 档位 0.65
FAILOPEN_CONT_GRADE: str = "NEUTRAL"
FAILOPEN_CONT_SCORE: float = 0.65

# BTC 专属胜率样本 < 5 → 0.50 中性，< 0.60 门槛
FAILOPEN_S_BTC_ONLY_LOW_SAMPLE: float = 0.50

# ============================================================
# CBR 五维核心键权重（5 维=70%，9 维形态=30%）
# ============================================================
CBR_CORE_KEY_WEIGHT: float = 0.70
CBR_MORPH_KEY_WEIGHT: float = 0.30
CBR_CANONICAL_5D_KEYS = ("symbol", "direction", "hexagram_name",
                         "bcrm_confidence_bucket", "p1_output_label")

# ============================================================
# 动态参数默认初值（与 P3/P4/P14/P15/P18 CBR θ/γ 对齐）
# 回测脚本输出到 runtime/phase_c_default_params.json 覆盖
# ============================================================
DYNAMIC_PARAM_DEFAULTS = {
    "wp_cold": 0.45,           # P3* w_P^0
    "we_cold": 0.30,           # P3* w_E^0
    "wb_cold": 0.25,           # P3* w_B^0
    "delta_max": 0.10,         # P4* Δ_max
    "p1_block_cap": 0.10,      # P14* F2 顶
    "global_clip_high": 1.50,  # P15* 全局 clip 上界
    "theta_match_star": 0.80,  # CBR θ_match*
    "gamma_max_star": 0.20,    # CBR γ_max*
}
