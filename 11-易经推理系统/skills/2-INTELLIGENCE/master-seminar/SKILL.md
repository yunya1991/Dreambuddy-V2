---
name: master-seminar
description: |
  🎓 大师研讨SKILL - 让已蒸馏的交易大师基于A系列报告分阵营辩论
  核心职能: 大师分阵营辩论 / 挑刺 / 追问 / 进化
  触发词: 大师研讨、召唤大师辩论、让大师讨论、大师评议
  差异化: 基于每日A系资料训练，驱动大师动态进化
version: 1.0.0
created: 2026-04-29
updated: 2026-04-29
status: 构建中
---

## 【合规要求】⭐ v1.0 新增

### §合规 问题处理流程

> ⚠️ **合规约束**: 遇到任何问题必须按以下顺序处理：

```
遇到问题
    ↓
Step 1️⃣ 查FAQ
  → WORKSPACE/.workbuddy/faq/OKX_FAQ.md（OKX相关）
  → WORKSPACE/.workbuddy/faq/技术_FAQ.md（技术相关）
  → WORKSPACE/.workbuddy/faq/运营_FAQ.md（运营相关）
    ↓ 有解 → 执行 ✓
    ↓ 无解 → Step 2

Step 2️⃣ 查治理文档
  → ~/.workbuddy/skills/dream-governance-manager/governance_docs/
    ↓ 有解 → 执行 + 补充FAQ ✓
    ↓ 无解 → Step 3

Step 3️⃣ 联网搜索
  → 使用 tavily/agent-reach 搜索
    ↓ 有解 → 执行 + 归档经验 ✓
    ↓ 无解 → Step 4

Step 4️⃣ 自主分析
    ↓ 有解 → 执行 + 输出报告 + 归档 ✓
    ↓ 无解 → 升级处理
```

### §合规 常见问题索引

| 问题类型 | FAQ位置 | 备注 |
|:---|:---|:---|
| OKX API错误 | `faq/OKX_FAQ.md` | CLI命令/API签名 |
| 账户查询问题 | `faq/OKX_FAQ.md` | 权限/配置文件 |
| 技术实现问题 | `faq/技术_FAQ.md` | 脚本/工具问题 |
| 流程协作问题 | `faq/运营_FAQ.md` | 制度/规范问题 |
| 合规判定问题 | `dream-governance-manager/` | 治理文档 |

### §合规 违规处理

| 违规类型 | 判定条件 | 处罚 |
|:---|:---|:---|
| 跳步违规 | 未查FAQ直接联网/分析 | 记过一次 |
| FAQ缺失 | 问题存在但未查阅 | 警告 |
| 归档缺失 | 问题解决但未归档 | 记录 |

---

# 🎓 Master-Seminar: 大师研讨SKILL v1.0

> **核心定位**: 让已蒸馏的交易大师基于A系列报告分阵营辩论，通过对抗性讨论发现隐藏风险，驱动大师动态进化。

## 一、核心职能

```
┌─────────────────────────────────────────────────────────┐
│              🎓 大师研讨SKILL (Master-Seminar)            │
├─────────────────────────────────────────────────────────┤
│  输入: A系列有价值报告 (A1调研/A3战略/A4验证/A5执行)     │
│       ↓                                                  │
│  过程: 大师分阵营辩论 / 挑刺 / 追问                       │
│       ↓                                                  │
│  输出: 多空阵营结论 + 关键争议点 + 可执行建议            │
│       ↓                                                  │
│  进化: 基于讨论质量更新大师权重/风格                     │
└─────────────────────────────────────────────────────────┘
```

## 二、大师阵营系统

```
                    ┌──────────────────┐
                    │   本次研讨议题    │
                    │ (A系列报告输入)  │
                    └────────┬─────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ↓                    ↓                    ↓
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│   🟢 多方阵营  │    │   🟡 中立阵营  │    │   🔴 空方阵营  │
│ (Soros系大师)  │    │ (Tharp系大师) │    │ (PTJ系大师)  │
├───────────────┤    ├───────────────┤    ├───────────────┤
│ • Soros       │    │ • Tharp       │    │ • PTJ        │
│ • Druckenmiller│    │ • Livermore  │    │ • 达利欧     │
│ • 巴菲特      │    │ • 欧奈尔     │    │ • 雷达里奥   │
└───────────────┘    └───────────────┘    └───────────────┘
        ↓                    ↓                    ↓
        └────────────────────┼────────────────────┘
                             ↓
                    ┌──────────────────┐
                    │   📊 研讨结论    │
                    │ • 多空倾向评分   │
                    │ • 关键争议点     │
                    │ • 可执行建议     │
                    └──────────────────┘
```

## 三、大师库（10位已蒸馏大师）

| 大师 | 阵营 | 核心风格 | 擅长Regime |
|:---|:---:|:---|:---|
| **Soros** | 多 | 反身性理论、宏观择时 | HIGH_VOL/BEAR |
| **Druckenmiller** | 多 | 趋势追踪、杠杆大师 | TREND_BULL/BEAR |
| **PTJ (Paul Tudor Jones)** | 空 | 宏观择时、危机Alpha | HIGH_VOL/BEAR |
| **巴菲特** | 多 | 价值投资、长期持有 | NEUTRAL/BULL |
| **Ray Dalio** | 空 | 宏观对冲、风险平价 | CRISIS/DEFLATION |
| **Tharp** | 中 | 交易系统、仓位管理 | ALL |
| **Livermore** | 中 | 趋势识别、关键点交易 | TREND/RANGE |
| **欧奈尔** | 多 | CANSLIM、成长股 | BULL_REGIME |
| **Stanley Druckenmiller** | 多 | 流动性狩猎 | VOLATILE |
| **Michele** | 中 | 量化系统、统计套利 | RANGE/SIDEWAYS |

## 四、触发机制

### 4.1 自动触发

| 触发条件 | 优先级 | 参与大师 |
|:---|:---:|:---|
| Regime从NEUTRAL→BULL/BEAR | P0 | 全量大师 |
| A5执行后24h内 | P1 | 相关Regime大师 |
| 连续SKIP≥7天 | P2 | 激进取态大师(Soros/PTJ) |
| FGI变化>20点 | P2 | 情绪相关大师 |

### 4.2 手动触发

```
触发词: "大师研讨"、"召唤大师辩论"、"让大师讨论"
输入: 可选 - 指定A系列报告或议题
```

## 五、研讨流程（5步）

```
Step 1: 议题输入
├── 触发条件: Regime变化 / A5执行后 / 手动触发
├── 输入内容: A系列报告摘要 + 当前市场状态
└── 大师筛选: 根据Regime选择相关大师

Step 2: 阵营分配
├── 多方阵营: 持有"看多"立场的大师
├── 空方阵营: 持有"看空"立场的大师
└── 中立阵营: 关注"风险"的大师

Step 3: 分阵营研讨
├── 每方阵营内部讨论 (2-3位大师)
├── 输出: 核心论点 + 支撑证据 + 反驳对方
└── 限制: 每轮最多3个核心论点

Step 4: 交叉辩论
├── 多空双方直接交锋
├── 大师间互相追问 (每次最多2轮)
├── 寻找共识点和核心分歧点
└── 中立大师担任裁判

Step 5: 结论输出
├── 多空倾向评分: +3(强多) ~ -3(强空)
├── 关键争议点: TOP 3 核心分歧
├── 可执行建议: 供A5参考的操作建议
└── 大师置信度: 每位大师的论点可信度
```

## 六、模块架构

```
master-seminar/
├── SKILL.md                    # 本文件 (主入口)
├── modules/
│   ├── __init__.py
│   ├── M1_orchestrator.py      # 研讨编排器
│   ├── M2_master_selector.py   # 大师选择器
│   ├── M3_camp_generator.py    # 阵营生成器
│   ├── M4_debate_engine.py     # 辩论引擎
│   ├── M5_conclusion_extractor.py  # 结论提取器
│   ├── M6_master_evolution.py  # 大师进化器
│   └── M7_report_writer.py     # 报告生成器
├── prompts/
│   ├── master_prompts.yaml     # 大师角色提示词
│   ├── debate_prompts.yaml     # 辩论提示词
│   └── evolution_prompts.yaml  # 进化提示词
├── templates/
│   ├── seminar_report.md       # 研讨报告模板
│   └── master_response.json    # 大师响应模板
├── config/
│   ├── masters.yaml            # 大师配置
│   └── rules.yaml              # 研讨规则
└── reports/                    # 研讨报告存档
    └── (seminar_YYYYMMDD_*.md)
```

## 七、大师进化机制

### 7.1 进化维度

| 维度 | 说明 | 更新频率 |
|:---|:---|:---:|
| 观点权重 | 大师观点被采纳的比率 | 每周 |
| 风格适应 | 对新Regime的适应度 | 每月 |
| 协作指数 | 与其他大师配合效率 | 每月 |
| 预测准确率 | 研讨结论与实际走势对比 | 每日 |

### 7.2 进化公式

```python
# 采纳率 = 被A5采纳的建议数 / 总建议数
adoption_rate = adopted_advice / total_advice

# 权重调整
if adoption_rate > 0.7:
    master.weight *= 1.1  # 加权
elif adoption_rate < 0.4:
    master.weight *= 0.9  # 降权

# 风格适应 (基于Regime表现)
if seminar_regime == "HIGH_VOLATILITY":
    master.tags.add("volatility_expert")
```

## 八、输出格式

### 8.1 研讨报告结构

```json
{
  "seminar_id": "SEM_20260429_001",
  "timestamp": "2026-04-29T10:30:00Z",
  "trigger": {
    "type": "REGIME_CHANGE|A5_EXECUTION|MANUAL",
    "source_report": "A5_20260429_..."
  },
  "camps": {
    "bullish": {
      "masters": ["soros", "druckenmiller", "buffett"],
      "thesis": "核心看多论点...",
      "evidence": ["证据1", "证据2"],
      "confidence": 0.75
    },
    "neutral": {
      "masters": ["tharp", "livermore"],
      "observations": ["风险观察1", "风险观察2"],
      "confidence": 0.60
    },
    "bearish": {
      "masters": ["ptj", "dalio"],
      "thesis": "核心看空论点...",
      "evidence": ["证据1", "证据2"],
      "confidence": 0.70
    }
  },
  "debate": {
    "rounds": 3,
    "key_disputes": [
      {
        "issue": "BTC是否突破$80K?",
        "bull_view": "突破概率70%",
        "bear_view": "突破概率30%",
        "resolution": "中立-等待验证"
      }
    ]
  },
  "conclusion": {
    "bias": 0.5,
    "confidence": 0.68,
    "actionable_suggestions": [
      "建议1: 轻仓试探，止损$75K",
      "建议2: 等待突破后追入"
    ],
    "master_agreement": 0.72
  },
  "evolution": {
    "soros_weight_update": "+0.05",
    "ptj_style_adjusted": "增加宏观权重"
  }
}
```

## 九、与其他SKILL的集成

| 集成点 | 方向 | SKILL | 说明 |
|:---|:---:|:---|:---|
| 大师库 ← | ← | master-distillation-orchestrator | 获取已蒸馏大师 |
| 触发 ← | ← | dream-regime-detector | Regime变化触发 |
| 反馈 ← | ← | dream-performance-review | 研讨质量反馈 |
| 结论 → | → | boss-secretary | 研讨结论归档 |
| 自检 ← | ← | A8-theory-practice-verification | 研讨质量由A8检验 |

## 十、使用示例

```
用户输入: "大师研讨一下当前市场"

系统执行:
1. M1读取最新A系列报告 (A1/A3/A5)
2. M2根据当前Regime选择大师
3. M3分配多空阵营
4. M4驱动辩论 (3轮)
5. M5提取结论
6. M6更新大师权重
7. M7生成报告
8. 归档到boss-secretary/reports/
```

---

**触发词**: 大师研讨、召唤大师辩论、让大师讨论、大师评议

**版本**: v1.0.0

**最后更新**: 2026-04-29
