"""哲学贡献特征工程

⚠️ 来源标注：本模块所有特征均来自实践回测验证，非理论假设。
   回测验证：9年数据（2017-10 ~ 2026-07，BTC/ETH/SOL/UNI四币种）
   回测策略：HalvingTopExitStrategy v4（综合评分1.592）
   回测结果：平均收益+1440.30%，夏普0.900，回撤53.46%（vs V2 +307.05%/0.482/65.61%）
   消融分析：减半周期锚定贡献BTC收益+600pp；MA128破位逃顶减少回撤12pp

从V2增强版MA200策略的4条哲学贡献 + V4减半周期逃顶策略的3条哲学贡献，
转化为ML可学习的结构化特征向量。

七条哲学贡献（均经9年回测消融验证）：
1. 分化对待BTC和小币：BTC可以做空，小币禁止做空
   ↳ 验证：UNI做空-99.62%爆仓 → 禁空后+41.76%正收益
2. 左侧抄底 > 右侧做空：周线MA200抄底收益贡献远大于熊市做空
   ↳ 验证：有抄底BTC+457% vs 无抄底+210%，贡献+246pp
3. 分层仓位管理：试探仓(3成) → 确认仓(5成) → 止盈减仓
   ↳ 验证：3/5成仓位+457% 优于 5/7成+398%（仓位过激进反而降收益）
4. 双牛过滤：小币需要BTC+自身双牛才做多
   ↳ 验证：UNI双牛率仅16%，89%时间空仓，避免熊市做多亏损
5. 减半周期锚定：减半后12-18个月为顶部时间窗口，逐步减仓
   ↳ 验证：V4综合评分1.592，贡献+59.2%（相对V2）
6. 四重逃顶机制：越高越卖 + MA128破位 + 反弹卖出 + 时间锚定
   ↳ 验证：V4最大回撤53.46% vs V2的65.61%，减少12pp
7. 左侧抄底优化：周线MA200越跌越买，4层仓位逐步加仓
   ↳ 验证：抄底阶段贡献BTC收益+246pp

特征设计原则：
- 每条哲学贡献拆解为可量化信号（连续值优先，离散标签次之）
- 无未来函数，所有特征向前滚动计算
- 特征可被LightGBM等树模型直接消费
- 同时适用于lr_feature_engineer（日线级）和algo_ensemble（信号级）
- ⚠️ 所有特征携带 practice_validated=True 元信息，标记为实践回测来源

特征清单（26维）：
=== 哲学1: BTC/小币分化 (4维) ===  [来源: v2策略法则2消融验证]
- btc_regime_label:        BTC牛熊状态标签 (1=牛, 0=震荡, -1=熊)
- btc_alt_divergence:      BTC vs 当前币种强弱分化度 [-1, 1]
- is_btc_asset:            当前币种是否为BTC (1/0)
- alt_short_risk_score:    小币做空风险评分 [0, 1]，越高越不适合做空

=== 哲学2: 左侧抄底 (4维) ===  [来源: v2策略法则1消融验证，贡献+246pp]
- weekly_ma200_distance:   价格相对周线MA200的距离百分比
- dip_buy_level:           当前已触发的抄底档位 (0-4)
- dip_buy_position_ratio:  抄底建议仓位比例 [0, 0.8]
- left_side_buy_signal:    左侧抄底信号强度 [0, 1]

=== 哲学3: 分层仓位 (4维) ===  [来源: v2策略法则2消融验证，3/5成优于5/7成]
- bear_short_layer:        做空档位 (0=无, 1=3成, 2=5成)
- fib_tp_remaining_ratio:  斐波那契止盈后剩余仓位比例 [0, 1]
- layered_position_target: 分层仓位目标 [-0.5, 1.0]
- position_adjustment:     仓位调整方向 (1=加仓, 0=持有, -1=减仓)

=== 哲学4: 双牛过滤 (3维) ===  [来源: v2策略法则3消融验证，UNI起死回生]
- btc_bull_confirmed:      BTC牛市确认 (1/0)
- self_bull_confirmed:     自身牛市确认 (1/0)
- double_bull_score:       双牛过滤得分 [0, 1]，1=双牛，0=非牛

=== 哲学5: 减半周期锚定 (3维) ===  [来源: v4策略消融验证，贡献+59.2%]
- halving_months_after:    距上次减半的月数 [0, +∞)
- halving_phase:           减半周期阶段 (normal/warn/danger/peak，编码为0/1/2/3)
- halving_position_cap:    减半周期仓位上限 [0.0, 1.0]

=== 哲学6: MA128破位逃顶 (2维) ===  [来源: v4策略消融验证，减少回撤12pp]
- ma128_distance_pct:      价格距MA128百分比 [-∞, +∞)
- ma128_below_days:        连续低于MA128天数 [0, +∞)

=== 哲学7: 越高越卖 (2维) ===  [来源: v4策略消融验证，V4综合评分1.592]
- ath_drawdown_pct:        距历史高点回撤百分比 [-∞, 0]
- bounce_from_low_pct:     从近期低点反弹幅度 [0, +∞)

=== 哲学8: 量价抄底确认 (2维) ===  [来源: 假设DIP-001，Stage 2.1验证]
- rsi_14:                  14日RSI值 [0, 100]，<30为超卖
- volume_ratio_20d:        当日成交量/20日均量 [0, +∞)，>1.5为放量

=== 哲学9: 周期相似性精选 (2维) ===  [来源: V5.1消融实验，V5.3正式集成]
  验证结果：TOP_EXIT AUC +0.0428, DIP_BUY AUC +0.0283（双场景均提升）
  历史平均顶→底月度跌幅: -23.5% → -51.7% → -61.4% → -68.7% → -80.1%
- drawdown_vs_hist_avg:    当前跌幅 - 历史同月数平均跌幅 (正值=强势)
- cycle_path_similarity:   当前周期路径与历史平均的相似度 [0, 1]

回退特征（计算代码保留，不进入FEATURE_NAMES）：
- V5.1: cycle_phase, drawdown_from_cycle_peak, months_since_cycle_peak,
        bear_phase_progress, vol_regime_ratio, bear_severity_score (AUC下降)
- V5.2: fed_rate_action, fed_months_in_cycle, fed_rate_level,
        fed_easing_btc_dip, fed_hawkish_top (AUC下降)
"""

from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import pandas as pd


def _safe_float(val, default: float = 0.0) -> float:
    """安全转换为 float"""
    try:
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


# ── 特征元信息：标记实践回测来源 ──────────────────────────────────────────
# 每个特征携带 source 和 practice_validated 字段，便于后续优化时溯源
FEATURE_METADATA: Dict[str, Dict[str, Any]] = {
    # 哲学1: BTC/小币分化 — 来源：v2策略消融验证（小币禁空使UNI从-99.62%→+41.76%）
    "btc_regime_label": {
        "source": "practice_backtest",
        "strategy": "EnhancedMA200Strategy v2",
        "philosophy": "BTC/小币分化",
        "validation": "9年4币种回测",
        "practice_validated": True,
        "contribution": "小币禁空前提条件，UNI从-99.62%→+41.76%",
    },
    "btc_alt_divergence": {
        "source": "practice_backtest",
        "strategy": "EnhancedMA200Strategy v2",
        "philosophy": "BTC/小币分化",
        "validation": "9年4币种回测",
        "practice_validated": True,
        "contribution": "量化BTC vs 小币强弱分化，指导跨币种配置",
    },
    "is_btc_asset": {
        "source": "practice_backtest",
        "strategy": "EnhancedMA200Strategy v2",
        "philosophy": "BTC/小币分化",
        "validation": "9年4币种回测",
        "practice_validated": True,
        "contribution": "BTC/小币策略分支路由",
    },
    "alt_short_risk_score": {
        "source": "practice_backtest",
        "strategy": "EnhancedMA200Strategy v2",
        "philosophy": "BTC/小币分化",
        "validation": "9年4币种回测，小币做空均值0.83+",
        "practice_validated": True,
        "contribution": "小币做空风险量化，越高越不应做空",
    },
    # 哲学2: 左侧抄底 — 来源：v2策略消融验证（贡献BTC收益+246pp）
    "weekly_ma200_distance": {
        "source": "practice_backtest",
        "strategy": "EnhancedMA200Strategy v2",
        "philosophy": "左侧抄底",
        "validation": "9年BTC回测，8.5%时间触发抄底",
        "practice_validated": True,
        "contribution": "周线MA200距离是抄底触发的基础信号",
    },
    "dip_buy_level": {
        "source": "practice_backtest",
        "strategy": "EnhancedMA200Strategy v2",
        "philosophy": "左侧抄底",
        "validation": "有抄底+457% vs 无抄底+210%，贡献+246pp",
        "practice_validated": True,
        "contribution": "抄底档位直接决定左侧布局仓位",
        "ml_redundant": True,
        "ml_redundant_reason": "WF验证重要性=0.0，从weekly_ma200_distance派生，LightGBM偏好连续值",
        "ml_redundant_stage": "Stage 2.0/2.1/2.4 WF验证",
    },
    "dip_buy_position_ratio": {
        "source": "practice_backtest",
        "strategy": "EnhancedMA200Strategy v2",
        "philosophy": "左侧抄底",
        "validation": "9年BTC回测",
        "practice_validated": True,
        "contribution": "抄底建议仓位比例，最大80%",
        "ml_redundant": True,
        "ml_redundant_reason": "WF验证重要性=0.0，与dip_buy_level信息重复",
        "ml_redundant_stage": "Stage 2.0/2.1/2.4 WF验证",
    },
    "left_side_buy_signal": {
        "source": "practice_backtest",
        "strategy": "EnhancedMA200Strategy v2",
        "philosophy": "左侧抄底",
        "validation": "9年BTC回测",
        "practice_validated": True,
        "contribution": "左侧抄底信号强度归一化[0,1]",
        "ml_redundant": True,
        "ml_redundant_reason": "WF验证重要性=0.0，三级派生链末端，信息量极低",
        "ml_redundant_stage": "Stage 2.0/2.1/2.4 WF验证",
    },
    # 哲学3: 分层仓位 — 来源：v2策略消融验证（3/5成优于5/7成）
    "bear_short_layer": {
        "source": "practice_backtest",
        "strategy": "EnhancedMA200Strategy v2",
        "philosophy": "分层仓位",
        "validation": "3/5成+457% 优于 5/7成+398%",
        "practice_validated": True,
        "contribution": "做空分层档位，避免一次性满仓被反弹打爆",
    },
    "fib_tp_remaining_ratio": {
        "source": "practice_backtest",
        "strategy": "EnhancedMA200Strategy v2",
        "philosophy": "分层仓位",
        "validation": "9年BTC回测，337天触发斐波那契止盈",
        "practice_validated": True,
        "contribution": "斐波那契止盈后剩余仓位比例",
    },
    "layered_position_target": {
        "source": "practice_backtest",
        "strategy": "EnhancedMA200Strategy v2",
        "philosophy": "分层仓位",
        "validation": "9年4币种回测",
        "practice_validated": True,
        "contribution": "分层仓位目标值[-0.5, 0.8]",
    },
    "position_adjustment": {
        "source": "practice_backtest",
        "strategy": "EnhancedMA200Strategy v2",
        "philosophy": "分层仓位",
        "validation": "9年4币种回测",
        "practice_validated": True,
        "contribution": "仓位调整方向信号",
    },
    # 哲学4: 双牛过滤 — 来源：v2策略消融验证（UNI起死回生）
    "btc_bull_confirmed": {
        "source": "practice_backtest",
        "strategy": "EnhancedMA200Strategy v2",
        "philosophy": "双牛过滤",
        "validation": "9年4币种回测",
        "practice_validated": True,
        "contribution": "BTC牛市确认，双牛过滤条件之一",
    },
    "self_bull_confirmed": {
        "source": "practice_backtest",
        "strategy": "EnhancedMA200Strategy v2",
        "philosophy": "双牛过滤",
        "validation": "9年4币种回测",
        "practice_validated": True,
        "contribution": "自身牛市确认，双牛过滤条件之二",
    },
    "double_bull_score": {
        "source": "practice_backtest",
        "strategy": "EnhancedMA200Strategy v2",
        "philosophy": "双牛过滤",
        "validation": "UNI双牛率仅16%，89%时间空仓→避免熊市做多亏损",
        "practice_validated": True,
        "contribution": "双牛过滤综合得分，1=双牛才做多",
    },
    # 哲学5: 减半周期锚定 — 来源：v4策略消融验证（贡献+59.2%）
    "halving_months_after": {
        "source": "practice_backtest",
        "strategy": "HalvingTopExitStrategy v4",
        "philosophy": "减半周期锚定",
        "validation": "9年BTC回测，V4综合评分1.592",
        "practice_validated": True,
        "contribution": "减半周期时间锚定，12-18个月为顶部窗口",
    },
    "halving_phase": {
        "source": "practice_backtest",
        "strategy": "HalvingTopExitStrategy v4",
        "philosophy": "减半周期锚定",
        "validation": "normal/warn/danger/peak四阶段验证",
        "practice_validated": True,
        "contribution": "减半周期阶段编码，指导仓位上限调整",
    },
    "halving_position_cap": {
        "source": "practice_backtest",
        "strategy": "HalvingTopExitStrategy v4",
        "philosophy": "减半周期锚定",
        "validation": "9年BTC回测，仓位上限从1.0→0.0逐步递减",
        "practice_validated": True,
        "contribution": "减半周期仓位上限，控制顶部风险",
    },
    # 哲学6: MA128破位逃顶 — 来源：v4策略消融验证（减少回撤12pp）
    "ma128_distance_pct": {
        "source": "practice_backtest",
        "strategy": "HalvingTopExitStrategy v4",
        "philosophy": "MA128破位逃顶",
        "validation": "V4最大回撤53.46% vs V2的65.61%",
        "practice_validated": True,
        "contribution": "价格距MA128百分比，破位后逐步减仓",
    },
    "ma128_below_days": {
        "source": "practice_backtest",
        "strategy": "HalvingTopExitStrategy v4",
        "philosophy": "MA128破位逃顶",
        "validation": "9年BTC回测，MA128下方持续时间与回撤相关",
        "practice_validated": True,
        "contribution": "连续低于MA128天数，越长越需要减仓",
    },
    # 哲学7: 越高越卖 — 来源：v4策略消融验证（V4综合评分1.592）
    "ath_drawdown_pct": {
        "source": "practice_backtest",
        "strategy": "HalvingTopExitStrategy v4",
        "philosophy": "越高越卖",
        "validation": "9年BTC回测，减半后18个月见顶",
        "practice_validated": True,
        "contribution": "距历史高点回撤，顶部区域内越高越卖",
    },
    "bounce_from_low_pct": {
        "source": "practice_backtest",
        "strategy": "HalvingTopExitStrategy v4",
        "philosophy": "越高越卖",
        "validation": "9年BTC回测，反弹卖出减少利润回吐",
        "practice_validated": True,
        "contribution": "从近期低点反弹幅度，反弹即卖出",
    },
    # 哲学8: 量价抄底确认 — 来源：假设DIP-001，Stage 2.1验证
    "rsi_14": {
        "source": "hypothesis_testing",
        "strategy": "假设DIP-001",
        "philosophy": "量价抄底确认",
        "validation": "RSI<30超卖 + 周线MA200附近 = 高质量抄底点",
        "practice_validated": False,
        "contribution": "14日RSI值，超卖区域辅助抄底确认",
    },
    "volume_ratio_20d": {
        "source": "hypothesis_testing",
        "strategy": "假设DIP-001",
        "philosophy": "量价抄底确认",
        "validation": "成交量放大确认抄底有效性",
        "practice_validated": False,
        "contribution": "当日成交量/20日均量，放量确认底部",
    },
    # 哲学9: 4年周期趋势预测 — 来源：BTC历史周期统计（V5新增）
    # 沿用V4设定：减半后18个月见顶；历史统计：顶后约12.5月见底，跌幅82.3%
    # 4年牛熊周期 = 减半 → 18月见顶 → 12.5月见底 → 17月累积 → 下次减半
    "cycle_phase": {
        "source": "cycle_statistics",
        "strategy": "V5周期趋势预测",
        "philosophy": "4年周期阶段",
        "validation": "减半后18月见顶(V4) + 历史平均顶到底12.5月",
        "practice_validated": True,
        "contribution": "周期阶段编码(0-3)，判断当前处于4年周期的哪个阶段",
    },
    "drawdown_from_cycle_peak": {
        "source": "cycle_statistics",
        "strategy": "V5周期趋势预测",
        "philosophy": "4年周期阶段",
        "validation": "历史平均顶到底跌幅82.3%，回撤>50%通常已进入熊市",
        "practice_validated": True,
        "contribution": "距当前周期内滚动高点回撤%，判断熊市深度",
    },
    "months_since_cycle_peak": {
        "source": "cycle_statistics",
        "strategy": "V5周期趋势预测",
        "philosophy": "4年周期阶段",
        "validation": "历史平均顶到底12.5月，时间维度判断熊市进度",
        "practice_validated": True,
        "contribution": "距周期内已实现高点的月数，判断距离底部还有多久",
    },
    "bear_phase_progress": {
        "source": "cycle_statistics",
        "strategy": "V5周期趋势预测",
        "philosophy": "4年周期阶段",
        "validation": "历史平均顶到底12.5月，progress=月数/12.5",
        "practice_validated": True,
        "contribution": "熊市进度估计[0,1]，1=预计已到底部",
    },
    # 哲学10: 周期相似性增强 — 来源：3轮历史周期月度跌幅路径对比（V5.1新增）
    "drawdown_vs_hist_avg": {
        "source": "cycle_similarity",
        "strategy": "V5.1周期相似性",
        "philosophy": "周期路径对比",
        "validation": "当前跌幅 - 历史同月数平均跌幅，正值=强势",
        "practice_validated": True,
        "contribution": "当前周期相对历史的强弱偏离，判断是否加速/减速下跌",
    },
    "cycle_path_similarity": {
        "source": "cycle_similarity",
        "strategy": "V5.1周期相似性",
        "philosophy": "周期路径对比",
        "validation": "近3月平均相似度，0.79=当前周期高度相似历史",
        "practice_validated": True,
        "contribution": "周期路径相似度[0,1]，高相似→延续历史趋势",
    },
    "vol_regime_ratio": {
        "source": "cycle_similarity",
        "strategy": "V5.1周期相似性",
        "philosophy": "量能周期位置",
        "validation": "当前30日均量/周期内峰值量，<0.5=熊市缩量",
        "practice_validated": True,
        "contribution": "量能相对周期峰值的比例，判断牛熊状态",
    },
    "bear_severity_score": {
        "source": "cycle_similarity",
        "strategy": "V5.1周期相似性",
        "philosophy": "周期路径对比",
        "validation": "时间进度 × 跌幅进度，综合评估熊市深度",
        "practice_validated": True,
        "contribution": "熊市严重度[0,1]，结合时间和跌幅双维度",
    },
    # 哲学11: 美联储利率周期 — 来源：FOMC决议+宏观流动性理论（V5.2新增）
    # 假设：美联储降息→流动性宽松→BTC上涨（特别在BTC低位时是all in信号）
    #       美联储加息→流动性收紧→BTC下跌（叠加V4见顶信号是开空加大信号）
    "fed_rate_action": {
        "source": "macro_policy",
        "strategy": "美联储利率周期",
        "philosophy": "宏观流动性",
        "validation": "2015-2026年7个周期阶段验证",
        "practice_validated": False,
        "contribution": "当前利率动作方向(-1降息/0持平/+1加息)",
    },
    "fed_months_in_cycle": {
        "source": "macro_policy",
        "strategy": "美联储利率周期",
        "philosophy": "宏观流动性",
        "validation": "周期持续时间与BTC趋势相关",
        "practice_validated": False,
        "contribution": "当前方向持续的月数，判断政策进度",
    },
    "fed_rate_level": {
        "source": "macro_policy",
        "strategy": "美联储利率周期",
        "philosophy": "宏观流动性",
        "validation": "利率水平影响风险资产估值",
        "practice_validated": False,
        "contribution": "当前目标利率上限(%)，绝对水平",
    },
    "fed_easing_btc_dip": {
        "source": "macro_policy",
        "strategy": "美联储利率周期",
        "philosophy": "宏观流动性",
        "validation": "降息+BTC低位=抄底all in组合信号",
        "practice_validated": False,
        "contribution": "降息周期×BTC低位组合信号[0,1]",
    },
    "fed_hawkish_top": {
        "source": "macro_policy",
        "strategy": "美联储利率周期",
        "philosophy": "宏观流动性",
        "validation": "加息+V4见顶=开空加大组合信号",
        "practice_validated": False,
        "contribution": "加息周期×V4见顶组合信号[0,1]",
    },
    # === V5.3 周期相似性精选（2维，消融实验验证通过） ===
    "drawdown_vs_hist_avg": {
        "source": "practice_backtest",
        "strategy": "V5.3周期相似性精选",
        "philosophy": "周期偏离度",
        "validation": "V5.1消融实验→V5.3正式集成，TOP_EXIT +0.0428, DIP_BUY +0.0283",
        "practice_validated": True,
        "contribution": "当前跌幅-历史同月数平均跌幅，正值=强势（独立信息76.4%）",
    },
    "cycle_path_similarity": {
        "source": "practice_backtest",
        "strategy": "V5.3周期相似性精选",
        "philosophy": "周期路径相似度",
        "validation": "V5.1消融实验→V5.3正式集成，与drawdown_vs_hist_avg协同效果最佳",
        "practice_validated": True,
        "contribution": "当前周期路径与历史平均的相似度[0,1]",
    },
    # === V5.4 美联储利率水平（1维，方向4验证通过） ===
    "fed_rate_level": {
        "source": "macro_policy",
        "strategy": "V5.4美联储利率精选",
        "philosophy": "宏观流动性水平",
        "validation": "V5.2消融→V5.4方向4验证，TOP_EXIT +0.0006, DIP_BUY +0.0058",
        "practice_validated": True,
        "contribution": "当前美联储目标利率上限(%)，独立信息占比81.4%",
    },
    # === V5.5 利率×周期交互（1维，方向2验证通过） ===
    "fed_level_x_cycle_sim": {
        "source": "practice_backtest",
        "strategy": "V5.5利率×周期交互",
        "philosophy": "宏观流动性×周期相似度",
        "validation": "V5.5方向2验证，TOP_EXIT +0.0166, DIP_BUY +0.0006",
        "practice_validated": True,
        "contribution": "利率水平 × 周期路径相似度，捕捉宏观流动性对周期路径的调制效应",
    },
}


class PhilosophyFeatureEngineer:
    """哲学贡献特征工程

    ⚠️ 实践回测来源标注
    本工程所有特征均来自 EnhancedMA200Strategy v2 的9年回测消融验证，
    非理论假设。每个特征携带 FEATURE_METADATA 元信息，
    包含 source/practice_validated/contribution 字段便于溯源。

    将v2增强版MA200策略的4条哲学贡献转化为ML特征。
    可独立使用，也可作为lr_feature_engineer/algo_ensemble的特征补充。

    用法:
        engineer = PhilosophyFeatureEngineer()
        feats = engineer.extract(
            prices=daily_df,
            symbol="ETH",
            btc_prices=btc_daily_df,
        )

    查询特征元信息:
        PhilosophyFeatureEngineer.get_feature_metadata("dip_buy_level")
        → {'source': 'practice_backtest', 'practice_validated': True, ...}
    """

    # 特征名列表（28维）
    # 注：V5/V5.1探索的8个周期相似性特征中，6个已回退（AUC下降），
    #     但 drawdown_vs_hist_avg + cycle_path_similarity 经消融实验验证双场景AUC提升，
    #     于V5.3正式集成（TOP_EXIT +0.0428, DIP_BUY +0.0283）。
    #     V5.2探索的5个美联储利率周期特征中，fed_rate_level 经V5.4方向4验证
    #     双场景提升（TOP +0.0006, DIP +0.0058），于V5.4正式集成。
    #     其余V5.2特征已回退，计算代码保留在 extract_series 中作为探索记录。
    FEATURE_NAMES: List[str] = [
        # 哲学1: BTC/小币分化 (4维)
        "btc_regime_label",
        "btc_alt_divergence",
        "is_btc_asset",
        "alt_short_risk_score",
        # 哲学2: 左侧抄底 (4维)
        "weekly_ma200_distance",
        "dip_buy_level",
        "dip_buy_position_ratio",
        "left_side_buy_signal",
        # 哲学3: 分层仓位 (4维)
        "bear_short_layer",
        "fib_tp_remaining_ratio",
        "layered_position_target",
        "position_adjustment",
        # 哲学4: 双牛过滤 (3维)
        "btc_bull_confirmed",
        "self_bull_confirmed",
        "double_bull_score",
        # 哲学5: 减半周期锚定 (3维)
        "halving_months_after",
        "halving_phase",
        "halving_position_cap",
        # 哲学6: MA128破位逃顶 (2维)
        "ma128_distance_pct",
        "ma128_below_days",
        # 哲学7: 越高越卖 (2维)
        "ath_drawdown_pct",
        "bounce_from_low_pct",
        # 哲学8: 量价抄底确认 (2维) — Stage 2.1新增
        "rsi_14",
        "volume_ratio_20d",
        # 哲学9: 周期相似性精选 (2维) — V5.3集成，消融实验验证双场景AUC提升
        "drawdown_vs_hist_avg",
        "cycle_path_similarity",
        # 哲学10: 美联储利率水平 (1维) — V5.4集成，方向4验证双场景提升
        "fed_rate_level",
        # 哲学11: 利率×周期交互 (1维) — V5.5集成，方向2验证双场景提升
        # fed_level_x_cycle_sim: 利率水平 × 周期路径相似度（TOP +0.0166, DIP +0.0006）
        "fed_level_x_cycle_sim",
        # 其余V5/V5.1/V5.2 探索特征已回退，见 extract_series 中注释代码
    ]

    # 比特币减半历史时间点
    BTC_HALVING_DATES = [
        pd.Timestamp("2012-11-28"),
        pd.Timestamp("2016-07-09"),
        pd.Timestamp("2020-05-11"),
        pd.Timestamp("2024-04-20"),
    ]

    # 历史平均顶→底跌幅曲线（3轮周期月度均值，单位%）
    # 来源：btc_cycle_deep_analysis.py 统计结果
    # 月0:-23.5%, 月1:-41.6%, 月2:-44.3%, 月3:-51.7%, 月4:-43.2%, 月5:-52.8%,
    # 月6:-61.4%, 月7:-66.4%, 月8:-64.6%, 月9:-68.7%, 月10:-69.5%, 月11:-74.3%, 月12:-80.1%
    HISTORICAL_PEAK_TO_BOTTOM_DRAWDOWN = [
        -23.5, -41.6, -44.3, -51.7, -43.2, -52.8,
        -61.4, -66.4, -64.6, -68.7, -69.5, -74.3, -80.1,
    ]
    HISTORICAL_AVG_TOTAL_DRAWDOWN_PCT = 82.3  # 历史平均顶到底总跌幅%

    # 美联储利率周期关键时间点（FOMC决议日期，目标利率上限%）
    # 格式: (日期, 利率上限%, 动作方向)  动作: +1=加息开始, -1=降息开始, 0=进入平台
    # 来源: 美联储公开FOMC决议
    FED_RATE_CHANGES = [
        (pd.Timestamp("2008-12-16"), 0.25, -1),  # GFC零利率
        (pd.Timestamp("2015-12-16"), 0.50, +1),  # 加息周期1开始
        (pd.Timestamp("2018-12-19"), 2.50, 0),   # 加息周期1顶点，进入高利率平台1
        (pd.Timestamp("2019-07-31"), 2.25, -1),  # 降息周期1开始
        (pd.Timestamp("2020-03-15"), 0.25, 0),   # 零利率平台开始
        (pd.Timestamp("2022-03-16"), 0.50, +1),  # 加息周期2开始
        (pd.Timestamp("2023-07-26"), 5.50, 0),   # 加息周期2顶点，进入高利率平台2
        (pd.Timestamp("2024-09-18"), 5.00, -1),  # 降息周期2开始
    ]

    def __init__(
        self,
        ma_period: int = 200,
        ma128_period: int = 128,
        slope_period: int = 5,
        warmup_periods: int = 260,
        dip_buy_max_position: float = 0.8,
        dip_buy_levels: int = 4,
        dip_buy_step_pct: float = 5.0,
        bear_short_level1_pct: float = 0.3,
        bear_short_level2_pct: float = 0.5,
        fib_levels: Optional[List[float]] = None,
        # V4减半周期参数
        halving_warn_months: int = 12,
        halving_danger_months: int = 15,
        halving_peak_months: int = 18,
        halving_end_months: int = 24,
        halving_warn_min_position: float = 0.7,
        halving_danger_min_position: float = 0.3,
        halving_peak_min_position: float = 0.0,
        # V4反弹检测参数
        bounce_lookback: int = 5,
        bounce_threshold: float = 0.03,
        # Stage 2.1 量价抄底确认参数
        rsi_period: int = 14,
        volume_ratio_period: int = 20,
        # V5 4年周期趋势预测参数（基于历史统计）
        cycle_bull_run_end_months: int = 12,      # 减半后0-12月=bull_run
        cycle_peak_warn_end_months: int = 18,     # 减半后12-18月=peak_warning
        cycle_bear_end_months: int = 30,          # 减半后18-30月=bear_market
        cycle_avg_peak_to_bottom_months: float = 12.5,  # 历史平均顶到底月数
    ):
        """
        参数:
            ma_period: MA周期（默认200）
            ma128_period: MA128周期（默认128）
            slope_period: 斜率计算周期（默认5）
            warmup_periods: 预热周期（默认260，确保周线MA200有效）
            dip_buy_*: 抄底参数（与EnhancedMA200Strategy一致）
            bear_short_*: 做空分层参数（与EnhancedMA200Strategy一致）
            fib_levels: 斐波那契止盈档位
            halving_*: 减半周期参数（与HalvingTopExitStrategy v4一致）
            bounce_*: 反弹检测参数
        """
        self.ma_period = ma_period
        self.ma128_period = ma128_period
        self.slope_period = slope_period
        self.warmup_periods = warmup_periods
        self.dip_buy_max_position = dip_buy_max_position
        self.dip_buy_levels = dip_buy_levels
        self.dip_buy_step_pct = dip_buy_step_pct
        self.bear_short_level1_pct = bear_short_level1_pct
        self.bear_short_level2_pct = bear_short_level2_pct
        self.fib_levels = fib_levels or [0.236, 0.382, 0.5, 0.618]

        # V4减半周期参数
        self.halving_warn_months = halving_warn_months
        self.halving_danger_months = halving_danger_months
        self.halving_peak_months = halving_peak_months
        self.halving_end_months = halving_end_months
        self.halving_warn_min_position = halving_warn_min_position
        self.halving_danger_min_position = halving_danger_min_position
        self.halving_peak_min_position = halving_peak_min_position

        # V4反弹检测参数
        self.bounce_lookback = bounce_lookback
        self.bounce_threshold = bounce_threshold

        # Stage 2.1 量价抄底确认参数
        self.rsi_period = rsi_period
        self.volume_ratio_period = volume_ratio_period

        # V5 4年周期趋势预测参数（基于历史统计）
        # 减半后0-12月=bull_run(1), 12-18月=peak_warning(2), 18-30月=bear_market(3), 其他=accumulation(0)
        self.cycle_bull_run_end_months = cycle_bull_run_end_months
        self.cycle_peak_warn_end_months = cycle_peak_warn_end_months
        self.cycle_bear_end_months = cycle_bear_end_months
        self.cycle_avg_peak_to_bottom_months = cycle_avg_peak_to_bottom_months

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def extract(
        self,
        prices: pd.DataFrame,
        symbol: str = "BTC",
        btc_prices: Optional[pd.DataFrame] = None,
    ) -> Dict[str, float]:
        """提取单时间点的哲学贡献特征

        参数:
            prices: 当前币种日线OHLCV（需含open/high/low/close/volume列）
            symbol: 当前币种代码
            btc_prices: BTC日线OHLCV（小币需要，BTC自身可传None）

        返回:
            28维特征字典
        """
        is_btc = symbol.upper() in ("BTC", "BITCOIN", "XBT")

        # 计算当前币种的MA200和斜率
        close = prices["close"].values
        ma = self._calc_ma(close)
        ma_slope = self._calc_slope(ma)
        ma128 = self._calc_ma128(close)
        weekly_ma200 = self._calc_weekly_ma200(prices) if is_btc else None

        # 计算BTC regime（小币需要）
        btc_regime_label = 0.0
        btc_bull = False
        btc_ma_slope = 0.0
        btc_ma = None
        if not is_btc and btc_prices is not None:
            btc_close = btc_prices["close"].values
            btc_ma = self._calc_ma(btc_close)
            btc_ma_slope = self._calc_slope(btc_ma)
            btc_regime_label, btc_bull = self._classify_btc_regime(btc_ma, btc_ma_slope)
        elif is_btc:
            btc_regime_label, btc_bull = self._classify_btc_regime(ma, ma_slope)

        # 当前价格和MA状态
        current_price = close[-1] if len(close) > 0 else 0.0
        current_ma = ma[-1] if len(ma) > 0 and not np.isnan(ma[-1]) else 0.0
        current_slope = ma_slope[-1] if len(ma_slope) > 0 else 0.0
        current_ma128 = ma128[-1] if len(ma128) > 0 and not np.isnan(ma128[-1]) else 0.0

        # 获取当前日期
        current_date = prices.index[-1] if len(prices) > 0 else pd.Timestamp.now()

        # === 哲学1: BTC/小币分化 ===
        btc_alt_div = self._calc_btc_alt_divergence(
            current_price, current_slope,
            btc_prices["close"].values[-1] if btc_prices is not None else current_price,
            btc_ma_slope,
            is_btc,
        )
        alt_short_risk = self._calc_alt_short_risk(is_btc, current_slope, btc_regime_label)

        # === 哲学2: 左侧抄底 ===
        weekly_dist = 0.0
        dip_level = 0
        dip_pos = 0.0
        left_signal = 0.0
        if is_btc and weekly_ma200 is not None and not np.isnan(weekly_ma200[-1]) and weekly_ma200[-1] > 0:
            weekly_dist = (weekly_ma200[-1] - current_price) / weekly_ma200[-1] * 100
            if weekly_dist > 0:
                dip_level = min(int(weekly_dist / self.dip_buy_step_pct), self.dip_buy_levels)
                if dip_level > 0:
                    dip_pos = (dip_level / self.dip_buy_levels) * self.dip_buy_max_position
                    left_signal = min(dip_pos / self.dip_buy_max_position, 1.0)

        # === 哲学3: 分层仓位 ===
        price_below = current_price < current_ma if current_ma > 0 else False
        slope_neg = current_slope < 0
        bear_layer = 0
        layered_target = 0.0
        if is_btc and price_below:
            if slope_neg:
                bear_layer = 2
                layered_target = -self.bear_short_level2_pct
            else:
                bear_layer = 1
                layered_target = -self.bear_short_level1_pct
        fib_remaining = 1.0
        if bear_layer > 0 and dip_pos > 0:
            fib_remaining = 1.0
            layered_target = dip_pos
        pos_adjust = self._calc_position_adjustment(
            bear_layer, dip_pos, current_slope, ma_slope
        )

        # === 哲学4: 双牛过滤 ===
        self_bull = bool(current_price > current_ma and current_slope > 0) if current_ma > 0 else False
        double_bull = self._calc_double_bull(is_btc, self_bull, btc_bull)

        # === 哲学5: 减半周期锚定 ===
        halving_months_after = 0.0
        halving_phase = 0.0
        halving_position_cap = 1.0
        if is_btc:
            halving_months_after, halving_phase, halving_position_cap = (
                self._calc_halving_features(current_date)
            )

        # === 哲学6: MA128破位逃顶 ===
        ma128_distance_pct = 0.0
        ma128_below_days = 0.0
        if current_ma128 > 0:
            ma128_distance_pct = (current_price - current_ma128) / current_ma128 * 100
            ma128_below_days = self._calc_ma128_below_days(close, ma128)

        # === 哲学7: 越高越卖 ===
        ath_drawdown_pct = 0.0
        bounce_from_low_pct = 0.0
        if len(close) > 0:
            ath_price = np.max(close[:-1]) if len(close) > 1 else current_price
            if ath_price > 0:
                ath_drawdown_pct = (current_price - ath_price) / ath_price * 100
            bounce_from_low_pct = self._calc_bounce_from_low(close)

        # === 哲学8: 量价抄底确认 ===
        rsi_14 = self._calc_rsi(close)
        volume_ratio_20d = self._calc_volume_ratio(prices)

        # === 哲学9: V5.3周期相似性精选特征（消融实验验证：TOP_EXIT +0.0428, DIP_BUY +0.0283）===
        # 仅计算 drawdown_vs_hist_avg 和 cycle_path_similarity 两个验证通过的特征
        drawdown_vs_hist_avg = 0.0
        cycle_path_similarity = 0.0
        if is_btc:
            # 先计算依赖的周期基础特征
            cycle_phase_val, drawdown_peak_val, months_since_peak_val, bear_progress_val = (
                self._calc_cycle_features_at(prices, close, is_btc)
            )
            drawdown_vs_hist_avg, cycle_path_similarity, _, _ = (
                self._calc_cycle_similarity_features_at(
                    prices, close,
                    prices["volume"].values if "volume" in prices.columns else None,
                    is_btc,
                    cycle_phase_val, drawdown_peak_val, months_since_peak_val, bear_progress_val,
                )
            )

        # === 哲学10: V5.4美联储利率水平（方向4验证：TOP_EXIT +0.0006, DIP_BUY +0.0058）===
        fed_rate_level = 0.25  # 默认值
        _, _, fed_rate_level, _, _ = self._calc_fed_features_at(prices, close, is_btc, weekly_dist)
        if not is_btc:
            fed_rate_level = 0.25

        # === 哲学11: V5.5利率×周期交互（方向2验证：TOP_EXIT +0.0166, DIP_BUY +0.0006）===
        fed_level_x_cycle_sim = fed_rate_level * cycle_path_similarity

        # === 哲学12: V5.1其余6个特征 + V5.2其余4个特征已回退（AUC下降）===
        # 计算代码保留在 _calc_cycle_similarity_features_at / _calc_fed_features_at 方法中

        return {
            # 哲学1
            "btc_regime_label": btc_regime_label,
            "btc_alt_divergence": btc_alt_div,
            "is_btc_asset": 1.0 if is_btc else 0.0,
            "alt_short_risk_score": alt_short_risk,
            # 哲学2
            "weekly_ma200_distance": weekly_dist,
            "dip_buy_level": float(dip_level),
            "dip_buy_position_ratio": dip_pos,
            "left_side_buy_signal": left_signal,
            # 哲学3
            "bear_short_layer": float(bear_layer),
            "fib_tp_remaining_ratio": fib_remaining,
            "layered_position_target": layered_target,
            "position_adjustment": pos_adjust,
            # 哲学4
            "btc_bull_confirmed": 1.0 if btc_bull else 0.0,
            "self_bull_confirmed": 1.0 if self_bull else 0.0,
            "double_bull_score": double_bull,
            # 哲学5
            "halving_months_after": halving_months_after,
            "halving_phase": halving_phase,
            "halving_position_cap": halving_position_cap,
            # 哲学6
            "ma128_distance_pct": ma128_distance_pct,
            "ma128_below_days": ma128_below_days,
            # 哲学7
            "ath_drawdown_pct": ath_drawdown_pct,
            "bounce_from_low_pct": bounce_from_low_pct,
            # 哲学8
            "rsi_14": rsi_14,
            "volume_ratio_20d": volume_ratio_20d,
            # 哲学9: V5.3周期相似性精选 (2维)
            "drawdown_vs_hist_avg": drawdown_vs_hist_avg,
            "cycle_path_similarity": cycle_path_similarity,
            # 哲学10: V5.4美联储利率水平 (1维)
            "fed_rate_level": fed_rate_level,
            # 哲学11: V5.5利率×周期交互 (1维)
            "fed_level_x_cycle_sim": fed_level_x_cycle_sim,
            # V5.1其余6个 + V5.2其余4个探索特征已回退，不返回
        }

    def extract_series(
        self,
        prices: pd.DataFrame,
        symbol: str = "BTC",
        btc_prices: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """批量计算整段历史的哲学贡献特征

        参数:
            prices: 完整日线OHLCV
            symbol: 币种
            btc_prices: BTC完整日线（小币需要）

        返回:
            DataFrame, index=prices.index, 列为28维特征
        """
        n = len(prices)
        result = pd.DataFrame(index=prices.index, columns=self.FEATURE_NAMES, dtype=float)

        is_btc = symbol.upper() in ("BTC", "BITCOIN", "XBT")
        close = prices["close"].values
        ma = self._calc_ma(close)
        ma_slope = self._calc_slope(ma)
        ma128 = self._calc_ma128(close)
        weekly_ma200 = self._calc_weekly_ma200(prices) if is_btc else None

        # 预先计算减半周期特征序列（BTC专用）
        halving_months_arr = np.zeros(n)
        halving_phase_arr = np.zeros(n)
        halving_cap_arr = np.ones(n)
        if is_btc:
            for i in range(n):
                current_date = prices.index[i]
                halving_months_arr[i], halving_phase_arr[i], halving_cap_arr[i] = (
                    self._calc_halving_features(current_date)
                )

        # 预先计算MA128下方天数序列
        ma128_below_days_arr = np.zeros(n)
        consecutive_below = 0
        for i in range(n):
            if not np.isnan(ma128[i]) and ma128[i] > 0 and close[i] < ma128[i]:
                consecutive_below += 1
            else:
                consecutive_below = 0
            ma128_below_days_arr[i] = consecutive_below

        # 预先计算ATH回撤序列
        ath_drawdown_arr = np.zeros(n)
        running_ath = close[0] if n > 0 else 0.0
        for i in range(n):
            if close[i] > running_ath:
                running_ath = close[i]
            if running_ath > 0:
                ath_drawdown_arr[i] = (close[i] - running_ath) / running_ath * 100

        # 预先计算反弹幅度序列
        bounce_from_low_arr = np.zeros(n)
        for i in range(n):
            bounce_from_low_arr[i] = self._calc_bounce_from_low_at(close, i)

        # 预先计算RSI序列
        rsi_arr = self._calc_rsi_series(close)

        # 预先计算成交量比率序列
        volume_arr = prices["volume"].values if "volume" in prices.columns else np.ones(n)
        volume_ratio_arr = self._calc_volume_ratio_series(volume_arr)

        # 预先计算V5 4年周期特征序列（BTC专用）
        # 1. cycle_phase: 周期阶段(0-3)
        # 2. drawdown_from_cycle_peak: 距周期内滚动高点回撤%
        # 3. months_since_cycle_peak: 距周期内已实现高点月数
        # 4. bear_phase_progress: 熊市进度[0,1]
        # V5.1 增强：
        # 5. drawdown_vs_hist_avg: 当前跌幅 - 历史同月数平均跌幅
        # 6. cycle_path_similarity: 近3月平均相似度[0,1]
        # 7. vol_regime_ratio: 当前30日均量/周期内峰值量
        # 8. bear_severity_score: 熊市严重度[0,1] = 时间进度 × 跌幅进度
        cycle_phase_arr = np.zeros(n)
        drawdown_peak_arr = np.zeros(n)
        months_since_peak_arr = np.zeros(n)
        bear_progress_arr = np.zeros(n)
        drawdown_vs_hist_arr = np.zeros(n)
        path_similarity_arr = np.zeros(n)
        vol_regime_arr = np.ones(n)
        bear_severity_arr = np.zeros(n)

        # 预先计算V5.2 美联储利率周期特征（5维）
        # 1. fed_rate_action: -1=降息, 0=持平, +1=加息
        # 2. fed_months_in_cycle: 当前方向持续月数
        # 3. fed_rate_level: 当前目标利率上限(%)
        # 4. fed_easing_btc_dip: 降息+BTC低位组合信号[0,1]
        # 5. fed_hawkish_top: 加息+V4见顶组合信号[0,1]
        fed_action_arr = np.zeros(n)
        fed_months_arr = np.zeros(n)
        fed_level_arr = np.zeros(n)
        fed_easing_dip_arr = np.zeros(n)
        fed_hawkish_top_arr = np.zeros(n)
        # 美联储周期对所有币种生效（宏观流动性），不限于BTC
        for i in range(n):
            current_date = prices.index[i]
            # 找最近一次FOMC利率变化点
            recent_change = None
            for change_date, rate_level, action in self.FED_RATE_CHANGES:
                if change_date <= current_date:
                    recent_change = (change_date, rate_level, action)
                else:
                    break

            if recent_change is None:
                # 数据早于2008年零利率，默认零利率平台
                fed_action_arr[i] = 0.0
                fed_months_arr[i] = 0.0
                fed_level_arr[i] = 0.25
                fed_easing_dip_arr[i] = 0.0
                fed_hawkish_top_arr[i] = 0.0
                continue

            change_date, rate_level, action_at_change = recent_change
            months_in_cycle = (current_date - change_date).days / 30.44

            # 判断当前动作方向（基于变化点动作）
            # action_at_change: +1=加息开始(进入加息周期), -1=降息开始(进入降息周期), 0=进入平台
            # 平台期间沿用上一阶段的方向更准确：
            # - 2008-12-16: 降息至零，进入零利率平台 → action=-1（降息周期延续）
            # - 2015-12-16: 加息开始 → action=+1
            # - 2018-12-19: 加息结束，平台 → action=+1（仍是紧缩性高位）
            # - 2019-07-31: 降息开始 → action=-1
            # - 2020-03-15: 降至零，平台 → action=-1（宽松延续）
            # - 2022-03-16: 加息开始 → action=+1
            # - 2023-07-26: 加息结束，平台 → action=+1（紧缩延续）
            # - 2024-09-18: 降息开始 → action=-1
            if action_at_change == +1:
                current_action = 1.0  # 加息或高位紧缩
            elif action_at_change == -1:
                current_action = -1.0  # 降息或低位宽松
            else:
                # 平台期，查找上一个非零动作方向
                prev_action = 0
                for prev_change_date, _, prev_act in reversed(self.FED_RATE_CHANGES):
                    if prev_change_date < change_date and prev_act != 0:
                        prev_action = prev_act
                        break
                current_action = float(prev_action) if prev_action != 0 else 0.0

            fed_action_arr[i] = current_action
            fed_months_arr[i] = months_in_cycle
            fed_level_arr[i] = rate_level

            # 组合信号4: fed_easing_btc_dip
            # 降息周期 + BTC处于相对低位（weekly_ma200_distance < 0，即价格在周线MA200下方）
            # 信号强度 = 降息力度 × BTC低估程度
            # weekly_dist 已在主循环中计算（但这里在预计算阶段，需独立判断）
            # 使用 close[i] vs 周线MA200近似：30日均价的200日扩展
            if current_action == -1.0 and i >= 200:
                # 周线MA200 ≈ 日线MA1400的近似，但数据可能不足
                # 用近200日均价作为周线MA200的近似
                ma200_approx = float(np.mean(close[max(0, i-200):i+1]))
                if ma200_approx > 0:
                    dist_to_ma200 = (close[i] - ma200_approx) / ma200_approx * 100
                    # BTC低位：dist_to_ma200 < 0（价格在MA200下方）
                    # 越低越强信号
                    if dist_to_ma200 < 0:
                        # 归一化到[0,1]：-50%以下为1.0，0%为0
                        dip_strength = min(1.0, abs(dist_to_ma200) / 50.0)
                        # 降息周期内信号随时间增强（前6个月最强）
                        cycle_boost = min(1.0, months_in_cycle / 6.0) if months_in_cycle < 12 else 1.0
                        fed_easing_dip_arr[i] = dip_strength * cycle_boost
                    else:
                        fed_easing_dip_arr[i] = 0.0
                else:
                    fed_easing_dip_arr[i] = 0.0
            else:
                fed_easing_dip_arr[i] = 0.0

            # 组合信号5: fed_hawkish_top
            # 加息周期 + V4见顶信号（halving_months_after在12-18月，即peak_warning阶段）
            # 信号强度 = 加息力度 × V4见顶强度
            if current_action == 1.0 and is_btc:
                # 计算减半后月数
                recent_halving = None
                for hd in self.BTC_HALVING_DATES:
                    if hd <= current_date:
                        recent_halving = hd
                    else:
                        break
                if recent_halving is not None:
                    months_after_halving = (current_date - recent_halving).days / 30.44
                    # V4见顶窗口：减半后12-18月
                    if 12 <= months_after_halving <= 18:
                        # 信号强度1.0（在见顶窗口内）
                        v4_top_signal = 1.0
                    elif 18 < months_after_halving <= 24:
                        # 衰减信号
                        v4_top_signal = max(0.0, 1.0 - (months_after_halving - 18) / 6.0)
                    else:
                        v4_top_signal = 0.0

                    if v4_top_signal > 0:
                        # 加息周期内信号随时间增强（前12个月逐步增强）
                        if months_in_cycle < 12:
                            hawkish_boost = months_in_cycle / 12.0
                        else:
                            hawkish_boost = 1.0
                        fed_hawkish_top_arr[i] = v4_top_signal * hawkish_boost
                    else:
                        fed_hawkish_top_arr[i] = 0.0
                else:
                    fed_hawkish_top_arr[i] = 0.0
            else:
                fed_hawkish_top_arr[i] = 0.0
        if is_btc:
            # 滚动高点：截至当前时点的周期内最高价（无未来函数）
            # 周期定义：从最近一次减半开始，到下次减半结束
            running_peak_price = 0.0
            running_peak_date = None
            last_halving_idx = -1
            # 周期内滚动峰值量
            running_peak_vol = 0.0
            # 滚动30日均量
            vol_ma30 = pd.Series(volume_arr).rolling(30, min_periods=1).mean().values

            for i in range(n):
                current_date = prices.index[i]
                current_price = close[i]
                current_vol = vol_ma30[i] if i < len(vol_ma30) else 0.0

                # 判断是否跨越减半点（重新开始一个周期）
                # 找到<= current_date 的最近一次减半
                recent_halving = None
                for hd in self.BTC_HALVING_DATES:
                    if hd <= current_date:
                        recent_halving = hd
                    else:
                        break

                if recent_halving is None:
                    # 数据早于第一次减半，阶段未知
                    cycle_phase_arr[i] = 0.0
                    drawdown_peak_arr[i] = 0.0
                    months_since_peak_arr[i] = 0.0
                    bear_progress_arr[i] = 0.0
                    drawdown_vs_hist_arr[i] = 0.0
                    path_similarity_arr[i] = 0.0
                    vol_regime_arr[i] = 1.0
                    bear_severity_arr[i] = 0.0
                    continue

                # 检测是否进入新周期（减半点变化）
                halving_idx_change = (recent_halving != last_halving_idx) if last_halving_idx != -1 else False
                if halving_idx_change or running_peak_price == 0.0:
                    # 新周期开始，重置滚动高点
                    running_peak_price = current_price
                    running_peak_date = current_date
                    running_peak_vol = current_vol
                    last_halving_idx = recent_halving

                # 更新滚动高点（无未来函数：只用当前及历史数据）
                if current_price > running_peak_price:
                    running_peak_price = current_price
                    running_peak_date = current_date
                if current_vol > running_peak_vol:
                    running_peak_vol = current_vol

                # 计算减半后月数
                months_after_halving = (current_date - recent_halving).days / 30.44

                # 1. cycle_phase: 周期阶段编码
                # 0=accumulation(减半前), 1=bull_run(0-12月), 2=peak_warning(12-18月), 3=bear_market(18-30月)
                if months_after_halving < 0:
                    phase = 0.0  # accumulation
                elif months_after_halving < self.cycle_bull_run_end_months:
                    phase = 1.0  # bull_run
                elif months_after_halving < self.cycle_peak_warn_end_months:
                    phase = 2.0  # peak_warning
                elif months_after_halving < self.cycle_bear_end_months:
                    phase = 3.0  # bear_market
                else:
                    phase = 0.0  # accumulation (下一个周期的累积阶段)
                cycle_phase_arr[i] = phase

                # 2. drawdown_from_cycle_peak: 距周期内滚动高点回撤%
                if running_peak_price > 0:
                    drawdown_pct_val = (current_price - running_peak_price) / running_peak_price * 100
                else:
                    drawdown_pct_val = 0.0
                drawdown_peak_arr[i] = drawdown_pct_val

                # 3. months_since_cycle_peak: 距周期内已实现高点月数
                if running_peak_date is not None:
                    months_since_peak = (current_date - running_peak_date).days / 30.44
                else:
                    months_since_peak = 0.0
                months_since_peak_arr[i] = months_since_peak

                # 4. bear_phase_progress: 熊市进度[0,1]
                # 仅在bear_market阶段(bear_end_months ~ peak_warn_end_months)计算
                # progress = (months_after_halving - peak_warn_end) / (bear_end - peak_warn_end)
                if phase == 3.0:
                    bear_duration = self.cycle_bear_end_months - self.cycle_peak_warn_end_months
                    if bear_duration > 0:
                        progress = (months_after_halving - self.cycle_peak_warn_end_months) / bear_duration
                        bear_progress = max(0.0, min(1.0, progress))
                    else:
                        bear_progress = 0.0
                else:
                    # 非熊市阶段，progress=0
                    bear_progress = 0.0
                bear_progress_arr[i] = bear_progress

                # 5. drawdown_vs_hist_avg: 当前跌幅 - 历史同月数平均跌幅
                # V5.3验证版本：仅在熊市阶段(phase==3.0)计算，与验证脚本一致
                if phase == 3.0 and months_since_peak > 0 and running_peak_price > 0:
                    idx = int(min(months_since_peak, len(self.HISTORICAL_PEAK_TO_BOTTOM_DRAWDOWN) - 1))
                    if idx >= 0:
                        hist_avg_dd = self.HISTORICAL_PEAK_TO_BOTTOM_DRAWDOWN[idx]
                        drawdown_vs_hist_arr[i] = drawdown_pct_val - hist_avg_dd
                else:
                    drawdown_vs_hist_arr[i] = 0.0

                # 6. cycle_path_similarity: 近3月平均相似度[0,1]
                # V5.3验证版本：仅在熊市阶段(phase==3.0)且months_since_peak>=3时计算
                # 相似度 = 1 - |当前跌幅 - 历史跌幅| / |历史跌幅|
                if phase == 3.0 and months_since_peak >= 3:
                    m_int = int(months_since_peak)
                    similarities = []
                    for m in range(max(0, m_int - 3), m_int):
                        if m < len(self.HISTORICAL_PEAK_TO_BOTTOM_DRAWDOWN):
                            hist_dd = self.HISTORICAL_PEAK_TO_BOTTOM_DRAWDOWN[m]
                            if abs(hist_dd) > 0:
                                sim = 1.0 - abs(drawdown_pct_val - hist_dd) / abs(hist_dd)
                                similarities.append(max(0.0, min(1.0, sim)))
                    if similarities:
                        path_similarity_arr[i] = float(np.mean(similarities))
                    else:
                        path_similarity_arr[i] = 0.0
                else:
                    path_similarity_arr[i] = 0.0

                # 7. vol_regime_ratio: 当前30日均量 / 周期内峰值量
                if running_peak_vol > 0:
                    vol_regime_arr[i] = current_vol / running_peak_vol
                else:
                    vol_regime_arr[i] = 1.0

                # 8. bear_severity_score: 熊市严重度[0,1]
                # = 时间进度(bear_phase_progress) × 跌幅进度(当前跌幅/历史平均总跌幅)
                if bear_progress > 0 and self.HISTORICAL_AVG_TOTAL_DRAWDOWN_PCT > 0:
                    drawdown_progress = min(1.0, abs(drawdown_pct_val) / self.HISTORICAL_AVG_TOTAL_DRAWDOWN_PCT)
                    bear_severity_arr[i] = bear_progress * drawdown_progress
                else:
                    bear_severity_arr[i] = 0.0

        # BTC regime序列（小币需要）
        btc_ma = None
        btc_ma_slope_arr = None
        btc_regime_labels = None
        btc_bull_arr = None
        if not is_btc and btc_prices is not None:
            btc_close = btc_prices["close"].values
            btc_ma = self._calc_ma(btc_close)
            btc_ma_slope_arr = self._calc_slope(btc_ma)
            btc_regime_labels = np.zeros(len(btc_close))
            btc_bull_arr = np.zeros(len(btc_close), dtype=bool)
            for i in range(self.warmup_periods, len(btc_close)):
                if not np.isnan(btc_ma[i]):
                    label, bull = self._classify_btc_regime_at(btc_ma[i], btc_ma_slope_arr[i])
                    btc_regime_labels[i] = label
                    btc_bull_arr[i] = bull
        elif is_btc:
            btc_regime_labels = np.zeros(n)
            btc_bull_arr = np.zeros(n, dtype=bool)
            for i in range(self.warmup_periods, n):
                if not np.isnan(ma[i]):
                    label, bull = self._classify_btc_regime_at(ma[i], ma_slope[i])
                    btc_regime_labels[i] = label
                    btc_bull_arr[i] = bull

        # BTC价格序列（用于分化度计算）
        btc_close_arr = btc_prices["close"].values if btc_prices is not None else close

        for i in range(n):
            if i < self.warmup_periods or np.isnan(ma[i]) or ma[i] <= 0:
                for name in self.FEATURE_NAMES:
                    result.iloc[i][name] = 0.0
                continue

            current_price = close[i]
            current_ma = ma[i]
            current_slope = ma_slope[i]

            # BTC regime
            btc_label = 0.0
            btc_bull = False
            btc_slope_val = 0.0
            if not is_btc and btc_regime_labels is not None:
                btc_idx = min(i, len(btc_regime_labels) - 1)
                btc_label = btc_regime_labels[btc_idx]
                btc_bull = btc_bull_arr[btc_idx] if btc_bull_arr is not None else False
                btc_slope_val = btc_ma_slope_arr[btc_idx] if btc_ma_slope_arr is not None else 0.0
            elif is_btc:
                btc_label = btc_regime_labels[i] if btc_regime_labels is not None else 0.0
                btc_bull = btc_bull_arr[i] if btc_bull_arr is not None else False
                btc_slope_val = current_slope

            btc_price_val = btc_close_arr[min(i, len(btc_close_arr) - 1)]

            # 哲学1
            btc_alt_div = self._calc_btc_alt_divergence(
                current_price, current_slope, btc_price_val, btc_slope_val, is_btc
            )
            alt_short_risk = self._calc_alt_short_risk(is_btc, current_slope, btc_label)

            # 哲学2
            weekly_dist = 0.0
            dip_level = 0
            dip_pos = 0.0
            left_signal = 0.0
            if is_btc and weekly_ma200 is not None and i < len(weekly_ma200):
                wma = weekly_ma200[i]
                if not np.isnan(wma) and wma > 0:
                    weekly_dist = (wma - current_price) / wma * 100
                    if weekly_dist > 0:
                        dip_level = min(int(weekly_dist / self.dip_buy_step_pct), self.dip_buy_levels)
                        if dip_level > 0:
                            dip_pos = (dip_level / self.dip_buy_levels) * self.dip_buy_max_position
                            left_signal = min(dip_pos / self.dip_buy_max_position, 1.0)

            # 哲学3
            price_below = current_price < current_ma
            slope_neg = current_slope < 0
            bear_layer = 0
            layered_target = 0.0
            if is_btc and price_below:
                if slope_neg:
                    bear_layer = 2
                    layered_target = -self.bear_short_level2_pct
                else:
                    bear_layer = 1
                    layered_target = -self.bear_short_level1_pct
            fib_remaining = 1.0
            if dip_pos > 0:
                layered_target = dip_pos
            pos_adjust = self._calc_position_adjustment(bear_layer, dip_pos, current_slope, ma_slope)

            # 哲学4
            self_bull = bool(current_price > current_ma and current_slope > 0)
            double_bull = self._calc_double_bull(is_btc, self_bull, btc_bull)

            # 哲学5: 减半周期锚定（预先计算）
            halving_months = halving_months_arr[i]
            halving_phase = halving_phase_arr[i]
            halving_cap = halving_cap_arr[i]

            # 哲学6: MA128破位逃顶
            ma128_dist_pct = 0.0
            if not np.isnan(ma128[i]) and ma128[i] > 0:
                ma128_dist_pct = (current_price - ma128[i]) / ma128[i] * 100
            ma128_below = ma128_below_days_arr[i]

            # 哲学7: 越高越卖（预先计算）
            ath_drawdown = ath_drawdown_arr[i]
            bounce_from_low = bounce_from_low_arr[i]

            # 哲学8: 量价抄底确认（预先计算）
            rsi_val = rsi_arr[i]
            vol_ratio = volume_ratio_arr[i]

            # 写入结果
            result.iloc[i]["btc_regime_label"] = btc_label
            result.iloc[i]["btc_alt_divergence"] = btc_alt_div
            result.iloc[i]["is_btc_asset"] = 1.0 if is_btc else 0.0
            result.iloc[i]["alt_short_risk_score"] = alt_short_risk
            result.iloc[i]["weekly_ma200_distance"] = weekly_dist
            result.iloc[i]["dip_buy_level"] = float(dip_level)
            result.iloc[i]["dip_buy_position_ratio"] = dip_pos
            result.iloc[i]["left_side_buy_signal"] = left_signal
            result.iloc[i]["bear_short_layer"] = float(bear_layer)
            result.iloc[i]["fib_tp_remaining_ratio"] = fib_remaining
            result.iloc[i]["layered_position_target"] = layered_target
            result.iloc[i]["position_adjustment"] = pos_adjust
            result.iloc[i]["btc_bull_confirmed"] = 1.0 if btc_bull else 0.0
            result.iloc[i]["self_bull_confirmed"] = 1.0 if self_bull else 0.0
            result.iloc[i]["double_bull_score"] = double_bull
            # V4新特征
            result.iloc[i]["halving_months_after"] = halving_months
            result.iloc[i]["halving_phase"] = halving_phase
            result.iloc[i]["halving_position_cap"] = halving_cap
            result.iloc[i]["ma128_distance_pct"] = ma128_dist_pct
            result.iloc[i]["ma128_below_days"] = ma128_below
            result.iloc[i]["ath_drawdown_pct"] = ath_drawdown
            result.iloc[i]["bounce_from_low_pct"] = bounce_from_low
            # Stage 2.1 新增
            result.iloc[i]["rsi_14"] = rsi_val
            result.iloc[i]["volume_ratio_20d"] = vol_ratio
            # V5.2 美联储利率周期特征：4个已回退，fed_rate_level 于V5.4正式集成
            # 回退特征（计算代码保留但不写入结果）：
            # result.iloc[i]["fed_rate_action"] = fed_action_arr[i]
            # result.iloc[i]["fed_months_in_cycle"] = fed_months_arr[i]
            # result.iloc[i]["fed_easing_btc_dip"] = fed_easing_dip_arr[i]
            # result.iloc[i]["fed_hawkish_top"] = fed_hawkish_top_arr[i]
            # V5.4 集成特征（方向4验证：TOP_EXIT +0.0006, DIP_BUY +0.0058）：
            result.iloc[i]["fed_rate_level"] = fed_level_arr[i]
            # V5.5 集成特征（方向2验证：TOP_EXIT +0.0166, DIP_BUY +0.0006）：
            # fed_level_x_cycle_sim = 利率水平 × 周期路径相似度
            result.iloc[i]["fed_level_x_cycle_sim"] = fed_level_arr[i] * path_similarity_arr[i]
            # V5/V5.1 周期相似性特征：6个已回退，2个于V5.3正式集成
            # 回退特征（计算代码保留但不写入结果）：
            # result.iloc[i]["cycle_phase"] = cycle_phase_arr[i]
            # result.iloc[i]["drawdown_from_cycle_peak"] = drawdown_peak_arr[i]
            # result.iloc[i]["months_since_cycle_peak"] = months_since_peak_arr[i]
            # result.iloc[i]["bear_phase_progress"] = bear_progress_arr[i]
            # result.iloc[i]["vol_regime_ratio"] = vol_regime_arr[i]
            # result.iloc[i]["bear_severity_score"] = bear_severity_arr[i]
            # V5.3 集成特征（消融实验验证：TOP_EXIT +0.0428, DIP_BUY +0.0283）：
            result.iloc[i]["drawdown_vs_hist_avg"] = drawdown_vs_hist_arr[i]
            result.iloc[i]["cycle_path_similarity"] = path_similarity_arr[i]

        return result

    def get_feature_names(self) -> List[str]:
        """获取特征名列表"""
        return self.FEATURE_NAMES.copy()

    @staticmethod
    def get_feature_metadata(feature_name: str) -> Optional[Dict[str, Any]]:
        """查询单个特征的实践回测元信息

        参数:
            feature_name: 特征名

        返回:
            元信息字典，包含 source/strategy/philosophy/validation/
            practice_validated/contribution 字段；未知特征返回 None
        """
        return FEATURE_METADATA.get(feature_name)

    @staticmethod
    def get_all_metadata() -> Dict[str, Dict[str, Any]]:
        """获取所有特征的实践回测元信息"""
        return FEATURE_METADATA.copy()

    @staticmethod
    def get_practice_validated_features() -> List[str]:
        """获取所有标注为实践回测验证的特征名列表"""
        return [
            name for name, meta in FEATURE_METADATA.items()
            if meta.get("practice_validated", False)
        ]

    @staticmethod
    def get_features_by_philosophy(philosophy: str) -> List[str]:
        """按哲学贡献分类查询特征

        参数:
            philosophy: 哲学贡献名称，如 "左侧抄底"/"双牛过滤"/"分层仓位"/"BTC/小币分化"
        """
        return [
            name for name, meta in FEATURE_METADATA.items()
            if meta.get("philosophy") == philosophy
        ]

    # ------------------------------------------------------------------
    # 内部计算方法
    # ------------------------------------------------------------------

    def _calc_ma(self, close: np.ndarray) -> np.ndarray:
        """计算MA序列"""
        return pd.Series(close).rolling(
            window=self.ma_period, min_periods=self.ma_period
        ).mean().values

    def _calc_slope(self, ma: np.ndarray) -> np.ndarray:
        """计算MA斜率序列"""
        n = len(ma)
        slope = np.zeros(n)
        for i in range(self.slope_period, n):
            if not np.isnan(ma[i]) and not np.isnan(ma[i - self.slope_period]):
                slope[i] = (ma[i] / ma[i - self.slope_period] - 1) * 100
        return slope

    def _calc_weekly_ma200(self, prices: pd.DataFrame) -> np.ndarray:
        """计算周线MA200（前向填充到日线）"""
        df = prices.copy()
        df.index = pd.to_datetime(df.index)
        weekly = df.resample("W").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()
        if len(weekly) < 200:
            return np.full(len(prices), np.nan)
        wma = pd.Series(weekly["close"].values).rolling(
            window=200, min_periods=200
        ).mean().values
        daily_wma = np.full(len(prices), np.nan)
        widx = 0
        for i in range(len(prices)):
            current_date = prices.index[i]
            while widx < len(weekly) and weekly.index[widx] <= current_date:
                widx += 1
            if widx >= 200:
                daily_wma[i] = wma[widx - 1]
        return daily_wma

    def _classify_btc_regime(
        self, ma: np.ndarray, ma_slope: np.ndarray
    ) -> Tuple[float, bool]:
        """分类当前BTC regime（取最后一个有效值）"""
        if len(ma) == 0 or np.isnan(ma[-1]):
            return 0.0, False
        return self._classify_btc_regime_at(ma[-1], ma_slope[-1] if len(ma_slope) > 0 else 0.0)

    def _classify_btc_regime_at(self, ma_val: float, slope_val: float) -> Tuple[float, bool]:
        """分类指定位置的BTC regime

        Returns:
            (label, is_bull): label=1(牛)/0(震荡)/-1(熊), is_bull=True/False
        """
        if np.isnan(ma_val) or ma_val <= 0:
            return 0.0, False
        # 这里需要价格数据，简化处理：斜率>0=牛，斜率<0=熊，其他=震荡
        # 实际使用时由extract_series传入完整数据
        if slope_val > 0:
            return 1.0, True
        elif slope_val < 0:
            return -1.0, False
        return 0.0, False

    def _calc_btc_alt_divergence(
        self,
        alt_price: float,
        alt_slope: float,
        btc_price: float,
        btc_slope: float,
        is_btc: bool,
    ) -> float:
        """计算BTC vs 小币的强弱分化度

        Returns:
            [-1, 1]: 正值=BTC强于小币, 负值=小币强于BTC
        """
        if is_btc:
            return 0.0
        # 斜率分化（主信号）
        slope_diff = btc_slope - alt_slope
        # tanh归一化到[-1, 1]
        return float(np.tanh(slope_diff / 5.0))

    def _calc_alt_short_risk(
        self, is_btc: bool, self_slope: float, btc_regime: float
    ) -> float:
        """计算小币做空风险评分

        Returns:
            [0, 1]: 越高越不适合做空
        """
        if is_btc:
            return 0.0
        # 小币做空风险 = 基础高风险 + 熊市反弹风险
        base_risk = 0.7  # 小币做空基础风险
        # BTC熊市时小币可能暴力反弹
        if btc_regime < 0:
            base_risk = min(base_risk + 0.2, 1.0)
        # 自身斜率为正时做空风险更高
        if self_slope > 0:
            base_risk = min(base_risk + 0.1, 1.0)
        return base_risk

    def _calc_double_bull(self, is_btc: bool, self_bull: bool, btc_bull: bool) -> float:
        """计算双牛过滤得分

        Returns:
            [0, 1]: 1=双牛确认, 0.5=单牛, 0=非牛
        """
        if is_btc:
            return 1.0 if self_bull else 0.0
        if self_bull and btc_bull:
            return 1.0
        elif self_bull or btc_bull:
            return 0.5
        return 0.0

    def _calc_position_adjustment(
        self,
        bear_layer: int,
        dip_pos: float,
        current_slope: float,
        ma_slope_arr: np.ndarray,
    ) -> float:
        """计算仓位调整方向

        Returns:
            1.0=加仓, 0.0=持有, -1.0=减仓
        """
        # 抄底触发 → 加仓
        if dip_pos > 0:
            return 1.0
        # 做空档位提升 → 加空仓
        if bear_layer == 2:
            return -1.0
        # 做空档位1 → 持有
        if bear_layer == 1:
            return 0.0
        return 0.0

    # ------------------------------------------------------------------
    # V4新增内部计算方法
    # ------------------------------------------------------------------

    def _calc_ma128(self, close: np.ndarray) -> np.ndarray:
        """计算MA128序列（V4哲学贡献6）"""
        return pd.Series(close).rolling(
            window=self.ma128_period, min_periods=self.ma128_period
        ).mean().values

    def _calc_halving_features(self, current_date: pd.Timestamp) -> Tuple[float, float, float]:
        """计算减半周期三特征（V4哲学贡献5）

        Args:
            current_date: 当前日期

        Returns:
            (halving_months_after, halving_phase, halving_position_cap)
            - halving_months_after: 距上次减半的月数 [0, +∞)
            - halving_phase: 减半周期阶段编码 (0=normal, 1=warn, 2=danger, 3=peak)
            - halving_position_cap: 仓位上限 [0.0, 1.0]
        """
        last_halving = None
        for halving_date in self.BTC_HALVING_DATES:
            if halving_date <= current_date:
                last_halving = halving_date
            else:
                break

        if last_halving is None:
            return 0.0, 0.0, 1.0

        months_after = (current_date.year - last_halving.year) * 12 + (current_date.month - last_halving.month)

        if months_after < self.halving_warn_months:
            return float(months_after), 0.0, 1.0
        elif months_after < self.halving_danger_months:
            return float(months_after), 1.0, self.halving_warn_min_position
        elif months_after < self.halving_peak_months:
            return float(months_after), 2.0, self.halving_danger_min_position
        elif months_after < self.halving_end_months:
            return float(months_after), 3.0, self.halving_peak_min_position
        else:
            return float(months_after), 0.0, 1.0

    def _calc_ma128_below_days(self, close: np.ndarray, ma128: np.ndarray) -> float:
        """计算连续低于MA128天数（V4哲学贡献6）

        Args:
            close: 收盘价序列
            ma128: MA128序列

        Returns:
            连续低于MA128的天数 [0, +∞)
        """
        n = len(close)
        if n == 0:
            return 0.0
        consecutive_below = 0
        for i in range(n - 1, -1, -1):
            if np.isnan(ma128[i]) or ma128[i] <= 0:
                break
            if close[i] < ma128[i]:
                consecutive_below += 1
            else:
                break
        return float(consecutive_below)

    def _calc_bounce_from_low(self, close: np.ndarray) -> float:
        """计算从近期低点反弹幅度（V4哲学贡献7）

        Args:
            close: 收盘价序列

        Returns:
            从近期低点的反弹幅度百分比 [0, +∞)
        """
        n = len(close)
        if n <= self.bounce_lookback:
            return 0.0
        current_price = close[-1]
        start_idx = max(0, n - 1 - self.bounce_lookback)
        recent_low = np.min(close[start_idx:-1])
        if recent_low <= 0:
            return 0.0
        bounce_pct = (current_price - recent_low) / recent_low * 100
        return bounce_pct

    def _calc_bounce_from_low_at(self, close: np.ndarray, idx: int) -> float:
        """在指定位置计算从近期低点反弹幅度（用于extract_series批量计算）

        Args:
            close: 收盘价序列
            idx: 当前位置索引

        Returns:
            从近期低点的反弹幅度百分比 [0, +∞)
        """
        if idx < self.bounce_lookback:
            return 0.0
        current_price = close[idx]
        start_idx = max(0, idx - self.bounce_lookback)
        recent_low = np.min(close[start_idx:idx])
        if recent_low <= 0:
            return 0.0
        bounce_pct = (current_price - recent_low) / recent_low * 100
        return bounce_pct

    # ------------------------------------------------------------------
    # Stage 2.1 新增：量价抄底确认计算方法
    # ------------------------------------------------------------------

    def _calc_rsi(self, close: np.ndarray) -> float:
        """计算当前RSI值（单时间点，用于extract）

        Args:
            close: 收盘价序列

        Returns:
            RSI值 [0, 100]，50表示中性
        """
        n = len(close)
        if n < self.rsi_period + 1:
            return 50.0

        deltas = np.diff(close[-(self.rsi_period + 1):])
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi

    def _calc_rsi_series(self, close: np.ndarray) -> np.ndarray:
        """计算RSI序列（用于extract_series批量计算）

        使用Wilder平滑法，与标准RSI一致。

        Args:
            close: 收盘价序列

        Returns:
            RSI序列 [0, 100]
        """
        n = len(close)
        rsi = np.full(n, 50.0)
        if n < self.rsi_period + 1:
            return rsi

        deltas = np.diff(close)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        # 初始平均值（简单平均）
        avg_gain = np.mean(gains[:self.rsi_period])
        avg_loss = np.mean(losses[:self.rsi_period])

        for i in range(self.rsi_period, n - 1):
            avg_gain = (avg_gain * (self.rsi_period - 1) + gains[i]) / self.rsi_period
            avg_loss = (avg_loss * (self.rsi_period - 1) + losses[i]) / self.rsi_period

            if avg_loss == 0:
                rsi[i + 1] = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi[i + 1] = 100.0 - (100.0 / (1.0 + rs))

        return rsi

    def _calc_volume_ratio(self, prices: pd.DataFrame) -> float:
        """计算当前成交量比率（单时间点，用于extract）

        Args:
            prices: OHLCV数据

        Returns:
            当日成交量 / 20日均量
        """
        if "volume" not in prices.columns or len(prices) < self.volume_ratio_period + 1:
            return 1.0

        vol = prices["volume"].values
        current_vol = vol[-1]
        avg_vol = np.mean(vol[-(self.volume_ratio_period + 1):-1])

        if avg_vol <= 0:
            return 1.0

        return current_vol / avg_vol

    def _calc_volume_ratio_series(self, volume: np.ndarray) -> np.ndarray:
        """计算成交量比率序列（用于extract_series批量计算）

        Args:
            volume: 成交量序列

        Returns:
            成交量比率序列（当日/前N日均量）
        """
        n = len(volume)
        ratio = np.ones(n)

        if n < self.volume_ratio_period + 1:
            return ratio

        for i in range(self.volume_ratio_period, n):
            avg_vol = np.mean(volume[i - self.volume_ratio_period:i])
            if avg_vol > 0:
                ratio[i] = volume[i] / avg_vol

        return ratio

    # ------------------------------------------------------------------
    # V5: 4年周期趋势预测特征计算
    # ------------------------------------------------------------------

    def _calc_cycle_features_at(
        self,
        prices: pd.DataFrame,
        close: np.ndarray,
        is_btc: bool,
    ) -> Tuple[float, float, float, float]:
        """计算当前时点的4年周期特征（单时间点，用于extract）

        历史规律：减半后18月见顶(V4)，顶后约12.5月见底，4年牛熊周期

        Args:
            prices: 完整价格序列（用于确定当前日期和周期高点）
            close: 收盘价数组
            is_btc: 是否为BTC

        Returns:
            (cycle_phase, drawdown_from_cycle_peak, months_since_cycle_peak, bear_phase_progress)
            - cycle_phase: 0=accumulation, 1=bull_run, 2=peak_warning, 3=bear_market
            - drawdown_from_cycle_peak: 距周期内滚动高点回撤% (<=0)
            - months_since_cycle_peak: 距周期内已实现高点月数
            - bear_phase_progress: 熊市进度[0,1]，1=预计到底
        """
        if not is_btc or len(prices) == 0:
            return 0.0, 0.0, 0.0, 0.0

        current_date = prices.index[-1]
        current_price = float(close[-1]) if len(close) > 0 else 0.0

        # 找最近一次减半
        recent_halving = None
        for hd in self.BTC_HALVING_DATES:
            if hd <= current_date:
                recent_halving = hd
            else:
                break

        if recent_halving is None:
            return 0.0, 0.0, 0.0, 0.0

        # 周期内滚动高点（只用当前及历史数据，无未来函数）
        cycle_start_mask = prices.index >= recent_halving
        cycle_close = close[cycle_start_mask]
        if len(cycle_close) == 0:
            return 0.0, 0.0, 0.0, 0.0

        running_peak_price = float(np.max(cycle_close))
        peak_idx_in_cycle = int(np.argmax(cycle_close))
        running_peak_date = prices.index[cycle_start_mask][peak_idx_in_cycle]

        # 减半后月数
        months_after_halving = (current_date - recent_halving).days / 30.44

        # 1. cycle_phase
        if months_after_halving < 0:
            phase = 0.0
        elif months_after_halving < self.cycle_bull_run_end_months:
            phase = 1.0
        elif months_after_halving < self.cycle_peak_warn_end_months:
            phase = 2.0
        elif months_after_halving < self.cycle_bear_end_months:
            phase = 3.0
        else:
            phase = 0.0

        # 2. drawdown_from_cycle_peak
        if running_peak_price > 0:
            drawdown = (current_price - running_peak_price) / running_peak_price * 100
        else:
            drawdown = 0.0

        # 3. months_since_cycle_peak
        months_since_peak = (current_date - running_peak_date).days / 30.44

        # 4. bear_phase_progress
        if phase == 3.0:
            bear_duration = self.cycle_bear_end_months - self.cycle_peak_warn_end_months
            if bear_duration > 0:
                progress = (months_after_halving - self.cycle_peak_warn_end_months) / bear_duration
                bear_progress = max(0.0, min(1.0, progress))
            else:
                bear_progress = 0.0
        else:
            bear_progress = 0.0

        return phase, drawdown, months_since_peak, bear_progress

    def _calc_cycle_similarity_features_at(
        self,
        prices: pd.DataFrame,
        close: np.ndarray,
        volume_arr: Optional[np.ndarray],
        is_btc: bool,
        cycle_phase: float,
        drawdown_from_cycle_peak: float,
        months_since_cycle_peak: float,
        bear_phase_progress: float,
    ) -> Tuple[float, float, float, float]:
        """计算当前时点的周期相似性增强特征（单时间点，用于extract）

        基于历史3轮周期月度平均跌幅曲线对比

        Args:
            prices: 完整价格序列
            close: 收盘价数组
            volume_arr: 成交量数组（可选）
            is_btc: 是否为BTC
            cycle_phase: 已计算的周期阶段
            drawdown_from_cycle_peak: 已计算的距周期高点回撤%
            months_since_cycle_peak: 已计算的距高点月数
            bear_phase_progress: 已计算的熊市进度

        Returns:
            (drawdown_vs_hist_avg, cycle_path_similarity, vol_regime_ratio, bear_severity_score)
        """
        if not is_btc or len(prices) == 0:
            return 0.0, 0.0, 1.0, 0.0

        # 默认值
        drawdown_vs_hist_avg = 0.0
        path_similarity = 0.0
        vol_regime_ratio = 1.0
        bear_severity = 0.0

        # 1. drawdown_vs_hist_avg: 当前跌幅 - 历史同月数平均跌幅
        # V5.3验证版本：仅在熊市阶段(cycle_phase==3.0)计算
        if cycle_phase == 3.0 and months_since_cycle_peak > 0:
            idx = int(min(months_since_cycle_peak, len(self.HISTORICAL_PEAK_TO_BOTTOM_DRAWDOWN) - 1))
            if idx >= 0:
                hist_avg_dd = self.HISTORICAL_PEAK_TO_BOTTOM_DRAWDOWN[idx]
                drawdown_vs_hist_avg = drawdown_from_cycle_peak - hist_avg_dd

            # 2. cycle_path_similarity: 近3月平均相似度[0,1]
            # V5.3验证版本：仅在熊市阶段且months_since_peak>=3时计算
            # 相似度 = 1 - |当前跌幅 - 历史跌幅| / |历史跌幅|
            if months_since_cycle_peak >= 3:
                m_int = int(months_since_cycle_peak)
                similarities = []
                for m in range(max(0, m_int - 3), m_int):
                    if m < len(self.HISTORICAL_PEAK_TO_BOTTOM_DRAWDOWN):
                        hist_dd = self.HISTORICAL_PEAK_TO_BOTTOM_DRAWDOWN[m]
                        if abs(hist_dd) > 0:
                            sim = 1.0 - abs(drawdown_from_cycle_peak - hist_dd) / abs(hist_dd)
                            similarities.append(max(0.0, min(1.0, sim)))
                if similarities:
                    path_similarity = float(np.mean(similarities))

        # 3. vol_regime_ratio: 当前30日均量 / 周期内峰值量
        if volume_arr is not None and len(volume_arr) > 0:
            current_date = prices.index[-1]
            recent_halving = None
            for hd in self.BTC_HALVING_DATES:
                if hd <= current_date:
                    recent_halving = hd
                else:
                    break
            if recent_halving is not None:
                cycle_start_mask = prices.index >= recent_halving
                cycle_vol = volume_arr[cycle_start_mask]
                if len(cycle_vol) > 0:
                    # 30日均量
                    vol_ma30_series = pd.Series(cycle_vol).rolling(30, min_periods=1).mean()
                    running_peak_vol = float(vol_ma30_series.max())
                    current_vol = float(vol_ma30_series.iloc[-1])
                    if running_peak_vol > 0:
                        vol_regime_ratio = current_vol / running_peak_vol

        # 4. bear_severity_score: 时间进度 × 跌幅进度
        if bear_phase_progress > 0 and self.HISTORICAL_AVG_TOTAL_DRAWDOWN_PCT > 0:
            drawdown_progress = min(1.0, abs(drawdown_from_cycle_peak) / self.HISTORICAL_AVG_TOTAL_DRAWDOWN_PCT)
            bear_severity = bear_phase_progress * drawdown_progress

        return drawdown_vs_hist_avg, path_similarity, vol_regime_ratio, bear_severity

    # ------------------------------------------------------------------
    # V5.2: 美联储利率周期特征计算
    # ------------------------------------------------------------------

    def _calc_fed_features_at(
        self,
        prices: pd.DataFrame,
        close: np.ndarray,
        is_btc: bool,
        weekly_ma200_distance: float,
    ) -> Tuple[float, float, float, float, float]:
        """计算当前时点的美联储利率周期特征（单时间点，用于extract）

        基于FOMC决议的加息/降息周期，构建宏观流动性特征
        假设：
        - 降息周期+BTC低位 → all in抄底信号
        - 加息周期+V4见顶 → 开空加大信号

        Args:
            prices: 完整价格序列
            close: 收盘价数组
            is_btc: 是否为BTC
            weekly_ma200_distance: 已计算的周线MA200距离%

        Returns:
            (fed_rate_action, fed_months_in_cycle, fed_rate_level,
             fed_easing_btc_dip, fed_hawkish_top)
        """
        if len(prices) == 0:
            return 0.0, 0.0, 0.0, 0.0, 0.0

        current_date = prices.index[-1]

        # 找最近一次FOMC利率变化点
        recent_change = None
        for change_date, rate_level, action in self.FED_RATE_CHANGES:
            if change_date <= current_date:
                recent_change = (change_date, rate_level, action)
            else:
                break

        if recent_change is None:
            return 0.0, 0.0, 0.25, 0.0, 0.0

        change_date, rate_level, action_at_change = recent_change
        months_in_cycle = (current_date - change_date).days / 30.44

        # 判断当前动作方向
        if action_at_change == +1:
            current_action = 1.0  # 加息或高位紧缩
        elif action_at_change == -1:
            current_action = -1.0  # 降息或低位宽松
        else:
            # 平台期，查找上一个非零动作方向
            prev_action = 0
            for prev_change_date, _, prev_act in reversed(self.FED_RATE_CHANGES):
                if prev_change_date < change_date and prev_act != 0:
                    prev_action = prev_act
                    break
            current_action = float(prev_action) if prev_action != 0 else 0.0

        # 组合信号4: fed_easing_btc_dip
        fed_easing_dip = 0.0
        if current_action == -1.0 and weekly_ma200_distance < 0:
            # BTC低位：weekly_ma200_distance < 0（价格在周线MA200下方）
            dip_strength = min(1.0, abs(weekly_ma200_distance) / 50.0)
            # 降息周期内信号随时间增强（前6个月最强）
            cycle_boost = min(1.0, months_in_cycle / 6.0) if months_in_cycle < 12 else 1.0
            fed_easing_dip = dip_strength * cycle_boost

        # 组合信号5: fed_hawkish_top
        fed_hawkish_top = 0.0
        if current_action == 1.0 and is_btc:
            recent_halving = None
            for hd in self.BTC_HALVING_DATES:
                if hd <= current_date:
                    recent_halving = hd
                else:
                    break
            if recent_halving is not None:
                months_after_halving = (current_date - recent_halving).days / 30.44
                # V4见顶窗口：减半后12-18月
                if 12 <= months_after_halving <= 18:
                    v4_top_signal = 1.0
                elif 18 < months_after_halving <= 24:
                    v4_top_signal = max(0.0, 1.0 - (months_after_halving - 18) / 6.0)
                else:
                    v4_top_signal = 0.0

                if v4_top_signal > 0:
                    if months_in_cycle < 12:
                        hawkish_boost = months_in_cycle / 12.0
                    else:
                        hawkish_boost = 1.0
                    fed_hawkish_top = v4_top_signal * hawkish_boost

        return current_action, months_in_cycle, rate_level, fed_easing_dip, fed_hawkish_top
