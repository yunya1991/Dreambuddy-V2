# PR: S层三层递进大模型集成 + Token预算管理 + 经典指标系统接管

## PR概述

**标题**: S层三层递进接入大模型 + Token预算管理 + 经典指标系统分级接管

**状态**: 待合并（DO NOT MERGE）

**分支**: feature/s-layer-llm-token-budget-handover

**作者**: AI Assistant

**日期**: 2026-07-01

---

## 一、变更说明

### 1.1 核心需求

根据S层三层递进架构设计，实现以下功能：

| 需求 | 说明 |
|------|------|
| **S层三层递进全部接入大模型** | Objective → OKR → Blueprint 三层都优先使用LLM，简单复杂任务都消耗Token |
| **Token预算管理** | 全程监控Token使用，低于阈值时主动提示用户 |
| **经典指标系统接管** | Token不足时提示用户，授权后全链路由经典指标系统接管 |
| **剩余Token用途限制** | 接管后剩余Token仅用于调整策略参数、解释结果等辅助功能 |
| **前端启动建议** | 严重不足时建议启动前端实现全面接管 |

### 1.2 设计理念

```
用户输入
    │
    ▼
【S层三层递进 - LLM优先】
  Layer 1: Objective提取（LLM）
  Layer 2: OKR构建（LLM）
  Layer 3: Blueprint生成（LLM）
    │
    ├─ Token充足 → 正常运行 ✓
    │
    ├─ Token < 70% → 健康提示
    ├─ Token < 30% → 低余额警告，建议接管
    ├─ Token < 10% → 严重警告，强制建议
    │
    └─ 用户授权接管 → 经典指标系统接管
        │
        ├─ 全链路接管：经典指标系统驱动
        ├─ 剩余Token用途：
        │   ├─ 调整策略参数
        │   ├─ 修改策略配置
        │   ├─ 解释结果
        │   └─ 辅助理解
        └─ 建议启动前端 → 全面接管
```

---

## 二、新增文件

### 2.1 核心实现

| 文件 | 行数 | 功能 |
|------|------|------|
| [s_layer_llm_integration.py](file:///workspace/experiments/ab-trading/core/intent_engine/s_layer_llm_integration.py) | 792 | S层LLM集成 + Token预算 + 接管管理 |

### 2.2 测试文件

| 文件 | 行数 | 功能 |
|------|------|------|
| [test_s_layer_llm_integration.py](file:///workspace/experiments/ab-trading/test_s_layer_llm_integration.py) | 486 | 30个测试用例 + 100轮压力测试 |

---

## 三、核心功能详解

### 3.1 Token预算管理器 (TokenBudgetManager)

**分级告警机制**：

| 状态 | 阈值 | 触发动作 |
|------|------|---------|
| HEALTHY | >70% | 正常运行 |
| WARNING | ≤70% | 健康提示，注意预算 |
| LOW | ≤30% | 低余额警告，建议接管 |
| CRITICAL | ≤10% | 严重警告，强制建议接管 |
| EXHAUSTED | 0% | 耗尽，强制降级 |
| HANDOVER_TRIGGERED | 授权后 | 已接管状态 |

**功能特性**：
- 精确Token消耗追踪（按层/按模块）
- 历史使用记录和审计
- 分级告警自动生成
- 接管授权管理
- 剩余Token可用性检查

### 3.2 S层三层递进LLM识别器 (SLayerLLMRecognizer)

**三层都使用LLM**：

| 层级 | 功能 | LLM角色 | 预估Token |
|------|------|---------|-----------|
| Layer 1 | Objective提取 | 理解用户意图，收敛到单点目标 | ~450 |
| Layer 2 | OKR构建 | 分解目标为可衡量的KR，确定复杂度 | ~500 |
| Layer 3 | Blueprint生成 | 映射为可执行的工程蓝图和节点序列 | ~700 |
| **合计** | | | **~1650/次** |

**降级机制**：
- Token不足时自动降级到本地规则
- 节省模式下减少LLM调用
- 接管后完全不使用LLM进行主流程

**接管后剩余Token用途**：
1. ✅ 调整经典指标系统策略参数
2. ✅ 修改策略配置和阈值
3. ✅ 查看和分析经典指标系统结果
4. ✅ 辅助解释和理解交易信号
5. ❌ 不用于主决策流程

### 3.3 经典指标系统接管管理器 (ClassicHandoverManager)

**分级接管**：

| 级别 | 名称 | 说明 | Token节省 |
|------|------|------|-----------|
| NONE | 不接管 | 正常运行 | 0% |
| TOKEN_SAVE | 节省模式 | 减少LLM调用频率 | ~50% |
| RECOMMEND | 建议接管 | 提示用户考虑 | - |
| PARTIAL | 部分接管 | 部分节点由经典指标处理 | ~70% |
| FULL | 全链路接管 | 完全由经典指标驱动 | ~90% |
| FRONTEND | 前端接管 | 建议启动前端 | 100% |

**前端启动建议**：
- Token严重不足时自动建议
- 提供前端URL和功能说明
- 用户确认后启动前端界面
- 实现用户直接操控经典指标系统

---

## 四、与现有系统集成

### 4.1 集成位置

```
IntentRecognitionEngine
    │
    └── SLayerLLMRecognizer (新增)
          ├── TokenBudgetManager (Token预算管理)
          ├── Layer 1: LLM Objective提取
          ├── Layer 2: LLM OKR构建
          └── Layer 3: LLM Blueprint生成
                │
                └── ClassicHandoverManager (接管管理)
                      ├── 接管授权
                      ├── 策略调整（剩余Token）
                      ├── 结果解释（剩余Token）
                      └── 前端启动建议
```

### 4.2 兼容性

| 组件 | 兼容性 | 说明 |
|------|--------|------|
| ObjectiveExtractor | 完全兼容 | 作为降级方案保留 |
| OKRBuilder | 完全兼容 | 作为降级方案保留 |
| BlueprintBuilder | 完全兼容 | 作为降级方案保留 |
| IntentGateway | 可集成 | 可替换原有意图识别 |
| 经典指标系统 | API对接 | 通过 :8092 接口通信 |

---

## 五、测试覆盖

### 5.1 30个测试用例

| 测试类 | 测试数 | 覆盖内容 |
|--------|--------|---------|
| TestTokenBudgetManager | 10 | Token消耗/状态/告警/授权/统计 |
| TestSLayerLLMRecognizer | 11 | 三层识别/Token消耗/降级/策略调整/前端建议 |
| TestClassicHandoverManager | 7 | 请求接管/授权/撤销/前端/策略调整/解释 |
| TestEndToEndIntegration | 1 | 完整用户旅程 |
| TestStress100Rounds | 1 | 100轮压力测试 |

### 5.2 测试结果

```
Ran 30 tests in 0.011s

OK

100轮压力测试统计:
  成功率: 100.00%
  平均延迟: 0.08ms
  总Token消耗: 51319
  剩余Token: 0
```

---

## 六、使用示例

### 6.1 基本使用

```python
from core.intent_engine.s_layer_llm_integration import (
    SLayerLLMRecognizer,
    ClassicHandoverManager,
)

# 初始化
recognizer = SLayerLLMRecognizer(config={'token_budget': 100000})
manager = ClassicHandoverManager(recognizer)

# S层三层递进识别（LLM优先）
result = recognizer.recognize("深度分析BTC的技术面和基本面")
# → objective/okr_set/blueprint 全部由LLM生成
# → 自动消耗Token
# → Token不足时自动降级

# 查看Token状态
stats = recognizer.token_budget.get_stats()
print(stats['remaining_percentage'])  # "75.32%"
```

### 6.2 接管流程

```python
# Token不足时，系统自动提示
if result['token_status'] == 'low':
    # 建议用户接管
    suggestion = manager.request_handover(
        level='full',
        reason='Token预算不足'
    )
    
    # 用户授权后...
    if user_confirm:
        handover_result = manager.authorize_handover(level='full')
        # → 全链路由经典指标系统接管
        # → 剩余Token仅用于策略调整和结果解释
```

### 6.3 接管后策略调整

```python
# 使用剩余Token调整策略
adjust_result = manager.adjust_strategy(
    strategy_id='BreakoutStrategy',
    user_request='降低风险，更保守一点',
    current_params={'position_size': 1.0, 'stop_loss_pct': 5.0}
)
# → 返回调整后的参数建议
# → 消耗少量Token
```

### 6.4 启动前端

```python
# 建议启动前端
frontend_result = manager.start_frontend()
# → 打开经典指标系统前端界面
# → 用户直接操控，零Token消耗
```

---

## 七、性能预估

| 指标 | 预估 | 说明 |
|------|------|------|
| 三层识别延迟 | <50ms（模拟） | 当前为模拟实现 |
| 单次三层Token消耗 | ~1650 | Layer1+Layer2+Layer3 |
| 策略调整Token消耗 | ~350 | 少量辅助调用 |
| 接管后Token节省 | ~90% | 主流程零消耗 |
| 前端接管Token节省 | 100% | 完全无需Token |

---

## 八、风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| LLM调用延迟 | 中 | 异步调用 + 缓存 + 降级机制 |
| Token超支 | 高 | 预算管理 + 分级告警 + 强制降级 |
| 接管误触发 | 中 | 用户授权 + 可撤销 + 明确提示 |
| 前端启动失败 | 低 | 备用方案：继续使用LLM辅助 |

---

## 九、后续工作

1. **接入真实LLM API**：实现 DeepSeek/OpenAI 真实调用
2. **Token精确统计**：接入真实Token计数
3. **异步LLM调用**：支持流式输出
4. **前端真实启动**：实现前端启动命令
5. **更细粒度接管**：按节点级别控制是否使用LLM
6. **用户偏好学习**：学习用户的接管触发偏好

---

## 十、合并检查清单

- [x] 核心实现完成
- [x] 测试文件完成（30个测试全部通过）
- [x] PR文档完成
- [ ] 真实LLM API集成
- [ ] 代码审查通过
- [ ] 性能测试通过
- [ ] 与现有系统集成测试
- [ ] 用户授权流程验证

---

## 十一、附录

### A. 文件变更清单

```
新增:
+ experiments/ab-trading/core/intent_engine/s_layer_llm_integration.py (792行)
+ experiments/ab-trading/test_s_layer_llm_integration.py (486行)

待集成（合并后）:
- experiments/ab-trading/core/intent_engine/__init__.py (导出新类)
- experiments/ab-trading/core/intent_engine/engine.py (集成SLayerLLMRecognizer)
- experiments/ab-trading/core/classic_driver.py (接管驱动集成)
```

### B. 测试命令

```bash
cd /workspace/experiments/ab-trading
python test_s_layer_llm_integration.py -v
```

### C. 关联文档

- [SYSTEM_ARCHITECTURE_OVERVIEW.md](file:///workspace/1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md) - S层三层递进架构
- [dreambuddy-os/SKILL.md](file:///workspace/1-ARCHITECTURE/skills/dreambuddy-os/SKILL.md) - 系统SKILL定义
- [classic_driver.py](file:///workspace/experiments/ab-trading/core/classic_driver.py) - 经典指标系统驱动

---

**声明**: 本PR暂不合并，待真实LLM API集成和完整测试验证后方可合并。