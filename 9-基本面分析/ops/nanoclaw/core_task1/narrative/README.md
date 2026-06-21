# 加密叙事分析 Skill 使用手册

**版本**: v1.0.0
**创建日期**: 2026-03-17

---

## 快速开始

### 1. 基本用法

```bash
# 进入目录
cd /workspace/ops/nanoclaw/core_task1/narrative

# 运行叙事分析（最近 24 小时）
./run_narrative_analysis.sh

# 或使用 Python 直接运行
python3 scripts/narrative_analyzer.py --hours 24
```

### 2. 使用模拟数据演示

```bash
# 使用模拟数据演示
./run_narrative_analysis.sh --mock

# 或
python3 scripts/narrative_analyzer.py --hours 24 --mock
```

### 3. 指定分析窗口

```bash
# 分析最近 4 小时
./run_narrative_analysis.sh hours 4

# 分析最近 12 小时
./run_narrative_analysis.sh hours 12
```

### 4. 指定输出文件

```bash
# 输出到指定文件
./run_narrative_analysis.sh --mock -o my_narrative_brief.md
```

---

## 输出文件

### 叙事登记簿 (JSON)

路径：`narrative/outputs/narrative_registry_YYYYMMDD_HHMM.json`

```json
{
  "timestamp": "2026-03-17T20:28:17Z",
  "analysis_window": "最近 24 小时 (模拟数据)",
  "narratives": [
    {
      "narrative_id": "etf_institutional_20260317",
      "narrative_name": "ETF/机构",
      "category": "etf_institutional",
      "status": "active",
      "heat_score": 0.37,
      "sentiment_score": 0.75,
      "sentiment_trend": "weakening",
      "related_tokens": ["BTC", "ETH"],
      "event_count": 2,
      "lifecycle_stage": "growing",
      "confidence": 0.60
    }
  ],
  "overall_sentiment": 0.2214,
  "overall_heat": 0.37,
  "top_narrative": "ETF/机构",
  "summary": "当前主导叙事为「ETF/机构」，热度 0.37，情绪 +0.75..."
}
```

### 叙事简报 (Markdown)

路径：`narrative/outputs/narrative_brief_YYYYMMDD_HHMM.md`

包含以下章节：
1. **核心叙事总览** - 表格形式展示所有叙事
2. **叙事热度排行** - Top 5 叙事详细分析
3. **情绪分析** - 正面/负面叙事分类
4. **策略解读** - 市场情绪判定和投资建议
5. **叙事分布** - 按类别统计

---

## 叙事分类体系

| 类别 ID | 类别名称 | 关键词示例 |
|--------|---------|-----------|
| `etf_institutional` | ETF/机构 | ETF、贝莱德、富达、IBIT |
| `layer2_scaling` | Layer2/扩容 | Arbitrum、Optimism、L2 |
| `defi` | DeFi | 借贷、DEX、Uniswap、TVL |
| `nft_metaverse` | NFT/元宇宙 | NFT、OpenSea、元宇宙 |
| `gamefi` | GameFi | GameFi、Play-to-Earn、链游 |
| `stablecoin` | 稳定币 | USDT、USDC、DAI |
| `regulation_policy` | 监管政策 | SEC、监管、合规 |
| `tech_innovation` | 技术创新 | 升级、硬分叉、EIP |
| `security` | 安全事件 | 攻击、黑客、漏洞 |
| `macro_finance` | 宏观金融 | 美联储、利率、CPI |

---

## 指标说明

### 叙事热度 (Heat Score)

计算公式：
```
heat = 0.4 × 事件数量分 + 0.35 × 互动量分 + 0.25 × 时间衰减分
```

| 热度范围 | 生命周期阶段 | 说明 |
|---------|------------|------|
| 0.0 - 0.3 | 🌱 萌芽期 | 叙事刚出现，关注度低 |
| 0.3 - 0.7 | 🌿 成长期 | 叙事快速传播，热度上升 |
| 0.7 - 0.9 | 🌳 成熟期 | 叙事成为主流，关注度高 |
| 0.9+ | 🍂 衰退期 | 叙事过热，可能即将转向 |

### 情绪分数 (Sentiment Score)

| 分数范围 | 情绪倾向 | 图标 |
|---------|---------|------|
| > 0.2 | 正面 | 🟢 |
| -0.2 ~ 0.2 | 中性 | 🟡 |
| < -0.2 | 负面 | 🔴 |

### 情绪趋势 (Sentiment Trend)

| 趋势 | 说明 | 图标 |
|------|------|------|
| strengthening | 情绪升温 | 📈 |
| weakening | 情绪降温 | 📉 |
| stable | 情绪稳定 | ➡️ |

---

## 与新闻分析 Skill 对比

| 特性 | crypto-news-digest | crypto-narrative-analysis |
|------|-------------------|--------------------------|
| **焦点** | 每日新闻事件 | 中长期叙事主题 |
| **时间尺度** | 分钟级~小时级 | 日级~周级 |
| **输出** | event_ledger + brief | narrative_registry + narrative_brief |
| **分析方法** | 事件情感分析 | 叙事聚合 + 热度追踪 |
| **优势** | 即时性强 | 趋势识别、噪音过滤 |

---

## 与新闻分析 Skill 联动

叙事分析依赖于新闻分析生成的 event_ledger 数据：

```
crypto-news-digest
       │
       │ event_ledger.jsonl
       │ (事件 + 情感)
       ▼
crypto-narrative-analysis
       │
       │ 聚合事件 → 识别叙事
       │ 追踪热度 → 分析情绪
       ▼
narrative_registry.json
narrative_brief.md
```

### 融合信号公式

```python
# 新闻信号 (T0/T1 事件驱动)
news_signal = weighted_sentiment_sum

# 叙事信号 (中长期趋势)
narrative_signal = Σ(narrative_heat × narrative_sentiment × lifecycle_weight)

# 融合信号
fused_signal = 0.6 × news_signal + 0.4 × narrative_signal
```

---

## 使用场景

| 场景 | 推荐命令 |
|------|----------|
| 每日复盘 | `./run_narrative_analysis.sh hours 24` |
| 周度总结 | `./run_narrative_analysis.sh hours 168` |
| 突发新闻后 | `./run_narrative_analysis.sh hours 4` |
| 演示测试 | `./run_narrative_analysis.sh --mock` |

---

## 文件结构

```
narrative/
├── scripts/
│   └── narrative_analyzer.py      # 核心分析引擎
├── outputs/
│   ├── narrative_registry_*.json  # 叙事登记簿
│   └── narrative_brief_*.md       # 叙事简报
├── history/                        # 历史记录（预留）
├── run_narrative_analysis.sh       # 运行脚本
└── README.md                       # 本文档
```

---

## 命令行选项

```
用法: narrative_analyzer.py [选项]

选项:
  --hours N        分析最近 N 小时的事件 (默认：24)
  --mock           使用模拟数据演示
  -o, --output     指定输出文件路径
  -h, --help       显示帮助信息
```

---

## 示例输出

```
============================================================
加密市场叙事分析生成器
============================================================

[1/3] 分析最近 24 小时事件...
  [使用模拟数据演示]

[2/3] 保存叙事登记簿...
  登记簿已保存：narrative/outputs/narrative_registry_20260317_2028.json

[3/3] 生成叙事简报...
  简报已保存：narrative/outputs/narrative_brief_20260317_2028.md

============================================================
叙事摘要:
  主导叙事：ETF/机构
  整体情绪：+0.2214
  叙事数量：7
  分析窗口：最近 24 小时 (模拟数据)
============================================================
```

---

## 注意事项

1. **数据依赖**: 叙事分析依赖于新闻分析生成的 event_ledger 数据
2. **时间窗口**: 建议使用至少 12 小时以上的窗口以获得足够事件
3. **模拟数据**: `--mock` 参数仅用于演示，真实分析请使用真实数据
4. **更新频率**: 建议每日运行一次，追踪叙事演化

---

*加密叙事分析 Skill v1.0 | 2026-03-17*
