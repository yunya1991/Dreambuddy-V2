# tavily 集成规范 (Team A Phase-0 + Team C + Process D)

> **原始 SKILL**: dream-multiskill-v2/skills/4-GENERIC/tavily/SKILL.md
> **集成团队**: Team A（Phase-0 强制数据采集）/ Team C（日内实时监控）/ Process D（复盘上下文研究）
> **触发时机**: Screen 1/2 Phase-0 P0.1-P0.6（HARD BLOCK）、P0.4b（非阻塞）、Team C A6 告警时

---

## 一、职责

为 6-TRADING 所有需要实时外部信息的环节提供标准化的 Tavily 搜索接口。
`dream-cost-control (CC)` 统一管理 Tavily 预算，tavily SKILL 负责实际搜索执行。

---

## 二、Phase-0 查询配置矩阵（Screen 1/2 标准配置）

| 步骤 | 查询模板 | 模式 | topic | max_results | 阻断级别 |
|------|---------|------|-------|------------|---------|
| P0.1 | `"Bitcoin BTC price USD {YYYY-MM-DD} current"` | basic | news | 5 | HARD BLOCK |
| P0.2 | `"Bitcoin perpetual futures funding rate {YYYY-MM-DD} OKX Binance"` | basic | news | 5 | HARD BLOCK |
| P0.3 | `"Bitcoin spot ETF net inflow outflow {YYYY-MM-DD}"` | basic | news | 5 | HARD BLOCK |
| P0.4 | `"Bitcoin macro risk factors {YYYY-MM-DD} Fed geopolitical"` | advanced | general | 8 | HARD BLOCK |
| P0.4b | `"Bitcoin {macro_keyword} historical price action 2020 2022 2024"` | advanced | general | 5 | 非阻塞 |
| P0.5 | `"Bitcoin support resistance technical analysis {YYYY-MM-DD}"` | basic | general | 5 | HARD BLOCK |
| P0.6 | `"Bitcoin fear greed index {YYYY-MM-DD}"` | basic | news | 3 | HARD BLOCK |
| Screen 2 P0.1 | `"Bitcoin BTC price USD {YYYY-MM-DD} current"` | basic | news | 3 | HARD BLOCK |

**模式选择逻辑**:
- `basic`（1-2s）: 事实查询（价格/费率/情绪指数）
- `advanced`（5-10s）: 宏观研究、历史类比分析（P0.4/P0.4b）

**总预算**: Phase-0 每次消耗 6-7 个 Tavily 调用（6 HARD + 1 可选 P0.4b）

---

## 三、权威数据域白名单（BTC 专用）

Phase-0 各步骤优先从以下域名提取数据（include_domains 配置）：

### 价格 / 行情（P0.1, Screen 2 P0.1）
```
coindesk.com, cointelegraph.com, coingecko.com, coinmarketcap.com,
tradingview.com, investing.com, finance.yahoo.com
```

### 资金费率 / 合约数据（P0.2）
```
coinglass.com, okx.com, binance.com, deribit.com, bybit.com
```

### ETF 资金流向（P0.3）
```
coindesk.com, theblock.co, bloomberg.com, wsj.com,
farside.co.uk, ssofficialsite.com
```

### 宏观 / 地缘风险（P0.4）
```
federalreserve.gov, reuters.com, bloomberg.com, ft.com,
marketwatch.com, cnbc.com, apnews.com
```

### 技术分析 / 价格关键位（P0.5）
```
tradingview.com, investing.com, cointelegraph.com, theblock.co,
cryptoquant.com, glassnode.com
```

### 恐贫指数（P0.6）
```
alternative.me, coinmarketcap.com, coindesk.com
```

### 历史类比研究（P0.4b）
```
coindesk.com, cointelegraph.com, messari.io, cryptoquant.com,
glassnode.com, research.binance.com
```

---

## 四、Team C 日内监控查询规范（dream-intelligence-monitor A6 使用）

| 告警级别 | 查询模板 | 模式 | topic | 触发条件 |
|---------|---------|------|-------|---------|
| P0 紧急 | `"Bitcoin breaking news crisis {YYYY-MM-DD HH:MM}"` | basic | news | 价格异动 >5% |
| P1 告警 | `"Bitcoin regulation news {YYYY-MM-DD}"` | basic | news | 监管事件信号 |
| P1 告警 | `"Bitcoin exchange hack exploit {YYYY-MM-DD}"` | basic | news | 安全事件信号 |
| 例行检查 | `"Bitcoin market update {YYYY-MM-DD}"` | basic | news | 每小时例行 |

**消耗预算**: 每次例行检查 1 个调用；P0/P1 告警最多额外 2-3 个调用

---

## 五、Process D 复盘研究查询（可选，非阻塞）

| 步骤 | 用途 | 查询模板 | 模式 |
|------|------|---------|------|
| D1 A8 偏见审计 | 验证上周 Screen1 判断的宏观事实 | `"Bitcoin {direction} rationale {YYYY-MM-DD week}"` | advanced |
| D2 规律验证 | 验证重复规律的外部佐证 | `"Bitcoin {pattern_key} market behavior"` | advanced |

**Process D Tavily 预算**: 最多 4 个额外调用，超预算时降级跳过（非 HARD BLOCK）

---

## 六、与 dream-cost-control (CC) 的协作规范

| CC 状态 | tavily 行为 |
|---------|-----------|
| `用量 >= 95%` | 全部停止，输出 `SCREEN_BLOCKED_BUDGET` |
| `用量 >= 85%` | **仅** P0.4b 降级跳过（archive_data:"budget_limited"）；P0.1-P0.6 其余步骤维持原模式正常执行 |
| `用量 < 85%` | 按矩阵正常执行 |

> **权威来源**: TRIGGER_PROMPTS.md §二 CC 前置规则（本文件与其保持一致，以触发提示词为准）

**预算记账规则**（CC 记录）:
- 每次 tavily SKILL 调用前，CC 先检查 `daily_tavily_calls` 计数器
- 每次成功调用后，CC 计数器 +1
- `include_raw_content=false`（默认）不额外消耗预算
- `search_depth=advanced` 消耗 2 个信用（相当于 2 次 basic 调用）

---

## 七、错误处理与降级链

| 错误类型 | tavily 处理 | 上游影响 |
|---------|-----------|---------|
| API key 无效 | 立即失败，输出 `TAVILY_AUTH_ERROR` | SCREEN1_BLOCKED → G4 SOP-2 |
| 无搜索结果（P0.1-P0.6）| 输出 `TAVILY_NO_RESULT:{step}` | SCREEN1_BLOCKED |
| 无搜索结果（P0.4b）| 设 `archive_data:"unavailable"` 继续 | 非阻塞，继续执行 |
| 超时 > 15s（basic）| 重试一次；失败则 NO_RESULT | 同上 |
| 超时 > 30s（advanced）| 降级为 basic 模式重试 | 标注 `mode_degraded:true` |
| 速率限制 | 等待 5s 重试一次 | 超时后同超时处理 |

---

## 八、输出格式规范（6-TRADING 版提取逻辑）

从 tavily 结构化结果中提取关键数据字段，注入 `data_context`：

```json
{
  "p0_1_price": {
    "value": 95420,
    "unit": "USD",
    "source": "coindesk.com",
    "ts": "2026-05-27T20:00:00+08:00",
    "score": 0.92
  },
  "p0_2_funding_rate": {
    "direction": "negative",
    "rate_pct": -0.015,
    "exchange": "OKX",
    "source": "coinglass.com"
  },
  "p0_3_etf_flow": {
    "direction": "inflow",
    "amount_usd_b": 0.45,
    "period": "daily",
    "source": "farside.co.uk"
  },
  "p0_4_macro": {
    "key_factors": ["Fed hawkish tone", "geopolitical risk elevated"],
    "sentiment": "risk-off",
    "source": "reuters.com"
  },
  "p0_5_key_levels": {
    "resistance": [97000, 100000],
    "support": [92000, 88500],
    "source": "tradingview.com"
  },
  "p0_6_fear_greed": {
    "index": 62,
    "label": "Greed",
    "source": "alternative.me"
  }
}
```

---

## 九、API Key 配置

```
TAVILY_API_KEY 存储于 Claude Code 环境变量或 Clawdbot config
键名: "tvly-..." (以 tvly- 开头)
计划要求: 最少 Free 计划（1000 credits/月）；建议 Professional 计划（月预算充足）
```

**每月预算估算**（50 calls/day × 30 days = 1500 calls/月）:
- Screen 1 (每周): 7 calls × 4 = 28 calls/月
- Screen 2 (每工作日 × ~22): 3 calls × 22 = 66 calls/月
- Team B (每工作日 × ~22): 1 call × 22 = 22 calls/月（仅价格校验）
- Team C 例行监控: ~1 call/天（仅持仓期，约 5 天/月）= 5 calls/月
- 缓冲/Process D: 20 calls/月
- **合计约 141 calls/月**（远低于 Free 计划 1000/月上限）

---

*最后更新: 2026-05-27 v1.1 | GAP-TA3 fix: 85% 规则对齐 TRIGGER_PROMPTS 权威来源（仅 P0.4b 降级）| 维护者: 6-TRADING Claude Code 协作系统*
