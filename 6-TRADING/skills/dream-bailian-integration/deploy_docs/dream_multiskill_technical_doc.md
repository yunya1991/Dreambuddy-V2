# Dream-MultiSkill 系统技术文档

**版本**: v1.0
**日期**: 2026-05-07
**分类**: 核心治理文档
**部门**: governance

---

## 一、系统概述

### 1.1 Dream-MultiSkill 是什么

Dream-MultiSkill 是一个基于双向进化架构的 OKX Agent Trade Kit 专属指挥官系统，整合多技能按 OKX 5步模板执行决策与交易。

### 1.2 核心架构

```
Dream-MultiSkill
├── A0 矛盾论 ────── 指导层（前置检查）
├── A1 深度调研 ──── 认识层
├── A2 第一性原理 ── 认识层
├── A3 沙盘推演 ──── 认识层
├── A4 战术验证 ──── 实践层
├── A5 战术执行 ──── 实践层
├── A6 监控层 ────── 监控层
├── A7 实践论 ────── 指导层（门禁）
├── A8 内部批评 ──── 独立批评
└── A9 离场决策 ──── 离场决策
```

### 1.3 核心交易理念

> **"市场总是沿着阻力最小方向运行，趋势具有延续性"**

融合 Livermore 关键点、Sperandeo 1-2-3、孙子兵法、战争论与 A0 矛盾论框架。

---

## 二、A系列决策链

### 2.1 A0 矛盾分析理论

**定位**: A1/A2/A3的统一矛盾操作系统

**核心方法**:
- 蒸馏毛泽东《矛盾论》+《孙子兵法》+克劳塞维茨《战争论》
- 8维度矛盾分析: 趋势/震荡、主要/次要、内部/外部、渐进/突变
- 5条铁律: 抓主要矛盾、矛盾转化、两点论、重点论、实践检验

**输出**: CX编号 + 矛盾描述

### 2.2 A1 深度调研

**定位**: 战略制定前的侦察兵

**职责**:
- 市场情报收集
- 档案数据研究
- 链上信号分析
- 宏观环境评估

**数据源**: NeoData（唯一合规数据源）

### 2.3 A2 第一性原理

**定位**: 战略制定的哲学根基

**核心原理**:
1. 阻力最小方向
2. 趋势延续性
3. 关键点突破
4. 矛盾转化时机

### 2.4 A3 沙盘推演

**定位**: 多情景模拟验证

**方法**:
- 情景推演 (情景/概率/证据)
- 矛盾验证
- 方案比较

### 2.5 A4 战术验证

**定位**: 验证方案设计师 + 矛盾论验证者

**核心功能**:
- 三层索引体系
- 高级委托落地
- 验证报告输出

**严格禁止**: A4自行做BUY/SHORT/SKIP方向判断

### 2.6 A5 战术执行

**定位**: 综合判断决策执行

**核心链路**:
- A4验证报告 → A6情报 → 综合判断 → 执行

**严格禁止**: A4做方向判断，仅A5可做最终决策

### 2.7 A6 情报监控

**定位**: 永不间断的市场雷达

**功能**:
- 每小时运行
- BTC雷达
- P0/P1自主响应 (v4.6)
- ETF流向
- 资金费率

### 2.8 A7 实践论

**定位**: 理论与实践结合验证

**门禁4项检查**:
1. 认识来源充分性
2. 验证设计合理性
3. 反馈机制完整性
4. 真理标准明确性

### 2.9 A9 离场决策

**定位**: 四层离场决策链

**组件**:
- 21风险事件模式库
- 15条L0-L2离场规则
- 6位大师离场策略

---

## 三、产物中心 (Product Hub)

### 3.1 架构

```
前端 (localhost:3456)
├── 产物中心 (新闻流)
├── 公司架构 (多层展开)
└── 会议室 (SSE实时辩论)
```

### 3.2 frontmatter规范

```yaml
---
title: "产物标题"
department: trading|governance|hr|knowledge|support|cfo
chain_phase: A1|A2|A3|A4|A5|A6|A7|A8|A9
date: "YYYY-MM-DDTHH:MM:SS+08:00"
type: report|analysis|decision|skill|artifact
status: draft|review|completed|archived
tags: "tag1 tag2 tag3"
by_a_phase: A1|A2|A3|A4|A5|A6|A7|A8|A9
---
```

### 3.3 双通道投递

| 通道 | 路径 |
|:---|:---|
| 秘书邮箱 | `~/.workbuddy/skills/boss-secretary/reports/` |
| 前端产物中心 | `~/.workbuddy/artifacts/` |

---

## 四、百炼集成

### 4.1 API配置

```
API Key: sk-c233489e73e94b9591e4776d89ec8cb8
Base URL: https://dashscope.aliyuncs.com/compatible-mode/v1
```

### 4.2 推荐模型

| 模型 | 用途 | 成本 |
|:---|:---|:---|
| qwen-plus | 通用对话 | 中 |
| qwen3.6-35b-a3b | 高性能蒸馏 | 低 |
| qwen-max | 复杂推理 | 高 |

### 4.3 集成架构

```
Dream-MultiSkill
├── A1 深度调研 → 百炼RAG → 知识库检索
├── A2 第一性原理 → 百炼LLM → 推理分析
├── A3 矛盾推演 → 百炼LLM → 情景模拟
├── A4 战术验证 → 百炼Function Calling → 工具调用
├── A5 战术执行 → 百炼API → 信号生成
└── A9 离场决策 → 百炼LLM → 决策支持
```

---

## 五、监控标的与数据源

### 5.1 监控标的

| 标的 | 类型 |
|:---|:---|
| BTC | 加密货币 |
| ETH | 加密货币 |
| SOL | 加密货币 |
| XAU | 黄金 |
| CL | 原油 |
| XCU | 铜 |
| TSLA | 股票 |

### 5.2 数据源

| 数据 | 来源 |
|:---|:---|
| 行情 | OKX |
| 链上数据 | OKX |
| ETF流向 | NeoData |
| 资金费率 | OKX |

### 5.3 交易对

- 合约: BTC-USDT-SWAP
- 现货: BTC-USDT

---

## 六、调度机制

### 6.1 定时任务

| 任务 | 频率 | 说明 |
|:---|:---|:---|
| A0-A8链 | 每日14:00 | 全链路调度 |
| A4 v7.1 | 每4小时 | Phase1执行 + Phase2监控 |
| A6雷达 | 每小时 | BTC监控 |

### 6.2 触发条件

**A5触发条件**:
- A4置信度≥70 + SI≥±30 + Edge同向≥20
- 或 A6 P0/P1事件
- 或 手动触发

---

## 七、合规与治理

### 7.1 宪法原则

1. **第一性原理**: "市场沿阻力最小方向运行"
2. **双脑协同**: 左脑规则 + 右脑启发
3. **证据驱动**: 每条规则必须有evidence_refs
4. **双保险策略**: 确保闭环可靠性

### 7.2 合规审查

所有P0/P1变更必须:
1. 通过 ai-trading-compliance SKILL 审查
2. 人工确认
3. 影子验证
4. 携带 rollback_plan_id

### 7.3 禁止事项

- ❌ A4禁止做方向判断
- ❌ 实盘/模拟盘混淆
- ❌ 绕过合规审查
- ❌ 无rollback_plan_id的发布

---

## 八、SKILL生态

### 8.1 核心SKILL

| SKILL | 定位 |
|:---|:---|
| dream-contradiction-theory | A0矛盾论 |
| dream-strategy-research | A1深度调研 |
| dream-first-principles | A2第一性原理 |
| dream-tactical-validator | A4战术验证 |
| dream-tactical-executor | A5战术执行 |
| dream-intelligence-monitor | A6情报监控 |
| A7-practice-theory | A7实践论 |
| A8-theory-practice-verification | A8内部批评 |
| dream-exit-skill-v2 | A9离场决策 |
| artifact-alignment-manager | 产物传递 |

### 8.2 SKILL路径

- 用户级: `~/.workbuddy/skills/`
- 项目级: `{workspace}/.workbuddy/skills/`

---

## 九、联系方式

- **系统管理员**: zhangjiangtao
- **SKILL管理**: dream-hr-recruitment
- **合规审查**: ai-trading-compliance

---

*本文档是Dream-MultiSkill系统的核心参考文档，通过百炼平台进行检索增强。*
