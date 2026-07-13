# 技术设计文档 — 易经推理系统

> **版本**: v1.0 | **更新日期**: 2026-07-12
> **定位**: 模块级技术设计文档，描述架构、数据流、算法细节

---

## 目录

- [1. 系统架构](#1-系统架构)
- [2. 决策链设计](#2-决策链设计)
- [3. 记忆系统](#3-记忆系统)
- [4. 数据流](#4-数据流)
- [5. 接口设计](#5-接口设计)
- [6. 配置管理](#6-配置管理)
- [7. 测试体系](#7-测试体系)
- [8. 扩展计划](#8-扩展计划)

---

## 1. 系统架构

### 1.1 模块定位

**模块名称**: 11-易经推理系统
**英文代号**: yijing-reasoning
**核心职责**: 基于矛盾分析法和第一性原理的 AI 驱动交易决策系统
**设计模式**: 状态机模式 + 策略模式 + 观察者模式

### 1.2 四层架构

```
┌─────────────────────────────────────────────────────────────┐
│                    用户交互层                                │
│  飞书消息 / CLI / 前端接口                                   │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────┴──────────────────────────────┐
│                    编排层 (orchestrator/)                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │state_machine │  │execution_loop│  │governance_   │       │
│  │   状态机     │  │   执行循环   │  │loop         │       │
│  │              │  │              │  │  治理循环    │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│         │                 │                 │                │
│         └────────┬────────┴────────┬────────┘                │
│                  │                 │                         │
│         ┌────────▼────────┐  ┌─────▼─────┐                  │
│         │memory_retriever │  │   replay  │                  │
│         │   记忆检索      │  │   回放    │                  │
│         └─────────────────┘  └───────────┘                  │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────┴──────────────────────────────┐
│                    决策层 (A0-A9)                            │
│  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ │
│  │ A0  │ │ A1  │ │ A2  │ │ A3  │ │ A4  │ │ A5  │ │ A6  │ │
│  │矛盾 │ │调研 │ │第一 │ │推演 │ │验证 │ │执行 │ │监控 │ │
│  │分析 │ │     │ │原理 │ │     │ │     │ │     │ │     │ │
│  └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ │
│  ┌─────┐ ┌─────┐                                            │
│  │ A7  │ │ A8  │                                            │
│  │门禁 │ │验证 │                                            │
│  └─────┘ └─────┘                                            │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────┴──────────────────────────────┐
│                    支撑层 (skills/)                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ 0-CORE      │  │ 1-TRADE      │  │ 2-INTELLIGENCE│       │
│  │ 核心技能    │  │ 交易技能    │  │ 智能技能     │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│  ┌──────────────┐  ┌──────────────┐                         │
│  │ 3-SUPPORT   │  │ 4-GENERIC    │                         │
│  │ 支持技能    │  │ 通用技能    │                         │
│  └──────────────┘  └──────────────┘                         │
└──────────────────────────────────────────────────────────────┘
```

### 1.3 目录结构

```
11-易经推理系统/
├── workflows/
│   ├── trading-decision/
│   │   ├── orchestrator/
│   │   │   ├── state_machine.py      # 状态机
│   │   │   ├── execution_loop.py     # 执行循环
│   │   │   ├── system_loop.py        # 系统循环
│   │   │   ├── governance_loop.py    # 治理循环
│   │   │   ├── memory_retriever.py   # 记忆检索
│   │   │   └── replay.py             # 回放功能
│   │   ├── A0_contradiction/         # 矛盾分析
│   │   ├── A1_research/              # 深度调研
│   │   ├── A2_first-principles/      # 第一性原理
│   │   ├── A3_simulation/            # 沙盘推演
│   │   ├── A4_validation/            # 战术验证
│   │   ├── A5_execution/             # 决策执行
│   │   ├── A6_intelligence/          # 情报监控
│   │   ├── A7_audit/                 # 审计门禁
│   │   ├── A8_theory-practice/       # 理论实践验证
│   │   └── A9_exit/                  # 离场决策
│   └── memory/
│       ├── L1_realtime/              # 实时记忆层
│       ├── L2_shortterm/             # 短期记忆层
│       ├── L3_longterm/              # 长期记忆层
│       ├── L4_archive/               # 归档记忆层
│       └── memory_engine/
│           ├── engine.py             # 记忆引擎
│           ├── optimizer.py          # 优化器
│           ├── consistency.py        # 一致性检查
│           ├── health.py             # 健康检查
│           └── retrievers/           # 检索器
├── skills/
│   ├── 0-CORE/                       # 核心技能
│   ├── 1-TRADE/                      # 交易技能
│   ├── 2-INTELLIGENCE/               # 智能技能
│   ├── 3-SUPPORT/                    # 支持技能
│   └── 4-GENERIC/                    # 通用技能
├── tests/
│   ├── e2e_l4_test.py                # L4端到端测试
│   ├── stress_test_l4.py             # L4压力测试
│   └── ...
├── docs/
│   ├── TECHNICAL_DESIGN.md           # 技术设计文档（本文件）
│   ├── ENGINEERING_INDEX.md          # 工程索引
│   └── architecture.md               # 架构概述
├── artifacts/                        # 产物存储
├── constraints/                      # 约束条件
├── data/                             # 数据文件
├── README.md
└── data_server_fixed.py
```

---

## 2. 决策链设计

### 2.1 A0-A9 决策流程

```
用户输入
  │
  ↓
A0 矛盾分析 ──→ 识别交易中的核心矛盾
  │
  ↓
A1 深度调研 ──→ 收集市场信息、历史数据、专家观点
  │
  ↓
A2 第一性原理 ──→ 基于基本面和核心逻辑重新推演
  │
  ↓
A3 沙盘推演 ──→ 多情景模拟，评估各种可能结果
  │
  ↓
A4 战术验证 ──→ 回测验证、风险评估、参数优化
  │
  ↓
A5 决策执行 ──→ 下单、监控、调整
  │
  ↓
A6 情报监控 ──→ 实时监控市场变化、新闻事件
  │
  ↓
A7 审计门禁 ──→ 合规检查、风险评估、人工审批
  │
  ↓
A8 理论实践验证 ──→ 复盘、总结、优化
  │
  ↓
A9 离场决策 ──→ 止盈、止损、减仓、持有
```

### 2.2 状态机设计

```python
class TradingDecisionStateMachine:
    STATES = [
        "WAITING",           # 等待输入
        "ANALYZING",         # 分析中
        "RESEARCHING",       # 调研中
        "SIMULATING",        # 推演中
        "VALIDATING",        # 验证中
        "EXECUTING",         # 执行中
        "MONITORING",        # 监控中
        "AUDITING",          # 审计中
        "EXITING",           # 离场中
        "COMPLETED"          # 完成
    ]
    
    TRANSITIONS = {
        "WAITING": ["ANALYZING"],
        "ANALYZING": ["RESEARCHING", "COMPLETED"],
        "RESEARCHING": ["ANALYZING", "SIMULATING"],
        "SIMULATING": ["RESEARCHING", "VALIDATING"],
        "VALIDATING": ["SIMULATING", "EXECUTING", "COMPLETED"],
        "EXECUTING": ["MONITORING"],
        "MONITORING": ["EXECUTING", "AUDITING", "EXITING"],
        "AUDITING": ["MONITORING", "EXITING", "COMPLETED"],
        "EXITING": ["COMPLETED"],
        "COMPLETED": ["WAITING"]
    }
    
    def transition(self, from_state, action):
        """状态转换"""
    
    def get_next_state(self, current_state):
        """获取下一个可能状态"""
```

---

## 3. 记忆系统

### 3.1 四层记忆架构

```
┌─────────────────────────────────────────────────────────────┐
│                    L1 实时记忆层                             │
│  最近1小时的交易信号、市场数据、事件                          │
│  存储: 内存 + Redis                                         │
│  TTL: 1小时                                                 │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────┴──────────────────────────────┐
│                    L2 短期记忆层                             │
│  最近7天的交易记录、决策过程、市场分析                        │
│  存储: SQLite                                               │
│  TTL: 7天                                                   │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────┴──────────────────────────────┐
│                    L3 长期记忆层                             │
│  历史交易记录、策略优化、市场模式识别                        │
│  存储: PostgreSQL                                           │
│  TTL: 永久                                                  │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────┴──────────────────────────────┐
│                    L4 归档记忆层                             │
│  长期归档、冷数据、历史复盘                                  │
│  存储: 文件系统 / 云存储                                     │
│  TTL: 永久                                                  │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 记忆引擎

```python
class MemoryEngine:
    def __init__(self, config=None):
        """初始化记忆引擎"""
    
    def store(self, layer, key, data, metadata=None):
        """存储记忆"""
    
    def retrieve(self, layer, key, query=None):
        """检索记忆"""
    
    def update(self, layer, key, data):
        """更新记忆"""
    
    def delete(self, layer, key):
        """删除记忆"""
    
    def optimize(self):
        """优化记忆存储"""
    
    def check_consistency(self):
        """检查一致性"""
    
    def health_check(self):
        """健康检查"""
```

---

## 4. 数据流

### 4.1 决策数据流

```
┌─────────────────────────────────────────────────────────────┐
│                    决策数据流                                │
├─────────────────────────────────────────────────────────────┤
│                                                            │
│  用户输入                                                   │
│    │                                                       │
│    ↓                                                       │
│  A0矛盾分析 ──→ 识别矛盾点                                   │
│    │                                                       │
│    ↓                                                       │
│  A1深度调研 ──→ 收集信息                                     │
│    │                                                       │
│    ↓                                                       │
│  记忆检索 ──→ 查询历史经验                                    │
│    │                                                       │
│    ↓                                                       │
│  A2第一性原理 ──→ 逻辑推演                                   │
│    │                                                       │
│    ↓                                                       │
│  A3沙盘推演 ──→ 多情景模拟                                   │
│    │                                                       │
│    ↓                                                       │
│  A4战术验证 ──→ 回测验证                                     │
│    │                                                       │
│    ↓                                                       │
│  A5决策执行 ──→ 下单交易                                     │
│    │                                                       │
│    ↓                                                       │
│  A6情报监控 ──→ 实时监控                                     │
│    │                                                       │
│    ↓                                                       │
│  A7审计门禁 ──→ 合规检查                                     │
│    │                                                       │
│    ↓                                                       │
│  A8理论实践验证 ──→ 复盘优化                                  │
│    │                                                       │
│    ↓                                                       │
│  A9离场决策 ──→ 离场执行                                     │
│    │                                                       │
│    ↓                                                       │
│  记忆存储 ──→ 保存经验到L1/L2/L3/L4                            │
│                                                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. 接口设计

### 5.1 核心类

#### TradingDecisionOrchestrator

```python
class TradingDecisionOrchestrator:
    def __init__(self, config=None):
        """初始化编排器"""
    
    def start_decision(self, user_input):
        """开始决策流程"""
    
    def run_cycle(self):
        """运行一个决策周期"""
    
    def get_status(self):
        """获取当前状态"""
    
    def stop_decision(self):
        """停止决策流程"""
    
    def replay_decision(self, session_id):
        """回放历史决策"""
```

### 5.2 技能接口

#### A系列技能接口

```python
class DecisionStep:
    def execute(self, context):
        """
        执行决策步骤
        
        参数:
            context: 决策上下文
        
        返回:
            dict: {status, result, next_step, confidence}
        """
    
    def validate(self, context):
        """验证步骤输入"""
    
    def get_requirements(self):
        """获取步骤依赖"""
```

---

## 6. 配置管理

### 6.1 配置结构

```python
{
    "decision": {
        "max_cycles": 10,
        "timeout_seconds": 3600,
        "confidence_threshold": 0.7
    },
    "memory": {
        "layers": ["L1", "L2", "L3", "L4"],
        "l1_ttl_hours": 1,
        "l2_ttl_days": 7,
        "optimize_interval_hours": 24
    },
    "skills": {
        "timeout_seconds": 600,
        "retry_count": 3
    },
    "logging": {
        "level": "INFO",
        "file_path": "~/.workbuddy/logs/yijing.log"
    }
}
```

---

## 7. 测试体系

### 7.1 测试文件

| 文件 | 测试类 | 测试用例 | 覆盖范围 |
|------|--------|----------|----------|
| tests/e2e_l4_test.py | - | ~5 | L4端到端测试 |
| tests/stress_test_l4.py | - | ~5 | L4压力测试 |
| tests/test_workflows_memory_engine_vector_docs.py | - | ~5 | 记忆引擎测试 |
| tests/test_qmm_stress_scenarios.py | - | ~5 | QMM压力测试 |

### 7.2 测试命令

```bash
cd 11-易经推理系统 && python -m pytest tests/ -v
```

---

## 8. 扩展计划

### Phase 1: 核心框架 ✅
- [x] A0-A9决策链
- [x] 状态机管理
- [x] 四层记忆架构
- [x] 基础测试

### Phase 2: 深化与扩展
- [ ] 接入通用风控模块
- [ ] RAISE_TP离场动作支持
- [ ] LLM推理优化
- [ ] 增强测试覆盖

### Phase 3: 系统对接
- [ ] V15马丁策略对接
- [ ] 三屏趋势系统对接
- [ ] 经典指标系统对接