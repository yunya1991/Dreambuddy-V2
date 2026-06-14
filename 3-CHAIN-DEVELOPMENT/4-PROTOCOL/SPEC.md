# Specification: 三链接力协议（方案B）

> **方案选择依据**: D3 三景推演结论 — 方案B（接力协议）是方法论深度与可执行约束的最佳平衡点。
> **2小时工作量**，预期 70% 跳步拦截率，可独立回滚。

---

## 1. 背景与目标

### 1.1 问题陈述

三链开发架构当前存在四个问题：
1. **工具隔离是声明而非约束** — README 写"调研阶段只读"，但没有物理阻止执行阶段工具
2. **缺少接力协议** — 没有状态文件做阶段追踪，AI 跳过了哪一步无从追溯
3. **矛盾论止于表面** — D1-D4 没有强制检查机制，跳步不被记录
4. **Z/E系列偏薄** — 但这不是 Spec 范围（本次只解决约束层）

### 1.2 为什么要做

所有方法论文档、检查清单、指导原则的共同死穴：AI 可以选择不遵守。
方案B 的核心不是"写更多文档教AI怎么做"，而是**提供一个物理约束**——让AI读状态文件来判断当前该做什么，不能让AI自己决定。

### 1.3 成功标准（可量化）

| # | 标准 | 验收方式 |
|:---|:---|---|
| 1 | 状态文件在 D 系列/Z 系列每次接力时自动更新 | 跑一次完整接力看到 chain_state.json 记录每个阶段 |
| 2 | 未完成前置阶段时，调用 `chain_check()` 返回拒绝 | 测试：D1 未完成时尝试 D2 → guard 拒绝 |
| 3 | 用户指定跳过时，`chain_override()` 在状态文件留下 `override: true + reason` | 查看 override 记录 |
| 4 | 新的 `4-PROTOCOL/` + `scripts/` 目录完成 | 文件存在 |
| 5 | 本次 D1→D2→D3→D4 接力已在状态文件中完整记录 | chain_state.json phases[0..3] 全部 completed+approved |

### 1.4 不做范围

- 不把三链做成 Hermes cron skill（方案C范围）
- 不动现有 A系列 cron 排程
- 不动 2-KNOWLEDGE/ 和 6-TRADING/ 任何内容
- 不改已有的 3-CHAIN-DEVELOPMENT/README.md（只补充新增文件引用）

---

## 2. 方案设计

### 2.1 核心方案（接力协议）

```
状态文件 (chain_state.json)
    ↓
Guard 脚本 (chain_guard.py)
    ├── chain_init(scope)            ← 启动新任务时初始化
    ├── chain_check(from_phase, to)  ← 每次跳转前检查合法性
    ├── chain_transition(from, to)   ← 通过后记录跳转
    └── chain_override(from, to, reason) ← 用户指定跳过时记录
    ↓
协议文档 (PROTOCOL.md)
    └── 详细的接力规则和用法说明
```

### 2.2 架构关系

```
current session (我)
    │
    ├── 进入新阶段前 → 调 chain_check() → ❌ 拒绝则停 → ✅ 通过则继续
    ├── 阶段产出后 → 等用户确认 → 调 chain_transition() → 看下一阶段
    ├── 用户说跳过 → 调 chain_override() → 记录理由 → 看下一阶段
    │
    └── 状态写入 → chain_state.json（唯一权威来源）
                     ↓
              3-CHAIN-DEVELOPMENT/4-PROTOCOL/PROTOCOL.md（文档解释）
```

### 2.3 状态文件结构

```json
{
  "scope": "任务描述",
  "created_at": "ISO时间戳",
  "modified_at": "ISO时间戳",
  "current_phase": null,
  "phases": [
    {
      "id": "d1",
      "name": "D1 深度调研",
      "methodology": "四准则调研法",
      "status": "pending | in_progress | completed | skipped",
      "approval": "pending | approved | rejected",
      "output_ref": "产出文件或摘要",
      "completed_at": null,
      "step_count": 0
    }
  ],
  "relay_history": [
    {
      "from": "d1",
      "to": "d2",
      "trigger": "chain_transition | chain_override",
      "reason": null,
      "at": "ISO时间戳"
    }
  ]
}
```

### 2.4 Guard 函数契约

```python
# chain_guard.py — 纯函数，不依赖外部状态，不加全局变量

def chain_init(scope: str) -> dict:
    """创建状态文件。scope = 本次任务的描述"""

def chain_check(state: dict, from_phase: str, to_phase: str) -> dict:
    """检查跳转是否合法。
    返回: {"allowed": True/False, "reason": "..."}
    规则:
    - from_phase 必须存在且状态为 completed 或 skipped
    - to_phase 必须存在且状态为 pending
    - 不允许从 D1 跳到 Z1（跨链必须过 D4→Z1）
    """

def chain_transition(state: dict, from_phase: str, to_phase: str) -> dict:
    """执行合法跳转。更新状态文件。
    返回: 更新后的 state
    """

def chain_override(state: dict, from_phase: str, to_phase: str, reason: str) -> dict:
    """用户指定跳过。记录 reason，不检查合法性。
    返回: 更新后的 state
    """

def chain_status(state_path: str = None) -> dict:
    """读取当前状态。无状态文件则返回空。"""
```

---

## 3. 实施路径

### Phase 1: Guard 脚本（1h）
- 创建 `scripts/chain_guard.py`
- 实现 5 个函数：init / check / transition / override / status
- 状态文件路径: `~/.workbuddy/memory/chain_state.json`（复用已有目录）

### Phase 2: 协议文档（0.5h）
- 创建 `4-PROTOCOL/PROTOCOL.md`
- 内容包括：用途、规则、接力表、用法示例、常见问题

### Phase 3: README 引用（0.5h）
- 在 `3-CHAIN-DEVELOPMENT/README.md` 中增加协议章节引用
- 更新 `3-CHAIN-DEVELOPMENT/1-RESEARCH/README.md` 增加接力协议约束说明

### Phase 4: 落地验证（0.5h）
- 用当前 D1→D2→D3→D4 这轮任务跑一次完整链
- 确认状态文件正确记录了四个阶段的接力

**预估总时间: 2.5h**

---

## 4. 验收标准

### 4.1 功能验收

| # | 场景 | 操作 | 预期 |
|:---|:---|---|:---:|
| TC1 | 初始化 | 调 `chain_init("测试任务")` | 状态文件创建，scope 正确 |
| TC2 | 合法跳转 | D1 completed → 调 chain_check 检查 D1→D2 | `allowed: true` |
| TC3 | 非法跳转 | D1 状态 pending → 调 chain_check 检查 D1→D2 | `allowed: false` |
| TC4 | 跨链跳转 | D1 完成 → 调 chain_check 检查 D1→Z1 | `allowed: false`（需要先D4） |
| TC5 | 正常跳转 | chain_transition(D1→D2) | D1 标记 completed, D2 标记 in_progress |
| TC6 | 用户跳过 | chain_override(D1→D3, "用户说跳过") | D1 skipped, D3 in_progress, reason 记录 |
| TC7 | 状态查询 | chain_status() | 返回完整的 phases 数组 |

### 4.2 非功能验收

- Guard 脚本是纯 Python，不依赖 pip 包（只用 json, os, datetime）
- 状态文件是 JSON 格式，可用 cat/cursor/jq 直接查看
- guard 函数的输入输出都是 dict，无副作用（除文件写入本身）

### 4.3 排除清单

- 不做并发安全（单session操作）
- 不支持多个任务并行状态
- 不支持定时器自动触发跳转
