# PR: 动态意图识别 + S思维链LLM降级机制

## PR概述

**标题**: 扩展意图识别引擎支持动态金融意图 + S思维链LLM降级

**状态**: 待合并（DO NOT MERGE）

**分支**: feature/dynamic-intent-s-chain-llm

**作者**: AI Assistant

**日期**: 2026-07-01

---

## 一、变更说明

### 1.1 核心问题

当前意图识别引擎存在以下限制：

| 问题 | 影响 |
|------|------|
| 仅支持6种硬编码意图类型 | 无法识别其他金融类意图（如NFT交易、DeFi研究等） |
| 本地规则无法处理模糊意图 | 用户输入不明确时直接返回低置信度，无降级机制 |
| 无法学习新意图类型 | 系统无法从用户交互中学习新的意图模式 |
| 无LLM降级机制 | 当本地规则失效时，无法调用大模型进行深度理解 |

### 1.2 解决方案

扩展意图识别引擎为**动态意图识别 + S思维链LLM降级**：

```
用户输入
    │
    ▼
【Step 1】本地规则识别（零Token）
    │ 关键词匹配 + 正则模式匹配
    │ 20+金融意图类型知识库
    │
    ├─ 置信度 ≥ 0.45 → 返回结果 ✓
    │
    └─ 置信度 < 0.45 → Step 2
            │
            ▼
    【Step 2】S思维链LLM降级
            │ Layer 1: Objective提取（收敛）
            │ Layer 2: OKR分解（展开）
            │ Layer 3: Blueprint构建（落地）
            │
            ├─ 置信度 ≥ 0.5 → 返回结果 + 学习 ✓
            │
            └─ 置信度 < 0.5 → 返回本地结果（标记低置信度）
```

---

## 二、新增文件

### 2.1 核心实现

| 文件 | 行数 | 功能 |
|------|------|------|
| [dynamic_intent_recognizer.py](file:///workspace/experiments/ab-trading/core/intent_engine/dynamic_intent_recognizer.py) | 1087 | 动态意图识别器 + S思维链LLM降级 |

### 2.2 测试文件

| 文件 | 行数 | 功能 |
|------|------|------|
| [test_dynamic_intent_recognizer.py](file:///workspace/experiments/ab-trading/test_dynamic_intent_recognizer.py) | 340 | 7大场景测试 + 200轮压力测试 |

---

## 三、新增功能详解

### 3.1 金融领域意图知识库（冷启动）

**20+预定义意图类型**，覆盖6大分类：

| 分类 | 意图类型 | 数量 |
|------|----------|------|
| **trading** | spot_trade, futures_trade, order_management, position_management | 4 |
| **analysis** | technical_analysis, fundamental_analysis, sentiment_analysis, volume_analysis, whale_tracking | 5 |
| **risk** | risk_assessment, liquidation_check, rebalance_suggestion | 3 |
| **portfolio** | portfolio_review, asset_allocation, diversification_check | 3 |
| **education** | concept_explanation, strategy_learning, indicator_usage | 3 |
| **research** | market_research, project_research, comparative_analysis | 3 |

每个意图类型包含：
- 关键词列表（支持中英文）
- 正则模式（精确匹配）
- 领域标签
- 推荐思维链（S/C/F组合）
- 基础置信度
- 优先级

### 3.2 S思维链LLM降级机制

**三层递进Prompt设计**：

```python
# Layer 1: 收敛（Objective提取）
分析用户的核心目标是什么

# Layer 2: 展开（OKR分解）
将目标展开为可衡量的关键结果

# Layer 3: 落地（Blueprint构建）
将OKR转化为可执行的工程蓝图
```

**LLM后端支持**：
- DeepSeek（优先）
- OpenAI（次选）
- 本地模拟（容错）

### 3.3 自定义意图注册

```python
# 示例：注册NFT交易意图
custom_intent_def = {
    'intent_id': 'nft_trade',
    'name': 'NFT交易',
    'category': 'trading',
    'keywords': ['NFT', 'nft', '数字藏品'],
    'patterns': [r'nft.*交易'],
    'recommended_chain': 'S+F',
}

recognizer.register_custom_intent(custom_intent_def)
```

### 3.4 从LLM结果学习

当LLM返回高置信度结果（≥0.6）时，自动学习：

```python
# 学习流程
if llm_result.confidence >= 0.6:
    # 1. 创建新的DynamicIntentType
    learned_intent = DynamicIntentType(
        intent_id=llm_result.intent_type,
        name=llm_result.intent_name,
        keywords=llm_result.keywords_matched,
        learned_count=1,
    )
    
    # 2. 加入知识库
    self._learned_intents[intent_type] = learned_intent
    
    # 3. 下次相同意图可直接本地识别
```

---

## 四、测试覆盖

### 4.1 7大测试场景

| 场景 | 测试内容 | 测试数 |
|------|----------|--------|
| 场景1 | 本地规则识别（20+金融意图） | 22 |
| 场景2 | S思维链LLM降级 | 3 |
| 场景3 | 自定义意图注册 | 2 |
| 场景4 | 从LLM结果学习 | 2 |
| 场景5 | 多轮对话意图识别 | 2 |
| 场景6 | 压力测试（200轮） | 1 |
| 场景7 | 意图类型统计 | 2 |

### 4.2 预期测试结果

```
test_local_recognition_trading_intents      ✓ 4/4
test_local_recognition_analysis_intents     ✓ 5/5
test_local_recognition_risk_intents         ✓ 3/3
test_local_recognition_portfolio_intents    ✓ 3/3
test_local_recognition_education_intents    ✓ 3/3
test_local_recognition_research_intents     ✓ 3/3
test_llm_fallback_threshold                 ✓
test_force_llm_recognition                  ✓
test_llm_s_chain_prompt_structure           ✓
test_custom_intent_registration             ✓
test_learning_from_llm_result               ✓
test_stress_200_rounds                      ✓ 成功率>80%
test_intent_type_count                      ✓ >20类型
```

---

## 五、接口设计

### 5.1 DynamicIntentRecognizer

```python
class DynamicIntentRecognizer:
    """动态意图识别器"""
    
    def recognize(
        self,
        user_message: str,
        context: Optional[Dict] = None,
        mkt_data: Optional[Dict] = None,
        force_llm: bool = False,
    ) -> DynamicIntentResult:
        """动态意图识别主入口"""
        pass
    
    def register_custom_intent(self, definition: Dict) -> bool:
        """注册用户自定义意图"""
        pass
    
    def get_all_intent_types(self) -> Dict[str, DynamicIntentType]:
        """获取所有意图类型（包括学习获得的）"""
        pass
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        pass
```

### 5.2 DynamicIntentResult

```python
@dataclass
class DynamicIntentResult:
    intent_type: str                    # 意图类型ID
    intent_name: str                    # 意图名称
    confidence: float                   # 置信度 (0-1)
    recognition_source: str             # local/llm_s_chain/learned
    rationale: str                      # 识别理由
    keywords_matched: List[str]         # 匹配关键词
    patterns_matched: List[str]         # 匹配模式
    recommended_chain: str              # 推荐思维链
    suggested_nodes: List[str]          # 建议节点
    llm_tokens_used: int                # Token消耗
    latency_ms: float                   # 耗时
```

---

## 六、与现有系统集成

### 6.1 替换方案

**推荐**: 在 `IntentRecognitionEngine` 中集成 `DynamicIntentRecognizer`：

```python
# engine.py
from .dynamic_intent_recognizer import DynamicIntentRecognizer

class IntentRecognitionEngine:
    def __init__(self, registry=None):
        # 新增：动态意图识别器
        self.dynamic_recognizer = DynamicIntentRecognizer()
        # ...原有代码...
    
    def recognize(self, user_message, ...):
        # 先尝试动态识别
        dynamic_result = self.dynamic_recognizer.recognize(user_message)
        
        if dynamic_result.confidence >= 0.5:
            # 转换为IntentRecognitionResult
            return self._convert_dynamic_result(dynamic_result)
        
        # 降级到原有逻辑
        return self._original_recognize(...)
```

### 6.2 兼容性

| 组件 | 兼容性 | 说明 |
|------|--------|------|
| IntentGateway | 完全兼容 | 可作为增强层 |
| ObjectiveExtractor | 完全兼容 | 可并行使用 |
| OKRBuilder | 完全兼容 | 输入不变 |
| BlueprintBuilder | 完全兼容 | 输入不变 |

---

## 七、性能预估

### 7.1 本地识别性能

| 指标 | 预估 |
|------|------|
| 平均延迟 | <1ms |
| Token消耗 | 0 |
| 成功率 | 80%+（对于明确意图） |

### 7.2 LLM降级性能

| 指标 | 预估 |
|------|------|
| 平均延迟 | 500-2000ms |
| Token消耗 | 300-800 |
| 成功率 | 90%+（对于模糊意图） |

### 7.3 缓存优化

```python
# 启用缓存后
config = {'enable_cache': True}

# 第二次相同输入
result = recognizer.recognize("买入BTC")  # <0.1ms（缓存命中）
```

---

## 八、风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| LLM响应解析失败 | 中 | 降级到本地模拟响应 |
| 自定义意图冲突 | 低 | 检查intent_id唯一性 |
| 学习噪声 | 中 | 仅学习置信度≥0.6的结果 |
| Token消耗增加 | 中 | 本地优先 + 缓存 |

---

## 九、后续工作

1. **接入真实LLM API**：实现 `_call_deepseek` 和 `_call_openai`
2. **持久化学习结果**：将学习获得的意图保存到文件/数据库
3. **意图类型扩展**：支持更多细分金融意图（期权、衍生品等）
4. **多语言支持**：扩展英文关键词覆盖率
5. **A/B测试**：对比动态识别与原有识别的准确率

---

## 十、合并检查清单

- [x] 核心实现完成
- [x] 测试文件完成
- [x] PR文档完成
- [ ] 单元测试全部通过
- [ ] 代码审查通过
- [ ] 性能测试通过
- [ ] 与现有系统集成测试

---

## 十一、附录

### A. 文件变更清单

```
新增:
+ experiments/ab-trading/core/intent_engine/dynamic_intent_recognizer.py (1087行)
+ experiments/ab-trading/test_dynamic_intent_recognizer.py (340行)

修改（待合并后）:
- experiments/ab-trading/core/intent_engine/__init__.py (导出新类)
- experiments/ab-trading/core/intent_engine/engine.py (集成DynamicIntentRecognizer)
```

### B. 测试命令

```bash
cd /workspace/experiments/ab-trading
python test_dynamic_intent_recognizer.py -v
```

---

**声明**: 本PR暂不合并，待测试验证和代码审查完成后方可合并。