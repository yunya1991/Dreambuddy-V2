# SPEC — 33-REA逆向解析工程

> **版本**: v0.1 (2026-10-10)
> **状态**: 草案（待评审）
> **灵感来源**: [morluto/rea](https://github.com/morluto/rea) — Reverse Engineer Anything
> **定位**: dreambuddy 的工程逆向解析子系统，开发时借鉴其他工程项目的强大工具

---

## 0. 文档定位

本文档定义 **33-REA逆向解析工程** 的完整设计规格。它不是 morluto/rea 的复刻，而是借鉴其 **Evidence-First** 设计哲学，为 dreambuddy 构建一个轻量、可控、与现有技术栈（Python）一致的逆向工程能力。

核心价值：**给 Agent 一个目标工程路径/URL，逆向其架构、调用链、关键算法实现，输出带证据的分析报告，辅助"理解原理→自己重写"。**

---

## 1. 背景与动机

### 1.1 问题

dreambuddy 开发过程中频繁遇到以下需求：
- 看到某开源项目的功能设计巧妙，想知道实现原理（如 freqtrade 的策略框架、vectorbt 的回测引擎）
- 理解复杂遗留代码的设计意图（dreambuddy 自身历史代码）
- 审计第三方依赖的实际调用路径和安全风险
- 竞品功能借鉴：理解某交易所/策略平台的功能实现

### 1.2 现有方案的不足

| 方案 | 不足 |
|---|---|
| 人工读源码 | 效率低，大型项目难以快速定位关键路径 |
| LLM 直接分析 | 无证据、易幻觉、不可追溯 |
| morluto/rea | 依赖 Node 22+ + Hopper/Ghidra，对 Python 项目过重 |

### 1.3 设计目标

1. **Evidence-First**：每条结论必须带证据（来源+行号+置信度+局限），禁止无证据猜测
2. **轻量可控**：Python 原生实现，零重型依赖，AST 分析即可覆盖 80% 场景
3. **DSH 集成**：作为 S33 节点接入 DreamOS，支持 Agent 调用
4. **可扩展**：适配器模式，可集成 morluto/rea（二进制分析）和 GitHub API（远程仓库）

---

## 2. 核心设计哲学（借鉴 REA）

### 2.1 Evidence-First（证据优先）

> "盲猜的逆向结论比没有结论更危险。" — morluto/rea

每条分析结论必须包含：
- **provenance**：来源（文件路径、行号、引擎）
- **confidence**：置信度（0.0-1.0 连续值）
- **known_gaps**：已知局限（明确标注"不知道什么"）
- **level**：事实分级（observation → derivation → inference → unknown）

### 2.2 四层事实分级

| 层级 | 含义 | 示例 |
|---|---|---|
| **observation** | 直接观察到的事实 | "文件 A.py 第 15 行 import 了 requests" |
| **derivation** | 从观察推导的结论 | "A.py 依赖 requests 库" |
| **inference** | 基于推导的推断 | "A.py 可能发起 HTTP 请求" |
| **unknown** | 已知的未知 | "无法确定 A.py 的 HTTP 请求目标 URL" |

### 2.3 Provider 确定性选择

多分析器支持同一目标时：
- 不自动选择，返回 `ambiguous` + 候选列表
- 显式选择后，会话内不摇摆
- 运行时失败不自动 fallback 到次优分析器（避免静默降级）

### 2.4 本地优先 + 只读

- 所有分析在本地运行，不上传目标代码
- 静态分析不执行目标程序（Python AST / TS AST）
- git 操作只读（log/blame），不修改仓库

---

## 3. 架构设计

### 3.1 分层架构（洋葱模型）

```
┌─────────────────────────────────────────────────────────┐
│                   DSH 接入层                              │
│         S33_rea_analyze / S33_rea_trace / S33_compare    │
├─────────────────────────────────────────────────────────┤
│                   应用编排层                              │
│         逆向调查工作流（定位→追踪→还原→标注）              │
├─────────────────────────────────────────────────────────┤
│                   核心分析层 (core/)                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐ │
│  │ Python   │ │ TS/JS    │ │ 依赖图   │ │ 调用链追踪 │ │
│  │ Analyzer │ │ Analyzer │ │          │ │            │ │
│  └──────────┘ └──────────┘ └──────────┘ └────────────┘ │
│  ┌──────────┐ ┌──────────────────────────────────────┐ │
│  │ Git历史  │ │ Evidence 数据结构（4层事实分级）      │ │
│  └──────────┘ └──────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────┤
│                   适配器层 (adapters/)                    │
│  ┌────────────────┐ ┌─────────────────────────────────┐│
│  │ REA MCP 适配器 │ │ GitHub API 适配器                ││
│  │ (二进制/重型)   │ │ (远程仓库元数据)                  ││
│  └────────────────┘ └─────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

**依赖方向**：DSH → 应用编排 → 核心分析 → 适配器。引擎协议不进核心层。

### 3.2 目录结构

```
33-REA逆向解析工程/
├── SPEC.md                          # 本文档
├── README.md                        # 项目定位+快速开始
├── dsh_nodes.py                     # DSH S33 节点（待实现）
├── core/                            # 核心分析层
│   ├── __init__.py
│   ├── evidence.py                  # Evidence 数据结构（已实现）
│   ├── analyzer_base.py             # 分析器基类（已实现）
│   ├── python_analyzer.py           # Python AST 分析
│   ├── ts_analyzer.py               # TS/JS AST 分析（已实现）
│   ├── dependency_graph.py          # 依赖图构建+环检测
│   ├── call_chain_tracer.py         # 调用链追踪
│   ├── git_history.py               # git 历史溯源
│   ├── algorithm_reducer.py         # 算法还原（已实现）
│   ├── dependency_audit.py          # 依赖审计（已实现）
│   ├── coverage_analyzer.py         # 测试覆盖分析（已实现）
│   ├── investigation_workflow.py    # 逆向调查工作流（已实现）
│   └── cognitive_integration.py     # 认知记忆集成（已实现）
├── adapters/                        # 适配器层
│   ├── __init__.py
│   ├── rea_mcp_adapter.py           # morluto/rea MCP 集成
│   └── github_api_adapter.py        # GitHub API
├── prompts/
│   └── investigation_prompt.md      # 逆向调查 prompt
└── tests/
    └── __init__.py
```

---

## 4. Evidence 数据结构

### 4.1 Evidence 定义

```python
@dataclass
class Evidence:
    evidence_id: str                    # ev_<64 hex>
    result: Any                         # 规范化结果
    level: EvidenceLevel                # observation/derivation/inference/unknown
    provenance: dict[str, Any]          # 来源：{file, line, engine, ...}
    confidence: float                   # 0.0 - 1.0
    known_gaps: list[str]               # 已知局限
    observations: list[dict[str, Any]]  # 支撑观察
    created_at: int                     # ms 时间戳
```

### 4.2 AnalyzeResult 容器

```python
@dataclass
class AnalyzeResult:
    target: str              # 分析目标
    summary: str             # 人类可读摘要
    evidence: list[Evidence] # 证据列表
    raw: dict[str, Any]      # 原始结构化数据
```

### 4.3 输出示例

```json
{
  "target": "/path/to/project",
  "summary": "该项目采用 MVC 架构，入口为 main.py，核心逻辑在 core/service.py",
  "evidence": [
    {
      "evidence_id": "ev_a1b2c3...",
      "result": "main.py 是程序入口",
      "level": "observation",
      "provenance": {"file": "main.py", "line": 1, "engine": "python_ast"},
      "confidence": 1.0,
      "known_gaps": [],
      "observations": [{"type": "if_name_main", "line": 45}]
    },
    {
      "evidence_id": "ev_d4e5f6...",
      "result": "核心业务逻辑在 core/service.py 的 UserService 类",
      "level": "derivation",
      "provenance": {"file": "main.py", "line": 12, "engine": "python_ast"},
      "confidence": 0.8,
      "known_gaps": ["未分析 UserService 的方法调用链"],
      "observations": [{"type": "import", "from": "core.service", "import": "UserService"}]
    }
  ]
}
```

---

## 5. 核心能力矩阵

| 能力 | 实现方式 | 证据来源 | 优先级 |
|---|---|---|---|
| 架构分层 | AST 解析 import 关系 + 目录结构 | 模块依赖图 | P0 |
| 调用链追踪 | AST 函数调用图 | 调用路径+行号 | P0 |
| 模块/类/函数清单 | AST 遍历 | 定义位置+签名 | P0 |
| 依赖关系 | import 语句解析 | 被依赖模块+位置 | P0 |
| Git 历史溯源 | git log/blame | 作者+时间+变更次数 | P1 |
| 关键算法还原 | AST 模式匹配 + 伪代码生成 | 代码片段+推导逻辑 | P1 |
| 依赖版本审计 | package.json/pyproject.toml | 声明版本+lock版本 | P1 |
| 测试覆盖分析 | pytest/vitest 覆盖率 | 覆盖率+未覆盖行 | P2 |
| 二进制反编译 | morluto/rea MCP（Hopper/Ghidra） | 伪代码+汇编 | P2 |
| 远程仓库分析 | GitHub API | 仓库元数据+目录树 | P2 |

---

## 6. DSH 节点设计

参照 [25-用户策略生成系统/dsh_nodes.py](../25-用户策略生成系统/dsh_nodes.py) 的模式，提供三个 DSH 节点：

### 6.1 S33_rea_analyze

**用途**：整体架构分析

```python
def S33_rea_analyze(target: str, scope: str = "architecture") -> dict:
    """
    Args:
        target: 本地路径或 GitHub URL
        scope: architecture / modules / dependencies / full
    Returns:
        AnalyzeResult.to_dict()
    """
```

### 6.2 S33_rea_trace

**用途**：功能追踪 — 某功能是怎么实现的

```python
def S33_rea_trace(target: str, feature: str, entry: str | None = None) -> dict:
    """
    Args:
        target: 本地路径或 GitHub URL
        feature: 要追踪的功能描述（自然语言）
        entry: 可选入口函数/类名
    Returns:
        {feature, call_chain, evidence, known_gaps}
    """
```

### 6.3 S33_compare

**用途**：两工程对比

```python
def S33_rea_compare(target_a: str, target_b: str, feature: str) -> dict:
    """
    Args:
        target_a / target_b: 两个工程
        feature: 对比的功能
    Returns:
        {common, differences, evidence_a, evidence_b}
    """
```

### 6.3 调用契约

```json
// DSH stdin NDJSON
{"method": "s33_rea_analyze", "params": {"target": "/path/to/proj", "scope": "architecture"}}
{"method": "s33_rea_trace", "params": {"target": "/path/to/proj", "feature": "用户登录"}}
```

---

## 7. 集成方案

### 7.1 DSH 接入

1. 在 `dsh_nodes.py` 中实现 S33 节点
2. 注册到 DSH 节点注册表（参照 25 系统的 `DSH_NODE_REGISTRY`）
3. DreamOS C-Drive Agent 通过 IPC 调用

### 7.2 morluto/rea 集成（可选，P2）

```python
# adapters/rea_mcp_adapter.py
class ReaMcpAdapter:
    def __init__(self, mcp_server_cmd: str = "rea mcp"): ...
    def is_available(self) -> bool: ...
    def analyze_native_binary(self, path: str, provider: str = "auto") -> dict: ...
```

前置条件：Node.js 22+ + `npm install -g rea-agents`

### 7.3 GitHub API 集成（可选，P2）

```python
# adapters/github_api_adapter.py
class GitHubApiAdapter:
    def __init__(self, token: str | None = None): ...
    def get_repo_metadata(self, owner: str, repo: str) -> dict: ...
    def get_directory_tree(self, owner: str, repo: str, path: str = "") -> list[dict]: ...
```

---

## 8. 实施路线图

### P0 — 核心骨架（1-2天）

- [x] 目录结构 + Evidence 数据结构 + 分析器基类
- [x] Python AST 分析器（模块/类/函数清单 + import 依赖）
- [x] 依赖图构建 + 环检测
- [x] 调用链追踪（入口→调用路径）
- [x] 单元测试（Evidence 结构 + Python 分析器）

### P1 — 增强能力（2-3天）

- [x] Git 历史溯源（log/blame）
- [x] 关键算法还原（AST 模式匹配）
- [x] 依赖版本审计
- [x] DSH S33 节点接入
- [x] 集成测试（端到端分析 dreambuddy 自身模块）

### P2 — 扩展集成（3-5天）

- [x] morluto/rea MCP 适配器（二进制分析）
- [x] GitHub API 适配器（远程仓库）
- [x] TS/JS AST 分析器
- [x] 测试覆盖分析

### P3 — 优化与应用（持续）

- [x] 逆向调查工作流编排（定位→追踪→还原→标注）
- [x] 与认知记忆系统集成（分析结果 record 入库）
- [ ] 金融逆向推导应用（见方向3）

---

## 9. 风险与约束

| 风险 | 应对 |
|---|---|
| AST 分析无法处理动态特性（反射、monkey patch） | Evidence 标注 `known_gaps: ["动态调用无法静态解析"]` |
| 大型项目分析性能 | 增量分析 + 结果缓存（snapshot） |
| morluto/rea 依赖 Node 环境 | 设为可选适配器，核心 Python 分析器零依赖 |
| 逆向结果被误用于抄袭 | prompt 强调"理解原理→自己重写"，不直接复制代码 |

---

## 10. 验收标准

### P0 验收

1. Evidence 数据结构：4 层事实分级 + provenance + confidence + known_gaps
2. Python 分析器：能解析任意 Python 项目，输出模块/类/函数清单 + 依赖图
3. 调用链追踪：给定入口函数，能输出完整调用路径（带行号证据）
4. 所有输出带 Evidence，无证据结论禁止输出
5. 单元测试覆盖率 ≥ 80%

### P1 验收

1. Git 溯源：能输出文件的作者、首次/末次提交、变更次数
2. DSH S33 节点可通过 IPC 调用，返回结构化 Evidence
3. 端到端测试：分析 dreambuddy 自身 `dreambuddy_evolution` 模块，输出架构报告

### P2 验收

1. TS/JS 分析器：能解析 .ts/.js 文件，提取 import/class/function/export + Evidence
2. GitHub API 适配器：能获取远程仓库元数据和目录树 + Evidence，网络错误降级为 unknown
3. REA MCP 适配器：is_available() 检测 rea 安装，未安装时降级返回 + Evidence(level=unknown)
4. 测试覆盖分析：能解析 coverage.xml，计算行/分支覆盖率，识别未覆盖行 + Evidence
5. 全部新增测试 + 回归测试零失败（77/77）

### P3 验收

1. 逆向调查工作流：四阶段(定位→追踪→还原→标注)完整执行，每阶段输出 Evidence
2. 认知记忆集成：调查结果格式化为认知记忆内容，输出 record 参数(content + quality_level + tags)
3. DSH S33_rea_investigate 节点：可通过 IPC 调用，返回含 cognitive_record 的结构化结果
4. python_analyzer.py 修复 IfExp.body 类型判断 bug（影响 _extract_functions 方法检测）
5. 全部新增测试 + 回归测试零失败（109/109）

---

## 11. 与 dreambuddy 其他系统的关系

| 系统 | 关系 |
|---|---|
| **认知记忆系统 (4-MEMORY)** | 分析结果可 record 入库，作为"架构记忆" |
| **自进化系统 (23-)** | 方向3：逆向推导用于交易优化 |
| **DreamOS DSH** | S33 节点接入，Agent 可调用 |
| **25-用户策略生成系统** | 参照其 DSH 节点模式 |

---

## 附录 A：REA 设计借鉴清单

| REA 设计 | dreambuddy 落地 |
|---|---|
| Evidence-First | `core/evidence.py` Evidence 数据结构 |
| 4 层事实分级 | `EvidenceLevel` enum |
| Provider 确定性选择 | 分析器选择策略（P1 实现） |
| 洋葱架构 | core/adapters/dsh 分层 |
| Local-only + 只读 | 静态 AST 分析，不执行目标程序 |
| tagged error algebra | 异常处理返回结构化错误（P1） |

## 附录 B：参考资料

- [morluto/rea GitHub](https://github.com/morluto/rea)
- [REA 官网](https://rea.tools/)
- [MCP 协议规范](https://modelcontextprotocol.io/)

---

## 附录 C：关联方向索引（任务跟踪）

> 本工程是 REA 逆向工程思维三方向调研的**方向2（核心工程）**。
> 方向1和方向3在其他目录独立落地，此处建立索引便于跟踪。

### 方向1：根据REA设计优化现有功能（增强任务清单）

REA 的工程设计原则反向应用到 dreambuddy 现有系统。分布在两个目录：

| 子任务 | 落地文档 | 状态 |
|---|---|---|
| 1-1 Evidence-First 增强认知记忆 | [`4-MEMORY/docs/Evidence-First增强任务清单.md`](../../4-MEMORY/docs/Evidence-First增强任务清单.md) | 待实施 |
| 1-2 Provider选择+Ownership+洋葱架构 | [`23-四层闭环自进化交易架构/docs/REA设计增强任务清单.md`](../../23-四层闭环自进化交易架构/docs/REA设计增强任务清单.md) | 待实施 |

**优先级**：方向1 先于 方向2 实施（先增强现有系统，再搭建新工程）。

### 方向3：金融逆向推导子系统

REA 的"从结果反推输入"思维应用到交易优化，作为 23-自进化系统的子 SPEC。

| 子任务 | 落地文档 | 状态 |
|---|---|---|
| 3-1 ReverseDeriver + 精准奖惩 | [`23-四层闭环自进化交易架构/docs/SPEC-金融逆向推导子系统.md`](../../23-四层闭环自进化交易架构/docs/SPEC-金融逆向推导子系统.md) | 待实施 |

**优先级**：方向3 后于 方向2（需先有 33-REA 的 Evidence 结构作为统一证据格式）。

### 三方向执行顺序

```
方向1（增强现有）→ 方向2（33-REA工程）→ 方向3（金融逆向推导）
```

### Evidence 结构统一

三个方向共享同一套 Evidence 数据结构（4层事实分级 + provenance + confidence + known_gaps）：
- 方向1：应用于认知记忆 `record` 工具
- 方向2：应用于工程逆向分析输出
- 方向3：应用于交易逆向推导输出

统一定义在 [`core/evidence.py`](./core/evidence.py)，三个方向复用。
