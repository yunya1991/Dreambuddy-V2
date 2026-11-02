# SACG-A × Super-agent 连接 SPEC(OKR→Ticket 契约桥接)

> **版本**: v0.2(评审修订版)
> **日期**: 2026-11-02
> **状态**: 🟡 修改后接受——已按评审修订(REVIEW-SUPERAGENT-FUSION-v0.1),待复核 M1-M4 落点
> **修订记录**: v0.2 增加 G0 前置契约核实(M1/DA-1/DA-5)、补替代方案评估(m1)、风险表补灌芯证伪降级路径
> **定位**: 以 A 层(OKR 验收体系)为「契约与验收层」对接 DeepSeek Super-agent 架构,实现 DreamOS 从「单任务深度」向「多任务广度+持续性」扩展
> **依据文档**:
> - [2026-11-02-DeepSeek-Super-agent架构调研与DreamOS对比分析.md](../../2-KNOWLEDGE/7-EXTERNAL-RESEARCH/technical/architecture/2026-11-02-DeepSeek-Super-agent架构调研与DreamOS对比分析.md)(含第八章连接点专项评估)
> - [SYSTEM_ARCHITECTURE_OVERVIEW.md](../SYSTEM_ARCHITECTURE_OVERVIEW.md) v4.1（§1.8 DSH 升级口径）(新 SACG 口径唯一依据)
> - 认知记忆 VM-1793584859748(连接点评估结论)
> - **上位设计**:[DESIGN-DSH-ARCH-UPGRADE-v0.1.md](../../46-DSH架构/docs/tech/DESIGN-DSH-ARCH-UPGRADE-v0.1.md)(本 SPEC 是其 ③ 契约层的实现规格)
>
> **口径声明(硬约束)**: 本文档一律使用 v4.0 新 SACG 口径(S=认知规划/A=OKR验收/C=执行驱动/G=压缩沉淀),旧 Sense/Arrange/Compute/GraphStore 口径已作废,禁止混用。

---

## 一、背景与核心判断

DeepSeek Harness 团队 2026-10-31 发布 Super-agent 架构(Router/Worker 双层 + 事件驱动 + 存算分离 + Watchdog),并开源 MIT 原型 `dsh-superagent-prototype`(Harness bundle)。**本项目 `.dsh-home` 的 DSH (0.1.5-rc.2) 已经验证就是 DeepSeek Harness**,原型可零迁移装入独立 profile。

经专项评估(调研报告第八章):
- **A 层(OKR)是最佳连接点,但定位是「契约与验收层」,不是 Router 本身**;
- OKR 节点契约 `{node_id, objective, criteria, source, verify, evidence_id?}` ≡ Super-agent Ticket 的 Mandate 内核;
- Router 角色由 C-drive 调度者语义 + S 层入口承担;Worker 由 C 层 DSH 子 agent 承担(完全同源);
- 三处错位需补:OKR 节点状态机化(P1)、事件驱动完成判定(P1)、Router 常驻化(P2)。

## 二、目标与非目标

### 2.1 目标(P0 本 SPEC 范围)

| # | 目标 | 验证方式 |
|---|------|---------|
| G0 | **【前置·契约核实】读 dsh-superagent-prototype 源码(store.py/session.py)**,核实:① Mandate 字段 schema(翻译目标格式)② 上下文注入 hook 点是否存在(灌芯可行性)。**若 hook 点不存在 → 融合降级:A 步仅借壳观察,灌芯改走 B 步自研**(评审 M1) | 契约核实纪要落档 46-DSH架构 |
| G1 | dsh-superagent bundle 装入**独立 DSH profile** 并运行,不动现有 web profile | `dsh --profile superagent --dump-config` 可见 bundle |
| G2 | **OKR→Ticket Mandate 契约翻译器**(`okr_ticket_bridge.py`)落地,TDD | 单测覆盖 3 类 verify 映射 + 降级 |
| G3 | 端到端最小闭环:测试仓库 Issue → A 层 OKR 分解 → Ticket 创建 → Worker 执行 → PR 产出 → verify 验收比对 | 端到端测试记录 |
| G4 | Ticket 生命周期事件写入三端协同 GitHub 存证层 | 存证记录可查 |

### 2.2 非目标(明确排除)

- ✗ 不启用 BYOM/本地设备接入(安全风险,P3 以后再议)
- ✗ 不启用异步 ReAct 与投机执行(官方未默认开启,成熟度不足,P3)
- ✗ 不接触交易热路径(polling_trader/开仓链路零改动)
- ✗ 不修改 DreamOS 内核与现有 web profile(隔离原则)
- ✗ OKR 节点状态机化、Thread 订阅直通、Watchdog 外化(P1/P2 单独立 SPEC)

**备选方案评估(评审 m1)**:「等待 DeepSeek 正式开源版」不采纳——原型已 MIT 在手且绑定 1 月底 harness 1.0 窗口,等待无收益且错过同源优势期;「不做整合」不采纳——subagent 能力缺口(Thread 直通、持续会话)会一直存在,且与官方演进方向同向,早吸收成本低。

## 三、架构映射(v4.0 口径)

| Super-agent 概念 | 本项目承担者 | P0 状态 |
| --- | --- | --- |
| Ticket + Mandate | **A 层 OKR 节点 + verify 分派(连接点核心)** | ✅ 本 SPEC 桥接 |
| Router | C-drive 调度者语义 + S 层认知规划入口 | 复用现有,不改造 |
| Worker | C 层 DSH 子 agent(Harness session,同源) | bundle 提供 Executor |
| MasterAssessor 门 | S 层元认知门控 + bundle 自带 Policy 白名单 | 双层叠加 |
| Thread/Subscription | bundle 内部实现;G 层引用链 | P1 接入 |
| Watchdog | C-drive 反思器语义外化 | P2 单独立项 |
| 完成判定 | verify 分派表(evidence_backed/gap_closed/c_action) | ✅ 本 SPEC 映射 |

## 四、P0 详设

### 4.1 bundle 试用(独立 profile)

```
.dsh-home/profiles/superagent/     # 新建独立 profile,不动 web
  └── cordis.patch.yml            # 仅启用 dsh-superagent bundle
```

- 监听范围:**仅限专用测试仓库**(禁止指向主仓库,防止原型 bug 污染主仓 PR);
- 授权:bundle 自带 Policy 白名单,仅允许指定 GitHub 账号触发;无人触发不行动(注意力预算纪律);
- 状态目录独立,与现有 profile 的 storages 隔离。

### 4.2 OKR→Ticket Mandate 契约翻译器

**位置**: `34-前端应用训练系统/core/okr_ticket_bridge.py`(与 okr_nodes.py 同层,纯函数,无副作用)

**输入**: `decompose_okr_nodes()` 输出 + `OKRBuilder` 的 OKRSet(dependency_graph / parallel_line_count)

**字段映射**:

| OKR 节点字段 | Ticket Mandate 字段 | 说明 |
| --- | --- | --- |
| `node_id` | `external_ref` | Chain of Recall 锚点,回写验收结论用 |
| `objective` | `mandate.goal` | 任务目标陈述 |
| `criteria` | `mandate.acceptance` | 验收标准原文透传 |
| `verify=evidence_backed` | 完成判定策略: Worker 报告须含 `evidence_id` 匹配 | 证据满足即验收 |
| `verify=gap_closed` | 完成判定策略: 缺口项关闭标记 | 缺口补齐即验收 |
| `verify=c_action` | 完成判定策略: 执行动作非 REDO/EARLY_TERMINATE | 决策动作即验收 |
| `evidence_id` | `mandate.evidence_refs[]` | 证据引用 |
| `domain=finance_research` | Worker 路由提示 | 金融域走金融 subagent 集群 |
| OKRSet.dependency_graph | 分派计划: 并行线→多 Worker,顺序依赖→串行 Ticket | 来自 OKRBuilder |

**输出**: 翻译结果为**建议性 Mandate 草案**,经 bundle Policy 门与 S 层元认知门控后才创建 Ticket(双门)。

### 4.3 硬约束

| # | 约束 | 违反后果 |
| --- | --- | --- |
| HC-1 | **FAIL-OPEN**: bundle 不可用/翻译器异常 → 退回现有单会话 C 链执行,行为字节等价「桥不存在」 | 阻塞主链路即违规 |
| HC-2 | **模块化开关** `enable_superagent_bridge`(默认 **False**),关断时翻译器不加载 | 默认改变现有行为即违规 |
| HC-3 | 独立 profile 隔离,**禁止修改 web profile / DreamOS 内核 / 交易热路径** | 污染现有链路即违规 |
| HC-4 | 监听范围白名单仅限测试仓库;凭据独立,不复用主仓 token | 越权操作主仓即违规 |
| HC-5 | Token 预算记账接入现有 Budget 横切层,单次 Ticket 推理成本可审计 | 成本黑盒即违规 |
| HC-6 | 文档与代码注释一律 v4.0 新 SACG 口径 | 旧口径出现即返工 |

### 4.4 验收标准(可测)

| # | 验收项 | 通过标准 |
| --- | --- | --- |
| A1 | profile 隔离 | `dsh --profile superagent --dump-config` 显示 bundle;`--profile web` 无变化 |
| A2 | 翻译器单测 | 3 类 verify 映射正确;空 plan/异常输入降级返回 None 且不抛错(FAIL-OPEN 测试) |
| A3 | 开关等价 | 开关关断前后,现有 C 链测试套件全绿(字节等价) |
| A4 | 端到端 | 测试仓库造 Issue → 观察到 Ticket 创建(含 mandate.goal/acceptance)→ Worker 产出 PR → verify 结论回写 |
| A5 | 存证 | Ticket 生命周期事件(created/ended)在 GitHub 存证层可查 |
| A6 | 成本 | 单 Ticket Token 消耗有 Budget 记录,超预算触发降级 |

## 五、风险与缓解

| 风险 | 等级 | 缓解 |
| --- | --- | --- |
| 原型为研究代码非正式产品,工程质量不齐 | 高 | 独立 profile + 测试仓库白名单 + 代码评审后改造,不直接使用其内部版本假设 |
| Token 开销(官方实测取消直通 +30% 决策/+37% 缓存读) | 中 | HC-5 Budget 记账;P1 引入直通后复测对比 |
| 提示词注入/凭据泄露(官方明示开放问题) | 高 | 不启用 BYOM;凭据独立;监听内容不进交易链路 |
| prototype 无上下文注入 hook 点(灌芯不可行) | 高 | G0 先核实;证伪则降级为"A 步借壳观察 + 灌芯走 B 步自研",不阻塞主线 |
| 新旧 SACG 口径混杂 | 中 | HC-6 + 文档 lint 检查 |

## 六、Roadmap(P1-P3 各立 SPEC,不在本范围)

| 阶段 | 内容 | 前置 |
| --- | --- | --- |
| P1 | OKR 节点状态机化(live/paused/waitsForPerson/ended)+ Thread 订阅直通(事件驱动 resume) | P0 验收通过 |
| P2 | C-drive 反思器语义外化为 Watchdog 独立会话;G 层承载 Thread 引用链(Chain of Recall) | P1 稳定运行 |
| P3 | 异步 ReAct(start/stop 事件回流);评估投机执行 | 官方机制默认开启后再议 |

## 七、评审清单(评审人勾选)

- [ ] A 层定位(契约/验收层)是否与 v4.0「A 层不包含业务节点」冲突?(翻译器放 34 系统 core,不进 DreamOS 内核——需评审确认边界)
- [ ] P0 范围是否过大?G4 存证是否可降级为 P1?
- [ ] 双门设计(bundle Policy + S 层元认知)是否冗余?
- [ ] 测试仓库选择与原 version 升级路径
- [ ] Token 预算阈值具体取值
- [ ] verify=evidence_backed 判定消费 45-评测系统 Evidence Bundle(A 层验收从 C 层自报升级为独立评测收口;2026-11-02 用户决策 45 入闭环)
