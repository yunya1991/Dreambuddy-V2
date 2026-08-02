# NanoClaw 技能调用策略与基本面分析系统协调方案

**文档状态**: Draft  
**更新时间**: 2026-04-05  
**适用范围**: NanoClaw 助手系统 + 经典指标机器学习系统 + 基本面分析系统

---

## 一、系统架构总览

### 1.1 三大系统定位

```
┌─────────────────────────────────────────────────────────────────┐
│                    用户请求入口                                  │
│                    (WhatsApp/Telegram/本地)                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      NanoClaw 助手系统                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │  工具类技能  │  │  协调层技能  │  │  基本面分析系统桥接     │ │
│  │  (纯工具)   │  │  (路由/编排) │  │  (Signal Bridge)        │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
│   - Ollama 模型调用        - 智能路由         - 新闻分析         │
│   - Playwright 浏览器      - 上下文管理        - 资金流分析       │
│   - 消息发送/任务调度      - 自动 Compact      - 叙事情绪分析     │
│   - Debug 诊断             - 权限校验          - Web3 行情汇总    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    基本面分析系统                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  五大模块（只读建议层 execution_gate=readonly_advisory）   │   │
│  │  /fundamental/news      - 新闻分析 (crypto-news-digest)  │   │
│  │  /fundamental/flows     - 资金流分析                      │   │
│  │  /fundamental/narrative - 叙事情绪分析                     │   │
│  │  /fundamental/trading   - 交易建议层                       │   │
│  │  /fundamental/web3-digest - Web3 行情汇总                  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  输出契约（标准化信号格式）                                 │   │
│  │  - signal: {buy_sell_signal, trend_direction, confidence} │   │
│  │  - advice: {bias_dir, execution_filter, risk_action}      │   │
│  │  - evidence_chain: [{module, metric, value, grade}]       │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    经典指标机器学习系统                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │  信号接收    │  │  策略执行    │  │  风控/审计/审批          │ │
│  │  (只读建议)  │  │  (受控写入)  │  │  (admin/sandbox)        │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、技能分类与职责边界

### 2.1 两类技能定义

#### A 类：纯工具类技能 (Tool Skills)

**定位**: 通用能力，不特定于交易业务

| 技能 | 版本 | 用途 | 触发条件 | 成本 |
|------|------|------|----------|------|
| `ollama` | 1.0.0 | 本地模型推理 | 简单任务/代码任务 | $0 |
| `compact` | 1.0.0 | 上下文压缩 | 50 条消息或手动 | $0 |
| `customize` | 1.0.0 | 配置助手 | 用户请求配置变更 | $0 |
| `debug` | 1.0.0 | 故障诊断 | 系统异常排查 | $0 |
| `agent-browser` | - | 浏览器 CLI | 快速网页访问 | $0 |
| `playwright` | 0.0.70 | 浏览器 MCP | 复杂网页交互 | $0 |

**智能路由规则**:
```
用户请求
  │
  ├─ 简单问答/翻译/摘要？
  │   └─→ ollama_generate(qwen2.5:7b-instruct)
  │
  ├─ 代码生成/调试？
  │   └─→ ollama_generate(qwen2.5-coder)
  │
  ├─ 需要访问网页？
  │   ├─ 快速访问 → agent-browser open <url>
  │   └─ 复杂交互 → Playwright MCP
  │
  ├─ 上下文超过 50 条消息？
  │   └─→ 自动触发 compact
  │
  └─ 复杂推理/创意？
      └─→ Claude 直接响应
```

#### B 类：基本面分析系统技能 (Fundamental Skills)

**定位**: 交易业务核心，输出标准化信号

| 技能 | 状态 | 输入源 | 输出目标 | 权限 |
|------|------|--------|----------|------|
| `crypto-news-digest` | 已落地 | 新闻 API/Twitter | brief/event_ledger | viewer/read |
| `flow-brief-generator` | 已落地 | 资金流数据 | FlowTrend/Impulse/Stress | viewer/read |
| `crypto-narrative-sentiment` | 已落地 | 社区/叙事数据 | CommunityEffective/Stress | viewer/read |
| `crypto-market-rank` | 在库 | Binance Web3 | rankings/digest | viewer/read |
| `fundamental-signal-bridge` | 已落地 | 研究仓产物 | 交易仓信号 payload | viewer/read |
| `fundamental-trading-advisor` | 规划中 | 1/2/3 汇总 | bias/filter/risk-off | viewer/read |

**输出契约（标准化信号格式）**:
```json
{
  "generated_at": "ISO8601",
  "execution_gate": "readonly_advisory",
  "signal": {
    "buy_sell_signal": "buy|sell|hold",
    "trend_direction": "up|down|neutral",
    "trend_speed": "slow|medium|fast",
    "signal_confidence": 0.0
  },
  "advice": {
    "bias_dir": "long_only|short_only|two_sided|neutral",
    "execution_filter": "allow|slowdown|block",
    "risk_action_proposal": "hold|reduce|hedge|stop_loss",
    "position_scale": 0.0,
    "ttl": "4h"
  },
  "quality_summary": {
    "overall_quality": "ok|stale|missing|backfilled|suspect",
    "coverage": 0.0,
    "missing_data": []
  },
  "evidence_chain": [
    {
      "module": "flows|news|narrative|web3",
      "metric": "string",
      "value": "number|string",
      "direction": "risk_up|risk_down|neutral",
      "source_ref": "path_or_url",
      "source_time": "ISO8601",
      "evidence_grade": "A|B|C|D"
    }
  ]
}
```

---

## 三、智能路由系统设计

### 3.1 请求分类决策树

```
用户请求
    │
    ├─ 【类型 A】系统运维类请求
    │   ├─ "检查系统状态" → debug 技能 + outbox 读取
    │   ├─ "查看日志" → debug 技能 + 日志文件读取
    │   ├─ "修复 XX 问题" → debug + customize（需要审批）
    │   └─ "添加新通道" → customize 技能交互式配置
    │
    ├─ 【类型 B】通用工具类请求
    │   ├─ 简单任务 → Ollama (qwen2.5:7b-instruct)
    │   ├─ 代码任务 → Ollama (qwen2.5-coder)
    │   ├─ 网页访问 → Playwright / agent-browser
    │   └─ 复杂推理 → Claude 直接响应
    │
    ├─ 【类型 C】基本面分析请求
    │   ├─ "查看新闻摘要" → crypto-news-digest
    │   ├─ "资金流情况" → flow-brief-generator
    │   ├─ "市场情绪如何" → crypto-narrative-sentiment
    │   ├─ "Web3 热点" → crypto-market-rank
    │   └─ "生成交易信号" → fundamental-signal-bridge
    │
    └─ 【类型 D】交易执行请求
        ├─ "执行交易" → 拒绝，引导至/fundamental/automation
        ├─ "修改策略" → 引导至审批流程
        └─ "查看信号" → viewer/read 权限读取
```

### 3.2 模型成本优化策略

| 任务类型 | 默认模型 | 触发条件 | 备选模型 | 成本 |
|---------|----------|----------|----------|------|
| 简单问答 | Ollama 7B | 无网页需求 | Claude Haiku | $0 |
| 翻译摘要 | Ollama 7B | 文本<1000 字 | Claude Haiku | $0 |
| 代码任务 | Ollama Coder | 纯代码/技术 | Claude Sonnet | $0 |
| 网页访问 | Playwright | 需要交互 | agent-browser | $0 |
| 复杂分析 | Claude Opus | 多步骤推理 | - | $$ |
| 创意写作 | Claude Opus | 需要创造力 | - | $$ |
| 新闻分析 | crypto-news-digest | 基本面请求 | - | $0 |
| 信号生成 | fundamental-signal-bridge | 交易请求 | - | $0 |

### 3.3 权限校验规则

```yaml
权限级别:
  viewer:
    允许:
      - 读取基本面信号
      - 读取系统状态
      - 读取日志
      - 使用工具类技能
    禁止:
      - 修改配置
      - 执行交易
      - 修改策略参数
      
  admin:
    允许:
      - viewer 所有权限
      - 审批变更请求
      - 修改配置（受审计）
    禁止:
      - 直接执行交易（需走审批）
      - 修改风控阈值（需走治理）
      
  super_admin:
    允许:
      - admin 所有权限
      - 紧急风控操作
      - 系统级配置
    约束:
      - 所有操作必须审计落盘
```

---

## 四、基本面分析系统集成

### 4.1 信号流转流程

```
┌─────────────────┐
│  数据采集层      │
│  - 新闻 API      │
│  - 资金流数据     │
│  - 社区/叙事数据  │
│  - Web3 榜单     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  分项技能层      │
│  - crypto-news-digest    → brief/event_ledger
│  - flow-brief-generator  → FlowTrend/Impulse/Stress
│  - crypto-narrative-sentiment → CommunityEffective/Stress
│  - crypto-market-rank    → rankings/digest
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  总控编排层      │
│  - 契约校验 (schema/quality/coverage)
│  - 证据链拼装
│  - 总览汇总
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  交易建议层      │
│  - fundamental-signal-bridge
│  - fundamental-trading-advisor (规划)
│  输出：bias/filter/risk-off 建议
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  经典指标系统    │
│  - 信号接收 (只读)
│  - 策略执行 (受控)
│  - 风控/审批 (admin)
└─────────────────┘
```

### 4.2 Fail-Closed 规则

```yaml
降级策略:
  coverage < 阈值:
    动作：不输出风险放大建议
    默认：hold + neutral + block
    
  missing_data 非空:
    动作：至少触发 execution_filter=slowdown
    披露：explicit_unknown + 降级原因
    
  evidence_chain 为空:
    动作：输出 buy_sell_signal=hold
    禁止：展示风险放大建议
    
  quality = missing/suspect:
    动作：页面显式降级提示
    约束：不得突破 readonly_advisory
```

---

## 五、监控与运维

### 5.1 系统健康检查清单

```yaml
10 分钟轮询 (轻量):
  - outbox 读取：audit_actions.jsonl 最新 10 条
  - 健康快照：health_snapshot 生成
  - 告警分级：P0/P1 优先推送
  
每日深检 (UTC 凌晨):
  - 链路检查：link_check
  - 根因分析：triage
  - 变更包：changeset 生成
  
告警分级:
  P0: 资金/执行安全风险（先止血后复盘）
  P1: 关键链路持续异常（信号/订单/门禁）
  P2: 功能降级或局部异常（可绕过）
  P3: 优化建议/边际偏离（周会复盘）
```

### 5.2 outbox 审计追踪

```
user_data/agent_outbox/
├── audit_actions.jsonl    # 审计动作落盘
├── chat.jsonl             # 对话记录
└── pipeline_artifacts.jsonl  # 流水线产物

关键字段:
- name: 动作名称 (如 agent.paramopt.completed)
- ts: 时间戳
- payload: 结构化负载 (含 trace_id)
```

---

## 六、实施路线图

### 6.1 短期（本周）

- [x] 智能路由提示集成到 System Prompt
- [x] Ollama MCP 工具描述增强
- [x] NanoClaw 技能分类文档
- [ ] 基本面分析系统技能状态盘点
- [ ] outbox 读取 MCP 工具添加

### 6.2 中期（本月）

- [ ] fundamental-hub-orchestrator 总控技能开发
- [ ] fundamental-trading-advisor 建议层技能开发
- [ ] 权限校验 MCP 中间件
- [ ] 系统健康检查定时任务

### 6.3 长期（下季度）

- [ ] 完整自动化决策闭环
- [ ] 跨系统证据链追踪
- [ ] AI Agent 自主修复（R2 级别）
- [ ] 审批流集成

---

## 七、风险与约束

### 7.1 权威边界 (SSoT)

```
生产交易系统行为边界：/技术文档.md
AI Agent/沙箱/门禁：/交易 AI Agent 技术文档 2.0.md
nanoclaw 运维隔离：/ops/nanoclaw/README.md
基本面分析系统：/基本面分析文档.md
```

### 7.2 默认策略

- **tighten-only**: 修复动作默认收紧风险，禁止用放宽掩盖问题
- **审批门禁**: 扩大风险敞口必须走人工审批
- **审计落盘**: 所有关键动作必须 trace_id + 证据链
- **fail-closed**: 缺失/冲突证据时默认保守

---

*文档结束*
