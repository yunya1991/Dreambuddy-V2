---
name: dream-tdd-dev-workflow
description: "Orchestrates TDD cycle: need analysis → RED (failing test) → GREEN (minimal impl) → REFACTOR → hermes reflection. Invoke for TDD dev, red-green-refactor."
version: 1.0.0
created: 2026-09-21
updated: 2026-09-21
license: Internal
status: active
category: orchestration
triggers: [TDD 开发, 红-绿-重构, red-green-refactor]
depends_on: [dream-contradiction-theory, tee-red-green-progress, test-driven-development]
provides: [tdd-orchestration]
cognitive_links: [VM-1790001702811-24bffe86, VM-1790003713722-e05028a2]
---

# Dream TDD Dev Workflow — TDD 开发工作流 SKILL

> 把"需求分析 → RED（写失败测试）→ GREEN（最简实现）→ REFACTOR（重构优化）→ hermes 反思"的 TDD 开发循环固化为可复用编排，元 SKILL 为 `dream-qwen-eval-collab`，结尾执行 hermes 反思决定是否再衍生新 SKILL。

> **双位置存储**：本 SKILL 同时存在于：
> - `.trae/skills/dream-tdd-dev-workflow/SKILL.md`（TRAE 调用入口）
> - `1-ARCHITECTURE/skills/dream-tdd-dev-workflow/SKILL.md`（项目级索引发现，本文件）

---

## 一、何时调用（触发条件）

满足以下任一条件即应调用本 SKILL：

1. **TDD 开发**：用户要求用测试驱动方式开发一个新模块/新功能
   - 触发词：「TDD 开发」「红-绿-重构」「red-green-refactor」
2. **新模块落地**：需要新增一个独立模块（不改动现有模块，符合零回归 + HC-1a）
3. **spec 落地**：`dream-qwen-eval-collab` 步骤 4 产出的 spec 需要进入实现阶段
4. **hermes 反思**：开发结束后，用户希望反思是否形成/衍生新 SKILL
   - 触发词：「形成 SKILL」「反思」「hermes」「可复用经验」

**与 `tee-red-green-progress` 的边界**：`tee-red-green-progress` 是 TEE 任务的 N→N+1 红绿进度工具（聚焦"写 RED 断言 ModuleNotFoundError → 跑出 red count → 实现 → 达 green"）；本 SKILL 是更高层的 5 步编排，把需求分析、REFACTOR、hermes 反思纳入。本 SKILL 步骤 2/3 直接复用 `tee-red-green-progress` 的红绿机制。

---

## 二、5 步标准流程

### 步骤 1：需求分析（验收标准 + 边界条件）

**输入**：用户功能需求文本（或来自 `dream-qwen-eval-collab` 的 spec）

**处理**：
1. 复用 `dream-contradiction-theory`（A0 矛盾分析）识别核心矛盾：新功能与现有系统的张力
2. 拆解验收标准（可量化、可测试）
3. 列出边界条件（空输入/非法输入/并发/超时/FAIL-OPEN）
4. 识别工程约束（HC-1a 不改核心 / HC-9 不做交易决策 / FAIL-OPEN / 零回归 / 模块化开关）
5. 确定新模块路径与接口签名（不改现有模块 = 零回归前提）

**输出**：TDD 任务包（YAML）

```yaml
功能: <一句话陈述>
核心矛盾: <新功能与现有系统的张力>
验收标准:
  - <可量化判据 1>
  - <可量化判据 2>
边界条件:
  - 空输入: <期望行为>
  - 非法输入: <期望行为，通常 FAIL-OPEN>
  - 并发: <期望行为>
  - 超时: <期望行为>
工程约束:
  - HC-1a: 不改 DreamOs 核心模块
  - HC-9: 只做<域>，不做交易决策
  - FAIL-OPEN: 异常 → <安全默认>
  - 零回归: 独立新模块，不改现有模块
新模块路径: <file_path>
接口签名: <函数/类签名>
```

### 步骤 2：RED — 写失败测试

**输入**：TDD 任务包

**处理**（复用 `tee-red-green-progress` 红绿机制 + `test-driven-development`）：
1. 先写测试文件，断言新模块 `ModuleNotFoundError`（TEE Task N→N+1 标准起手）
2. 再写具体行为测试（每个验收标准/边界条件至少 1 个测试用例）
3. 运行测试，确认 **RED**（失败计数 = 预期，且失败原因正确）

**RED 示例**（Python，新模块 `risk_expression.py`）：

```python
# test_risk_expression.py
import pytest

def test_module_importable():
    # RED 起手：模块尚未创建，应抛 ModuleNotFoundError
    with pytest.raises(ModuleNotFoundError):
        from dreambuddy.risk_expression import RiskExpression  # noqa

def test_approve_is_executable():
    from dreambuddy.risk_expression import RiskExpression
    v = RiskExpression.approve()
    assert v.is_executable() is True

def test_reject_is_not_executable():
    from dreambuddy.risk_expression import RiskExpression
    v = RiskExpression.reject()
    assert v.is_executable() is False

def test_reduce_size_keeps_half():
    from dreambuddy.risk_expression import RiskExpression
    v = RiskExpression.reduce_size(reduced_size_pct=0.5)
    assert v.effective_size_multiplier() == 0.5

def test_invalid_verdict_fails_open():
    from dreambuddy.risk_expression import RiskExpression
    # FAIL-OPEN：非法 verdict → None
    assert RiskExpression.from_dict({"verdict": "bogus"}) is None
```

**运行确认 RED**：

```bash
pytest test_risk_expression.py -v
# 预期：5 failed（第 1 个 ModuleNotFoundError，其余因模块缺失连锁失败）
# red count = 5，与预期一致 → RED 确认
```

**已知坑**（必须遵守）：

| 坑 | 现象 | 解决 |
|----|------|------|
| RED 失败原因不对 | 测试因语法错误失败而非断言失败 | 先修测试语法，再确认 RED 是"断言失败" |
| 模块路径漂移 | 测试 import 路径与实际不符 | 在任务包里固定 `<file_path>`，测试与实现路径一致 |
| HC-1b 假阳性 | `from dreambuddy` 子串匹配 `dreambuddy_dal` | 用词边界正则排除，见记忆 `VM-1789621219116-d9c6395b` |
| 模块级常量 import 时求值 | `homedir()` 在 import 时求值，测试 beforeEach 设 HOME 太晚 | 改为惰性函数求值，见记忆 `VM-1789621219116-d9c6395b` |

**输出**：测试文件路径 + RED 运行日志（含 red count）

### 步骤 3：GREEN — 最简实现通过测试

**输入**：测试文件 + TDD 任务包

**处理**（复用 `tee-red-green-progress`）：
1. 写**最简**实现（不过度设计，不提前抽象）
2. 逐步让测试通过（一次一个，或一次性全绿，按任务复杂度选）
3. 运行测试，确认 **GREEN**（全部通过）
4. 跑全量回归，确认 **零回归**（原有测试全绿）

**GREEN 示例**（对应步骤 2 的 RED）：

```python
# risk_expression.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

RISK_VERDICTS = frozenset({
    "approve", "reject", "conditional_approve",
    "reduce_size", "delay", "require_hedge",
})

@dataclass(frozen=True)
class RiskExpression:
    verdict: str
    condition: Optional[str] = None
    reduced_size_pct: Optional[float] = None
    delay_seconds: Optional[float] = None
    hedge_requirement: Optional[str] = None
    confidence: Optional[float] = None
    reasoning: Optional[str] = None

    def is_executable(self) -> bool:
        return self.verdict in {"approve", "conditional_approve", "reduce_size", "require_hedge"}

    def effective_size_multiplier(self) -> float:
        if self.verdict == "reduce_size":
            return self.reduced_size_pct or 0.0
        if self.verdict in {"reject", "delay"}:
            return 0.0
        return 1.0

    @classmethod
    def approve(cls): return cls(verdict="approve")
    @classmethod
    def reject(cls): return cls(verdict="reject")
    @classmethod
    def reduce_size(cls, reduced_size_pct): return cls(verdict="reduce_size", reduced_size_pct=reduced_size_pct)

    @classmethod
    def from_dict(cls, d) -> Optional["RiskExpression"]:
        v = d.get("verdict")
        if v not in RISK_VERDICTS:
            return None  # FAIL-OPEN
        return cls(verdict=v)
```

**运行确认 GREEN + 零回归**：

```bash
pytest test_risk_expression.py -v          # 预期：5 passed → GREEN
pytest -q                                  # 全量回归，预期 <原 N> passed，0 failed → 零回归
```

**输出**：实现文件路径 + GREEN 日志 + 全量回归日志

### 步骤 4：REFACTOR — 重构优化，保持测试绿

**输入**：GREEN 实现 + 测试文件

**处理**：
1. 识别坏味道（重复/长函数/魔法数字/命名不清）
2. 小步重构（每次一个改动，每次跑测试确认仍绿）
3. 提取公共逻辑、引入工厂、消除重复
4. 不改公共接口（测试不变 = 接口契约不变）

**REFACTOR 示例**（在步骤 3 GREEN 基础上）：

```python
# 重构：把 6 个 verdict 的可执行性/缩放逻辑从 if-else 改为表驱动
# 好处：新增 verdict 只改表不改方法

_EXECUTABLE_VERDICTS = frozenset({"approve", "conditional_approve", "reduce_size", "require_hedge"})

@dataclass(frozen=True)
class RiskExpression:
    verdict: str
    # ... 其余字段不变

    def is_executable(self) -> bool:
        return self.verdict in _EXECUTABLE_VERDICTS  # 表驱动，替代 if-else

    def effective_size_multiplier(self) -> float:
        if self.verdict == "reduce_size":
            return self.reduced_size_pct or 0.0
        return 0.0 if self.verdict in {"reject", "delay"} else 1.0
```

**重构后确认仍绿**：

```bash
pytest test_risk_expression.py -q   # 预期：5 passed → 重构未破坏行为
pytest -q                           # 全量回归仍零回归
```

**REFACTOR 红线**（不可违反）：
- 不改测试（除非测试本身错了，且需说明）
- 不改公共接口签名
- 每次小步重构后立即跑测试
- 不引入未在 RED 阶段约定的功能（防过度设计）

**输出**：重构后的实现 + 仍绿的测试日志

### 步骤 5：hermes 反思

**输入**：GREEN 实现 + 重构后的测试日志

**处理**：
1. 输出模块路径 + 测试路径给用户审阅
2. 用户确认后，调用认知系统 `record` 记录经验
3. **hermes 反思**：评估本次流程是否值得形成/衍生新 SKILL（决策树见第五节）
4. 若模块需要进一步评估/送千问，转 `dream-qwen-eval-collab`

**record 模板**：

```
record(
  content="[TDD开发] <功能一句话> | RED <N> → GREEN <N> | 全量回归 <原+N> passed 0 failed | 模块: <路径>",
  quality_level="B",
  tags="TDD开发,协作流程,红绿重构,hermes反思,可复用,<域标签>"
)
```

---

## 三、输入输出契约

| 阶段 | 输入 | 输出 |
|------|------|------|
| 步骤 1 | 功能需求 / spec | TDD 任务包（YAML，含验收标准+边界+约束） |
| 步骤 2 | TDD 任务包 | 测试文件 + RED 日志（red count） |
| 步骤 3 | 测试文件 + 任务包 | 实现文件 + GREEN 日志 + 零回归日志 |
| 步骤 4 | GREEN 实现 + 测试 | 重构后实现 + 仍绿测试日志 |
| 步骤 5 | 重构后实现 | 用户审阅 + 认知 record + 可选新 SKILL |

---

## 四、相关 SKILL 与文档

| 类型 | 名称 | 用途 |
|------|------|------|
| 元 | `dream-qwen-eval-collab` | 本 SKILL 的元编排，hermes 反思决策树来源 |
| 上游 | `dream-contradiction-theory` | A0 矛盾分析（识别新功能与现有系统的张力） |
| 工具 | `tee-red-green-progress` | TEE Task N→N+1 红绿进度机制（RED/GREEN 直接复用） |
| 工具 | `test-driven-development` | 通用 TDD 方法论（RED/GREEN/REFACTOR 纪律） |
| 上游 | `dream-qwen-eval-collab` | spec 来源（步骤 1 可选输入） |
| 下游 | `dream-bugfix-workflow` | 模块上线后若出 bug，转 bugfix 流程 |
| 元 | `skill-creator` | hermes 反思后创建新 SKILL |
| 认知 | `recall`/`record`/`verify` | 认知闭环 |

---

## 五、hermes 反思决策树

> 引用元 SKILL `dream-qwen-eval-collab` 第五节决策树（来源记忆 `VM-1790001702811-24bffe86`，B 级硬约束）。

```
本次 TDD 开发流程是否值得形成/衍生 SKILL？
├── 是（满足以下任一）：
│   ├── 流程被复用 ≥ 2 次
│   ├── 涉及多步编排（≥ 3 步，本 SKILL 5 步满足）
│   ├── 涉及新域的 TDD 模式（如 async/并发/外部依赖 mock 模式沉淀）
│   └── 用户明确要求「形成 SKILL」
│   → 调用 skill-creator 创建新 SKILL
│   → record 经验，tags 含「SKILL,hermes反思」
│
└── 否（满足以下全部）：
    ├── 一次性小改动
    ├── 无新测试模式沉淀
    └── 无复用价值
    → 仅 record 经验
    → tags 不含「SKILL」
```

---

## 六、认知闭环（recall + record + verify）

**任务开始前**（硬约束，不可跳过）：

```
recall(context="TDD 开发 <功能关键词>", top_k=5, min_quality="C")
```

**任务完成后**：

```
record(content="<本次 TDD 摘要> | RED <N> → GREEN <N> | 回归 <原+N> passed | 模块: <路径>",
       quality_level="B",
       tags="TDD开发,协作流程,红绿重构,hermes反思,可复用,<域标签>")

# 如已验证某条已有记忆
verify(memory_id="VM-xxx", success=true)
```

**已沉淀的认知记忆**（可 recall 复用）：

| Memory ID | 等级 | 内容摘要 |
|-----------|------|---------|
| `VM-1790001702811-24bffe86` | B | hermes 反思决策树硬约束（4 延伸 SKILL 配套） |
| `VM-1789621219116-d9c6395b` | B | E2 验收经验（HC-1b 假阳性 / IPC 延迟 / HOME 重定向 / 惰性求值） |
| `VM-1789993099772-45aec081` | B | 风控表达增强 TDD 落地（独立模块零回归 / FAIL-OPEN / verdict 命名空间） |
| 本 SKILL 创建后新增 | B | TDD 开发落地经验，tags 含「SKILL,TDD开发,hermes反思」 |

---

## 七、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-09-21 | 初始版本，5 步流程 + RED/GREEN/REFACTOR 三阶段示例 + hermes 反思决策树 |
