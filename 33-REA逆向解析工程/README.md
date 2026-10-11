# 33-REA逆向解析工程

> **Reverse Engineer Anything** — dreambuddy 的工程逆向解析子系统
> 借鉴 [morluto/rea](https://github.com/morluto/rea) 的 Evidence-First 设计哲学

## 定位

给 Agent 一个目标工程路径/URL，逆向其架构、调用链、关键算法实现，输出**带证据**的分析报告，辅助"理解原理→自己重写"。

## 核心原则

- **Evidence-First**：每条结论必须带证据（来源+行号+置信度+局限）
- **四层事实分级**：observation → derivation → inference → unknown
- **本地只读**：静态 AST 分析，不执行目标程序
- **轻量可控**：Python 原生实现，零重型依赖

## 快速开始

```python
from core import PythonAnalyzer, Evidence

analyzer = PythonAnalyzer()
result = analyzer.analyze("/path/to/your/project")
print(result.summary)
for e in result.evidence:
    print(f"[{e.level}] {e.result} (confidence={e.confidence})")
```

## 能力

### P0 核心（已完成 / 待实现）

| 能力 | 状态 |
|---|---|
| Python AST 分析（模块/类/函数/依赖） | 待实现 |
| 依赖图构建 + 环检测 | 待实现 |
| 调用链追踪 | 待实现 |
| Git 历史溯源 | 待实现 |
| morluto/rea MCP 集成（二进制） | 待实现 |
| GitHub API 集成 | 待实现 |

### PoE 扩展层（v1.0 已落地 — commit 16826f4eb1）

| 能力 | 状态 |
|---|---|
| ★ PoE 审计门禁（poe_score 计算 + 三级门禁） | ✅ 已完成（ai_audit.py, 9 tests） |
| 架构模式识别器（MVC/Event-Driven/Pipeline 等） | ✅ 已完成（architecture_pattern_detector.py, 6 tests） |
| 设计决策还原（ADR 风格 + 替代方案推断） | ✅ 已完成（design_decision_recovery.py, 6 tests） |
| 演化叙事生成（架构成长史 + 重构动机） | ✅ 已完成（evolution_narrative.py, 6 tests） |
| 方法论抽象层（跨项目聚类 + 通用解法蒸馏） | ✅ 已完成（methodology_abstraction.py, 6 tests） |
| AI 产出审计闭环（证明链完整度 + 认知债务） | ✅ 已完成（ai_audit.py + cognitive_integration.py, 6+9 tests） |
| DSH 3 新节点（audit/recover_decisions/narrative） | ✅ 已完成（dsh_nodes.py, 8 tests） |
| 端到端集成测试 | ✅ 已完成（test_integration_poe.py, 5 tests） |
| Agent 信用评分（任务难度加权 + slash 机制） | 设计完成（待后续迭代） |
| 创新性快速通道（experimental 标记） | 设计完成（待后续迭代） |

## 目录结构

```
33-REA逆向解析工程/
├── SPEC.md                          # 核心设计规格
├── README.md                        # 本文档
├── DESIGN-PHILOSOPHY-PoE.md         # ★ PoE 设计哲学（顶层协议）v1.1
├── HYPOTHESIS-VERIFICATION-PoE.md   # PoE 关键假设验证 v1.1
├── PEER-REVIEW-PoE.md               # PoE 同行评审报告 v1.0
├── SPEC-工程实践复现器.md            # PoE 工程实践复现器 SPEC v0.3
├── TASKS-工程实践复现器.md           # PoE 实施任务清单 v1.0
├── core/                            # 核心分析层
├── adapters/                        # 外部适配器（REA MCP / GitHub API）
├── prompts/                         # 逆向调查 prompt
└── tests/
```

## 文档

### 核心设计
- [SPEC.md](./SPEC.md) — 完整设计规格（架构、Evidence结构、DSH节点、实施路线）

### ★ PoE（Proof of Engineering）体系
- [DESIGN-PHILOSOPHY-PoE.md](./DESIGN-PHILOSOPHY-PoE.md) — **PoE 设计哲学 v1.1**：AI 编码时代的工程证明协议（类比区块链 POW/POS，五大系统协同）
- [HYPOTHESIS-VERIFICATION-PoE.md](./HYPOTHESIS-VERIFICATION-PoE.md) — PoE 关键假设验证 v1.1（w1 权重 + 门禁阈值可证伪性分析）
- [PEER-REVIEW-PoE.md](./PEER-REVIEW-PoE.md) — PoE 同行评审报告 v1.0（四角色 + 7 模式阻断）
- [SPEC-工程实践复现器.md](./SPEC-工程实践复现器.md) — 工程实践复现器 SPEC v0.3（4 方向 + 8 任务）
- [TASKS-工程实践复现器.md](./TASKS-工程实践复现器.md) — 实施任务清单 v1.0

## 参考

- [morluto/rea](https://github.com/morluto/rea) — 灵感来源
