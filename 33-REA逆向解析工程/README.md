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

| 能力 | 状态 |
|---|---|
| Python AST 分析（模块/类/函数/依赖） | 待实现 |
| 依赖图构建 + 环检测 | 待实现 |
| 调用链追踪 | 待实现 |
| Git 历史溯源 | 待实现 |
| morluto/rea MCP 集成（二进制） | 待实现 |
| GitHub API 集成 | 待实现 |

## 目录结构

```
33-REA逆向解析工程/
├── SPEC.md              # 完整设计规格
├── README.md            # 本文档
├── core/                # 核心分析层
├── adapters/            # 外部适配器（REA MCP / GitHub API）
├── prompts/             # 逆向调查 prompt
└── tests/
```

## 文档

- [SPEC.md](./SPEC.md) — 完整设计规格（架构、Evidence结构、DSH节点、实施路线）

## 参考

- [morluto/rea](https://github.com/morluto/rea) — 灵感来源
