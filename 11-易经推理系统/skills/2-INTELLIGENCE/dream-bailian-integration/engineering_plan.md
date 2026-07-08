# Dream-MultiSkill 百炼项目工程步骤

**版本**: v1.0
**日期**: 2026-05-07
**状态**: 规划中

---

## 一、项目背景

### 1.1 目标
将阿里云百炼平台深度集成到 Dream-MultiSkill 交易系统，实现：
- 智能推理与决策支持
- 知识库 RAG 增强
- 工具调用自动化
- 产物传递标准化

### 1.2 当前状态
| 组件 | 状态 | 说明 |
|:---|:---:|:---|
| 百炼API Key | ✅ | sk-c233489e73e94b9591e4776d89ec8cb8 |
| 模型测试 | ✅ | qwen3.6-35b-a3b 可用 |
| 治理文档 | ✅ | 宪法/流程/FAQ/索引 |
| 技术文档 | ✅ | 平台概览/API参考 |
| SKILL模板 | ✅ | AAM/合规 |
| 实际集成 | ⏳ | 待实施 |

---

## 二、工程阶段

### Phase 1: 基础集成 (1-2周)

#### 1.1 API客户端封装
**目标**: 建立标准化的百炼API调用层

**任务清单**:
- [ ] 创建 `src/bailian_client.py` 标准客户端
- [ ] 实现认证和错误处理
- [ ] 实现重试和超时机制
- [ ] 集成日志和追踪
- [ ] 编写单元测试

**交付物**:
```
src/bailian_client.py    # 核心客户端
tests/test_bailian_client.py  # 单元测试
```

**代码结构**:
```python
class BailianClient:
    """百炼API标准客户端"""

    def __init__(self, api_key=None):
        self.api_key = api_key or os.environ.get("BAILIAN_API_KEY")
        self.base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def chat(self, messages, model="qwen3.6-35b-a3b", **kwargs):
        """聊天补全"""
        pass

    def embed(self, texts, model="text-embedding-v3"):
        """文本向量化"""
        pass

    def image_generate(self, prompt, model="wanx-plus"):
        """图像生成"""
        pass
```

#### 1.2 配置管理
**目标**: 建立统一的配置管理

**任务清单**:
- [ ] 创建 `config/api_config.yaml`
- [ ] 支持多环境配置 (dev/staging/prod)
- [ ] 实现配置热加载
- [ ] 配置验证和默认值

**配置模板**:
```yaml
bailian:
  api_key: "${BAILIAN_API_KEY}"
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  timeout: 30
  max_retries: 3
  default_model: "qwen3.6-35b-a3b"

models:
  chat:
    default: "qwen3.6-35b-a3b"
    high_performance: "qwen-plus"
    max: "qwen-max"
  embedding:
    default: "text-embedding-v3"
  image:
    default: "wanx-plus"

logging:
  level: "INFO"
  trace_header: "X-Trace-Id"
```

---

### Phase 2: 知识库RAG集成 (2-3周)

#### 2.1 知识库架构设计
**目标**: 构建 Dream-MultiSkill 专属知识库

**知识分类**:
| 知识类型 | 来源 | 存储位置 |
|:---|:---|:---|
| 交易策略 | A1-A5 产物 | `artifacts/trading/` |
| 治理规范 | A7/A8 产物 | `artifacts/governance/` |
| 技能文档 | SKILL.md | `skills/*/SKILL.md` |
| 经验教训 | episodes | `memory/lessons/` |
| 市场情报 | A6 监控 | `artifacts/intelligence/` |

#### 2.2 RAG引擎开发
**任务清单**:
- [ ] 创建 `src/rag_engine.py`
- [ ] 实现文档加载器 (Markdown/PDF/DOCX)
- [ ] 实现文本分块器
- [ ] 实现向量化模块
- [ ] 实现向量检索
- [ ] 实现 RAG 管道

**代码结构**:
```python
class RAGEngine:
    """RAG 检索增强生成引擎"""

    def __init__(self, config):
        self.loader = DocumentLoader()
        self.chunker = TextChunker(chunk_size=500, overlap=50)
        self.embedder = BailianEmbedder()
        self.vector_store = FAISSVectorStore()

    def ingest(self, documents):
        """文档摄入"""
        # 加载 → 分块 → 向量化 → 存储
        pass

    def retrieve(self, query, top_k=5):
        """检索相关文档"""
        # 查询向量化 → 向量检索 → 返回结果
        pass

    def generate(self, query, context):
        """生成回答"""
        # 构建提示 → 调用模型 → 返回结果
        pass

    def query(self, question, use_rag=True):
        """完整查询流程"""
        if use_rag:
            docs = self.retrieve(question)
            context = self._format_context(docs)
        else:
            context = None

        return self.generate(question, context)
```

#### 2.3 知识库初始化
**任务清单**:
- [ ] 整理现有 Markdown 文档
- [ ] 设计文档元数据 (frontmatter)
- [ ] 编写导入脚本
- [ ] 执行初始索引
- [ ] 验证检索效果

---

### Phase 3: 工作流编排 (2-3周)

#### 3.1 工作流引擎
**目标**: 实现可视化工作流编排

**任务清单**:
- [ ] 创建 `src/workflow_engine.py`
- [ ] 实现节点注册表
- [ ] 实现节点执行器
- [ ] 实现边条件解析
- [ ] 实现状态管理
- [ ] 实现执行监控

**代码结构**:
```python
class WorkflowEngine:
    """工作流编排引擎"""

    def __init__(self):
        self.nodes = NodeRegistry()
        self.executor = NodeExecutor()
        self.state_manager = StateManager()

    def register_node(self, node_type, handler):
        """注册节点类型"""
        self.nodes.register(node_type, handler)

    def execute(self, workflow_definition, initial_input):
        """执行工作流"""
        state = self.state_manager.init_state(initial_input)

        while not self._is_complete(state):
            next_node = self._get_next_node(state)
            result = self.executor.execute(next_node, state)
            state = self.state_manager.update_state(state, next_node, result)

        return state

    def get_status(self, workflow_id):
        """获取执行状态"""
        return self.state_manager.get_status(workflow_id)
```

#### 3.2 预定义工作流
| 工作流 | 用途 | 节点数 |
|:---|:---|:---:|
| 调研工作流 | A1 深度调研 | 5 |
| 分析工作流 | A2/A3 分析推理 | 4 |
| 验证工作流 | A4 战术验证 | 6 |
| 决策工作流 | A5 交易执行 | 7 |
| 离场工作流 | A9 离场决策 | 5 |

#### 3.3 工作流示例
```yaml
workflow: "a4_verification"
name: "A4 战术验证工作流"

nodes:
  - id: "input"
    type: "start"
    output: "signal_data"

  - id: "validate_signal"
    type: "validation_check"
    input: "signal_data"
    output: "validation_result"

  - id: "retrieve_knowledge"
    type: "rag_retrieve"
    input: "signal_data"
    config:
      top_k: 5
      filters:
        department: "trading"
    output: "relevant_knowledge"

  - id: "analyze"
    type: "llm"
    input: "signal_data + relevant_knowledge"
    config:
      model: "qwen-plus"
      prompt: "analysis_prompt"
    output: "analysis_result"

  - id: "risk_check"
    type: "risk_gate"
    input: "analysis_result"
    output: "risk_assessment"

  - id: "decision"
    type: "decision_gate"
    input: "risk_assessment"
    output: "final_decision"

edges:
  - from: "input"
    to: "validate_signal"

  - from: "validate_signal"
    to: "retrieve_knowledge"
    condition: "validation_result.pass == true"

  - from: "retrieve_knowledge"
    to: "analyze"

  - from: "analyze"
    to: "risk_check"

  - from: "risk_check"
    to: "decision"
```

---

### Phase 4: Function Calling集成 (2周)

#### 4.1 工具注册表
**目标**: 建立统一的工具调用管理

**任务清单**:
- [ ] 创建 `src/tool_registry.py`
- [ ] 定义标准工具接口
- [ ] 实现工具发现机制
- [ ] 实现参数校验
- [ ] 实现安全检查

**代码结构**:
```python
class ToolRegistry:
    """工具注册表"""

    def __init__(self):
        self.tools = {}

    def register(self, tool_schema, handler):
        """注册工具"""
        self.tools[tool_schema["function"]["name"]] = {
            "schema": tool_schema,
            "handler": handler
        }

    def get_tools(self):
        """获取所有工具定义"""
        return [t["schema"] for t in self.tools.values()]

    def execute(self, tool_name, parameters):
        """执行工具"""
        if tool_name not in self.tools:
            raise ValueError(f"Unknown tool: {tool_name}")

        tool = self.tools[tool_name]

        # 参数校验
        self._validate_parameters(tool["schema"], parameters)

        # 执行
        return tool["handler"](**parameters)

    def _validate_parameters(self, schema, params):
        """校验参数"""
        # JSON Schema 校验
        pass
```

#### 4.2 预定义工具
| 工具 | 用途 | 权限 |
|:---|:---|:---|
| `get_market_data` | 获取行情 | 读取 |
| `get_orderbook` | 获取订单簿 | 读取 |
| `get_positions` | 获取持仓 | 读取 |
| `place_order` | 下单 | 写入(需审批) |
| `cancel_order` | 撤单 | 写入(需审批) |
| `deliver_artifact` | 产物投递 | AAM |
| `check_compliance` | 合规审查 | 系统 |

#### 4.3 工具调用集成
```python
# 初始化工具注册表
registry = ToolRegistry()

# 注册市场数据工具
registry.register(
    tool_schema={
        "type": "function",
        "function": {
            "name": "get_market_data",
            "description": "获取市场行情数据",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "interval": {"type": "string", "enum": ["1m", "5m", "1h", "4h", "1d"]}
                },
                "required": ["symbol"]
            }
        }
    },
    handler=get_market_data
)

# 注册产物投递工具
registry.register(
    tool_schema={
        "type": "function",
        "function": {
            "name": "deliver_artifact",
            "description": "投递产物到双通道",
            "parameters": {
                "type": "object",
                "properties": {
                    "artifact_name": {"type": "string"},
                    "content": {"type": "string"},
                    "config": {"type": "object"}
                },
                "required": ["artifact_name", "content", "config"]
            }
        }
    },
    handler=deliver_artifact
)
```

---

### Phase 5: AAM产物传递集成 (1-2周)

#### 5.1 AAM服务
**目标**: 实现标准化的产物传递

**任务清单**:
- [ ] 封装 AAMDeliverer 类
- [ ] 集成到各 SKILL
- [ ] 实现自动验证
- [ ] 监控投递状态

**代码集成**:
```python
# 在各 SKILL 中使用
from src.aam_deliverer import AAMDeliverer

class TacticalValidator:
    def __init__(self):
        self.aam = AAMDeliverer()

    def run_validation(self, signal_data):
        # 执行验证...
        result = self._validate(signal_data)

        # 投递产物
        self.aam.deliver(
            artifact_name="a4_verification_report",
            content=result.markdown,
            config={
                "title": "A4 战术验证报告",
                "department": "trading",
                "chain_phase": "A4",
                "type": "report",
                "tags": "a4 tactical-validation",
                "by_a_phase": "A4"
            }
        )

        return result
```

---

### Phase 6: 合规审查集成 (1-2周)

#### 6.1 合规门禁
**目标**: 实现强制合规审查

**任务清单**:
- [ ] 实现 ComplianceGate 类
- [ ] 实现 ShadowVerifier 类
- [ ] 集成到变更流程
- [ ] 建立人工审批流程

**代码集成**:
```python
from src.compliance_gate import ComplianceGate

class ChangeManager:
    def __init__(self):
        self.gate = ComplianceGate()

    def submit_change(self, change_plan):
        # 合规审查
        review_result = self.gate.review(change_plan)

        if review_result.decision == "APPROVE":
            return self.execute_change(change_plan)

        elif review_result.decision == "PENDING_HUMAN_REVIEW":
            # 发送人工审批请求
            self.request_human_review(review_result)
            return {"status": "pending", "reason": "需要人工审批"}

        else:
            return {"status": "rejected", "reason": review_result.reason}
```

---

## 三、实施计划

### 3.1 时间线
```
Week 1-2:   Phase 1 - 基础集成
Week 3-5:   Phase 2 - 知识库RAG
Week 6-8:   Phase 3 - 工作流编排
Week 9-10:  Phase 4 - Function Calling
Week 11-12: Phase 5 - AAM集成
Week 13-14: Phase 6 - 合规集成
```

### 3.2 里程碑
| 里程碑 | 日期 | 交付物 |
|:---|:---|:---|
| M1 | Week 2 | 标准化API客户端 |
| M2 | Week 5 | RAG知识库上线 |
| M3 | Week 8 | 工作流引擎完成 |
| M4 | Week 10 | Function Calling集成 |
| M5 | Week 12 | AAM全链路打通 |
| M6 | Week 14 | 合规门禁上线 |

### 3.3 资源需求
| 资源 | 数量 | 说明 |
|:---|:---:|:---|
| 开发时间 | 14周 | 按计划执行 |
| 百炼费用 | ¥500/月 | API调用成本 |
| 存储空间 | 10GB | 知识库+日志 |

---

## 四、风险与对策

| 风险 | 影响 | 概率 | 对策 |
|:---|:---:|:---:|:---|
| 百炼服务中断 | 高 | 低 | 备用模型/本地推理 |
| API成本超支 | 中 | 中 | 预算告警/优化调用 |
| 知识库质量差 | 中 | 中 | 人工审核/持续迭代 |
| 合规审查延迟 | 中 | 中 | 异步处理/人工兜底 |

---

## 五、验收标准

### 5.1 功能验收
- [ ] API调用成功率 > 99%
- [ ] RAG检索准确率 > 80%
- [ ] 工作流执行成功率 > 95%
- [ ] 产物投递成功率 = 100%

### 5.2 性能验收
- [ ] API响应时间 p99 < 5s
- [ ] RAG检索时间 < 1s
- [ ] 工作流执行时间符合预期

### 5.3 合规验收
- [ ] 所有P0/P1变更经过人工审批
- [ ] 影子验证通过率 > 90%
- [ ] 审计日志完整率 = 100%

---

## 六、下一步行动

### 立即执行 (本周)
1. ✅ API Key 验证完成
2. ⬜ 创建 `src/bailian_client.py` 
3. ⬜ 编写单元测试
4. ⬜ 部署到测试环境

### 下周计划
1. ⬜ 完成 API 客户端开发
2. ⬜ 集成日志和追踪
3. ⬜ 开始 RAG 知识库设计

---

*本计划是百炼集成的工程指南，按阶段逐步推进。*
