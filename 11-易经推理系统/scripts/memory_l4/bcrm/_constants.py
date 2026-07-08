"""
BCRM 常量定义。

包含：
- 八卦定义（先天八卦、后天八卦）
- 六十四卦定义
- 方向、状态枚举
- 哲学依据枚举
"""

# ============================================================
# 版本信息
# ============================================================
BCRM_VERSION = "bcrm-v0.2"
FEATURE_DEF_VERSION = "bcrm-fd-v0.2"

# ============================================================
# 八卦（经卦）——三爻
# ============================================================
# 八卦二进制表示：阳爻=1，阴爻=0，从下到上（初爻→上爻）
GUA_QIAN = "qian"      # 乾 ☰ 111 天
GUA_KUN = "kun"        # 坤 ☷ 000 地
GUA_ZHEN = "zhen"      # 震 ☳ 001 雷
GUA_XUN = "xun"        # 巽 ☴ 110 风
GUA_KAN = "kan"        # 坎 ☵ 010 水
GUA_LI = "li"          # 离 ☲ 101 火
GUA_GEN = "gen"        # 艮 ☶ 100 山
GUA_DUI = "dui"        # 兑 ☱ 011 泽

EIGHT_GUAS = [
    GUA_QIAN, GUA_KUN, GUA_ZHEN, GUA_XUN,
    GUA_KAN, GUA_LI, GUA_GEN, GUA_DUI,
]

# 八卦中文名
GUA_NAMES_CN = {
    GUA_QIAN: "乾",
    GUA_KUN: "坤",
    GUA_ZHEN: "震",
    GUA_XUN: "巽",
    GUA_KAN: "坎",
    GUA_LI: "离",
    GUA_GEN: "艮",
    GUA_DUI: "兑",
}

# 八卦自然象征
GUA_NATURE = {
    GUA_QIAN: "天",
    GUA_KUN: "地",
    GUA_ZHEN: "雷",
    GUA_XUN: "风",
    GUA_KAN: "水",
    GUA_LI: "火",
    GUA_GEN: "山",
    GUA_DUI: "泽",
}

# 八卦五行属性
GUA_WUXING = {
    GUA_QIAN: "金",
    GUA_KUN: "土",
    GUA_ZHEN: "木",
    GUA_XUN: "木",
    GUA_KAN: "水",
    GUA_LI: "火",
    GUA_GEN: "土",
    GUA_DUI: "金",
}

# 八卦二进制编码（三爻，初爻在最低位）
GUA_BINARY = {
    GUA_QIAN: 0b111,  # 7
    GUA_KUN: 0b000,   # 0
    GUA_ZHEN: 0b001,  # 1
    GUA_XUN: 0b110,   # 6
    GUA_KAN: 0b010,   # 2
    GUA_LI: 0b101,    # 5
    GUA_GEN: 0b100,   # 4
    GUA_DUI: 0b011,   # 3
}

# 反向映射：二进制 → 卦名
BINARY_TO_GUA = {v: k for k, v in GUA_BINARY.items()}

# 对立卦（错卦）
OPPOSITE_GUAS = {
    GUA_QIAN: GUA_KUN,
    GUA_KUN: GUA_QIAN,
    GUA_ZHEN: GUA_XUN,
    GUA_XUN: GUA_ZHEN,
    GUA_KAN: GUA_LI,
    GUA_LI: GUA_KAN,
    GUA_GEN: GUA_DUI,
    GUA_DUI: GUA_GEN,
}

# 趋势卦（看涨属性较强）
TREND_GUAS_UP = [GUA_QIAN, GUA_ZHEN, GUA_LI, GUA_DUI]
# 震荡/积累卦
ACCUMULATING_GUAS = [GUA_KUN, GUA_XUN, GUA_KAN, GUA_GEN]

# 阳卦（奇数阳爻为主）：乾、震、坎、艮
YANG_GUAS = [GUA_QIAN, GUA_ZHEN, GUA_KAN, GUA_GEN]
# 阴卦（偶数阳爻为主）：坤、巽、离、兑
YIN_GUAS = [GUA_KUN, GUA_XUN, GUA_LI, GUA_DUI]

# 蓄势卦（艮、兑）→ 趋势卦（乾、坤）
ZHISHI_GUAS = [GUA_GEN, GUA_DUI]
QUSHI_GUAS = [GUA_QIAN, GUA_KUN]


def is_trend_gua(gua: str) -> bool:
    """判断是否为趋势卦。"""
    return gua in TREND_GUAS_UP or gua in [GUA_KAN]


def is_accumulating_gua(gua: str) -> bool:
    """判断是否为积累卦。"""
    return gua in ACCUMULATING_GUAS


def get_gua_yin_yang(gua: str) -> str:
    """获取卦象的阴阳属性：'yang' 或 'yin'。"""
    if gua in YANG_GUAS:
        return "yang"
    return "yin"


def is_zhishi_gua(gua: str) -> bool:
    """判断是否为蓄势卦。"""
    return gua in ZHISHI_GUAS


def is_qushi_gua(gua: str) -> bool:
    """判断是否为趋势卦（乾/坤）。"""
    return gua in QUSHI_GUAS


# ============================================================
# 方向枚举
# ============================================================
DIR_UP = "UP"
DIR_DOWN = "DOWN"
DIR_FLAT = "FLAT"
DIR_TRANSITIONING = "TRANSITIONING"
DIR_UNKNOWN = "UNKNOWN"

# ============================================================
# 螺旋阶段（否定之否定）
# ============================================================
SPIRAL_FIRST_AFFIRMATION = "FIRST_AFFIRMATION"
SPIRAL_FIRST_NEGATION = "FIRST_NEGATION"
SPIRAL_SECOND_NEGATION = "SECOND_NEGATION"
SPIRAL_UNKNOWN = "UNKNOWN"

# ============================================================
# Reason Codes（全大写英文）
# ============================================================
REASON_HIGH_UNCERTAINTY = "HIGH_UNCERTAINTY"
REASON_NO_CONTRADICTION_DATA = "NO_CONTRADICTION_DATA"
REASON_CONTRADICTION_UNRESOLVED = "CONTRADICTION_UNRESOLVED"
REASON_INSUFFICIENT_MEMORY = "INSUFFICIENT_MEMORY"
REASON_AMBIGUOUS_SCENARIO = "AMBIGUOUS_SCENARIO"
REASON_COLD_START_THRESHOLD = "COLD_START_THRESHOLD"
REASON_INSUFFICIENT_NEGATION_HISTORY = "INSUFFICIENT_NEGATION_HISTORY"
REASON_HIGH_CHAOS = "HIGH_CHAOS"
REASON_BULLISH_ALIGNMENT = "BULLISH_ALIGNMENT"
REASON_BEARISH_ALIGNMENT = "BEARISH_ALIGNMENT"
REASON_QUANTITATIVE_CHANGE_PHASE = "QUANTITATIVE_CHANGE_PHASE"
REASON_QUALITATIVE_CHANGE_TRIGGERED = "QUALITATIVE_CHANGE_TRIGGERED"
REASON_LOW_CONFIDENCE = "LOW_CONFIDENCE"

# ============================================================
# 哲学依据枚举
# ============================================================
PHIL_MAO_CONTRADICTION = "MAO_CONTRADICTION"
PHIL_MATERIALIST_DIALECTIC = "MATERIALIST_DIALECTIC"
PHIL_HEGELIAN = "HEGELIAN"
PHIL_YIJING = "YIJING"
PHIL_PRACTICE_THEORY = "PRACTICE_THEORY"

# ============================================================
# 状态机状态
# ============================================================
STATE_TAIJI = "TAIJI"
STATE_LIANGYI = "LIANGYI"
STATE_SIXIANG = "SIXIANG"
STATE_BAGUA = "BAGUA"
STATE_64GUA = "LIU_SHI_SI_GUA"
STATE_TRANSFORMATION = "TRANSFORMATION"
STATE_SPIRAL = "SPIRAL"
STATE_STRATEGY = "STRATEGY"
STATE_QIANKUN = "QIANKUN"
STATE_FAIL_CLOSED = "FAIL_CLOSED"
STATE_COMPLETED = "COMPLETED"

# ============================================================
# 爻变等级
# ============================================================
YAO_CHANGE_NONE = "NONE"
YAO_CHANGE_MINOR = "MINOR"
YAO_CHANGE_MODERATE = "MODERATE"
YAO_CHANGE_MAJOR = "MAJOR"


def yao_change_level(num_changing_yaos: int) -> str:
    """根据动爻数量判断变化等级。"""
    if num_changing_yaos == 0:
        return YAO_CHANGE_NONE
    elif num_changing_yaos <= 2:
        return YAO_CHANGE_MINOR
    elif num_changing_yaos <= 4:
        return YAO_CHANGE_MODERATE
    else:
        return YAO_CHANGE_MAJOR

# ============================================================
# 默认阈值
# ============================================================
DEFAULT_QUALITATIVE_THRESHOLD = 0.7
DEFAULT_SPIRAL_NEGATION_THRESHOLD = 0.6
DEFAULT_HIGH_UNCERTAINTY = 0.8
DEFAULT_HIGH_CHAOS = 0.75
DEFAULT_MIN_MEMORY_CASES = 3
DEFAULT_MIN_CONFIDENCE_THRESHOLD = 0.36

# 质变张力阈值（engine.py 使用）
TENSION_HIGH_THRESHOLD = 0.7       # 高张力阈值
TENSION_MEDIUM_THRESHOLD = 0.6     # 中张力阈值

# 力学引擎参数（force_engine.py 使用）
FORCE_MAGNITUDE_NORM_FACTOR = 2.5  # 力幅值归一化系数
VELOCITY_NORM_FACTOR = 3.0         # 速度归一化系数
CONFIDENCE_WEIGHT_FORCE = 0.25     # 置信度：力幅值权重
CONFIDENCE_WEIGHT_AGREEMENT = 0.25 # 置信度：一致性权重
CONFIDENCE_WEIGHT_VELOCITY = 0.50  # 置信度：速度权重
VELOCITY_ZERO_THRESHOLD = 0.01     # 速度归零阈值
REVERSAL_STRENGTH_THRESHOLD = 0.05 # 转折强度阈值

# 易经引擎参数（yijing_engine.py 使用）
YAO_PROB_ADJUSTMENT_FACTOR = 0.3   # 动爻概率调整系数
YAO_PROB_MAX = 0.6                 # 动爻概率上限
YAO_PROB_REVERSAL_BONUS = 0.15     # 转折预警动爻概率加成
YAO_PROB_REVERSAL_MAX = 0.7        # 转折预警动爻概率上限
PHASE_BOUNDARY_LOW = 0.2           # 爻位低边界
PHASE_BOUNDARY_MID_LOW = 0.4       # 爻位中低边界
PHASE_BOUNDARY_MID = 0.6           # 爻位中边界
PHASE_BOUNDARY_MID_HIGH = 0.8      # 爻位中高边界

# 螺旋否定判定权重（价格40% + 矛盾35% + 卦象25%）
SPIRAL_WEIGHT_PRICE = 0.40
SPIRAL_WEIGHT_CONTRADICTION = 0.35
SPIRAL_WEIGHT_GUA = 0.25
SPIRAL_NEGATION_THRESHOLD = 0.6
SPIRAL_PRICE_REVERSAL_FULL = 0.05  # 5% 反转 = 满分

# 质变双标签法参数
QUALITATIVE_PNL_REVERSAL_THRESHOLD = 0.03  # 3% PnL 反转
QUALITATIVE_LABEL_WINDOW = 5  # 未来 window 个 bar
QUALITATIVE_THRESHOLD_PERCENTILE = 25  # 25 分位数
QUALITATIVE_THRESHOLD_MIN = 0.5
QUALITATIVE_THRESHOLD_MAX = 0.9
QUALITATIVE_THRESHOLD_DEFAULT = 0.8  # 无样本时默认值

# 辩证一致性度量权重
CONSISTENCY_WEIGHT_OPPOSITION = 0.40
CONSISTENCY_WEIGHT_QUANTITATIVE = 0.30
CONSISTENCY_WEIGHT_NEGATION = 0.30
CONSISTENCY_THRESHOLD = 0.7

# 变爻传统概率（易经铜钱法）
YAO_PROB_OLD_YIN = 1 / 16       # 老阴（变）6
YAO_PROB_SHAO_YANG = 5 / 16     # 少阳（不变）7
YAO_PROB_SHAO_YIN = 5 / 16      # 少阴（不变）8
YAO_PROB_OLD_YANG = 5 / 16      # 老阳（变）9

# ============================================================
# 四象（传统）
# ============================================================
SIXIANG_TAIYANG = "taiyang"   # 老阳 ⚌
SIXIANG_SHAOYIN = "shaoyin"   # 少阴 ⚍
SIXIANG_SHAOYANG = "shaoyang" # 少阳 ⚎
SIXIANG_TAIYIN = "taiyin"     # 老阴 ⚏

SIXIANG_LIST = [SIXIANG_TAIYANG, SIXIANG_SHAOYANG, SIXIANG_SHAOYIN, SIXIANG_TAIYIN]

# ============================================================
# 四象（新定义：时空表里）
# ============================================================
# 第一性原理：市场沿阻力最小方向运动 = 力的合成
# 四象 = 四个力场维度
SIXIANG_TIME = "time"          # 时：周期力（康波/中周期/短周期）
SIXIANG_SPACE = "space"        # 空：空间力（斐波那契/价格位置反重力）
SIXIANG_SURFACE = "surface"    # 表：技术力（均线/MACD/RSI 数字化表观）
SIXIANG_CORE = "core"          # 里：内驱力（供需/资金/情绪）

SIXIANG_FORCE_LIST = [SIXIANG_TIME, SIXIANG_SPACE, SIXIANG_SURFACE, SIXIANG_CORE]

# 四象力场权重（里>表>时>空，内驱力最根本）
FORCE_WEIGHT_CORE = 0.35       # 里：供需/资金/情绪 — 最根本的驱动力
FORCE_WEIGHT_SURFACE = 0.30    # 表：技术分析 — 数字化综合体现
FORCE_WEIGHT_TIME = 0.20       # 时：周期 — 时间维度
FORCE_WEIGHT_SPACE = 0.15      # 空：空间 — 反重力效应

# 时间轴映射
TIME_HORIZON_SHORT = 0.3       # 短周期
TIME_HORIZON_MID = 0.6         # 中周期
TIME_HORIZON_LONG = 1.0        # 长周期（康波）

# 空间力参数（弹簧/皮球模型）
SPACE_EQUILIBRIUM = 0.5        # 均衡位置
SPACE_SPRING_K = 2.0           # 弹簧系数：偏离越远反向力越大

# 市场惯性参数
MARKET_MASS_BASE = 1.0         # 基础质量
MARKET_MASS_VOLATILITY_FACTOR = 2.0  # 波动率对质量的影响因子

# 速度衰减（摩擦力）
VELOCITY_DECAY = 0.85          # 每步速度衰减（市场摩擦）
ACCELERATION_DT = 1.0          # 时间步长

# 转折预警阈值
REVERSAL_WARNING_THRESHOLD = 0.15  # 减速超过此值触发预警

# ============================================================
# 小大之辩 — 市场体量自适应参数
# ============================================================
# 连续体量系数 scale ∈ [0, 1]
#   0.0 = 微盘（高波动、短时间、小空间、表强里弱）
#   0.5 = 中盘
#   1.0 = 超大盘（低波动、长时间、大空间、里强表弱）

# 体量→波动率基准
SCALE_VOLATILITY_BASE = 0.5      # 中盘基准波动率
SCALE_VOLATILITY_RANGE = 0.4     # 小盘+0.2, 大盘-0.2

# 体量→时间尺度
SCALE_TIME_SHORT = 0.2           # 微盘短期权重
SCALE_TIME_MID = 0.5             # 中盘中期权重
SCALE_TIME_LONG = 0.8            # 超大盘长期权重

# 体量→空间振幅敏感度
SCALE_SPACE_SENSITIVITY_SMALL = 3.0   # 微盘：小幅变动即触发
SCALE_SPACE_SENSITIVITY_LARGE = 1.0   # 超大盘：需要大幅变动才触发

# 体量→表里权重偏移
# 小体量：表（技术）> 里（基本面），消息驱动
# 大体量：里（基本面）> 表（技术），价值驱动
SCALE_SURFACE_WEIGHT_SMALL = 0.40  # 微盘技术力权重
SCALE_SURFACE_WEIGHT_LARGE = 0.20  # 超大盘技术力权重
SCALE_CORE_WEIGHT_SMALL = 0.20     # 微盘内驱力权重
SCALE_CORE_WEIGHT_LARGE = 0.45     # 超大盘内驱力权重

# 体量→市场质量
SCALE_MASS_SMALL = 0.5            # 微盘质量小，容易加速
SCALE_MASS_LARGE = 2.0            # 超大盘质量大，惯性大

# 体量→速度衰减
SCALE_DECAY_SMALL = 0.70          # 微盘衰减快（短期效应）
SCALE_DECAY_LARGE = 0.92          # 超大盘衰减慢（长期趋势）

# 体量→置信度阈值
SCALE_CONFIDENCE_THRESHOLD_SMALL = 0.30  # 微盘门槛低
SCALE_CONFIDENCE_THRESHOLD_LARGE = 0.45  # 超大盘门槛高

# 体量→转折预警阈值
SCALE_REVERSAL_THRESHOLD_SMALL = 0.10  # 微盘小减速即预警
SCALE_REVERSAL_THRESHOLD_LARGE = 0.25  # 超大盘需要大减速

# ============================================================
# 两仪 — 宏观（美林时钟）× 微观（生命周期）
# ============================================================
# 太极=本体（小大之辩/scale），两仪=双时间维度周期
# 两仪生四象：两仪状态影响时空表里参数偏置

# --- 宏观美林时钟4阶段（春夏秋冬）---
MACRO_RECOVERY = "recovery"      # 复苏（春）：GDP↑ + CPI↓ + 利率↓
MACRO_OVERHEAT = "overheat"      # 过热（夏）：GDP↑ + CPI↑ + 利率↑
MACRO_STAGFLATION = "stagflation"  # 滞胀（秋）：GDP↓ + CPI↑ + 利率↑
MACRO_RECESSION = "recession"     # 衰退（冬）：GDP↓ + CPI↓ + 利率↓

MACRO_PHASES = [MACRO_RECOVERY, MACRO_OVERHEAT, MACRO_STAGFLATION, MACRO_RECESSION]
MACRO_PHASES_CN = {
    MACRO_RECOVERY: "复苏",
    MACRO_OVERHEAT: "过热",
    MACRO_STAGFLATION: "滞胀",
    MACRO_RECESSION: "衰退",
}
MACRO_SEASON = {
    MACRO_RECOVERY: "春",
    MACRO_OVERHEAT: "夏",
    MACRO_STAGFLATION: "秋",
    MACRO_RECESSION: "冬",
}

# --- 微观生命周期4阶段（春夏秋冬，作物之于）---
MICRO_SPROUT = "sprout"    # 萌芽（春）：price_position<0.25，趋势刚启动
MICRO_GROWTH = "growth"    # 生长（夏）：0.25-0.6，趋势强
MICRO_MATURE = "mature"    # 成熟（秋）：0.6-0.85，趋势减弱
MICRO_DECLINE = "decline"  # 衰落（冬）：>0.85 或趋势消失

MICRO_PHASES = [MICRO_SPROUT, MICRO_GROWTH, MICRO_MATURE, MICRO_DECLINE]
MICRO_PHASES_CN = {
    MICRO_SPROUT: "萌芽",
    MICRO_GROWTH: "生长",
    MICRO_MATURE: "成熟",
    MICRO_DECLINE: "衰落",
}
MICRO_SEASON = {
    MICRO_SPROUT: "春",
    MICRO_GROWTH: "夏",
    MICRO_MATURE: "秋",
    MICRO_DECLINE: "冬",
}

# --- 两仪季节→四象权重偏置 ---
# 春（生发期）→ 时权重↑：时间敏感，周期力主导
# 夏（活跃期）→ 表权重↑：表观活跃，技术力主导
# 秋（成熟期）→ 里权重↑：内因主导，供需资金决定
# 冬（蛰伏期）→ 空权重↑：空间反转力主导，跌多了会反弹
LIANGYI_SEASON_BIAS = {
    "春": {"time": +0.05, "space": +0.00, "surface": -0.02, "core": -0.03},
    "夏": {"time": -0.02, "space": -0.03, "surface": +0.06, "core": -0.01},
    "秋": {"time": -0.01, "space": -0.02, "surface": -0.02, "core": +0.05},
    "冬": {"time": -0.03, "space": +0.06, "surface": -0.01, "core": -0.02},
}

# --- 两仪共振/对冲系数 ---
# 宏观微观同季 → 共振放大（confidence × 1.05）
# 宏观微观反季（春↔秋，夏↔冬）→ 对冲减弱（confidence × 0.85）
# 相邻季节 → 中性（confidence × 1.00）
# 注：经回测调优，共振放大不需太强（1.05优于1.10），对冲惩罚需更强（0.85优于0.92）
LIANGYI_RESONANCE_BONUS = 1.05   # 同季共振（调优后）
LIANGYI_CONFLICT_PENALTY = 0.85  # 反季对冲（调优后）
LIANGYI_NEUTRAL = 1.00           # 中性

# 季节相反映射（春↔秋，夏↔冬）
SEASON_OPPOSITE = {
    "春": "秋",
    "夏": "冬",
    "秋": "春",
    "冬": "夏",
}

# --- 两仪→力学参数偏置 ---
# 春：质量略减（易启动）+ 衰减加快（短周期）
# 夏：质量中性 + 衰减中性
# 秋：质量略增（惯性大）+ 衰减减慢（趋势延续）
# 冬：质量增（难启动）+ 衰减减慢（旧趋势惯性）
LIANGYI_SEASON_MECH_BIAS = {
    "春": {"mass": -0.10, "decay": -0.03, "conf": -0.02, "reversal": +0.01},
    "夏": {"mass": +0.00, "decay": +0.00, "conf": +0.02, "reversal": +0.00},
    "秋": {"mass": +0.10, "decay": +0.02, "conf": +0.03, "reversal": -0.01},
    "冬": {"mass": +0.15, "decay": +0.03, "conf": -0.03, "reversal": -0.02},
}

# --- 八卦两极定义（时空表里里的两极）---
# 时之两极：起始(阳) vs 终结(阴) — 趋势时间维度
# 空之两极：顶(阳) vs 底(阴) — 价格空间维度
# 表里之两极：实(阳) vs 虚(阴) — 量价能量维度
# 三爻组合 → 2^3 = 8卦
POLE_TIME_START = "time_start"   # 起始
POLE_TIME_END = "time_end"       # 终结
POLE_SPACE_TOP = "space_top"     # 顶
POLE_SPACE_BOTTOM = "space_bottom"  # 底
POLE_ENERGY_REAL = "energy_real"   # 实
POLE_ENERGY_VIRTUAL = "energy_virtual"  # 虚

# 八卦两极阈值
BAGUA_POLE_TIME_THRESHOLD = 0.5    # 时间中点
BAGUA_POLE_SPACE_HIGH = 0.65       # 高位
BAGUA_POLE_SPACE_LOW = 0.35        # 低位
BAGUA_POLE_ENERGY_THRESHOLD = 0.5  # 量价能量中点
