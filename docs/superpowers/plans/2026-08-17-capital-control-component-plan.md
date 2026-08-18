# 实施计划：账户资金调控通用组件（CapitalControlComponent）

> **关联 Spec：** [2026-08-17-capital-control-component-design.md](../specs/2026-08-17-capital-control-component-design.md)
> **创建日期：** 2026-08-17
> **状态：** 待执行
> **作者：** TRAE Code Assistant

---

## 0. 计划概览

### 0.1 总体路径

按 Spec 第 10 节实施顺序，共 10 个步骤，分 4 个阶段：

| 阶段 | 步骤 | 范围 | 验收 |
|------|------|------|------|
| **阶段 A：前置依赖** | 步骤 1 | equity 字段补齐 + total_equity 聚合 | unified_position_query 6 系统全部填充 equity |
| **阶段 B：核心组件** | 步骤 2-6 | RuleRegistry 扩展、types、4 条规则、主组件、配置 | 单元测试 + 集成测试通过 |
| **阶段 C：一期挂载** | 步骤 7-9 | auto_exit_system 步骤 1.5、Bug 修复、测试、文档 | E2E 测试通过，调控报告产物生成 |
| **阶段 D：二期接入** | 步骤 10 | A9 Layer 5 资金调控修正 | A9 评估结果含 layer5_capital_adjustment |

### 0.2 依赖关系

```
步骤 1 (equity 补齐)
    ↓
步骤 2 (RuleRegistry 扩展) ← 独立可并行
    ↓
步骤 3 (types.py) ← 依赖步骤 2
    ↓
步骤 4 (4 条规则) ← 依赖步骤 1、3
    ↓
步骤 5 (主组件) ← 依赖步骤 2、3、4
    ↓
步骤 6 (配置文件) ← 依赖步骤 5
    ↓
步骤 7 (一期挂载 + Bug 修复) ← 依赖步骤 1、5、6
    ↓
步骤 8 (测试) ← 依赖步骤 7
    ↓
步骤 9 (文档) ← 依赖步骤 7
    ↓
步骤 10 (二期 A9 接入) ← 依赖步骤 7、8
```

### 0.3 风险控制

- 每个步骤完成后立即运行该步骤的验证命令
- 阶段 B 结束前不修改 auto_exit_system.py（避免影响现有 08:00/20:00 调度）
- 二期 A9 接入默认 `phase2.enabled=false`，可通过配置开关启用

---

## 阶段 A：前置依赖

### 步骤 1：equity 字段补齐与全局聚合

**目标：** 补齐 unified_position_query.py 中 4 个系统的 equity 字段，并在 fetch_all_positions 增加 total_equity 聚合。

**子任务：**

1.1. V15 马丁补齐（[unified_position_query.py](../../../16-调控系统/core/unified_position_query.py) `fetch_v15_martin_positions()`）
- 在函数末尾新增对 V15 `capital_manager.get_account_balance()` 的调用
- 复用 [V15 capital_manager.py:111-153](../../../14-V15经典马丁策略/lib/capital_manager.py) 的现有实现
- 失败时 equity=0.0，extra 字段记录错误
- 验证：`python -c "from unified_position_query import fetch_v15_martin_positions; r = fetch_v15_martin_positions(); print(r['equity'], r.get('extra'))"`

1.2. 易经推理补齐（`fetch_yijing_positions()`）
- 在函数中新增对 [11-易经 okx_simulated.py](../../../11-易经推理系统/scripts/memory_l4/okx_simulated.py) `OKXSimulatedClient` 的调用
- 注意：使用 `simulated=True`，凭证从易经的独立配置加载（不走 V15 的 .env.common）
- 失败时降级到 equity=0.0
- 验证：`python -c "from unified_position_query import fetch_yijing_positions; r = fetch_yijing_positions(); print(r['equity'])"`

1.3. 三屏趋势补齐（`fetch_three_screen_positions()`）
- 已有 `requests.get(f"{THREE_SCREEN_API_BASE}/tracker/stats")` 调用
- 从返回的 data 中提取 `account_value` 字段作为 equity
- 失败时 equity=0.0
- 验证：`python -c "from unified_position_query import fetch_three_screen_positions; r = fetch_three_screen_positions(); print(r['equity'])"`

1.4. Agent C 补齐（`fetch_agent_c_positions()`）
- 直接复用 Agent B 的 equity 缓存（共用账户）
- 实现：`agent_b_result = _cache_get("hl_0x6632da9c91A959eEBf1343f8AFAbf2807414004A")`
- 验证：`python -c "from unified_position_query import fetch_agent_c_positions; r = fetch_agent_c_positions(); print(r['equity'])"`

1.5. fetch_all_positions 聚合
- 在 [fetch_all_positions() line 617-681](../../../16-调控系统/core/unified_position_query.py) 新增 `total_equity` 计算
- version 升级到 "1.1"
- 验证：`python -c "from unified_position_query import fetch_all_positions; r = fetch_all_positions(); print(r['total_equity'], r['version'])"`

**验收标准：**
- [ ] 6 个系统的 fetch_* 函数均填充 equity 字段
- [ ] fetch_all_positions 返回 total_equity 字段
- [ ] version 升级到 "1.1"
- [ ] 现有调用方（unified_position_query 的其他使用者）不受影响

**风险：**
- V15 capital_manager 加载需要正确设置 sys.path
- 易经 okx_simulated 凭证独立，可能与 V15 实盘凭证冲突——必须确保各自独立 import

---

## 阶段 B：核心组件

### 步骤 2：RuleRegistry 扩展

**目标：** 在 [13-通用风控模块/core/registry.py](../../../13-通用风控模块/core/registry.py) 新增 CAPITAL 类别与 register_capital 装饰器。

**子任务：**

2.1. 修改 `RuleCategory` 枚举
- 在 [registry.py:19-24](../../../13-通用风控模块/core/registry.py) 新增 `CAPITAL = "capital"`

2.2. 新增 `register_capital` 装饰器
- 仿照 [register_gate/register_position/register_exit (line 94-140)](../../../13-通用风控模块/core/registry.py) 实现
- 参数：`name, priority=100, config_schema=None, description=""`
- 内部调用 `RuleRegistry.DEFAULT_RULES[name] = RuleInfo(...)`

2.3. 在 `RuleRegistry.execute_chain` 中支持 CAPITAL 类别
- 检查 execute_chain 是否需要新增 CAPITAL 分支（看现有实现是否泛化）
- 如果 execute_chain 是按 category 通用过滤，则无需改动

**验收标准：**
- [ ] `from registry import RuleCategory; RuleCategory.CAPITAL` 可访问
- [ ] `@register_capital(name="test", priority=10)` 装饰器可正常使用
- [ ] 现有 GATE/POSITION/EXIT 三类规则不受影响（运行现有测试 `13-通用风控模块/tests/`）

**验证命令：**
```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
python -m pytest 13-通用风控模块/tests/ -v
```

### 步骤 3：实现 types.py

**目标：** 创建 [16-调控系统/core/capital_control/types.py](../../../16-调控系统/core/capital_control/types.py)

**子任务：**

3.1. 创建包目录
- `16-调控系统/core/capital_control/__init__.py`（空文件）
- `16-调控系统/core/capital_control/types.py`

3.2. 实现 4 个核心类型（按 Spec 3.1 节）
- `CapitalMode` 枚举（FIXED / DYNAMIC）
- `AccountType` 枚举（OKX_LIVE / OKX_SIMULATED / HYPERLIQUID / ASTER / UNKNOWN）
- `CapitalResult` dataclass（11 字段）
- `CapitalSnapshot` dataclass（10 字段）

3.3. 实现 `assess_health(snapshot)` 辅助函数
- 按 Spec 3.4 节判定 HEALTHY / WARNING / CRITICAL

**验收标准：**
- [ ] `from capital_control.types import CapitalMode, AccountType, CapitalResult, CapitalSnapshot, assess_health` 可导入
- [ ] `CapitalResult(system="test", account_type=AccountType.UNKNOWN, mode=CapitalMode.DYNAMIC, total_eq=0, avail_balance=0, used_margin=0, used_pct=0)` 可实例化

### 步骤 4：实现 4 条资金规则

**目标：** 在 `16-调控系统/core/capital_control/capital_rules/` 目录下实现 4 条 handler。

**子任务：**

4.1. 创建 `capital_rules/__init__.py`

4.2. `okx_live_rule.py`（priority=10）
- `@register_capital(name="capital.okx_live", priority=10, ...)`
- 复用 [V15 capital_manager.get_account_balance()](../../../14-V15经典马丁策略/lib/capital_manager.py)
- DYNAMIC 模式：调用 API，返回 CapitalResult
- FIXED 模式：直接返回 `fallback_static_budget` 配置值
- 失败降级：429/401/timeout → fallback_static_budget

4.3. `okx_simulated_rule.py`（priority=20）
- `@register_capital(name="capital.okx_simulated", priority=20, ...)`
- 复用 [11-易经 okx_simulated.py](../../../11-易经推理系统/scripts/memory_l4/okx_simulated.py)
- 注意：simulated=True，凭证独立

4.4. `hyperliquid_rule.py`（priority=30）
- `@register_capital(name="capital.hyperliquid", priority=30, ...)`
- 复用 unified_position_query 的 equity 缓存（不直接调 API）
- 实现：从 `fetch_agent_a_positions()` / `fetch_agent_b_positions()` 提取 equity

4.5. `aster_rule.py`（priority=40）
- `@register_capital(name="capital.aster", priority=40, ...)`
- 复用 ml_trade_service API
- 从 `fetch_three_screen_positions()` 提取 equity

**验收标准：**
- [ ] 4 个规则文件均可独立 import
- [ ] 每个规则 handler 签名符合 Spec 3.3 节
- [ ] 每个规则在 DYNAMIC 模式下返回有效 CapitalResult
- [ ] 每个规则在 API 失败时降级到静态值

### 步骤 5：实现 CapitalControlComponent 主组件

**目标：** 创建 [16-调控系统/core/capital_control/component.py](../../../16-调控系统/core/capital_control/component.py)

**子任务：**

5.1. `CapitalControlComponent.__init__`
- 加载 capital_control.json 配置
- 实例化 RuleRegistry
- import capital_rules 包（触发 @register_capital 装饰器）
- 根据 enabled_systems 调用 registry.enable/disable
- 初始化 60s 缓存

5.2. `evaluate(systems=None) -> CapitalSnapshot`
- 遍历 enabled_systems
- 对每个系统调用 registry.execute_chain(CAPITAL, ...)
- 单系统失败不影响整体（Spec 6.4）
- 聚合为 CapitalSnapshot

5.3. `get_capital_advice(system, action) -> Dict`（二期接口）
- 默认实现：根据 margin_pressure 返回 `{"allowed": True/False, "reason": ..., "max_position_usdt": ..., "current_avail": ..., "margin_pressure": ...}`

5.4. `get_snapshot() -> Optional[CapitalSnapshot]`
- 返回最近一次 evaluate 缓存

5.5. `health_check() -> Dict`
- 返回组件健康状态（用于 16-调控系统健康监控）

5.6. 在 `capital_control/__init__.py` 导出
- `from .types import *`
- `from .component import CapitalControlComponent`

**验收标准：**
- [ ] `from capital_control import CapitalControlComponent, CapitalMode` 可导入
- [ ] 实例化 `CapitalControlComponent(mode=CapitalMode.DYNAMIC)` 不报错
- [ ] `component.evaluate()` 返回 CapitalSnapshot
- [ ] 单系统失败时整体仍返回结果（含 fallback_used=True 的 CapitalResult）

### 步骤 6：创建配置文件

**目标：** 创建 `16-调控系统/config/capital_control.json`（按 Spec 6.1 节）

**子任务：**

6.1. 创建 `16-调控系统/config/capital_control.json`
- 按 Spec 6.1 节的 JSON 结构

6.2. 创建 `16-调控系统/config/capital_control.example.json`
- 示例配置（用于文档参考）

**验收标准：**
- [ ] 配置文件可被 `json.load()` 正确解析
- [ ] 包含所有 Spec 6.1 节字段

---

## 阶段 C：一期挂载

### 步骤 7：修改 auto_exit_system.py

**目标：** 在 [auto_exit_system.py](../../../16-调控系统/scripts/auto_exit_system.py) 步骤 1 之后插入步骤 1.5 资金调控挂载，并修复 line 183 Bug。

**子任务：**

7.1. 修复 line 183 Bug（前置）
- 错误：`a9_exit_decision.evaluate_position_for_exit(...)`
- 修复：改为 `SkillEngine.execute("dream-exit-skill-v2", {...})`
- 验证：`python 16-调控系统/scripts/auto_exit_system.py --dry-run` 不再抛 AttributeError

7.2. 在 `run_exit_evaluation_cycle()` 步骤 1 之后插入步骤 1.5
- 实例化 CapitalControlComponent
- 调用 `evaluate()`
- 调用 `_write_capital_report(snapshot, positions_result)` 写入产物

7.3. 实现 `_write_capital_report()`
- 写入 `16-调控系统/artifacts/capital-reports/capital_YYYYMMDD_HHMMSS.json`
- 结构按 Spec 5.4 节

7.4. 集成 AAM 投递（可选，先观察）
- 通过 [aam_deliverer.py](../../../16-调控系统/core/aam_deliverer.py) 投递调控报告
- 默认先不投递，注释代码留出

**验收标准：**
- [ ] `python 16-调控系统/scripts/auto_exit_system.py --dry-run` 完整运行无异常
- [ ] `artifacts/capital-reports/` 目录下生成 JSON 产物
- [ ] CRITICAL 健康状态触发飞书告警（mock 测试）

### 步骤 8：编写测试

**目标：** 在 `16-调控系统/tests/capital_control/` 下编写三层测试。

**子任务：**

8.1. 创建 `tests/capital_control/__init__.py`

8.2. `test_unit.py`
- TestOkxLiveRule（成功/降级/429）
- TestOkxSimulatedRule
- TestHyperliquidRule
- TestAsterRule
- TestHealthAssessment（HEALTHY/WARNING/CRITICAL）

8.3. `test_integration.py`
- TestCapitalControlComponent（evaluate / fixed mode / 单系统失败容错）
- TestRuleRegistryCapital（注册/启停/优先级排序）

8.4. `test_e2e.py`
- TestAutoExitSystemIntegration（步骤 1.5 挂载 / 产物生成）
- 需 mock OKX API 和 Hyperliquid API

**验收标准：**
- [ ] `python -m pytest 16-调控系统/tests/capital_control/ -v` 全部通过
- [ ] 覆盖率达标（types 95%、component 85%、rules 75%、auto_exit_system 80%）

**验证命令：**
```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
python -m pytest 16-调控系统/tests/capital_control/ -v --cov=16-调控系统/core/capital_control
```

### 步骤 9：更新文档

**目标：** 同步更新 16-调控系统的设计文档与索引。

**子任务：**

9.1. 更新 [TECHNICAL_DESIGN.md](../../../16-调控系统/docs/TECHNICAL_DESIGN.md)
- 在 2.1 分层架构图新增 L1.5 资金调控层
- 在 2.2 模块关系图新增 CapitalControlComponent
- 在 5.1 内部接口新增资金调控 API 表
- 在 6.1 状态文件新增 capital_control.json / capital-reports/
- 在 9.4 模块文件索引新增 capital_control/ 目录

9.2. 更新 [ENGINEERING_INDEX.md](../../../16-调控系统/docs/ENGINEERING_INDEX.md)
- 新增 capital_control 模块文件清单（15 个新文件）

9.3. 更新 [API_SPEC.md](../../../16-调控系统/docs/API_SPEC.md)
- 新增资金调控组件对外 API 表
- 标记 line 183 Bug 已修复

9.4. 创建 `16-调控系统/docs/CAPITAL_CONTROL_DESIGN.md`
- 从 spec 派生的产品化设计文档（移除 superpowers 元信息）

**验收标准：**
- [ ] 文档与代码一致
- [ ] 无 TBD / TODO 占位符
- [ ] 文件链接全部有效

---

## 阶段 D：二期接入

### 步骤 10：A9 Layer 5 资金调控修正

**目标：** 在 [a9_exit_decision.py](../../../16-调控系统/core/a9_exit_decision.py) 新增 Layer 5 资金调控修正。

**子任务：**

10.1. 扩展 a9_exit_decision_handler 输入契约
- 新增可选字段 `capital_advice: Dict[str, Dict]`
- 默认空字典，向后兼容

10.2. 实现 Layer 5 资金调控修正
- 在 4 层决策链之后新增 Layer 5
- 检查 `capital_advice[position.system].margin_pressure`
- HIGH 压力下：RAISE_TP → HOLD，confidence × 0.8

10.3. 修改 auto_exit_system.py 步骤 6.5
- 构建 capital_advice 字典
- 传入 SkillEngine.execute("dream-exit-skill-v2", {..., "capital_advice": ...})

10.4. 在 ExitEvaluation 输出新增 layer5_capital_adjustment 字段

10.5. 在 capital_control.json 中默认 `phase2.enabled=false`
- 二期接入完成后默认关闭，需显式开启

**验收标准：**
- [ ] phase2.enabled=false 时，A9 行为与一期完全一致（向后兼容）
- [ ] phase2.enabled=true 时，HIGH 压力系统 RAISE_TP 被降级为 HOLD
- [ ] ExitEvaluation.layers 包含 layer5_capital_adjustment 字段
- [ ] `python -m pytest 16-调控系统/tests/capital_control/test_e2e.py::TestPhase2 -v` 通过

---

## 附录 A：命令速查

### A.1 阶段 A 验证
```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
python -c "import sys; sys.path.insert(0, '16-调控系统/core'); from unified_position_query import fetch_all_positions; r = fetch_all_positions(); print('total_equity:', r['total_equity']); print('version:', r['version']); print('systems:', {k: v.get('equity', 0) for k, v in r['systems'].items()})"
```

### A.2 阶段 B 验证
```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
python -m pytest 13-通用风控模块/tests/ -v
python -c "import sys; sys.path.insert(0, '16-调控系统/core'); from capital_control import CapitalControlComponent, CapitalMode; c = CapitalControlComponent(mode=CapitalMode.DYNAMIC); s = c.evaluate(); print('health:', s.health); print('total_equity:', s.total_equity)"
```

### A.3 阶段 C 验证
```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
python -m pytest 16-调控系统/tests/capital_control/ -v --cov=16-调控系统/core/capital_control
python 16-调控系统/scripts/auto_exit_system.py --dry-run
ls -la 16-调控系统/artifacts/capital-reports/
```

### A.4 阶段 D 验证
```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
python -m pytest 16-调控系统/tests/capital_control/test_e2e.py::TestPhase2 -v
```

---

## 附录 B：回滚方案

### B.1 阶段 A 回滚
- 恢复 unified_position_query.py 到修改前
- equity 字段默认 0.0，不影响现有功能

### B.2 阶段 B 回滚
- 删除 `16-调控系统/core/capital_control/` 目录
- 恢复 13-通用风控模块/core/registry.py（移除 CAPITAL 枚举）

### B.3 阶段 C 回滚
- 恢复 auto_exit_system.py（移除步骤 1.5）
- 注意：line 183 Bug 修复可保留（独立改进）

### B.4 阶段 D 回滚
- 在 capital_control.json 中设置 `phase2.enabled=false`
- A9 handler 中 `capital_advice` 字段为空字典时完全不影响决策

---

## 附录 C：检查清单（执行前确认）

- [ ] 当前 git 工作区干净（`git status`）
- [ ] 备份当前 16-调控系统目录
- [ ] 确认 OKX 实盘凭证可用（V15 .env.common）
- [ ] 确认 OKX 模拟盘凭证可用（易经配置）
- [ ] 确认 Hyperliquid API 可访问
- [ ] 确认 ml_trade_service 运行中（三屏 equity 来源）
- [ ] 确认 Python 环境（pytest、pytest-cov 已安装）

---

## 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| v1.0 | 2026-08-17 | 初始实施计划，按 Spec 第 10 节展开为 4 阶段 10 步骤 |
