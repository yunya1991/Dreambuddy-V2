# 优化提案：进化参数接线缺口 — config.json 采纳参数未注入生产引擎

> **提案编号**: PROP-20260810-CONFIG-WIRING
> **提案类型**: 系统升级（交易进化引擎代码变更）
> **审批类别**: `trading`（交易进化提案 → **人工审批，永不自动批准**）
> **R 级别**: R2（须人工审核，禁止自动落地 — 宪法 H009 约束）
> **状态**: `pending_approval`
> **创建时间**: 2026-08-09 02:10 UTC
> **前置提案**: PROP-20260809（自进化引擎三点升级，已实施交付）
> **提案来源**: PROP-20260809 E2 独立对抗审查 W5 发现（"config.json 无生产消费点"）+ D 链调研核实
> **目标文件**: `11-易经推理系统/scripts/memory_l4/`（6 处引擎构造点 + engine.py 工厂）

---

## 一、背景

PROP-20260809 已完成进化闭环的前半段：

```
实盘统计 → 停滞检测 → 三层反思(A8/做梦部/联网) → 提案池
→ 白名单 AND 真实 walk-forward 双门禁 → 采纳
→ 固化 config.json + constraints/releases/v0.1.N.json   ← 闭环到此为止
→ ??? 生产引擎生效                                       ← 缺失的最后一跳
```

E2 独立审查（W5）发现：**进化采纳的参数固化进 config.json 后，没有任何生产代码消费它**。进化闭环"实践→认知升级→回测→固化"全部打通，唯独"生效"一环断裂——认知系统闭环在最后一跳失效。

---

## 二、问题证据（D 链调研，2026-08-09）

### 2.1 生产路径全部裸构造引擎

| 文件:行号 | 代码 | 角色 |
|:---|:---|:---|
| `polling_trader.py:114` | `self.bcrm_engine = BCRMEngine()` | **实盘轮询交易器** |
| `yijing_monitor.py:266` | `bcrm = BCRMEngine()` | 监控器推理 |
| `ab_bridge.py:554` | `engine = BCRMEngine()` | AB 决策桥 |
| `ab_bridge.py:757` | `engine = BCRMEngine()` | AB 决策桥 |
| `ab_bridge.py:1459` | `engine = BCRMEngine()` | AB 决策桥 |
| `bcrm/engine.py:928` | `return BCRMEngine()` | 默认工厂 |

6 处构造全部无 config 注入，引擎恒用构造默认值（`min_confidence_threshold=0.25`）。

### 2.2 讽刺的断裂：monitor 读阈值却不传给引擎

`yijing_monitor.py` 自己实现了完整的阈值进化读写：

- L383-386: 读 `config.json` 的 `confidence_threshold`（默认 0.70）
- L424-427: 自适应调整（+0.03/-0.02，夹在 [0.55, 0.80]）
- L438: 写回 config.json

但它 L266 构造的 `BCRMEngine()` **没有接收这个阈值**——阈值只作用于 monitor 外层门控，引擎内部的 fail_closed 判定（`engine.py` L211-219，PROP-001 的作用点）永远用默认 0.25。

### 2.3 影响

`self_evolution_engine._apply_adopted_to_config()` 通过 `_PARAM_KEY_TO_CONFIG`（`min_confidence_threshold` → `confidence_threshold`）固化采纳值。但由于无消费点：

1. 进化采纳 `min_confidence_threshold=0.30` → 写入 config.json → **生产引擎仍用 0.25**
2. 回测验证（PROP-001）验证的是"引擎在 0.30 下的表现"，生产跑的却是 0.25 → **回测结论与生产行为脱钩**
3. 认知系统四支柱闭环（实践→认知升级→固化→生效）最后一跳断裂

---

## 三、修复方案（最小侵入）

### 3.1 新增 config-aware 工厂（bcrm/engine.py）

```python
@classmethod
def from_config(cls, config_path=None):
    """从 config.json 加载进化采纳的参数构造引擎。
    映射表与 self_evolution_engine._PARAM_KEY_TO_CONFIG 一致。
    任何异常（文件缺失/损坏/键缺失）→ 回退默认构造，行为不变。"""
```

- 映射：`confidence_threshold` → `min_confidence_threshold`（当前唯一引擎消费参数，映射表可扩展）
- 合法性裁剪复用 `evolution_backtest._ENGINE_FIELD_BOUNDS`（0.01-0.95）

### 3.2 替换 6 处裸构造

全部改为 `BCRMEngine.from_config()`。默认回退保证：config.json 不存在/损坏时行为与现状**完全一致**（零风险切换）。

### 3.3 不做的事（范围约束）

- ❌ 不触碰 V9 基线规则（加仓间隔/止盈/止损/仓位上限）
- ❌ 不触碰 yijing_monitor 的自适应调参逻辑（L424-438 保持原样）
- ❌ 不新增 config 键，只消费既有 `confidence_threshold`
- ❌ 不做运行时热重载（引擎构造时读一次即可——polling_trader 每轮构造周期自然重读）

---

## 四、验收标准

| # | 标准 | 验证方式 |
|:---|:---|:---|
| 1 | config.json `confidence_threshold=0.30` → `from_config().min_confidence_threshold == 0.30` | 单元测试 |
| 2 | config 缺失/损坏/键越界 → 默认构造，不抛异常 | 单元测试 |
| 3 | 6 处构造点全部替换，`grep 'BCRMEngine()'` 生产路径零残留 | grep 验证 |
| 4 | PROP-20260809 回归测试 24/24 + 新增测试全过 | pytest |
| 5 | E2E：进化采纳 0.30 → 新构造引擎实例实际生效 0.30 | 集成测试 |

---

## 五、安全与回滚

- **安全**: 纯读取接线，无新外部依赖；异常全回退默认构造
- **回滚**: git revert 单 commit 即可，config.json 不受影响
- **风险评级**: 低（默认回退保证行为不变；唯一行为变化 = 进化采纳值真正生效，这正是提案目的）

---

## 六、状态流转记录

| 时间 (UTC) | 状态 | 说明 |
|:---|:---|:---|
| 2026-08-09 02:10 | `pending_approval` | D 链调研完成，提案创建，提交飞书审批（trading 类，人工审批） |
