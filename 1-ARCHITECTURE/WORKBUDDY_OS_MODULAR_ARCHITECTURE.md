# WorkBuddy OS 模块化架构技术文档

> **版本**: v1.1
> **日期**: 2026-07-01
> **状态**: 已实现验证
> **核心理念**: 意图驱动 + 图编排 + 高度模块化 + 双语言协同
> **定位**: 本文档是 WorkBuddy OS 的底层架构规范，定义操作系统级别的模块化接口、注册表和调用协议

---

## 一、架构总览

### 1.1 设计哲学

**WorkBuddy OS = 意图驱动的操作系统**

就像 Linux 内核管理进程、内存、文件系统一样，WorkBuddy OS 管理：
- **意图进程**：用户意图 → 思维链构建 → 节点执行 → 结果产出
- **能力模块**：SKILL + 外部系统 + 本地工具，统一接口、统一调度
- **记忆资源**：产物中台 + 知识库 + 历史经验，全局共享
- **治理约束**：宪法 + 合规 + 风控，全局生效

### 1.2 四层架构模型

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Layer 1: 意图识别层 (Intent Layer)                 │
│                                                                     │
│  职责: 理解用户意图，决定"做什么"                                      │
│  核心: IntentRouter                                                 │
│  输出: IntentResult (意图类型 + 处理策略 + 推荐链路 + 上下文)         │
│                                                                     │
│  原 S 链定位升级: 从"思维骨架" → "意图理解 + 路由调度"                │
└───────────────────────────────────┬─────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   Layer 2: 图编排层 (Graph Orchestrator)              │
│                                                                     │
│  职责: 根据意图动态构建思维链，决定"怎么做"                             │
│  核心: GraphOrchestrator + NodeRegistry                             │
│  机制: 大模型驱动 + 置信度评估 + 动态扩展("一生二，二而三")           │
│  输出: ChainResult (最终决策 + 完整思考轨迹 + 节点调用链)             │
│                                                                     │
│  图架构核心: 不是固定流水线，是动态构建的思维图                        │
└───────────────────────────────────┬─────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   Layer 3: 模块接口层 (Module API Layer)              │
│                                                                     │
│  职责: 统一所有能力的调用接口，操作系统的"系统调用"层                 │
│  核心: ModuleRegistry + Adapter Framework                           │
│  协议: 统一输入输出契约 + 置信度评分 + 降级容错 + 成本核算             │
│  输出: ModuleResult (结构化输出 + 置信度 + 元数据)                    │
│                                                                     │
│  操作系统核心: 像系统调用一样，所有能力通过统一API调用                 │
└───────────────────────────────────┬─────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   Layer 4: 能力层 (Capability Layer)                 │
│                                                                     │
│  职责: 提供具体专业能力，操作系统的"硬件驱动"层                       │
│  分类: A_domain / C_domain / F_domain / G_domain / T_domain        │
│  粒度: 粗(领域) → 中(子系统) → 细(模块) 三层可组合                    │
│  数量: 5 大领域 / 20+ 子系统 / 50+ 独立模块                          │
│                                                                     │
│  高度模块化: 每个能力独立、可替换、可升级，不影响上层编排               │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.3 关键概念重定义

| 概念 | 原定义 | 新定义 (WorkBuddy OS) |
|------|--------|---------------------|
| **S链** | 思维链骨架 (S1-S5) | **意图识别层** - S链 + 意图识别引擎，解决用户目标 → 图架构B层 |
| **A链** | S链的具体实现 | **执行闭环** - 三大闭环（执行闭环 + 监控闭环 + 治理进化闭环）+ 三屏交易 |
| **C链** | 独立的量化思维链 | **经典量化** - 经典指标系统（技术指标/策略/回测） |
| **F链** | 独立的基本面思维链 | **基本面** - 资金流/情绪/新闻/链上/宏观 |
| **思维链** | 固定的S/C/F链路 | **动态构建的思维图** - 根据意图从模块库中编排组合 |

### 1.4 架构实现进展

截至 v1.1 版本，核心架构组件已全部实现并通过验证：

| 组件 | 状态 | 实现详情 |
|------|------|---------|
| **节点注册表 NodeRegistry** | ✅ 已实现 | 35个模块配置 + 11个本地实现，支持元数据查询、依赖管理、动态注册 |
| **模块注册表 ModuleRegistry** | ✅ 已实现 | Python侧完整加载，支持YAML配置解析、内存缓存、热更新 |
| **统一节点执行器 UnifiedNodeExecutor** | ✅ 已实现 | 整合注册表 + 适配器框架 + 重试机制 + 降级策略，统一入口 |
| **错误码体系 ErrorCode** | ✅ 已实现 | 6大类错误码，覆盖系统级/模块节点/适配器/执行/数据/编排全场景 |
| **适配器框架** | ✅ 已实现 | Skill / API / Local / Node 四种适配器，支持扩展新适配器类型 |
| **压力测试框架** | ✅ 已实现 | 6种压测场景全部通过，验证高并发下的稳定性和性能表现 |

---

## 二、粗-中-细三层模块化体系

### 2.1 设计原则

- **细粒度为基础**：每个SKILL/功能都是独立模块，最大灵活性
- **中粒度为组合**：按子系统分组，便于整体调用和管理
- **粗粒度为分类**：按领域划分，便于理解和导航
- **高可组合性**：可以跨层级、跨领域任意组合
- **统一接口契约**：所有粒度层级都遵循相同的调用协议

### 2.2 三层结构总览

```
粗粒度 Layer 1: Domain (5 大领域)
│
├── A_domain (AI交易能力)
│   └── 中粒度 Layer 2: Category (4 个子系统)
│       ├── 三屏交易系统
│       │   └── 细粒度 Layer 3: Module (3 个模块)
│       │       ├── Screen1_周线方向
│       │       ├── Screen2_日线预设
│       │       └── Screen3_实时执行
│       ├── 执行闭环
│       │   ├── A0_矛盾论
│       │   ├── A1_调研
│       │   ├── A2_第一性原理
│       │   ├── A3_策略设计
│       │   ├── A4_实践验证
│       │   ├── A5_战术执行
│       │   ├── A7_实践门禁
│       │   └── A9_离场决策
│       ├── 情报闭环
│       │   ├── A6_情报监控
│       │   ├── 大师辩论
│       │   └── 做梦部
│       └── 复盘进化
│           ├── A8_知行合一
│           ├── 数据分析
│           └── 知识库
│
├── C_domain (经典量化能力)
│   ├── 指标库
│   ├── 策略库
│   ├── 回测引擎
│   └── 执行引擎
│
├── F_domain (基本面能力)
│   ├── 新闻聚合
│   ├── 资金流分析
│   ├── 情绪分析
│   ├── 链上指标
│   └── 宏观数据
│
├── G_domain (治理能力)
│   ├── 宪法校验
│   ├── 合规审查
│   ├── 成本控制
│   └── 性能评估
│
└── T_domain (工具能力)
    ├── Tavily搜索
    ├── 产物中台
    ├── 记忆系统
    └── 系统维护
```

### 2.3 各层级调用方式

| 层级 | 调用示例 | 适用场景 |
|------|---------|---------|
| **细粒度 (Module)** | `call_module("A2_第一性原理", input)` | 需要精确控制调用哪个具体能力 |
| **中粒度 (Category)** | `call_category("执行闭环", input)` | 需要整个子系统协同工作 |
| **跨粒度组合** | `[C1技术扫描, A0矛盾论, F2资金流] → 综合` | 需要跨领域、跨子系统组合 |
| **动态编排** | `GraphOrchestrator` 自动选择 | 大模型驱动，根据置信度动态调整 |

---

## 三、模块接口契约 (Module API)

### 3.1 统一调用协议

所有模块（不论粒度、不论语言）都遵循完全相同的调用协议：

```python
def execute_module(
    module_id: str,
    inputs: Dict[str, Any],
    context: ExecutionContext
) -> ModuleResult:
    """
    统一模块调用接口
    
    Args:
        module_id: 模块唯一标识 (如 "A0_矛盾论", "C1_技术扫描")
        inputs: 结构化输入参数
        context: 执行上下文（会话、市场状态、记忆等）
    
    Returns:
        ModuleResult: 结构化结果
    """
```

### 3.2 ModuleResult 结构

```typescript
interface ModuleResult {
    // 基本信息
    success: boolean;
    module_id: string;
    module_version: string;
    
    // 核心输出
    direction?: 'LONG' | 'SHORT' | 'HOLD' | 'NEUTRAL';
    confidence: number;           // 0-1，本次执行的置信度
    outputs: Record<string, any>; // 结构化输出数据
    
    // 置信度分项（可选但推荐）
    confidence_dimensions?: {
        data_completeness: number;    // 数据完整性
        logical_consistency: number;  // 逻辑一致性
        cross_validation?: number;    // 交叉验证度
        historical_performance?: number; // 历史表现加权
    };
    
    // 推理过程
    reasoning: string[];           // 推理步骤说明
    warnings?: string[];           // 警告信息
    suggestions?: string[];        // 下一步建议
    
    // 成本与性能
    tokens_used?: number;
    latency_ms: number;
    execution_mode: 'skill' | 'api' | 'local_fallback' | 'hybrid';
    
    // 错误处理
    error?: string;
    error_code?: string;
    fallback_used?: boolean;
    fallback_reason?: string;
}
```

### 3.3 ExecutionContext 结构

```typescript
interface ExecutionContext {
    // 会话信息
    session_id: string;
    user_id?: string;
    
    // 市场状态
    market_state: {
        symbol: string;
        price: number;
        regime?: string;
        // ... 其他市场数据
    };
    
    // 记忆系统
    memory: {
        lessons: any[];
        recent_decisions: any[];
        // ...
    };
    
    // 治理约束
    governance: {
        constitution_version: string;
        compliance_level: 'R0' | 'R1' | 'R2' | 'R3';
    };
    
    // 配置
    config: {
        llm_preference: string[];
        max_tokens: number;
        enable_skill_execution: boolean;
        // ...
    };
    
    // 产物引用
    context_artifacts?: string[];  // 可复用的产物ID
    
    // 追踪
    trace_id?: string;
    parent_module?: string;        // 父模块ID（用于嵌套调用）
}
```

### 3.4 统一节点执行器

统一节点执行器 `UnifiedNodeExecutor` 是模块调用的唯一入口，整合了注册表查询、适配器路由、重试机制和降级策略：

```python
class UnifiedNodeExecutor:
    """统一节点执行器 - 所有模块调用的唯一入口"""
    
    def execute_node(
        self,
        node_id: str,
        inputs: Dict[str, Any],
        context: ExecutionContext,
        options: Optional[ExecuteOptions] = None
    ) -> ModuleResult:
        """
        执行节点的统一入口
        
        执行流程:
        1. 从 NodeRegistry 查询节点元数据
        2. 根据适配器类型路由到对应适配器
        3. 执行重试策略（可重试错误自动重试）
        4. 执行失败时触发降级策略
        5. 返回统一格式的 ModuleResult
        """
```

### 3.5 节点元数据

每个节点在注册表中都包含完整的元数据定义，用于执行器决策和验证：

| 元数据项 | 说明 | 示例 |
|---------|------|------|
| **输入Schema** | 输入参数的类型、必填性、描述 | `symbol: string, required` |
| **输出Schema** | 输出参数的类型、描述 | `direction: string, confidence: number` |
| **超时配置** | 单次执行的超时时间(ms) | `timeout_ms: 120000` |
| **重试策略** | 最大重试次数、重试间隔、可重试错误码 | `max_retries: 3, retry_delay_ms: 1000` |
| **降级策略** | 是否启用降级、降级目标模块、降级条件 | `fallback_enabled: true, fallback_module: A2_第一性原理` |

### 3.6 错误码体系

已实现 6 大类错误码，覆盖全场景错误处理：

| 错误类别 | 前缀 | 说明 | 示例 |
|---------|------|------|------|
| **系统级错误** | `SYS_` | 系统级故障，如服务不可用、资源耗尽 | `SYS_001: 系统内部错误` |
| **模块节点错误** | `NODE_` | 节点本身的错误，如节点不存在、版本不兼容 | `NODE_001: 节点未找到` |
| **适配器错误** | `ADAPTER_` | 适配器层错误，如适配器初始化失败、连接失败 | `ADAPTER_001: 适配器类型不支持` |
| **执行错误** | `EXEC_` | 执行过程中的错误，如超时、执行失败 | `EXEC_001: 执行超时` |
| **数据错误** | `DATA_` | 数据相关错误，如输入校验失败、输出格式错误 | `DATA_001: 输入参数校验失败` |
| **编排错误** | `ORCH_` | 图编排层错误，如循环依赖、节点冲突 | `ORCH_001: 检测到循环依赖` |

**可重试错误**：标记为 `retryable` 的错误会由执行器自动重试，如网络超时、临时服务不可用等。
**不可重试错误**：需要人工介入或配置调整的错误，如参数校验失败、节点不存在等。

### 3.7 重试与降级机制

#### 重试机制
- 可重试错误自动重试，默认最大重试 3 次
- 支持指数退避策略，重试间隔逐级递增
- 重试次数耗尽后触发降级流程
- 重试过程完整记录到 trace 中，便于排查

#### 降级策略
- **同类型替换**：优先使用同类别其他模块作为 fallback
- **跨链补充**：同领域模块不可用时，跨领域补充
- **本地规则降级**：所有外部依赖不可用时，使用本地硬编码规则
- 降级触发时在 ModuleResult 中标记 `fallback_used` 和 `fallback_reason`

---

## 四、模块化注册表 (Module Registry)

### 4.1 注册表定位

Module Registry 是 WorkBuddy OS 的"设备管理器"，是**唯一真相源**：
- 所有可用能力的完整清单
- 每个能力的元数据、接口契约、配置参数
- 双语言同步（TS侧和Python侧都从同一注册表加载）
- 支持热更新（修改注册表文件 → 双端自动reload）

### 4.2 注册表文件结构

```yaml
# module_registry.yaml
# WorkBuddy OS 模块化注册表
# 本文件是唯一真相源，TS侧和Python侧都从此文件加载

version: "1.0"
updated_at: "2026-06-30"
total_modules: 52

# ─── 粗粒度 Layer 1: Domain ───────────────────────────────────
domains:
  A_domain:
    name: "AI交易能力"
    description: "基于AI的交易分析与执行能力集"
    color: "#8b5cf6"
    
    # ─── 中粒度 Layer 2: Category ─────────────────────────
    categories:
      三屏交易系统:
        name: "三屏交易系统"
        description: "Elder三屏交易体系：周线方向 + 日线预设 + 实时执行"
        
        # ─── 细粒度 Layer 3: Module ──────────────────────
        modules:
          Screen1_周线方向:
            id: "dream-screen1-first"
            name: "第一屏：周线方向"
            description: "周线级别方向判断，七维牛熊评分 + 大师辩论"
            version: "v1.0"
            chain: "A"
            category: "三屏交易"
            tags: ["screen1", "weekly", "direction"]
            
            # 成本与性能
            estimated_tokens: 8000
            estimated_latency_ms: 120000
            confidence_range: [0.65, 0.85]
            
            # 适用场景
            applicable_stages: ["research"]
            market_conditions: ["all"]
            applicable_intents: ["full_analysis", "strategy_custom"]
            
            # 接口契约
            input_schema:
              - name: "symbol"
                type: "string"
                required: true
                description: "交易品种"
              - name: "market_data"
                type: "object"
                required: true
                description: "市场数据"
            output_schema:
              - name: "direction"
                type: "string"
                description: "周线方向"
              - name: "confidence"
                type: "number"
                description: "置信度"
            
            # 适配器配置
            adapter:
              type: "skill"
              skill_name: "dream-screen1-first"
              skill_path: "6-TRADING/skills/dream-screen1-first/SKILL.md"
              execution_engine: "python"
            
            # 历史表现（动态更新）
            historical_accuracy: 0.78
            total_calls: 356
            last_called: "2026-06-29T20:00:00Z"
            
            # 降级配置
            fallback:
              enabled: true
              fallback_module: "A2_第一性原理"
              fallback_reason: "Screen1不可用时降级到A2独立分析"
            
            # 依赖关系
            dependencies:
              - "A0_矛盾论"
              - "A1_调研"
              - "A2_第一性原理"
              - "A3_策略设计"
              - "大师辩论"
          
          Screen2_日线预设:
            id: "dream-screen2-second"
            # ... 同上结构
          
          Screen3_实时执行:
            id: "dream-screen3-third"
            # ... 同上结构
      
      执行闭环:
        name: "执行闭环"
        description: "A0-A9 完整执行链路：矛盾→调研→分析→策略→验证→执行→门禁→离场"
        modules:
          A0_矛盾论:
            id: "dream-contradiction-theory"
            name: "A0 矛盾论分析"
            description: "多维度矛盾分析，确定市场主要矛盾和主导力量"
            version: "v1.0"
            chain: "A"
            category: "执行闭环"
            tags: ["contradiction", "analysis", "multi-dimension"]
            estimated_tokens: 2000
            estimated_latency_ms: 15000
            confidence_range: [0.6, 0.85]
            applicable_stages: ["analysis"]
            market_conditions: ["all"]
            
            adapter:
              type: "skill"
              skill_name: "dream-contradiction-theory"
              skill_path: "6-TRADING/skills/dream-contradiction-theory/SKILL.md"
              execution_engine: "python"
            
            fallback:
              enabled: true
              fallback_type: "local_rules"
            
            historical_accuracy: 0.72
            total_calls: 1247
          
          A1_调研:
            id: "dream-strategy-research"
            # ...
          
          A2_第一性原理:
            id: "dream-first-principles"
            # ...
          
          # ... 更多A系列模块
      
      情报闭环:
        # ...
      
      复盘进化:
        # ...
  
  C_domain:
    name: "经典量化能力"
    description: "经典技术指标和量化策略能力集"
    color: "#3b82f6"
    
    categories:
      指标库:
        modules:
          C1_技术扫描:
            id: "classic-indicators-scan"
            name: "C1 技术指标扫描"
            description: "多周期技术指标全面扫描，RSI/MACD/EMA/ATR等"
            version: "v2.0"
            chain: "C"
            category: "指标库"
            tags: ["technical", "indicators", "rsi", "macd"]
            estimated_tokens: 0
            estimated_latency_ms: 500
            confidence_range: [0.5, 0.75]
            
            adapter:
              type: "api"
              api_name: "classic_indicators"
              base_url: "http://localhost:8092"
              endpoint: "/api/scan"
              execution_engine: "python"
            
            fallback:
              enabled: true
              fallback_type: "local_calculation"
            
            historical_accuracy: 0.65
            total_calls: 5280
      
      策略库:
        # ...
      
      回测引擎:
        # ...
      
      执行引擎:
        # ...
  
  F_domain:
    name: "基本面能力"
    description: "基本面分析能力集：新闻、资金、情绪、链上、宏观"
    color: "#10b981"
    
    categories:
      新闻聚合:
        modules:
          F1_新闻:
            id: "fundamental-news"
            # ...
      
      资金流分析:
        modules:
          F2_资金流:
            id: "fundamental-fund-flow"
            name: "F2 资金流分析"
            description: "ETF资金流、交易所净流入、大额转账等资金面分析"
            version: "v1.0"
            chain: "F"
            category: "资金流分析"
            # ...
            
            adapter:
              type: "api"
              api_name: "fundamental"
              base_url: "http://localhost:8092"
              endpoint: "/api/fund-flows"
              execution_engine: "python"
      
      情绪分析:
        modules:
          F3_情绪:
            id: "fundamental-sentiment"
            # ...
      
      链上指标:
        # ...
      
      宏观数据:
        # ...
  
  G_domain:
    name: "治理能力"
    description: "系统治理与约束能力：宪法、合规、成本、性能"
    color: "#ef4444"
    
    categories:
      宪法校验:
        # ...
      合规审查:
        # ...
      成本控制:
        # ...
      性能评估:
        # ...
  
  T_domain:
    name: "工具能力"
    description: "基础工具能力：搜索、存储、记忆、维护"
    color: "#6b7280"
    
    categories:
      Tavily搜索:
        # ...
      产物中台:
        # ...
      记忆系统:
        # ...
      系统维护:
        # ...
```

### 4.3 模块元数据字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | ✅ | 全局唯一标识 |
| `name` | string | ✅ | 可读名称 |
| `description` | string | ✅ | 简短描述 |
| `version` | string | ✅ | 语义化版本号 |
| `chain` | string | ✅ | 所属链: A/C/F/G/T |
| `category` | string | ✅ | 所属子系统分类 |
| `tags` | string[] | ✅ | 标签，用于检索和匹配 |
| `estimated_tokens` | number | ✅ | 预估token消耗 |
| `estimated_latency_ms` | number | ✅ | 预估延迟(ms) |
| `confidence_range` | [number, number] | ✅ | 典型置信度范围 |
| `applicable_stages` | string[] | ✅ | 适用阶段: research/analysis/design/validate/execute |
| `market_conditions` | string[] | ✅ | 适用市场条件 |
| `input_schema` | array | ✅ | 输入参数契约 |
| `output_schema` | array | ✅ | 输出参数契约 |
| `adapter` | object | ✅ | 适配器配置 |
| `adapter.type` | string | ✅ | 适配器类型: skill/api/local/external |
| `adapter.execution_engine` | string | ✅ | 执行引擎: python/typescript/hybrid |
| `fallback` | object | ✅ | 降级配置 |
| `dependencies` | string[] | ❌ | 依赖的其他模块ID |
| `historical_accuracy` | number | ❌ | 历史准确率（动态更新） |
| `total_calls` | number | ❌ | 总调用次数（动态更新） |
| `last_called` | string | ❌ | 最后调用时间（动态更新） |

---

## 五、双语言架构 (TypeScript + Python)

### 5.1 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                    TypeScript 侧（编排核心）                   │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ IntentRouter │  │ GraphOrchestr│  │ ModuleRegistry│       │
│  │ 意图识别路由 │  │   ator        │  │ (主内存缓存)  │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│         │                 │                  │                │
│         └─────────────────┼──────────────────┘                │
│                           │                                   │
│                  ┌────────▼────────┐                          │
│                  │  Bridge Client  │                          │
│                  │  (HTTP + SSE)   │                          │
│                  └────────┬────────┘                          │
└───────────────────────────┼───────────────────────────────────┘
                            │  HTTP / WebSocket / SSE
                            │  协议: Module Execution Protocol
┌───────────────────────────┼───────────────────────────────────┐
│                    Python 侧（能力执行）                       │
│                           │                                   │
│                  ┌────────▼────────┐                          │
│                  │  Bridge Server  │                          │
│                  │  (FastAPI)      │                          │
│                  └────────┬────────┘                          │
│                           │                                   │
│         ┌─────────────────┼──────────────────┐                │
│         │                 │                  │                │
│  ┌──────▼───────┐  ┌──────▼───────┐  ┌──────▼───────┐       │
│  │ SkillLoader  │  │ ClassicIndic │  │ Fundamental  │       │
│  │  SKILL执行器  │  │   ators API   │  │   API        │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│         │                 │                  │                │
│  ┌──────▼───────┐  ┌──────▼───────┐  ┌──────▼───────┐       │
│  │ 31个S链SKILL │  │ 经典指标系统  │  │ 基本面系统   │       │
│  │ (6-TRADING)  │  │ (10-经典指标) │  │ (9-基本面)   │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│                                                               │
│  ModuleRegistry (Python侧内存缓存，与TS侧同步)                │
└───────────────────────────────────────────────────────────────┘
```

### 5.2 职责分工

| 层级 | TypeScript 侧 | Python 侧 |
|------|--------------|-----------|
| **意图层** | ✅ IntentRouter | ❌ (可提供规则降级) |
| **编排层** | ✅ GraphOrchestrator | ❌ |
| **模块接口层** | ✅ ModuleRegistry (主) | ✅ ModuleRegistry (副本) |
| **能力层** | ⚠️ 部分纯JS/TS模块 | ✅ 大部分SKILL和外部系统 |

### 5.3 桥接协议 (Module Execution Protocol)

```typescript
// 请求
interface ModuleExecuteRequest {
    module_id: string;
    inputs: Record<string, any>;
    context: ExecutionContext;
    options?: {
        timeout_ms?: number;
        enable_fallback?: boolean;
        priority?: 'low' | 'normal' | 'high';
    };
}

// 响应
interface ModuleExecuteResponse {
    success: boolean;
    result?: ModuleResult;
    error?: {
        code: string;
        message: string;
        retryable: boolean;
    };
}

// SSE 事件（流式执行时）
type ModuleExecutionEvent = 
    | { type: 'start'; module_id: string }
    | { type: 'progress'; phase: string; progress: number; message: string }
    | { type: 'partial_output'; data: any }
    | { type: 'complete'; result: ModuleResult }
    | { type: 'error'; error: string; retryable: boolean };
```

### 5.4 注册表同步机制

```
唯一真相源: module_registry.yaml (文件系统)
    │
    ├── TS侧启动时: 加载 → 解析 → 内存缓存
    │   └── 文件监听: watch → 变更时自动 reload
    │
    └── Python侧启动时: 加载 → 解析 → 内存缓存
        └── 文件监听: watchdog → 变更时自动 reload
```

---

## 六、图架构动态思维链构建

### 6.1 核心机制

**从"固定流水线"到"动态思维图"**：

```
传统模式 (固定流水线):
    A1 → A2 → A3 → A4 → A5 (固定顺序，每步必走)

WorkBuddy OS 模式 (动态思维图):
    意图 → 初始节点集 → 执行 → 置信度评估 → 动态追加/跳过 → 最终结果
    
    例: "BTC现在能不能做多"
    → 初始: [C1技术扫描, F2资金流, A0矛盾论]
    → 执行后: C1(55%), F2(60%), A0(70%) → 综合置信度 62%
    → 置信度不足? → 动态追加 A2第一性原理
    → 执行A2: 置信度 75%
    → 分歧检测: C1看空 vs A2看多 → 动态追加 A3策略设计
    → 执行A3: 综合置信度 82%
    → 达标 → 输出结果 + 完整思考轨迹
```

### 6.2 动态编排算法

```
输入: IntentResult (意图 + 初始推荐节点集)
输出: ChainResult (最终决策 + 节点调用轨迹)

算法步骤:
1. 从 IntentResult 获取初始节点列表
2. 初始化执行队列 = 初始节点列表
3. 初始化已执行节点 = []
4. 初始化综合置信度 = 0
5. WHILE 执行队列不为空:
   a. 取出下一个节点
   b. 调用模块执行器执行该节点
   c. 记录结果到已执行节点
   d. 评估当前综合置信度
   e. 检查是否需要动态调整:
      - 置信度太低 → 追加更多分析节点
      - 节点间冲突 → 追加裁判节点 (如A3策略设计)
      - 数据不足 → 追加数据采集节点 (如F1新闻, A1调研)
      - 置信度已达标 + 用户要求不高 → 跳过后续节点
   f. 更新执行队列
6. 综合所有节点结果，输出最终决策
7. 记录完整思维图到图压缩模块
```

### 6.3 节点选择策略

模块选择器根据以下因素选择最佳模块组合：

| 因素 | 权重 | 说明 |
|------|------|------|
| **意图匹配度** | 30% | 模块功能与当前意图的相关度 |
| **历史准确率** | 25% | 模块在类似场景下的历史表现 |
| **置信度范围** | 20% | 模块典型输出的置信度水平 |
| **成本效率** | 15% | token消耗 / 延迟 / 资源占用 |
| **市场适配性** | 10% | 模块在当前市场条件下的适用性 |

---

## 七、降级容错机制

### 7.1 三级降级策略

```
Level 1: 同类型替换
    模块A不可用 → 调用同类别其他模块
    例: Screen1不可用 → 降级到 A2第一性原理 + 大师辩论

Level 2: 跨链补充
    某条链整体不可用 → 调用其他链的相关模块补充
    例: F链基本面API宕机 → 用C链技术指标 + A链AI分析补充

Level 3: 本地规则降级
    所有外部依赖都不可用 → 使用本地硬编码规则
    例: 所有SKILL和API都不可用 → 用本地RSI/EMA基础规则
```

### 7.2 熔断机制

- 某模块连续失败3次 → 临时熔断（5分钟）
- 熔断期间自动跳过该模块，直接降级
- 熔断期后自动重试

---

## 八、实现路线图

### Phase 1: 注册表建设 ✅ 已完成
- ✅ 技术文档输出
- ✅ 完整注册表文件 (module_registry.yaml)
- ✅ Python侧注册表加载器
- ✅ NodeRegistry 节点注册表（35个模块配置 + 11个本地实现）
- ✅ 与现有系统实践二次对齐

### Phase 2: 模块接口层 ✅ 已完成
- ✅ 统一 ModuleResult / ExecutionContext 类型定义
- ✅ Python侧 Adapter Framework（Skill / API / Local / Node 四种适配器）
- ✅ UnifiedNodeExecutor 统一节点执行器
- ✅ 错误码体系（6大类错误码）
- ✅ 重试与降级机制
- ✅ 端到端调用验证

### Phase 3: 图编排引擎 ✅ 已完成
- ✅ GraphOrchestrator 核心实现
- ✅ 动态节点选择器
- ✅ 置信度评估器
- ✅ 冲突检测与解决机制
- ✅ 与图压缩模块集成

### Phase 4: 意图识别层升级
- IntentRouter 增强
- 产物检索评估器
- 增量更新引擎
- 用户语言 → 内部术语映射

### Phase 5: 治理与进化
- 宪法/合规模块集成
- 成本控制与预算管理
- 性能评估与动态权重
- 学习闭环与模块进化

### Phase 6: 压力测试与性能优化 ✅ 已完成
- ✅ 压力测试框架搭建
- ✅ 高并发场景测试
- ✅ 6种压测场景全部通过
- ✅ 性能瓶颈定位与优化
- ✅ 稳定性验证

---

## 九、与现有系统的关系

| 现有系统 | 新架构中的位置 | 改造程度 |
|---------|--------------|---------|
| 6-TRADING SKILLs (31个) | Layer 4 A_domain / G_domain / T_domain | 低 - 通过SkillAdapter接入 |
| 10-经典指标系统 | Layer 4 C_domain | 低 - 通过ClassicIndicatorsAPI接入 |
| 9-基本面分析系统 | Layer 4 F_domain | 低 - 通过FundamentalAPI接入 |
| 6-图结构上下文压缩 | Layer 2 图编排层 + 记忆系统 | 中 - 新增GraphOrchestrator集成 |
| 前端网关 (INTENT_ROUTER) | Layer 1 意图识别层 | 中 - 升级为完整IntentRouter |
| ab-trading 实验代码 | Layer 2/3 原型验证基础 | 高 - 重构为正式架构 |
| 产物中台 | Layer 4 T_domain | 低 - 作为模块接入 |

---

## 附录A: 模块清单 (按领域分类)

### A_domain (AI交易能力) - 24个模块
| 子系统 | 模块数 | 模块列表 |
|--------|--------|---------|
| 三屏交易系统 | 3 | Screen1, Screen2, Screen3 |
| 执行闭环 | 8 | A0, A1, A2, A3, A4, A5, A7, A9 |
| 情报闭环 | 3 | A6, 大师辩论, 做梦部 |
| 复盘进化 | 3 | A8, 数据分析, 知识库 |
| 策略工具 | 4 | 策略解析, 信号评分, 风险仓位, 执行成本 |
| 门禁系统 | 3 | 预交易门禁, 双代理冲突门禁, 实践门禁 |

### C_domain (经典量化能力) - 8个模块
| 子系统 | 模块数 | 模块列表 |
|--------|--------|---------|
| 指标库 | 3 | 技术扫描, Regime识别, 指标计算 |
| 策略库 | 2 | 经典策略, 马丁策略 |
| 回测引擎 | 2 | 历史回测, 参数优化 |
| 执行引擎 | 1 | 条件单执行 |

### F_domain (基本面能力) - 7个模块
| 子系统 | 模块数 | 模块列表 |
|--------|--------|---------|
| 新闻聚合 | 1 | F1新闻 |
| 资金流分析 | 1 | F2资金流 |
| 情绪分析 | 1 | F3情绪 |
| 链上指标 | 2 | F4链上, 巨鲸追踪 |
| 宏观数据 | 2 | F5宏观, 宏观事件 |

### G_domain (治理能力) - 4个模块
| 子系统 | 模块数 | 模块列表 |
|--------|--------|---------|
| 宪法校验 | 1 | dream-constitution |
| 合规审查 | 1 | ai-trading-compliance |
| 成本控制 | 1 | dream-cost-control |
| 性能评估 | 1 | dream-performance-review |

### T_domain (工具能力) - 9个模块
| 子系统 | 模块数 | 模块列表 |
|--------|--------|---------|
| Tavily搜索 | 1 | tavily |
| 产物中台 | 2 | 产物归档, 产物检索 |
| 记忆系统 | 2 | 经验教训, 策略记忆 |
| 系统维护 | 2 | 自动修复, 健康检查 |
| 数据工具 | 2 | 数据采集, 数据清洗 |

**总计: 52 个模块**

---

*文档版本: v1.1 | 最后更新: 2026-07-01 | 维护者: WorkBuddy OS 架构组*
