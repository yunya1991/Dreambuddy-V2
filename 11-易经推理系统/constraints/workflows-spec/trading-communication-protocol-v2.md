# Dream-MultiSkill A0-A9 通信协议与定时驱动架构

> **文档版本**: v2.1 (定时驱动 + A0 集成化重构)  
> **更新时间**: 2026-05-11  
> **架构**: 执行环 + 情报环 + 治理环（三环嵌套，定时任务驱动）

---

## 📋 目录

1. [三大核心闭环架构](#三大核心闭环架构)
2. [A0 矛盾 Skill 集成说明](#a0-矛盾-skill-集成说明)
3. [定时任务调度系统](#定时任务调度系统)
4. [通信协议规范](#通信协议规范)
5. [闭环触发机制](#闭环触发机制)
6. [消息格式定义](#消息格式定义)
7. [状态机与转换](#状态机与转换)
8. [处罚与重试机制](#处罚与重试机制)
9. [实现示例](#实现示例)

---

## 三大核心闭环架构

### 架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Dream-MultiSkill                          │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  🕐 定时调度层 (Cron Scheduler)                              │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │   │
│  │  │ A1 触发   │  │ A4 4h    │  │ A5 8h    │  │ A6 1h    │    │   │
│  │  │ 定时任务  │  │ 验证检查 │  │ 执行检查 │  │ 情报监控 │    │   │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘    │   │
│  │       │              │              │              │         │   │
│  └───────┼──────────────┼──────────────┼──────────────┼─────────┘   │
│          │              │              │              │             │
│  ┌───────▼──────────────▼──────────────▼──────────────▼─────────┐   │
│  │                  🔵 执行环 (Execution Loop)                   │   │
│  │         A1 → A2 → A3 → A4 → A5 → A9                      │   │
│  │         - A1: 深度调研 (A0 矛盾 Skill 内置)                  │   │
│  │         - A2: 第一性原理分析 (A0 矛盾 Skill 内置)            │   │
│  │         - A3: 策略设计 (A0 矛盾 Skill 内置)                  │   │
│  │         - A4: 战术验证 (每 4h 定时检查)                      │   │
│  │         - A5: 战术执行 (每 8h 定时运行)                      │   │
│  │         - A9: 离场决策                                     │   │
│  └────────────────────────┬────────────────────────────────────┘   │
│                           │ 执行结果通知                            │
│  ┌────────────────────────▼────────────────────────────────────┐   │
│  │                🟠 情报环 (Intelligence Loop)                 │   │
│  │                        A6 (每 1h 自动运行)                   │   │
│  │        5级放射驱动:                                         │   │
│  │        L0致命 → A9 (离场)                                 │   │
│  │        L1高 → A4 (验证)                                   │   │
│  │        L1.5变 → A2 (增量更新)                             │   │
│  │        L2中 → 观察                                        │   │
│  │        L3背离 → A1+A3 (重启)                              │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    🟣 治理环 (Governance Loop)               │   │
│  │           A7 → A8 → A1/A2/A3 (理论闭环)                    │   │
│  │           - A7: 实践记录 (A9 离场触发)                       │   │
│  │           - A8: 理论验证 (知行合一)                         │   │
│  │           - A1/A2/A3: 理论修正 (根据 gap_score 路由)         │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  🚀 驱动演进: 当前通过脚本/cron/Action 驱动 → 后期接入大模型自主驱动 │
└─────────────────────────────────────────────────────────────────────┘
```

---

### 1️⃣ 执行环 (Execution Loop) - 蓝色

#### 职能
正向执行交易决策，从调研到执行的完整链路。

#### 模块序列
```
定时任务 → A1 (调研) → A2 (分析) → A3 (策略) → A4 (验证) → A5 (执行) → A9 (离场)
```

#### 闭环特性
- **正向流**: A1→A2→A3→A4→A5→A9
- **反馈点**:
  - A4 验证失败 → 返回 A3 (策略调整)
  - A5 执行失败 → 返回 A4 (重新验证)
  - A9 离场 → 触发 A7 (实践记录，进入治理环)

#### 通信模式
- **同步调用**: A1→A2→A3→A4→A5 (串行)
- **异步通知**: A5→A6 (执行结果通知情报环)
- **事件驱动**: A9→A7 (离场触发治理环)

#### 状态转换
```
[IDLE] → 定时任务触发 → [RESEARCH] (A1) → [ANALYZING] (A2) → [STRATEGIZING] (A3)
       → [VALIDATING] (A4) → [EXECUTING] (A5) → [EXIT] (A9)
       → [PRACTICE] (A7) → [VERIFICATION] (A8) → [IDLE]
```

---

### 2️⃣ 情报环 (Intelligence Loop) - 琥珀色

#### 职能
A6 作为中枢，每 1 小时自动运行，通过 5 级放射驱动整个交易链路，实现实时监控与响应。

#### A6 中枢 5 级放射驱动

| 级别 | 触发条件 | 目标模块 | 动作 | 优先级 |
|------|----------|----------|------|--------|
| **L0 致命** | 风险事件 / 黑天鹅 | A9 | 立即离场 | CRITICAL |
| **L1 高** | 重大变化 / 验证失败 | A4 | 重新验证 | HIGH |
| **L1.5 变** | Regime 变化 | A2 | 增量更新 | HIGH |
| **L2 中** | 异常信号 | 观察 | 记录日志 | MEDIUM |
| **L3 背离** | 理论与实践背离 | A1+A3 | 重启调研 | MEDIUM |

#### 驱动能力

A6 不仅是一个监控模块，它可以根据 5 级评估结果**驱动整个交易链路**：

- **L0 驱动**: A9 立即离场 → 触发 A7 (实践记录) → A8 (理论验证) → A1/A2/A3 (修正) → 重新进入执行环
- **L1 驱动**: A4 重新验证 → 若通过则驱动 A5 → A9 → A7 → A8 → A1/A2/A3 → 执行环
- **L1.5 驱动**: A2 增量更新 → A3 → A4 → A5 → A9 → ... → 执行环
- **L3 驱动**: A1 重启调研 → A2 → A3 → A4 → A5 → A9 → ... → 执行环

#### 反馈闭环

```
                    ┌───────────────────────────────┐
                    │       A6 情报监控             │
                    │  (每 1h 自动运行)            │
                    └──────┬────────────┬─────────┘
                           │            │
              ┌────────────▼──────┐  │
              │  5级放射驱动      │  │
              └──────┬──────────┘  │
                     │              │
       ┌─────────────┼──────────────┼─────────────┐
       │             │              │             │
       ▼             ▼              ▼             ▼
  ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐
  │A9 离场  │   │A4 验证  │   │A2 更新  │   │A1+A3  │
  │(L0致命) │   │(L1高)   │   │(L1.5变)│   │重启    │
  └───┬────┘   └───┬────┘   └───┬────┘   └───┬────┘
      │               │              │              │
      └───────────────┴──────────────┴──────────────┘
                     │
                     ▼
              ┌──────────────┐
              │  执行环重启   │
              │  (A1→A5)    │
              └──────────────┘
```

#### 通信模式
- **发布/订阅**: A6 发布情报，其他模块订阅
- **事件驱动**: L0-L3 事件触发相应模块
- **异步推送**: A6 → A1/A2/A3/A4/A9

#### 定时触发
```yaml
schedule: "0 * * * *"  # 每小时
timeout: 300
retry: 3
```

---

### 3️⃣ 治理环 (Governance Loop) - 紫色

#### 职能
实现理论与实践的结合验证，推动系统进化。

#### 模块序列
```
A9 离场触发 → A7 (实践记录) → A8 (理论验证) → A1/A2/A3 (理论修正)
```

#### 理论闭环 (A7-A8 内部循环)

```
┌─────────────────────────────────────────────────────────────┐
│                                🟣 理论闭环                  │
│  ┌─────────────────┐                                       │
│  │  实践 (A7)        │                                       │
│  │  - 记录执行过程    │                                       │
│  │  - 提炼经验教训    │                                       │
│  └────────┬────────┘                                       │
│           │ 实践记录                                          │
│           ▼                                                  │
│  ┌─────────────────┐                                       │
│  │  理论 (A8)        │                                       │
│  │  - 知行合一检查    │                                       │
│  │  - 批判性分析      │                                       │
│  │  - 理论修正建议    │                                       │
│  └────────┬────────┘                                       │
│           │ gap_score 路由                                    │
│           ▼                                                  │
│  ┌─────────────────┐                                       │
│  │  修正 (A1/A2/A3)  │                                       │
│  │  - gap_score 高 → A1 重启调研                             │
│  │  - gap_score 中 → A2 更新分析                             │
│  │  - gap_score 低 → A3 优化策略                             │
│  └────────┬────────┘                                       │
│           │ 理论更新                                          │
│           ▼                                                  │
│  ┌─────────────────┐                                       │
│  │  下一轮实践 (A7)  │                                       │
│  └─────────────────┘                                       │
└─────────────────────────────────────────────────────────────┘
```

#### 知行合一评分

| 评分 | 含义 | 动作 |
|------|------|------|
| **0.9-1.0** | 知行合一 | 继续 |
| **0.7-0.9** | 轻微背离 | 记录观察 |
| **0.5-0.7** | 中度背离 | 理论修正 (→ A3) |
| **<0.5** | 严重背离 | 重启调研 (→ A1/A2) |

#### 通信模式
- **请求/响应**: A7→A8→A1/A2/A3
- **批处理**: A8 每日 14:00 运行
- **异步通知**: A8→A1/A2/A3 (理论修正通知)

#### 定时触发
```yaml
schedule: "0 14 * * *"  # 每日 14:00
timeout: 600
retry: 2
```

---

## A0 矛盾 Skill 集成说明

### A0 的定位

A0 矛盾分析**不是独立运行的模块**，而是一个**矛盾分析 Skill**，自动集成在 A1、A2、A3 三个阶段的内部。

仓库中提供的 `workflows/trading-decision/A0_contradiction/entrypoint.py` 独立入口仅用于测试/集成编排，不作为生产链路的独立触发器。

```
┌─────────────────────────────────────────┐
│  A1 调研阶段                            │
│  ┌─────────────────────────────────┐   │
│  │  [A0 Skill 内置] 矛盾检测        │   │
│  │  - 市场矛盾识别                  │   │
│  │  - 多空力量对比                  │   │
│  └─────────────────────────────────┘   │
│  ┌─────────────────────────────────┐   │
│  │  A1 核心逻辑：深度调研            │   │
│  │  - 市场分析                      │   │
│  │  - 历史案例                      │   │
│  │  - 宏观环境                      │   │
│  └─────────────────────────────────┘   │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│  A2 分析阶段                            │
│  ┌─────────────────────────────────┐   │
│  │  [A0 Skill 内置] 矛盾排序        │   │
│  │  - 矛盾优先级排序                │   │
│  │  - 方向确认                      │   │
│  └─────────────────────────────────┘   │
│  ┌─────────────────────────────────┐   │
│  │  A2 核心逻辑：第一性原理分析      │   │
│  │  - RSI/资金费率/恐慌指数         │   │
│  │  - 阻力最小路径                  │   │
│  └─────────────────────────────────┘   │

┌─────────────────────────────────────────┐
│  A3 策略阶段                            │
│  ┌─────────────────────────────────┐   │
│  │  [A0 Skill 内置] 矛盾验证        │   │
│  │  - 策略与矛盾一致性校验          │   │
│  │  - 策略模式调整                  │   │
│  └─────────────────────────────────┘   │
│  ┌─────────────────────────────────┐   │
│  │  A3 核心逻辑：策略模拟            │   │
│  │  - 信号评分                      │   │
│  │  - 波动率评估                    │   │
│  │  - 市场体制识别                  │   │
│  └─────────────────────────────────┘   │
```

### 治理环中的 A4 不一致驱动

当 A4 (每 4h 定时验证) 与 A3 结果**不一致**时，根据严重程度驱动到不同环节：

| 不一致程度 | 严重程度 | 驱动目标 | 动作 |
|-----------|---------|---------|------|
| **轻度** | A4 与 A3 有偏差但不影响方向 | A3 | 策略微调 |
| **中度** | A4 发现 A3 策略存在风险 | A2 | 重新分析，更新理论模型 |
| **严重** | A4 发现根本性矛盾 | A1 | 重启调研 |
| **极端** | A4 发现黑天鹅/系统性风险 | A9 | 立即离场 |

当 A4 与 A3 **一致**时：
- 更新 A3 策略状态
- 正向驱动 A5 执行

---

## 定时任务调度系统

> 原技术文档缺失此部分。本系统当前**不依赖 A0 作为独立触发器**，而是通过**定时任务 + 事件驱动**的混合模式运行。

### 定时任务一览表

| 任务 | 调度频率 | Cron 表达式 | 说明 |
|------|---------|------------|------|
| **A1 调研** | 定时触发 | 可配置 | 交易信号触发后，A1 作为执行环起点 |
| **A4 验证** | 每 4h | `0 */4 * * *` | 独立验证运行，检查结果与 A3 一致性 |
| **A5 执行** | 每 8h | `0 */8 * * *` | 独立检查运行，验证执行状态 |
| **A6 情报监控** | 每 1h | `0 * * * *` | 全天候监控市场，5 级放射驱动 |
| **A8 理论验证** | 每日 14:00 | `0 14 * * *` | 知行合一批处理检查 |

### 驱动链路总览

```
                    ┌─────────────┐
                    │  定时调度器   │
                    │ (Cron/Action)│
                    └──┬──┬──┬──┬─┘
                       │  │  │  │
                 ┌─────┘  │  │  └─────┐
                 ▼        ▼  ▼        ▼
              ┌────┐  ┌────┐┌────┐ ┌────┐
              │ A1 │  │ A4 ││ A5 │ │ A6 │
              │定时│  │ 4h ││ 8h │ │ 1h │
              └──┬─┘  └──┬─┘└──┬─┘ └──┬─┘
                 │       │    │       │
                 ▼       │    │       ▼
              ┌────┐     │    │    ┌────┐
              │ A2 │     │    │    │ L0 │ → A9 离场
              └──┬─┘     │    │    └────┘
                 │       │    │    ┌────┐
              ┌──▼─┐     │    │    │ L1 │ → A4 重验证 (与定时A4合并)
              │ A3 │◄────┘    │    └────┘
              └──┬─┘          │    ┌──────┐
                 │            │    │ L1.5 │ → A2 增量更新
              ┌──▼─┐          │    └──────┘
              │ A4 │          │    ┌────┐
              │(顺序)         │    │ L3 │ → A1+A3 重启
              └──┬─┘          │    └────┘
                 │            │
              ┌──▼─┐     ┌────┘
              │ A5 │◄────┘
              │(顺序)
              └──┬─┘
              ┌──▼─┐
              │ A9 │
              └──┬─┘
              ┌──▼─┐
              │ A7 │  (治理环)
              └──┬─┘
              ┌──▼─┐
              │ A8 │
              └──┬─┘
                 │
                 ▼
           ┌───────────┐
           │ A1/A2/A3  │  (理论修正)
           └───────────┘
```

### 驱动方式演进

#### Phase 1: 当前 — 脚本 / GitHub Actions / Cron

通过定时脚本、GitHub Actions 工作流或系统 crontab 触发各阶段：

```yaml
# GitHub Actions 示例: A6 情报监控 (每 1h)
- cron: "0 * * * *"
  steps:
    - run: python workflows/trading-decision/A6_intelligence/entrypoint.py

# A4 验证检查 (每 4h)
- cron: "0 */4 * * *"
  steps:
    - run: python workflows/trading-decision/A4_validation/entrypoint.py

# A5 执行检查 (每 8h)
- cron: "0 */8 * * *"
  steps:
    - run: python workflows/trading-decision/A5_execution/entrypoint.py
```

#### Phase 2: 大模型自主驱动

后期接入大模型 (LLM)，由模型根据市场状态自主决策触发时机和目标模块：

```
┌─────────────────────────────────────────┐
│           LLM 驱动引擎                   │
│                                         │
│  输入: 市场数据 + 历史交易 + 矛盾信号     │
│  输出: 触发决策 (哪个模块 + 何时 + 参数)  │
│                                         │
│  优势:                                   │
│  - 非固定频率，按需触发                  │
│  - 多因子综合判断，超越简单规则          │
│  - 自适应市场体制变化                    │
└─────────────────────────────────────────┘
```

---

## 通信协议规范

### 1. 消息头规范 (Message Header)

所有模块间通信必须包含标准消息头：

```json
{
  "header": {
    "message_id": "msg_{source}_{timestamp}_{seq}",  // 全局唯一 ID
    "timestamp": "2026-05-11T10:10:30+08:00",      // ISO 8601 时间戳
    "version": "2.0",                                 // 协议版本
    "source": "A1",                                   // 源模块
    "target": "A2",                                   // 目标模块
    "type": "REQUEST",                                 // 消息类型
    "priority": "HIGH",                               // 优先级
    "correlation_id": "sig_20260511_1010",            // 关联 ID
    "trace_id": "trace_20260511_1010",               // 追踪 ID (全链路)
    "loop_type": "execution",                         // 所属闭环
    "timeout_ms": 30000                                // 超时时间 (毫秒)
  },
  "payload": {
    // 消息体
  }
}
```

#### 字段说明

| 字段 | 说明 | 取值 |
|------|------|------|
| **loop_type** | 消息所属的闭环 | `execution` / `intelligence` / `governance` |
| **trace_id** | 全链路追踪 ID | 贯穿三大闭环的唯一 ID |

---

### 2. 消息类型 (Message Types)

| 类型 | 说明 | 是否需要响应 | 超时处理 | 适用闭环 |
|------|------|--------------|----------|----------|
| **REQUEST** | 请求消息 | ✅ 需要 | 触发重试/降级 | 执行环、治理环 |
| **RESPONSE** | 响应消息 | ❌ 不需要 | 忽略 | 执行环、治理环 |
| **NOTIFICATION** | 通知消息 | ❌ 不需要 | 记录日志 | 情报环 |
| **EVENT** | 事件消息 | ❌ 不需要 | 触发订阅者 | 情报环 |
| **HEARTBEAT** | 心跳消息 | ❌ 不需要 | 标记离线 | 所有闭环 |
| **ERROR** | 错误消息 | ❌ 不需要 | 触发处罚 | 所有闭环 |
| **FEEDBACK** | 反馈消息 | ❌ 不需要 | 触发理论修正 | 治理环 |

---

### 3. 传输协议 (Transport Protocol)

#### 方案 A：HTTP REST API (适用于执行环和治理环)

```yaml
协议: HTTP/1.1 或 HTTP/2
格式: JSON
认证: JWT Token
超时: 默认 30s，可配置
重试: 指数退避 (Exponential Backoff)
适用: 同步调用 (A1→A2→A3→A4→A5)
```

**端点规范**：
```bash
# 执行环
POST /a1/research
POST /a2/analysis
POST /a3/strategy
POST /a4/validation
POST /a5/execution
POST /a9/exit

# 情报环 (A6 中枢)
POST /a6/intelligence
POST /a6/alert

# 治理环
POST /a7/practice
POST /a8/verification
```

#### 方案 B：消息队列 (适用于情报环)

```yaml
消息队列: RabbitMQ / Apache Kafka / Redis Streams
格式: JSON
持久化: ✅ 开启
ACK 机制: ✅ 开启
重试: 死信队列 (DLQ)
适用: 异步通知 (A6 → A1/A2/A3/A4/A9)
```

**Topic 规范**：
```bash
# 执行环
dream.execution.a1.*                   # A1 调研
dream.execution.a2.*                   # A2 分析
dream.execution.a3.*                   # A3 策略
dream.execution.a4.*                   # A4 验证
dream.execution.a5.*                   # A5 执行
dream.execution.a9.*                   # A9 离场

# 情报环 (A6 中枢)
dream.intelligence.a6.alert            # A6 警报
dream.intelligence.a6.L0              # L0 致命 → A9
dream.intelligence.a6.L1              # L1 高 → A4
dream.intelligence.a6.L1.5            # L1.5 变 → A2
dream.intelligence.a6.L2              # L2 中 → 观察
dream.intelligence.a6.L3              # L3 背离 → A1+A3

# 治理环
dream.governance.a7.*                 # A7 实践
dream.governance.a8.*                 # A8 验证
dream.governance.a8.feedback          # A8 反馈 → A1/A2/A3
```

---

## 闭环触发机制

### 1. 执行环触发机制 — 定时任务驱动

#### 触发源

执行环由**定时任务**触发 A1 开始，然后按顺序驱动后续阶段。

| 触发类型 | 触发源 | 目标模块 | 条件 |
|----------|----------|----------|------|
| **定时触发** | Cron 调度器 | A1 | 交易信号/定时到达 |
| **依赖触发** | A1 | A2 | A1 完成 |
| **依赖触发** | A2 | A3 | A2 完成 |
| **依赖触发** | A3 | A4 | A3 完成 |
| **依赖触发** | A4 | A5 | A4 通过 (risk_gate == PASS) |
| **事件触发** | A5 | A6 | 执行结果通知情报环 |
| **事件触发** | A9 | A7 | 离场完成，触发治理环 |

#### 触发流程

```
定时任务触发
    ↓
[A1 调研] → 完成？
    ↓ 是
[A2 分析] → 完成？
    ↓ 是
[A3 策略] → 完成？
    ↓ 是
[A4 验证] → risk_gate == PASS?
    ↓ 是 (或重试后通过)
[A5 执行] → 完成？
    ↓ 是
[A9 离场] → 完成？
    ↓ 是
[A7 实践记录] → 完成？
    ↓ 是
[A8 理论验证] → gap_score 评估
    ↓
[A1/A2/A3 理论修正] → 根据 gap_score 路由
    ↓
[回到 IDLE，等待下一轮]
```

#### A4 独立验证 (每 4h)

A4 不仅在执行环中运行，还作为**独立定时任务**每 4 小时运行一次：

```
A4 定时运行 (4h)
    ↓
[获取当前 A3 策略状态]
    ↓
[独立验证]
    ↓
    ├── 与 A3 一致？ → 是 → [更新 A3 状态] → [驱动 A5]
    │
    └── 不一致？ → [评估严重程度]
                    ├── 轻度 → 驱动 A3 (策略微调)
                    ├── 中度 → 驱动 A2 (重新分析)
                    ├── 严重 → 驱动 A1 (重启调研)
                    └── 极端 → 驱动 A9 (立即离场)
```

#### A5 独立执行 (每 8h)

A5 不仅受 A4 驱动，还作为**独立定时任务**每 8 小时运行一次：

```
A5 定时运行 (8h)
    ↓
[检查当前持仓/执行状态]
    ↓
    ├── 有活跃交易？ → [更新执行状态] → [通知 A6]
    │
    └── 无活跃交易？ → [检查 A4 验证状态]
                       ├── A4 通过？ → [执行 A5] → [通知 A6]
                       └── A4 未通过？ → [跳过，等待 A4]
```

---

### 2. 情报环触发机制

#### A6 中枢 5 级放射触发

| 级别 | 触发条件 | 目标模块 | 动作 | 消息类型 |
|------|----------|----------|------|----------|
| **L0 致命** | `risk_score >= 0.9` | A9 | 立即离场 | EVENT |
| **L1 高** | `risk_score >= 0.7` | A4 | 重新验证 | REQUEST |
| **L1.5 变** | `regime_change == true` | A2 | 增量更新 | REQUEST |
| **L2 中** | `risk_score >= 0.5` | 观察 | 记录日志 | NOTIFICATION |
| **L3 背离** | `theory_practice_score < 0.7` | A1+A3 | 重启调研 | EVENT |

#### 驱动流程

```
A6 每小时运行
    ↓
[监控市场状态]
    ↓
[5级评估]
    ↓
┌─────────────────────────────────────────┐
│ L0 致命？ → 是 → 触发 A9 (离场) → A7 → A8 → A1/A2/A3 → 执行环 │
│ L1 高？   → 是 → 触发 A4 (验证) → A5 → A9 → ... → 执行环   │
│ L1.5 变？ → 是 → 触发 A2 (更新) → A3 → A4 → A5 → ... → 执行环  │
│ L2 中？   → 是 → 记录观察                           │
│ L3 背离？ → 是 → 触发 A1+A3 (重启) → A2 → A4 → A5 → ... → 执行环 │
└─────────────────────────────────────────┘
```

---

### 3. 治理环触发机制

#### 触发类型

| 触发类型 | 触发源 | 目标模块 | 条件 |
|----------|----------|----------|------|
| **事件触发** | A9 | A7 | 离场完成 |
| **时间触发** | 定时器 | A8 | 每日 14:00 |
| **事件触发** | A8 | A1/A2/A3 | 理论修正 (根据 gap_score 路由) |

#### A8 → A1/A2/A3 路由规则

| gap_score 范围 | 路由目标 | 含义 | 动作 |
|---------------|---------|------|------|
| **>= 0.9** | A1 | 知行高度合一 | 继续执行，无需修正 |
| **0.7-0.9** | A3 | 轻微背离 | 策略微调 |
| **0.5-0.7** | A2 | 中度背离 | 重新分析，更新理论模型 |
| **< 0.5** | A1 | 严重背离 | 重启调研 |

#### 触发流程

```
A9 离场完成
    ↓
[A7 实践记录]
    ↓
[记录执行过程]
    ↓
[提炼经验教训]
    ↓
[触发 A8] → A7 → A8
    ↓
[A8 理论验证]
    ↓
[知行合一检查]
    ↓
[生成 gap_score]
    ↓
[gap_score 路由]
    ├── >= 0.9 → [继续] → [下一轮执行环]
    ├── 0.7-0.9 → [触发 A3] → [策略微调] → [下一轮执行环]
    ├── 0.5-0.7 → [触发 A2] → [重新分析] → [下一轮执行环]
    └── < 0.5 → [触发 A1] → [重启调研] → [下一轮执行环]
```

---

## 消息格式定义

### 1. 执行环消息格式

#### A1 → A2: 调研报告消息

```json
{
  "header": {
    "message_id": "msg_a1_a2_20260511_1030_001",
    "timestamp": "2026-05-11T10:30:00+08:00",
    "version": "2.0",
    "source": "A1",
    "target": "A2",
    "type": "REQUEST",
    "priority": "HIGH",
    "correlation_id": "sig_20260511_1010",
    "trace_id": "trace_20260511_1010",
    "loop_type": "execution",
    "timeout_ms": 60000
  },
  "payload": {
    "research_id": "a1_research_20260511_1030",
    "signal_id": "sig_20260511_1010",
    "research_data": {
      "market_analysis": { /* ... */ },
      "historical_cases": { /* ... */ },
      "macro_environment": { /* ... */ },
      "sentiment_analysis": { /* ... */ }
    },
    "conclusions": {
      "triangular_assessment": "BULLISH",
      "signal_sufficiency": 0.85,
      "action_pressure": "HIGH"
    },
    "artifact_path": "artifacts/trading/a1_research/a1_research_20260511_1030.md"
  }
}
```

#### A2 → A3: 分析报告消息

```json
{
  "header": {
    "message_id": "msg_a2_a3_20260511_1050_001",
    "timestamp": "2026-05-11T10:50:00+08:00",
    "version": "2.0",
    "source": "A2",
    "target": "A3",
    "type": "REQUEST",
    "priority": "HIGH",
    "correlation_id": "sig_20260511_1010",
    "trace_id": "trace_20260511_1010",
    "loop_type": "execution",
    "timeout_ms": 60000
  },
  "payload": {
    "analysis_id": "a2_analysis_20260511_1050",
    "research_id": "a1_research_20260511_1030",
    "analysis_data": {
      "contradiction_analysis": { /* ... */ },
      "regime_classification": "TREND_STRONG",
      "path_of_least_resistance": "UP",
      "clarity": "CLEAR"
    },
    "artifact_path": "artifacts/trading/a2_analysis/a2_analysis_20260511_1050.md"
  }
}
```

#### A6 → A9: L0 致命警报消息 (情报环 → 执行环)

```json
{
  "header": {
    "message_id": "msg_a6_a9_20260511_1300_001",
    "timestamp": "2026-05-11T13:00:00+08:00",
    "version": "2.0",
    "source": "A6",
    "target": "A9",
    "type": "EVENT",
    "priority": "CRITICAL",
    "correlation_id": null,
    "trace_id": "trace_a6_20260511_1300",
    "loop_type": "intelligence",
    "timeout_ms": 0
  },
  "payload": {
    "alert_id": "alert_20260511_1300",
    "alert_level": "L0",
    "alert_type": "RISK_EVENT",
    "alert_data": {
      "risk_score": 0.95,
      "event_type": "BLACK_SWAN",
      "description": "黑天鹅事件，立即离场"
    },
    "action_required": true,
    "target_module": "A9",
    "action": "IMMEDIATE_EXIT"
  }
}
```

#### A7 → A8: 实践记录消息 (治理环)

```json
{
  "header": {
    "message_id": "msg_a7_a8_20260511_1400_001",
    "timestamp": "2026-05-11T14:00:00+08:00",
    "version": "2.0",
    "source": "A7",
    "target": "A8",
    "type": "REQUEST",
    "priority": "MEDIUM",
    "correlation_id": "sig_20260511_1010",
    "trace_id": "trace_20260511_1010",
    "loop_type": "governance",
    "timeout_ms": 300000
  },
  "payload": {
    "practice_id": "a7_practice_20260511_1400",
    "execution_id": "a5_execution_20260511_1200",
    "practice_data": {
      "decision": "BUY BTC/USDT @ $96,500",
      "theory_basis": "a3_strategy_20260511_1100",
      "execution_result": "SUCCESS, profit +5%",
      "lessons_learned": "入场时机可优化"
    },
    "artifact_path": "artifacts/trading/a7_practice/a7_practice_20260511_1400.md"
  }
}
```

---

## 状态机与转换

### 全局状态机 (三大闭环)

> 相比 v2.0，移除了 `SIGNAL` 状态（原 A0 独立阶段），改为定时任务直接从 `IDLE` 进入 `RESEARCH`。

```
                ┌───────────┐
                │   IDLE    │  (空闲)
                └─────┬─────┘
                      │ 定时任务触发 / A6 情报驱动
                      ▼
                ┌───────────┐
                │ RESEARCH  │  (调研中) - A1
                └─────┬─────┘
                      │ A1 完成
                      ▼
                ┌───────────┐
                │ ANALYZING │  (分析中) - A2
                └─────┬─────┘
                      │ A2 完成
                      ▼
                ┌───────────┐
                │ STRATEGIZ │  (策略制定) - A3
                └─────┬─────┘
                      │ A3 完成
                      ▼
                ┌───────────┐
                │ VALIDATING│  (验证中) - A4
                └─────┬─────┘
                      │ A4 完成
                      ▼
                ┌───────────┐
                │ EXECUTING │  (执行中) - A5
                └─────┬─────┘
                      │ A5 完成
                      ▼
                ┌───────────┐
                │   EXIT    │  (已离场) - A9
                └─────┬─────┘
                      │ A9 完成
                      ▼
                ┌───────────┐
                │ PRACTICE  │  (实践记录) - A7
                └─────┬─────┘
                      │ A7 完成
                      ▼
                ┌───────────┐
                │VERIFICATION│  (理论验证) - A8
                └─────┬─────┘
                      │ A8 完成
                      ▼
                ┌───────────┐
                │   IDLE    │  (回到空闲)
                └───────────┘
```

### 状态转换表

| 当前状态 | 下一状态 | 触发条件 |
|---------|---------|---------|
| `IDLE` | `RESEARCH` | 定时任务触发 / A6 L3 驱动 |
| `RESEARCH` | `ANALYZING` | A1 完成 |
| `ANALYZING` | `STRATEGIZING` | A2 完成 |
| `STRATEGIZING` | `VALIDATING` | A3 完成 |
| `VALIDATING` | `EXECUTING` | A4 risk_gate == PASS |
| `VALIDATING` | `STRATEGIZING` | A4 risk_gate != PASS (重试) |
| `EXECUTING` | `EXIT` | A5 完成 |
| `EXECUTING` | `VALIDATING` | A5 失败 (重试) |
| `EXIT` | `PRACTICE` | A9 完成 |
| `PRACTICE` | `VERIFICATION` | A7 完成 |
| `VERIFICATION` | `IDLE` | A8 完成，gap_score >= 0.9 |
| `VERIFICATION` | `STRATEGIZING` | A8 gap_score 0.7-0.9 (→ A3) |
| `VERIFICATION` | `ANALYZING` | A8 gap_score 0.5-0.7 (→ A2) |
| `VERIFICATION` | `RESEARCH` | A8 gap_score < 0.5 (→ A1) |

---

## 处罚与重试机制

### 1. 处罚机制 (Penalty Mechanism)

#### 处罚规则

| 违规行为 | 处罚类型 | 处罚力度 | 恢复条件 | 适用闭环 |
|----------|----------|----------|----------|----------|
| **超时未响应** | 警告 | -10 分 | 下次成功执行 | 执行环、治理环 |
| **消息格式错误** | 警告 | -5 分 | 下次格式正确 | 所有闭环 |
| **处理失败** | 扣分 | -20 分 | 下次成功执行 | 所有闭环 |
| **连续失败 3 次** | 降级 | 优先级降低 | 连续成功 5 次 | 所有闭环 |
| **恶意消息** | 封禁 | 模块禁用 | 人工审核 | 所有闭环 |
| **理论背离** | 警告 | -15 分 | 理论修正 | 治理环 |

---

## 实现示例

### 1. 执行环通信实现 (HTTP REST API)

#### A1 调研处理器 (定时任务触发)

```python
from flask import Flask, request, jsonify
from typing import Dict
import json

app = Flask(__name__)

class A1ResearchProcessor:
    def __init__(self):
        self.state = "IDLE"
        self.current_task = None

    def on_cron_trigger(self, message: Dict) -> Dict:
        """定时任务触发 A1 调研"""
        if not self.validate_message(message):
            return {"status": "ERROR", "reason": "Invalid message format"}

        self.state = "PROCESSING"
        try:
            research_result = self.conduct_research(message["payload"])
            self.state = "COMPLETED"
            self.trigger_a2(research_result)
            return {"status": "SUCCESS", "data": research_result}
        except Exception as e:
            self.state = "ERROR"
            return {"status": "ERROR", "reason": str(e)}

    def validate_message(self, message: Dict) -> bool:
        required_fields = ["header", "payload"]
        for field in required_fields:
            if field not in message:
                return False
        required_header_fields = ["message_id", "source", "target", "type", "loop_type"]
        for field in required_header_fields:
            if field not in message["header"]:
                return False
        return True

    def conduct_research(self, signal_data: Dict) -> Dict:
        # A1 调研逻辑 (内置 A0 矛盾分析 Skill)
        return {
            "research_id": "a1_research_20260511_1030",
            "signal_id": signal_data["signal_id"],
            "conclusions": {
                "triangular_assessment": "BULLISH",
                "signal_sufficiency": 0.85
            }
        }

    def trigger_a2(self, research_result: Dict):
        # 构造 A1 → A2 消息并发送
        pass

processor = A1ResearchProcessor()

@app.route('/a1/research', methods=['POST'])
def trigger_research():
    message = request.json
    result = processor.on_cron_trigger(message)
    return jsonify(result)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)
```

---

### 2. 情报环通信实现 (消息队列 - RabbitMQ)

#### A6 警报发布者 (A6 中枢)

```python
import pika
import json
from datetime import datetime
from typing import Dict

class A6AlertPublisher:
    def __init__(self, host: str = 'localhost'):
        self.connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=host)
        )
        self.channel = self.connection.channel()

        self.channel.exchange_declare(
            exchange='dream_intelligence',
            exchange_type='topic',
            durable=True
        )

    def publish_alert(self, alert_data: Dict, alert_level: str):
        routing_key = f"dream.intelligence.a6.{alert_level.lower()}"

        message = {
            "header": {
                "message_id": f"msg_a6_{datetime.now().strftime('%Y%m%d_%H%M%S')}_001",
                "timestamp": datetime.now().isoformat(),
                "version": "2.0",
                "source": "A6",
                "target": alert_data["target_module"],
                "type": "EVENT" if alert_level in ["L0", "L3"] else "REQUEST",
                "priority": "CRITICAL" if alert_level == "L0" else "HIGH",
                "loop_type": "intelligence"
            },
            "payload": alert_data
        }

        self.channel.basic_publish(
            exchange='dream_intelligence',
            routing_key=routing_key,
            body=json.dumps(message),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type='application/json'
            )
        )

        print(f"✅ 警报已发布: {routing_key}")

    def close(self):
        self.connection.close()

publisher = A6AlertPublisher()

# L0 致命 → A9
alert_data_l0 = {
    "alert_id": "alert_20260511_1300",
    "alert_level": "L0",
    "alert_type": "RISK_EVENT",
    "alert_data": {"risk_score": 0.95, "event_type": "BLACK_SWAN"},
    "action_required": True,
    "target_module": "A9",
    "action": "IMMEDIATE_EXIT"
}
publisher.publish_alert(alert_data_l0, "L0")

publisher.close()
```

---

## 总结

本文档定义了 Dream-MultiSkill A0-A9 系统的 **三大核心闭环架构 + 定时调度系统**：

### 闭环架构

1. **执行环 (Execution Loop)** - 蓝色
   - 模块序列: A1→A2→A3→A4→A5→A9
   - 通信模式: 同步调用 (HTTP REST API)
   - 触发机制: 定时任务触发 A1 → 顺序执行
   - **A0 矛盾 Skill 集成在 A1/A2/A3 内部**，不独立运行

2. **情报环 (Intelligence Loop)** - 琥珀色
   - A6 中枢每 **1 小时**自动运行
   - 5 级放射驱动: L0→A9, L1→A4, L1.5→A2, L2→观察, L3→A1+A3
   - 通信模式: 异步通知 (消息队列)
   - **可驱动整个交易链路**

3. **治理环 (Governance Loop)** - 紫色
   - 序列: A7→A8→**A1/A2/A3** (根据 gap_score 路由)
   - 通信模式: 请求/响应 (HTTP REST API)
   - 触发机制: A9 离场事件 + 每日 14:00 定时

### 定时调度

| 任务 | 频率 | Cron |
|------|------|------|
| A1 调研 | 定时触发 | 可配置 |
| A4 验证 | 每 4h | `0 */4 * * *` |
| A5 执行 | 每 8h | `0 */8 * * *` |
| A6 情报 | 每 1h | `0 * * * *` |
| A8 理论验证 | 每日 14:00 | `0 14 * * *` |

### 驱动演进

- **Phase 1 (当前)**: 脚本 / GitHub Actions / Cron 定时驱动
- **Phase 2 (规划)**: 大模型 (LLM) 自主决策驱动

---

**END OF DOCUMENT**
