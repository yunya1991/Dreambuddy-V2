# 易经蒸馏 — 八卦形式与卜算算法

> 蒸馏日期：2026-07-04
> 用途：BCRM 第三层（过程层）的卜算形式定义
> 关联文档：
> - [BCRM 核心方法论三层架构](bcrm_methodology_three_layers.md)（统领）
> - [易经价值定位](yijing_value_positioning.md)（价值总纲）
> - [唯物辩证法三规律](materialist_dialectic_distillation.md)（理论约束）
> 关联设计稿：`docs/superpowers/specs/2026-07-04-binary-contradiction-reasoning-model-design.md`

---

## 一、易经三大原则

| 原则 | 含义 | BCRM 应用 |
|---|---|---|
| **变易** | 万物皆变，没有静止 | 变爻机制（实时动态修正）|
| **简易** | 复杂现象背后有简单规律 | 八卦→乾坤的简化映射 |
| **不易** | 变易之中有不变规律 | 辩证法三规律作为不变约束 |

---

## 二、太极→两仪→四象→八卦→乾坤

### 2.1 太极（混沌度评估）

**定义**：市场的原始混沌状态，未分化的多维信息

**BCRM 算法**：

```python
def compute_taiji_chaos(market_snapshot: Dict, qmm_uncertainty: float) -> float:
    """
    太极混沌度：多维信息分歧度 + QMM 不确定性
    
    混沌度高 → 难以分判阴阳 → fail-closed 风险
    混沌度低 → 可以进入两仪判定
    """
    # 四象评分的离散度
    scores = [market_snapshot[k] for k in 
              ['supply_demand', 'technical', 'capital_flow', 'market_sentiment']]
    dispersion = np.std(scores)
    
    # 两仪分歧
    macro = (market_snapshot['supply_demand'] + market_snapshot['technical']) / 2
    micro = (market_snapshot['capital_flow'] + market_snapshot['market_sentiment']) / 2
    liangyi_divergence = abs(macro - micro)
    
    chaos = 0.4 * dispersion + 0.3 * liangyi_divergence + 0.3 * qmm_uncertainty
    return round(chaos, 4)
```

**阈值**：chaos > 0.7 → fail-closed（HIGH_CHAOS）

### 2.2 两仪（宏观/微观）

**定义**：
- **阳（宏观）**：决定趋势和方向，长期、静态、有惯性
- **阴（微观）**：决定短期波动，量变积累，动态变化

**关系**：宏观决定微观（任何趋势不会骤然改变），但微观量变可引发质变

**BCRM 算法**：

```python
def compute_liangyi(sixiang: Dict, trend_state: Dict) -> Dict:
    """
    两仪评分：宏观定基调，微观找拐点
    
    宏观 = 供需（本质，0.7）+ 技术（表象，0.3）
    微观 = 技术 + 资金 + 情绪
    """
    macro = 0.7 * sixiang['supply_demand'] + 0.3 * sixiang['technical']
    micro = (sixiang['technical'] + sixiang['capital_flow'] + sixiang['market_sentiment']) / 3
    
    # 主导权判定
    macro_dominant = abs(macro) > abs(micro)
    
    # 背离度（量变积累的信号）
    divergence = abs(macro - micro)
    
    return {
        'macro': macro,
        'micro': micro,
        'macro_dominant': macro_dominant,
        'divergence': divergence,
    }
```

### 2.3 四象（四个维度）

**定义**：
- **技术指标**（表象/博弈结果）：均线、MACD 等
- **实际供需**（本质/内在决定）：库存、产能、PE/PB 估值
- **资金流**（动能）：主力资金、北向资金、ETF 申赎
- **市场情绪**（势能）：恐贪指数、多空比、社交热度

**关系**：技术和供需是内在体现，资金和情绪是外在表现

**BCRM 算法**：

```python
def compute_sixiang(market_data: Dict) -> Dict:
    """
    四象评分：四个维度的综合评估
    
    可靠性排序: 供需(0.8) > 资金(0.7) > 技术(0.65) > 情绪(0.5)
    """
    return {
        'supply_demand': market_data['supply_demand_score'],    # 本质
        'technical': market_data['technical_score'],             # 表象
        'capital_flow': market_data['capital_flow_score'],       # 动能
        'market_sentiment': market_data['sentiment_score'],      # 势能
    }
```

### 2.4 八卦（八种市场状态）

**三爻叠加法**：
- **初爻（本质层）**：供需（权重 40%）
- **二爻（表现层）**：技术 + 资金 + 情绪（权重 35%）
- **三爻（趋势层）**：宏观/微观主导权（权重 25%）

**八卦定义**：

| 卦 | 符号 | 三爻 | 含义 | 哲学 |
|---|---|---|---|---|
| 乾 ☰ | yang/yang/yang | 强势上涨 | 趋势确立 | 天行健 |
| 坤 ☷ | yin/yin/yin | 强势下跌 | 趋势确立 | 地势坤 |
| 震 ☳ | yang/yin/yin | 突发上涨 | 启动阶段 | 量变开始 |
| 巽 ☴ | yin/yang/yang | 突发下跌 | 启动阶段 | 量变开始 |
| 坎 ☵ | yin/yang/yin | 弱势下跌 | 回调阶段 | 量变积累 |
| 离 ☲ | yang/yin/yang | 弱势上涨 | 回调阶段 | 量变积累 |
| 艮 ☶ | yang/yang/yin | 蓄势上涨 | 质变前夜 | 蓄势待发 |
| 兑 ☱ | yin/yin/yang | 蓄势下跌 | 质变前夜 | 蓄势待发 |

**BCRM 算法**：

```python
def determine_bagua(liangyi: Dict, sixiang: Dict) -> str:
    """
    八卦判定：三爻叠加法
    
    初爻(供需) 权重 40% > 二爻(技术资金情绪) 35% > 三爻(宏观微观) 25%
    符合"本质决定表现、宏观决定微观"的哲学原则
    """
    # 初爻：供需（本质层）
    initial_yao = 'yang' if sixiang['supply_demand'] > 0.5 else 'yin'
    
    # 二爻：表现层综合
    performance = (sixiang['technical'] + sixiang['capital_flow'] 
                   + sixiang['market_sentiment']) / 3
    middle_yao = 'yang' if performance > 0.5 else 'yin'
    
    # 三爻：宏观/微观主导
    top_yao = 'yang' if liangyi['macro_dominant'] else 'yin'
    
    # 三爻组合 → 八卦
    gua_map = {
        ('yang', 'yang', 'yang'): 'qian',   # 乾
        ('yin',  'yin',  'yin'):  'kun',    # 坤
        ('yang', 'yin',  'yin'):  'zhen',   # 震
        ('yin',  'yang', 'yang'): 'xun',    # 巽
        ('yin',  'yang', 'yin'):  'kan',    # 坎
        ('yang', 'yin',  'yang'): 'li',     # 离
        ('yang', 'yang', 'yin'):  'gen',    # 艮
        ('yin',  'yin',  'yang'): 'dui',    # 兑
    }
    
    return gua_map[(initial_yao, middle_yao, top_yao)]
```

### 2.5 乾坤（涨跌判断）

**定义**：乾为天（涨/顶），坤为地（跌/底）

**BCRM 算法**：

```python
def determine_qiankun(bagua: str, transformation: Dict, 
                      spiral: Dict, consistency: Dict) -> Dict:
    """
    乾坤判断：综合卦方向 + 转化修正 + 螺旋修正 + 一致性修正
    """
    # 卦方向
    gua_direction = {
        'qian': 'UP', 'zhen': 'UP', 'li': 'UP', 'gen': 'UP',
        'kun': 'DOWN', 'xun': 'DOWN', 'kan': 'DOWN', 'dui': 'DOWN',
    }
    direction = gua_direction[bagua]
    
    # 转化修正：蓄势 → 趋势 时强化方向
    if transformation.get('transformed'):
        direction = transformation.get('post_direction', direction)
    
    # 螺旋修正：SECOND_NEGATION 时方向可能反转
    if spiral.get('stage') == 'SECOND_NEGATION':
        direction = 'UP' if direction == 'DOWN' else 'DOWN'
    
    # 一致性修正：一致性低时降级
    confidence = consistency.get('score', 0.5)
    if confidence < 0.5:
        direction = 'UNCERTAIN'
    
    return {
        'direction': direction,
        'confidence': confidence,
        'bagua': bagua,
    }
```

---

## 三、卦象转化规律

### 3.1 量变质变（蓄势 → 趋势）

```python
def compute_transformation(bagua: str, accumulation: float, 
                           threshold: float) -> Dict:
    """
    卦象转化：量变积累达到阈值 → 质变
    
    蓄势卦（艮/兑）→ 趋势卦（乾/坤）
    启动卦（震/巽）→ 趋势卦（乾/坤）
    """
    # 蓄势/启动阶段：算累积度
    if bagua in ('gen', 'dui', 'zhen', 'xun'):
        if accumulation >= threshold:
            # 质变发生
            post_direction = 'UP' if bagua in ('gen', 'zhen') else 'DOWN'
            return {
                'transformed': True,
                'pre_gua': bagua,
                'post_gua': 'qian' if post_direction == 'UP' else 'kun',
                'post_direction': post_direction,
            }
    
    # 趋势阶段：算盛极而衰度
    if bagua in ('qian', 'kun'):
        # 物极必反：趋势到极致后转化
        if accumulation >= threshold:
            return {
                'transformed': True,
                'pre_gua': bagua,
                'post_gua': 'dui' if bagua == 'qian' else 'gen',
                'post_direction': 'DOWN' if bagua == 'qian' else 'UP',
            }
    
    return {'transformed': False, 'pre_gua': bagua, 'post_gua': bagua}
```

### 3.2 否定之否定（螺旋定位）

```python
def determine_spiral_stage(negation_count: int) -> str:
    """
    螺旋阶段：FIRST_AFFIRMATION → FIRST_NEGATION → SECOND_NEGATION
    """
    if negation_count == 0:
        return 'FIRST_AFFIRMATION'
    elif negation_count == 1:
        return 'FIRST_NEGATION'
    elif negation_count == 2:
        return 'SECOND_NEGATION'
    else:
        return 'FIRST_AFFIRMATION'  # 重置
```

### 3.3 对立统一（对立卦分析）

| 卦 | 对立卦 | 关系 |
|---|---|---|
| 乾 ☰ | 坤 ☷ | 强涨 ↔ 强跌 |
| 震 ☳ | 巽 ☴ | 启动涨 ↔ 启动跌 |
| 坎 ☵ | 离 ☲ | 回调跌 ↔ 回调涨 |
| 艮 ☶ | 兑 ☱ | 蓄势涨 ↔ 蓄势跌 |

---

## 四、变爻机制（实时动态修正）

### 4.1 变爻等级

| 等级 | 触发 | 处置 |
|---|---|---|
| NO_CHANGE | 0 爻变 | 维持当前卦象 |
| MINOR | 1 爻变（小变）| 调整置信度 |
| MODERATE | 2 爻变（中变）| 重新卜算 |
| MAJOR | 3 爻变（大变=变卦）| 立即重新卜算 + 预警 |

### 4.2 变爻概率（易经传统）

| 爻象 | 概率 | 含义 |
|---|---|---|
| 老阴（变）| 1/16 | 阴极变阳 |
| 少阳（不变）| 5/16 | 阴中有阳 |
| 少阴（不变）| 5/16 | 阳中有阴 |
| 老阳（变）| 5/16 | 阳极变阴 |

Phase 1 用传统概率做基线，Phase 2 回测后校准。

---

## 五、八卦与辩证法的对应

| 辩证法规律 | 易经体现 | 八卦应用 |
|---|---|---|
| 对立统一 | 对立卦（乾↔坤）| 主矛盾和主要方面识别 |
| 量变质变 | 卦象流转（艮→乾）| accumulation + threshold |
| 否定之否定 | 螺旋定位 | FIRST_AFFIRMATION → FIRST_NEGATION → SECOND_NEGATION |

---

## 六、八卦哲学指引

| 卦 | 哲学指引 | 交易启示 |
|---|---|---|
| 乾 | 天行健，君子以自强不息 | 顺势而为，不要逆势 |
| 坤 | 地势坤，君子以厚德载物 | 承认下跌，不要硬抗 |
| 震 | 雷动万物 | 关注启动信号，量变开始 |
| 巽 | 风行天下 | 警惕突发下跌，风无常形 |
| 坎 | 水流就下 | 回调是常态，不要恐慌 |
| 离 | 火炎向上 | 反弹要谨慎，火易熄 |
| 艮 | 山止蓄势 | 蓄势待发，耐心等待 |
| 兑 | 泽润万物 | 蓄势下跌，准备应对 |

---

## 七、与其他文档的关系

```
                ┌─────────────────────────────┐
                │  BCRM 核心方法论三层架构      │ ← 统领
                └──────────────┬──────────────┘
                               │
            ┌──────────────────┼──────────────────┐
            ↓                  ↓                  ↓
   ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
   │ 唯物辩证法三规律  │ │ 矛盾论补充       │ │ 易经价值定位      │
   │ 第二层核心规律    │ │ 第二层操作方法   │ │ 第三层价值定位    │
   └─────────────────┘ └─────────────────┘ └─────────────────┘
                               │                  │
                               ↓                  ↓
                       ┌─────────────────┐ ┌─────────────────┐
                       │ 易经蒸馏（本文） │ │ 黑格尔正反合      │
                       │ 第三层卜算形式    │ │ 第三层推理步形式  │
                       └─────────────────┘ └─────────────────┘
```

**本文档与 [易经价值定位](yijing_value_positioning.md) 的关系**：
- 易经价值定位：为什么用易经、用什么、不用什么
- 本文档：怎么用易经卜算（八卦形式 + 算法）

---

## 八、关键要点总结

1. **三大原则**：变易（变爻）/ 简易（八卦简化）/ 不易（辩证法规律）
2. **卜算流程**：太极→两仪→四象→八卦→乾坤，每层有明确算法
3. **三爻叠加法**：初爻（本质40%）+ 二爻（表现35%）+ 三爻（趋势25%）
4. **八卦定义**：严格遵循辩证法（量变质变 + 否定之否定）
5. **对立卦**：乾↔坤、震↔巽、坎↔离、艮↔兑
6. **变爻机制**：单爻变小变、双爻变中变、三爻变大变
7. **变爻概率**：Phase 1 用传统概率（1/16/5/16/5/16/5/16），Phase 2 校准
8. **哲学指引**：每卦有对应的交易启示

---

**蒸馏完成**：易经八卦形式与卜算算法已独立成文。本文档定义了 BCRM 第三层的卜算形式，与 [易经价值定位](yijing_value_positioning.md)（价值总纲）和 [黑格尔正反合](hegelian_dialectic_distillation.md)（推理步形式）共同构成过程层文档体系。
