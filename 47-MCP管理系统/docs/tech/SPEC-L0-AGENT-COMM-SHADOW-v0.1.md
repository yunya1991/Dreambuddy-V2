# SPEC-L0-AGENT-COMM-SHADOW — AgentMail 跨域通信影子验证 SPEC

> **版本**: v0.1 ｜ **日期**: 2026-11-02 ｜ **状态**: 📋 设计草案，影子 Phase 1 启动后实施
> **上游**: [评估报告](../../../../../2-KNOWLEDGE/7-EXTERNAL-RESEARCH/technical/architecture/2026-11-02-跨域Agent通信与REA做梦器范式推广评估.md)（架构评估，本 SPEC 是其影子落地）· [SPEC-L0-DOMAIN-AGENTS v0.2](./SPEC-L0-DOMAIN-AGENTS-v0.1.md)（域内 agent 化蓝图）· [TECH-L0-MCP v0.1](./TECH-L0-MCP-v0.1.md)（壳实现手册）
> **依赖前置**: SPEC-L0-MCP-PACKAGING v0.3 M1 基础（壳层就绪，envelope.data 业务体透传）· M2-M3 部分壳落地（至少有一个跨域场景可观察）· bcrm2 切流**之后**时间窗
> **定位**: 影子验证 = 观察 + 记录 + 评估 + 产出报告，**绝不触发**任何域内 agent 实际行为
> **约束**: 单人维护 · 零 GPU · 零切流 · 影子硬约束 S1/S2/S3（H9 已记录 B 级认知 VM-1793614927363-5f70cc60）

---

## §0 Executive Summary

### 0.1 本 SPEC 回答什么

**AgentMail 影子模式** = 在 MCP 壳（SPEC-L0-MCP-PACKAGING）和域内 agent（SPEC-L0-DOMAIN-AGENTS）之间，插入一层**只观察不行动**的影子路由层。影子层收集跨域 Agent 交互轨迹、评估通信策略质量、产出激活建议报告，但**绝不触发**任何域内 agent 的实际行为。

影子是**激活模式的前置门禁**：激活任何 AgentMail 通信模式之前，必须通过影子验证全部 5 项验收（§6）。

### 0.2 影子做什么 vs 不做什么

| 做什么 | 不做什么 | 硬约束 |
|---|---|---|
| 观察各域 agent 产出的 envelope.data（壳返回体） | 触发域内 agent 执行任何行为 | **S1** |
| 记录跨域 Agent 交互轨迹树（JSON） | 写入 cognitive record / verify | **S1** |
| 匹配预定义的候选通信策略 π | 自动更新策略 π（argmax V 选最优） | 影子阶段**不自动迭代** π |
| 评估通信 V 值（§4） | 干预线上调用链延迟超过 < 1ms 阈值 | **S3** 零资源开销 |
| 产出 markdown 格式的影子报告 | 新增 DB 表 / 进程 / 网络连接 | **S3** |
| trace_id 前缀 `shadow-` 区分线上 | 线上行为零变化（覆盖率/延迟/verify 命中率前后对比一致） | **S2** |

### 0.3 影子与壳/agent 的位置

```
[IDE / DSH / 外部系统]
        │  MCP stdio JSON-RPC
        ▼
┌ MCP 壳 ───────────────────┐
│ envelope.data 业务体透传   │ ← 不变（SPEC-L0-MCP-PACKAGING）
└──────────┬────────────────┘
           │ 壳返回 envelope
           ▼
┌ AgentMailShadow 观察器 ──┐
│ observe(envelope)          │ ← 本 SPEC 要实现的
│ record(trajectory_tree)    │     只观察 + 记录 + 评估
│ evaluate(V(tree, π))       │     绝不触发 agent
│ report(markdown)           │
└──────────┬────────────────┘
           │ 不注入，让 envelope 原样传给 agent
           ▼
┌ 各域内 Agent ─────────────┐
│ 认知 / REA / 评测 / 语义 / 数据 │ ← 不变（SPEC-L0-DOMAIN-AGENTS）
└──────────────────────────┘
```

**关键**：AgentMailShadow 不是拦截器，是**旁路观察器**。壳正常返回 envelope → 影子旁路观察 → envelope 继续传给 agent。零侵入。

---

## §1 影子观察范围（三种通信模式的观察清单）

### 模式 A：事件订阅-触发（Event Subscription）

影子只观察 **envelope.meta 中含特定 event_type 的产出**，匹配预定义候选 π。

| # | 候选事件（观察触发） | 预期订阅关系（影子评估用） | 影子产出 |
|---|---|---|---|
| A1 | 知识检索产出 `event.type="knowledge_retrieval.new_doc"` | → REA agent 订阅 → 触发 s33_rea_analyze | 影子报告"如果触发会对 project_x 跑 s33_rea_analyze" |
| A2 | REA 做梦器产出 `π.V > 0.85`（来自 replay_pool） | → 评测 agent 订阅 → 跑 eval_psi_check + eval_analyze | 影子报告"如果触发会跑 psi_check + eval_analyze，估计 cost=850ms" |
| A3 | 评测反思产出 `reflection.verdict="needs_improvement"` | → 语义 agent 订阅 → 跑 PSI 漂移监控 | 影子报告"如果触发会跑 PSI 漂移监控，估计 cost=150ms" |

### 模式 B：最优路径蒸馏（Dream Path Distillation）

影子观察 **REA 做梦器 replay_pool 中 V>0.85 的策略配置**，用跨域历史轨迹树回放评估。

| # | 策略源 | 回放目标 | 影子产出 |
|---|---|---|---|
| B1 | REA 内部 replay_pool V>0.85 策略 π | 评测域 agent 历史轨迹树（≥ 5 棵） | 影子报告"π 在评测域 V=0.72（REA V=0.85），PoE 信度 0.82" |
| B2 | REA 外部 replay_pool 成熟项目策略 π | 语义域 agent 历史轨迹树（≥ 5 棵） | 影子报告"π 在语义域 V=0.61，known_gaps=2 条" |

### 模式 C：主动反思闭环（Proactive Reflection）

影子观察 **任一域 agent 的 reflection 产出**，判断是否跨域问题。

| # | 反思源 | 预期跨域通知 | 影子产出 |
|---|---|---|---|
| C1 | 评测反思"实体解析漂移"（reflection.verdict="fail", target="semantic"） | → 语义域自动跑 PSI drift | 影子报告"如果触发会跑语义域 PSI drift，估计 cost=200ms" |
| C2 | REA 反思"Python 项目质量低"（reflection.verdict="needs-improvement", target="data"） | → 数据域跑采集质量监控 | 影子报告"如果触发会跑数据采集质量监控，估计 cost=500ms" |

---

## §2 AgentMailShadow 接口设计（最小实现，≤ 300 行 Python）

### 2.1 类定义

```python
class AgentMailShadow:
    """AgentMail 影子观察器 — 只观察 + 记录 + 评估 + 产出报告
    
    约束（S1/S2/S3）：
      - S1: 绝不触发任何域内 agent 实际行为
      - S2: trace_id 必须前缀 shadow-
      - S3: 零资源开销（不新增 DB/进程/网络连接）
    """
    
    def __init__(
        self,
        candidate_policies: list[dict],        # §3 候选通信策略 π 数组
        trajectory_store_path: str,             # 轨迹树存储路径（本地文件系统）
        report_dir: str,                        # 影子报告输出目录
    ) -> None: ...
    
    # === 影子观察核心 ===
    
    def observe(self, envelope: dict) -> None:
        """旁路观察壳返回的 envelope
        
        S1: 只记录，不触发 agent
        S2: 内部加 shadow_trace_id 前缀
        """
        
    # === 轨迹树管理 ===
    
    def get_recent_trajectories(self, domain: str, limit: int = 10) -> list[dict]:
        """获取最近 N 条跨域交互轨迹树"""
        
    # === 通信 V 评估 ===
    
    def evaluate_policy(
        self,
        policy: dict,                            # 候选通信策略 π
        trajectories: list[dict],                # 历史跨域交互轨迹树数组
    ) -> float:
        """计算通信 V 值（§4 目标函数）
        
        V = 归一化(质量) / max(归一化(成本), 1)
        质量 = sum(node.poe_score * (1 + 0.1 * node.cross_domain_refs))
        成本 = sum(node.messages_sent * node.latency_ms)
        """
        
    # === 影子报告 ===
    
    def generate_report(self, days: int = 7) -> str:
        """生成 markdown 格式影子报告
        
        内容：
         1. 观察到的跨域事件数（按 A/B/C 三类分组）
         2. 轨迹树收集情况（按 domain × interaction_type 分组）
         3. V 值分布（候选 π × 轨迹树）
         4. 跨域策略蒸馏结果（REA V>0.85 策略在其他域 V 值）
         5. 激活建议（是否满足 §6 升级条件）
        """
```

### 2.2 observe 入参 / 轨迹树条目

```python
# observe 入参：壳返回的 envelope.data + meta
envelope = {
    "envelope": {
        "ok": True,
        "data": { ...业务体... },
        "source": "l0.cognition.mcp",
        "timestamp": 1730000000,
        "meta": {
            "event_type": "knowledge_retrieval.new_doc",   # 模式 A 观察触发
            "poe_score": 0.82,                              # PoE 评分
            "cross_domain_refs": 2,                         # 跨域引用数
        },
        "trace_id": "...",
    }
}

# AgentMailShadow 内部记录的轨迹树条目
trajectory_entry = {
    "seq": 1,
    "agent_domain": "knowledge",
    "agent_id": "k_agent_001",
    "action": "knowledge_retrieval.new_doc",
    "cost": {"messages_sent": 2, "latency_ms": 45},
    "evidence_refs": ["receipt_hash:sha256:..."],
    "poe_score": 0.82,
    "cross_domain_refs": 2,
    "policy_distill": None,          # 模式 B 评估后填
}
```

### 2.3 候选通信策略 π Schema

候选 π 是人工定义的 JSON（影子阶段**不自动迭代** π，只评估）：

```json
{
  "policy_id": "π_knowledge_to_rea_v1",
  "mode": "A",                        // A/B/C 三种模式
  "trigger": {                        // 模式 A 专用：触发条件
    "source_domain": "knowledge",
    "event_type": "knowledge_retrieval.new_doc",
    "poe_score_min": 0.7
  },
  "target": {
    "domain": "rea",
    "handler": "s33_rea_analyze.triggered",
    "budget": {"max_calls": 3, "max_latency_ms": 5000}
  },
  "v_target": 0.7,                    // 模式 B 专用：跨域 V ≥ 此值才建议激活
  "status": "candidate"               // candidate | shadow_evaluated | ready_for_activation
}
```

---

## §3 候选通信策略 π 初始集（影子 Phase 1 启动时创建）

| π_id | 模式 | 触发 | 目标 | V 目标 | 来源 |
|---|---|---|---|---|---|
| π_knowledge_to_rea_v1 | A | knowledge_retrieval.new_doc, poe ≥ 0.7 | REA s33_rea_analyze | - | 评估报告 §1 C1 场景 |
| π_rea_dream_to_eval_v1 | B | REA replay_pool V>0.85 策略 | 评测域 agent 策略配置 | ≥ 0.7 | 评估报告 §1 C5 场景 |
| π_eval_reflect_to_semantic_v1 | C | 评测 reflection.verdict=fail, target=semantic | 语义域 PSI drift | - | 评估报告 §1 C3 场景 |
| π_semantic_new_entity_to_cognition_v1 | C | 语义域发现新实体无认知 | 认知域主动 recall | - | 评估报告 §1 C4 场景 |
| π_rea_external_to_data_v1 | B | REA external replay_pool 成熟项目 V>0.85 | 数据域 agent 采集策略 | ≥ 0.6 | 评估报告 §1 C5 场景（跨域 2） |

---

## §4 通信 V 目标函数（影子阶段初版，Phase 2 后调优）

```python
def V_communication(trajectories: list[dict], policy: dict) -> float:
    """跨域通信质量-成本目标函数（影子阶段初版，1 周后调优）
    
    与 REA Dream-RSI V(π, T) 结构对齐（hypervolume + λ 惩罚）。
    """
    # 质量 = sum(poe_score × (1 + 0.1 × cross_domain_refs))
    quality = sum(
        node.get("poe_score", 0.5) * (1 + 0.1 * node.get("cross_domain_refs", 0))
        for node in trajectories
    )
    # 成本 = sum(messages_sent × latency_ms)
    cost = sum(
        node.get("cost", {}).get("messages_sent", 1) * node.get("cost", {}).get("latency_ms", 100)
        for node in trajectories
    )
    # 归一化 hypervolume（REA Dream-RSI 结构复用）
    # 参考点 = (0, max_cost_observed)
    max_cost = max(cost, 1)
    normalized_quality = quality / max(quality, 1)
    normalized_cost = 1.0  # 成本已经在 quality/cost 中
    
    # V ∈ [0, 1]，越高越好
    # λ = 0.1 惩罚高并行度（多条消息同策略）
    parallelism_penalty = 0.1 * max(node.get("cost", {}).get("messages_sent", 1) for node in trajectories)
    
    return normalized_quality / normalized_cost - parallelism_penalty
```

---

## §5 影子硬约束（S1/S2/S3，H9 已记录）

### S1 影子绝不触发 agent 行为

| 检查项 | 验证方法 |
|---|---|
| AgentMailShadow.observe() 只写轨迹树，不调 agent 任何函数 | 代码静态分析 + 单元测试：observe() 调用树 ≤ 2 层，末端只有文件写入 |
| 影子报告中的 projected action 只是文本描述，不注入调用链 | 代码静态分析：generate_report() 返回字符串，不调任何 agent 接口 |
| 影子 trace_id 前缀 shadow- 不会被 agent 路由逻辑消费 | 代码静态分析 + 集成测试：agent_mail.meta.shadow_only=true 的 envelope 被 agent 直接丢弃或旁路 |

### S2 trace_id 前缀 shadow-

```python
# AgentMailShadow 内部处理
def _shadow_trace_id(self, original_trace_id: str) -> str:
    return f"shadow-{original_trace_id}-{uuid.uuid4().hex[:8]}"
```

集成测试：影子观察后 cognitive_links 覆盖率、verify 命中率、recall 延迟前后对比一致。

### S3 零资源开销

| 资源项 | 影子开销上限 | 验证 |
|---|---|---|
| CPU 延迟（每次 observe） | < 1ms | perf_counter 计时，单元测试 |
| 内存（轨迹树缓存） | ≤ 50MB | 常驻内存监控 |
| DB 连接 | 0 | 代码中不 import sqlite3/psycopg2 |
| 网络连接 | 0 | 代码中不 import requests/http/urllib |
| 文件存储 | ≤ 100MB/周 | 影子报告 + 轨迹树 JSON 落本地，周清理 |

---

## §6 影子 → 激活 升级判据（Phase 1-2 完成后评估）

| # | 升级条件 | 判定方法 | 数据来源 |
|---|---|---|---|
| **V-S1** | 事件订阅匹配 ≥ 3 次 + 人工确认 projected action 合理 | 影子报告中 A 类匹配条目 ≥ 3，人工 review | AgentMailShadow.generate_report() |
| **V-S2** | 跨域交互轨迹树 ≥ 10 棵（覆盖 ≥ 4 个 domain × interaction_type 组合） | trajectory_store 统计 | trajectory_store_path/*.json 计数 |
| **V-S3** | V 值分布区分度好（0.3 < median < 0.9，标准差 > 0.15） | 影子报告 V 值直方图 | generate_report() |
| **V-S4** | REA 做梦器策略跨域 V ≥ 0.6（≥ 2 个候选 π 达标） | 影子报告模式 B 评估章节 | generate_report() |
| **V-S5** | 影子模式零副作用（前后对比一致） | cognitive_links 覆盖率 / verify 命中率 / recall 延迟 前后对比 | 指标监控（Phase 0 基线） |
| **V-S6** | bcrm2 切流完成（避免并行） | 实盘运维确认 | 项目节奏 |

**升级门禁**：V-S5 和 V-S6 必须同时满足，V-S1/V-S2/V-S3/V-S4 至少满足 3 项。

---

## §6.5 演进路线分叉图（Major #6 修复：明确 TRAIN-BASE vs COMM-SHADOW bcrm2 阻塞链）

```
MCP 壳层（当前主线）───────────────────────────── bcrm2 切流 ──────┐
    │                                                              │
    │ 并行两条轨迹                                                  │
    ├──▶ [并行·不受 bcrm2 阻塞] TRAIN-BASE Phase 0 ──────────────┐│
    │      TB1 PSI → TB2 Beta → TB3 AlphaPareto → TB4 Thompson → ││
    │      TB5 GRPO → 影子合并验证                               ││
    │                                                              ││
    └──▶ [依赖 bcrm2 切流] COMM-SHADOW Phase 0-1-2 ──────────────┘│
           Phase 0: 候选 π + 轨迹 Schema + 基线（等 bcrm2 后启动）
           Phase 1: 影子观察 1-2 周
           Phase 2: 影子评估 1 周
                                                                    │
                                                                    ▼
                                             Agent 域内 agent Phase A-E 依赖
                                             TB1+TB2+TB3+TB4+TB5 训练基座就绪
                                                                    │
                                                                    ▼
                                             COMM-SHADOW V-S1~V-S6 全通过
                                             → AgentMail 激活模式
```

**关键分叉**：TRAIN-BASE Phase 0 完全不依赖 bcrm2 切流（7 天开发周期与壳搭建并行）。COMM-SHADOW Phase 0 必须等 bcrm2 切流（V-S6 强制）。两条轨迹在 bcrm2 切流点会合，之后 COMM-SHADOW 的 Phase 1-2 影子观察/评估才启动。

---

## §7 实施计划

### Phase 0：影子 Phase 1 前准备（依赖 bcrm2 切流，1 周）

| 任务 | 产出 | 代码量 |
|---|---|---|
| 写 5 个候选通信策略 π | `agent_mail/candidate_policies/π_knowledge_to_rea_v1.json` 等 | 纯 JSON，5 × 30 行 |
| 定义轨迹树 Schema v0.1 | `agent_mail/trajectory_schema.py` dataclass + JSON schema | ~60 行 |
| 基线指标采集 | cognitive_links 覆盖率 / verify 命中率 / recall 延迟 3 指标 | 采集脚本 ~30 行 |

### Phase 1：影子观察（1-2 周，并行 bcrm2 切流）

| 任务 | 产出 | 代码量 |
|---|---|---|
| AgentMailShadow 核心类 | `agent_mail/shadow_observer.py` | ~200 行 |
| observe() 接入壳返回体旁路 | cognitive_mcp_server.py 新增 `_hook_shadow_observe(envelope)` | ~20 行（纯旁路，FAIL-OPEN） |
| generate_report() 实现 | 自动产出 `47-MCP管理系统/shadow_reports/shadow_report_wX.md` | ~100 行 |

### Phase 2：影子评估（与 Phase 1 并行 1 周）

| 任务 | 产出 | 代码量 |
|---|---|---|
| V_communication() 实现 | `agent_mail/v_function.py` | ~80 行 |
| 模式 B（REA 做梦策略跨域回放） | `agent_mail/policy_distill.py` | ~120 行 |
| V 值分布分析 | Phase 2 结束时产出 V 值分布报告 | 脚本 ~50 行 |

### Phase 3：激活升级判定

Phase 1+2 结束后评估 V-S1~V-S6 全部判据，决定是否激活模式 A/C（先在 REA→评测 跨域试点）。

激活后**影子观察器保留作为 fallback**（影子始终可以跑，不因为激活而删除）。

---

## §8 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| shadow- trace_id 被 agent 误路由消费 | 低 | 中 | agent_mail.meta.shadow_only=true 硬编码标记，agent 路由逻辑检查此字段直接旁路 |
| observe() 延迟超 1ms | 低 | 中 | observe() 异步（threading），不阻塞主路径；FAIL-OPEN |
| 轨迹树收集量不够（< 10 棵） | 中 | 低 | 影子观察周期延长到 3 周；或 Phase 1 启动前先人工跑几个典型跨域任务 |
| REA 做梦策略跨域 V 连续 < 0.6 | 中 | 中 | Phase 4 硬门禁不注入；说明跨域统一通信层不可行，各域保持硬接线 |
| 激活模式绕过 Mandate 写门控 | 高 | 极高 | 激活模式 agent_mail.meta 必须带 principal 角色声明，壳 Mandate 拦截逻辑不变 |
| bcrm2 切流延迟影子 Phase 1 启动 | 中 | 中 | 影子观察不阻塞 bcrm2 切流，bcrm2 切流后立即启动 Phase 1 |

---

## 附录 A：AgentMailShadow 模块目录（影子 Phase 1 时创建）

```
mcp_shells/
└── _shared/
    └── agent_mail/
        ├── __init__.py
        ├── shadow_observer.py          # Phase 1
        ├── trajectory_schema.py         # Phase 0
        ├── v_function.py                # Phase 2
        ├── policy_distill.py            # Phase 2
        ├── candidate_policies/          # Phase 0
        │   ├── π_knowledge_to_rea_v1.json
        │   ├── π_rea_dream_to_eval_v1.json
        │   ├── π_eval_reflect_to_semantic_v1.json
        │   ├── π_semantic_new_entity_to_cognition_v1.json
        │   └── π_rea_external_to_data_v1.json
        └── reports/                     # 运行时自动生成
            └── shadow_report_wX.md
```

**重要**：AgentMailShadow 放在 `mcp_shells/_shared/` 下 —— 这是壳共享模块目录，但影子**不是壳**（壳是协议转换层），影子是壳后旁路观察层。位置放在壳共享目录是因为需要旁路观察壳返回体。

**import 规约**（SPEC §3.4）：AgentMailShadow 不新增 sys.path hack，宿主 mcp.json PYTHONPATH 自动注入。
