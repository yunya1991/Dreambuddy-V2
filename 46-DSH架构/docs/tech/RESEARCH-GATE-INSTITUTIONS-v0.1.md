# RESEARCH: 工作门禁的制度来源（管理制度 ↔ 飞书 ↔ DreamOS 原生门禁）

> **版本**: v0.2 ｜ **日期**: 2026-11-18 ｜ **状态**: 调研完成；§2.6 新增「飞书工作流内化 / GateFlow」，结论并入 [DESIGN-QUANT-TEAM-v0.1](DESIGN-QUANT-TEAM-v0.1.md) §11.8 与 [SPEC-SYSTEM-ARCH-CAPABILITY v1.1](../../../1-ARCHITECTURE/specs/SPEC-SYSTEM-ARCH-CAPABILITY-v1.0.md) §6.9
> **调研目的**: 为「AI Agent 工作门禁」找制度依据。**不是接入飞书能力**，而是把上百年验证有效的员工管理 / 公司管理控制制度，制度化到 Agent 的原生工作与推理流中：AI 干活，规划 / 验收 / 门禁 / 审批由前端原生承载。
> **调研方式**: 公开资料检索（监管规范、方法论原始出处、厂商帮助文档），不凭印象。

---

## 零、结论先行

### 0.1 十条可落地结论

| # | 结论 | 直接约束 |
| --- | --- | --- |
| 1 | **门禁是状态机守卫，不是 UI 装饰**。未过门禁，下游不可执行 | 服务端裁决 + 409 阻断，前端只负责决策入口 |
| 2 | **执行者与批准者必须分离**（SoD / maker-checker / four-eyes） | `deny_same_actor`；Agent 不能批自己产出的门 |
| 3 | **授权要分级、要写清额度与边界**（DoA 授权矩阵） | 门禁按 `task_type + risk_level` 路由，不写死 |
| 4 | **每道门必须有交付物、判据、结论**（Stage-Gate） | 证据为空即 FAIL，不允许"看情况通过" |
| 5 | **变更要分级**：标准 / 常规 / 紧急（ITIL） | 只有"标准变更"可预授权；紧急通道事后必须复盘 |
| 6 | **一线有权停线，且停线不受惩罚**（Andon） | Worker 可主动 `blocked`，不得因误报被降权 |
| 7 | **超时默认阻塞并升级，绝不自动放行** | `on_timeout = remind \| escalate`；`auto_approve` 默认禁用 |
| 8 | **驳回必须回转并带原因**，不是终止 | `reject → rewind_to + comment(必填)` |
| 9 | **例外要有书面理由、风险说明、有效期**（例外管理） | 例外不可绕过验收门；过期自动失效 |
| 10 | **审计不可变、可回放、记到人和证据版本** | append-only 事件流 + `evidence_ref` 绑定 |
| 11 | **审批模型必须与生产模型异构**（模型级 SoD） | `gate` 类模型独立供应商/家族，同源拒绝启动 |
| 12 | **会签必须是异构模型会签**，不是同模型多开 | 按 `provider + model` 去重计票；模型票不单独放行高风险门 |

### 0.2 三条必须避免的反模式

1. **橡皮图章**：门禁太多、太低风险，人开始无脑点通过 → 制度失效。治理手段：风险分级、合并低风险门、待办限流。
2. **门禁篡改进度**：为了"卡住"把已完成的事实回退成"未派工"，看板开始说谎 → 进度只由事实决定，待确认由 `status=waiting` 表达。
3. **静默旁路**：超时自动通过、Agent 自批、管理员改状态 → 三者都必须被审计事件捕获，且默认关闭。

---

## 一、传统管理制度：控制目标、规则、失效模式、AI 原生落地

### 1.1 不相容职务分离（Segregation of Duties, SoD）

**来源**：《企业内部控制基本规范》（财会〔2008〕7 号）第二十九条明确要求分析、梳理业务流程中的不相容职务并实施分离，"形成各司其职、各负其责、相互制约的工作机制"。

**关键规则**
- 发起、审批、执行、记录、保管不得由同一主体包办；
- 高风险动作至少两个独立主体参与；
- 分离关系要**在系统里强制**，不能只写在制度文档里。

**失效模式**：形式分离（同一人两个账号）、上级代批、紧急流程绕过。

**AI 原生落地**
- 硬约束：`producer.actor_id != approver.actor_id`；
- 子 Agent 只能产出证据，**永远不能批准任何门**；
- 批门主体只有人（或人显式授权的门禁角色），且审批身份取自服务端会话，不取请求体。

### 1.2 授权审批控制（Delegation of Authority, DoA）

**来源**：《企业内部控制基本规范》第三十条要求区分**常规授权与特别授权**，明确各岗位权限范围、审批程序和责任，并编制权限指引。MAS《Internal Controls》指引进一步要求：授权额度与职级匹配；授权须书面化，写清授权范围、可否转授权、限制条件；并有监控机制确保活动被正确授权。

**关键规则**
- 审批矩阵：`操作 + 风险 + 金额/影响面 + 组织 + 角色 → 需要的审批`；
- 例外申请：书面理由 + 风险评估 + **有效期**，纳入跟踪与报告；
- 临时授权：有时限、有记录、可见，**不得用来绕过 SoD**；
- 授权嵌入系统（ERP），不是靠记忆执行。

**失效模式**：权限只增不减、转授权无限传递、例外变成影子流程。

**AI 原生落地**
- `GatePolicy` 以配置表达授权矩阵，禁止在代码里散落 `if (role === ...)`；
- 例外 = 一条带 `expires_at` 的 `exception` 记录，到期自动失效并回到 `waiting`；
- 转授权（delegate）默认关闭，开启时必须记录 `delegated_from / delegated_to / reason / ttl`。

### 1.3 双人复核（Maker-Checker / Four-Eyes / Two-Person Rule）

**来源**：金融与核工业的通用控制。Maker 发起，Checker 独立复核；两人须为不同的人、各自拥有被分配的权限；提交动作只有在批准后才执行。奥地利 eLaw 案例把 four-eyes 表述为"两个主体必须对一项变更达成一致或相互监督"，并禁止同一办事员从起草一路做到发布。

**关键规则**
- 状态机：`draft → submitted → approved/rejected → executed`；
- 必须有证据、时限、异常路径、审计记录；
- 高风险动作要求 `min_distinct = 2`。

**失效模式**：Checker 不看内容直接点同意；Maker 与 Checker 私下串通；加签被当成"多一个人点头"。

**AI 原生落地**
- 高风险门（交易方案、策略变更、生产写入）`quorum = all` 且 `min_distinct >= 2`；
- 审批卡片必须展示**证据摘要 + 证据版本 + 变更 diff**，不展示就无法判断；
- 同一 `actor_id` 重复批准不计入 quorum。

### 1.4 阶段门（Stage-Gate）

**来源**：Robert G. Cooper 的 Stage-Gate 体系，四十余年新产品开发治理实践。每道 Gate 结构固定：**交付物（deliverables）→ 判据（criteria）→ 输出（outputs：Go / Kill / Hold / Recycle）**；Gatekeeper 是跨职能管理者；Gate 是**向前看**的资源承诺决策，不是向后看的进度汇报。

**关键规则**
- 门在阶段之前，不是阶段之后；
- 判据必须**事先定义**且可判定（must-meet / should-meet）；
- 结论是四选一，不是"通过/不通过"二元；
- 每道门都有明确的责任人。

**失效模式**：门变成汇报会；判据事后补；只有 Go 没有 Kill；Gatekeeper 无实权。

**AI 原生落地**
- 五道门对应五个 `GateKind`，每道门声明 `evidence.required[]`；
- 输出四态扩展为：`approved / rejected / hold（挂起补充）/ rewind（回转）`；
- 判据来自 SPEC 与 OKR，不由 Agent 在门禁时临时生成；
- Gatekeeper 是角色，不是具体 Agent。

### 1.5 变更分级与变更审批（ITIL CAB / ECAB）

**来源**：ITIL 变更管理把变更分为 **标准变更（预授权，低风险，走既定流程）**、**常规变更（CAB 评估技术范围、资源、运营/业务/安全风险后审批）**、**紧急变更（ECAB 或紧急变更授权人快速审批，事后必须做实施后评审 PIR）**。CAB 的职责是评估、排优先级、排期与批准。

**关键规则**
- 分级标准写死，避免"什么都走紧急通道"；
- 紧急通道必须有人有权当场决策，且事后复盘；
- 标准变更的前提是"流程已验证 + 风险已知"。

**失效模式**：紧急通道常态化；CAB 变成排队会；标准变更清单长期不审。

**AI 原生落地**
- `change_class: standard | normal | emergency` 作为 `GatePolicy` 的一等字段；
- `standard` 才允许预授权（`preauthorized: true` + TTL + 次数上限 + 必须留痕）；
- `emergency` 允许单人或双人快速批，但强制生成 `pir_required` 事件，下一次同类任务未复盘则不得再走紧急通道。

### 1.6 停线权（Andon Cord / Jidoka）

**来源**：丰田生产体系。任何操作员发现异常都可以拉绳停线；停线**不会受到惩罚**，反而被感谢；先用黄灯预警、到固定停止线仍未解决才真正停线；管理层统计拉绳次数是为了定位薄弱工位，**不是为了惩罚拉绳的人**。

**关键规则**
- 一线有停线权，且行使权利无成本；
- 停线后必须有人响应、定位、修复，然后恢复；
- 停线数据用于改进，不用于考核。

**失效模式**：拉绳被视为"惹事"；停了没人来；为了不停线而隐瞒异常。

**AI 原生落地**
- Worker 可主动上报 `blocked`，状态进入 `waiting` 而不是 `failed`；
- 上报不扣分、不降权，且必须进入待办队列有人处理；
- 统计每类 `blocked` 的原因分布，用于改 SPEC 判据与能力配置，而不是给 Agent "打差评"。

### 1.7 审计追踪与证据保全

**来源**：COSO / SOX 404 的核心不是"多审批"，而是**控制可被独立验证**：谁、在什么时间、基于什么证据、做了什么决定，全部可追溯；审批样本、工单、签署备忘录都是审计证据。

**关键规则**
- 只追加，不修改；
- 记录主体、时间、动作、证据引用、理由；
- 可回放到任意历史时点。

**失效模式**：日志可被覆盖；只记结果不记理由；证据引用指向会变的 URL。

**AI 原生落地**
- 事件流 append-only + 内容指纹去重（已实现于 `server-store.ts`）；
- 门禁记录 `evidence_ref`（如 `spec:xxx:v2`），证据变化 → 旧确认自动失效（已实现于 `reconcileGates`）；
- 驳回原因必填，写入同一事件；
- 回放得到同一快照（同一 `trace_id` 一致）。

### 1.8 质量门与例外管理（PDCA / 例外管理）

**来源**：质量管理中的质量门（quality gate）与 PDCA 循环；管理控制中的例外管理原则——只对超出阈值的偏差升级处理，避免管理者被噪声淹没。

**关键规则**
- 门只看**关键判据**，不是全量检查；
- 偏差分级：可接受 / 需说明 / 需升级；
- 例外必须显性化，不能静默消化。

**AI 原生落地**
- `data_quality` 缺口分级：`missing / partial / stale`；
- 只有阻断级缺口才卡门，其余作为"需说明"随结论一起交付；
- 例外清单在汇总页可见，不允许藏在日志里。

### 1.9 模型级不相容职务分离（AI 原生扩展）

传统 SoD 分离的是"人"；在 Agent 系统里，**同一个模型既生产又自审**会引入可测量的自偏好偏差。LLM-as-a-judge 研究显示，模型倾向于高估自己（或同家族模型）的输出；而使用来自不同模型家族的评审团（Panel of LLM evaluators）比单一大型评审模型偏差更小、成本更低；跨模型审计（Chain-of-Models）让后一个模型检查前一个模型的推理链，能发现单模型会自信坚持的错误。这与"四眼原则"的制度逻辑完全同构。

**关键规则**
- 生产模型与审批模型必须异构（不同 provider 或不同家族）；
- 门禁模型只读证据，无工具、无写权限，`temperature=0`，prompt 版本固定；
- 会签按 `provider + model` 去重，同模型多实例只计 1 票；
- 脑暴 / 辩论（bull-bear、红队）同样要求异构，否则只是同一模型的自我复述；
- 模型不可用或输出不合规 → `needs_human`，不允许默认放行。

**失效模式**：同源会签造成"假独立"；门禁模型被证据中的提示注入操纵；模型升级后 prompt 与判据漂移；把模型票当人工票直接放行高风险门。

**AI 原生落地**
- 三类模型：`judge`（S/A 判定）、`worker`（C/G 生产与辩论）、`gate`（门禁预审）；
- 启动期校验三方异构与权限，失败即拒绝启动；
- 审批记录写清 `provider / family / model / prompt_version`，可复盘；
- 模型票与人工票分开计数，高风险门人工票为必要条件。

### 1.10 制度类比的边界（必须写清）

AI Agent 不是会计，不能照搬财务内控的全部形式：

- 不需要"凭证 / 账簿 / 报表"三件套；
- 不需要为每个动作配一名全职复核人；
- 门禁的目的是**防黑箱、防漂移、防越权**，不是制造流程负担。

因此落地原则是：**制度内核（分离、授权、证据、分级、停线、审计）保留，制度外壳（表单、会签仪式、层级签字）按需裁剪。**

---

## 二、飞书机制对照（设计参考，不接 API）

> 只借鉴"制度如何产品化"，不引入飞书依赖。

### 2.1 审批：流程设计能力

| 能力 | 飞书做法 | 对我们的启示 |
| --- | --- | --- |
| 条件分支 | 按表单字段走不同分支（如请假 <2 天 / ≥2 天） | `GatePolicy` 按 `task_type + risk_level` 路由，同构 |
| 并行分支 | 财务 / HR / IT 同时审批（如离职） | 高风险门可并行征集多角色意见，再汇总裁决 |
| 审批人类型 | 上级 / 部门负责人 / 角色 / 用户组 / 指定成员 / 提交人自选 / 提交人本人 / 节点审批人 / 连续多级上级 / 连续多级部门负责人 / 表单内联系人 / 表单内部门 | 我们的 `approver.roles` 对应"角色 / 用户组"；"节点审批人"对应"上一道门的批准人复用到下一道" |
| 多人审批方式 | 会签（全同意）/ 或签（任一同意）/ 依次审批 | 直接映射 `quorum: all / any / sequential` |
| 审批人为空 | 自动通过 / 指定人员 / 转交审批管理员 | 我们默认 **转交管理员 + 告警**，不默认自动通过 |
| 审批人 = 发起人 | 发起人自审 / 自动跳过 / 转上级 / 转部门负责人 | 对应 `sod.deny_same_actor`：Agent 发起的门，禁止 Agent 自批；人发起的门可配置"自审"但需留痕 |
| 抄送 | 可设"仅同意时抄送" | 对应 `notify.on_approve`，让相关方知情但不阻塞 |
| 表单权限 | 节点级"可读 / 可编辑" | 对应门禁卡片按角色裁剪可见字段（脱敏） |
| 操作权限 | 转交 / 加签 / 减签 / 回退 / 手写签名 / 审批意见 | 转交与加签默认关闭；**回退 = 我们的 rewind**；意见在高风险门必填 |
| 限时处理 | 节点限时 10 分钟–31 天，可组合超时规则；超时自动提醒或关闭 | 我们只取"提醒 / 升级"，**不取"超时关闭即通过"** |
| 催办 | 24 小时内仅可催办 1 次 | 对应 SLA 提醒限流，防打扰 |
| 效率诊断 | 团队 / 个人 / 流程效率 | 对应门禁吞吐与积压指标，用于治理审批疲劳 |

### 2.2 OKR：目标与验收

| 能力 | 飞书做法 | 启示 |
| --- | --- | --- |
| 打分 | O 不可直接打分，KR 可打分，O = KR 加权平均 | 我们的 O 进度必须由 KR 推导，**不允许手工填进度** |
| 对齐 | 对齐视图，可展示被对齐方的 KR | 任务目标要能回溯到上层目标（Episode / 策略） |
| 进展 | 进展可回写、可评论 | 验收记录带理由，可被追问 |

### 2.3 任务与项目

| 能力 | 飞书做法 | 启示 |
| --- | --- | --- |
| 任务 | 分配、协作成员、状态、附件 | 对应 `AgentRun.role` + `owner` |
| 项目节点流 | 节点有序拆解，节点可设流转条件，角色/节点可裁剪 | 对应 `DispatchRail` 六步 + 条件推进 |
| 里程碑 | 阶段与里程碑 | 对应 Stage 边界，里程碑=门 |

### 2.4 多维表格：权限与留痕

| 能力 | 飞书做法 | 启示 |
| --- | --- | --- |
| 高级权限 | 记录级（可新增/可删除、指定记录范围）、字段级（可阅读/可新增/可编辑）、视图级 | 门禁视图按角色裁剪；证据字段只读 |
| 历史记录 | 180 天内配置与数据增删改记录；单条记录变更历史含内容、时间、操作人；可还原历史版本 | 对应 append-only 事件 + 快照回放；保留期应≥业务审计要求 |
| AI 配置权限 | 用自然语言描述即可生成角色与权限 | 未来可做"用自然语言描述门禁策略"，但**生成后必须人工确认** |

### 2.5 知识库：制度 SSoT

飞书知识库承担"制度文档"的单一事实源。对我们：`GatePolicy` 是机器可执行的制度，设计文档与调研报告是人可读的制度说明，两者必须互相引用，禁止只改一边。

### 2.6 工作流内化：从飞书流程定义到 GateFlow

> **结论：真正要内化的不是飞书的表单或组织架构，而是"流程定义 + 运行状态机"这套控制语义。**
> 飞书的价值在于把"谁在什么条件下、按什么顺序、以什么方式批准"做成了可配置对象；我们把它翻译成可校验、可回放、不可绕过的 `GateFlow`。

#### 2.6.1 三层内化

| 层 | 飞书对应 | DreamOS 对应 | 可配置性 |
| --- | --- | --- | --- |
| 制度层 | 审批模板、制度文档 | Policy Template（标准 / 高风险 / 紧急 / 热修） | 只能走版本评审，不能在前端随意改 |
| 流程层 | 审批流程设计器 | `GateFlow`（节点、条件、会签、时限） | 前端可配，但必须过校验器 |
| 运行层 | 审批实例、操作日志 | `GateRun` + 事件流 | 只追加，不改写 |

关键区分：**制度层决定"必须控什么"，流程层决定"怎么控"，运行层只记录"实际怎么发生"**。三者混在一起，就会出现"改流程等于改制度"的失控。

#### 2.6.2 GateFlow v0.1

```ts
type GateNodeType = "gate" | "condition" | "parallel" | "cc" | "timer" | "terminate";

interface GateFlow {
  flow_id: string;
  version: number;                       // 流程版本，运行实例绑定版本
  status: "draft" | "active" | "archived";
  applies_to: {
    task_types: string[];                // trading_analysis / code_change / research
    risk_levels: RiskLevel[];
  };
  entry: string;                         // 入口节点 id
  nodes: GateFlowNode[];
  guardrails: {
    must_end_with: "acceptance";         // 所有路径必须以验收门结束
    forbid_skip_high_risk: true;
    max_nodes: 12;
    max_gates: 5;
  };
}

type GateFlowNode =
  | { id: string; type: "gate"; gate: GatePolicy; next: string | null }
  | { id: string; type: "condition"; when: ConditionExpr; then: string; else: string }
  | { id: string; type: "parallel"; branches: string[]; join: "all" | "any"; next: string }
  | { id: string; type: "cc"; to: string[]; next: string }
  | { id: string; type: "timer"; hours: number; on_timeout: "remind" | "escalate" | "block"; next: string }
  | { id: string; type: "terminate"; reason: string; admin_only: true };

interface ConditionExpr {
  // 只允许读取事实字段，不允许自由文本或 LLM 判定
  field: "risk_level" | "task_type" | "change_class" | "evidence_count" | "kr_verdict";
  op: "eq" | "neq" | "gt" | "lt" | "in";
  value: string | number | string[];
}
```

示例（交易研判）：

```json
{
  "flow_id": "trading_analysis_v1",
  "version": 1,
  "status": "active",
  "applies_to": { "task_types": ["trading_analysis"], "risk_levels": ["low", "medium", "high"] },
  "entry": "intent",
  "nodes": [
    { "id": "intent", "type": "gate", "gate": { "kind": "intent", "approver": { "roles": ["owner"], "quorum": "any" } }, "next": "spec" },
    { "id": "spec", "type": "gate", "gate": { "kind": "spec", "approver": { "roles": ["owner", "team_lead"], "quorum": "all" } }, "next": "risk_branch" },
    { "id": "risk_branch", "type": "condition", "when": { "field": "risk_level", "op": "in", "value": ["high", "critical"] }, "then": "risk_review", "else": "dispatch" },
    { "id": "risk_review", "type": "gate", "gate": { "kind": "dispatch", "approver": { "roles": ["risk_reviewer"], "quorum": "all" } }, "next": "dispatch" },
    { "id": "dispatch", "type": "gate", "gate": { "kind": "dispatch", "approver": { "roles": ["team_lead"], "quorum": "any" } }, "next": "acceptance" },
    { "id": "acceptance", "type": "gate", "gate": { "kind": "acceptance", "approver": { "roles": ["owner", "risk_reviewer"], "quorum": "all", "min_distinct": 2 } }, "next": "cc_admin" },
    { "id": "cc_admin", "type": "cc", "to": ["admin"], "next": "end" },
    { "id": "end", "type": "terminate", "reason": "completed" }
  ],
  "guardrails": { "must_end_with": "acceptance", "forbid_skip_high_risk": true, "max_nodes": 12, "max_gates": 5 }
}
```

#### 2.6.3 运行状态机与事件

- `GateRun` 状态：`running / waiting / approved / rejected / terminated / escalated`；
- 必须事件：`flow.started`、`node.entered`、`node.waiting`、`node.approved`、`node.rejected`、`node.delegated`、`node.signer_added`、`node.signer_removed`、`node.rewound`、`flow.terminated`、`flow.completed`、`sla.reminded`、`sla.escalated`；
- 快照由事件回放，前端不得自建流程状态；
- 每个事件必须带 `trace_id + run_id + flow_version`，否则不可作为验收证据。

#### 2.6.4 十二条校验规则（GateFlow 编译期）

1. 所有路径必须最终到达 `acceptance`，否则拒绝发布；
2. `high / critical` 节点必须 `human_required=true`，不得只靠模型票；
3. 禁止存在绕过验收门的边；
4. 图必须无环，节点 ≤12、门 ≤5；
5. 条件表达式只能读事实字段，禁止自由文本、LLM 判定或外部调用；
6. `quorum=all` 且高风险时，`min_distinct≥2`；
7. 转交只允许人→人，带 TTL 与 `delegated_from`，高风险验收门禁止转交；
8. 加签（前/并/后）必须使该节点已有批准失效，重新会签；
9. 退回目标必须是当前节点的祖先，且必须填原因，下游批准全部失效；
10. 终止仅管理员可执行，终止后所有 pending 失效且不可恢复；
11. 审批人为空 → 升级管理员并阻塞，**禁止自动通过**；
12. 超时只允许提醒 / 升级 / 阻塞，**禁止超时自动通过**；抄送节点不计票。

#### 2.6.5 飞书原语 → GateFlow 对照（扩展）

| 飞书原语 | GateFlow 对应 | 关键约束 |
| --- | --- | --- |
| 条件分支 | `condition` 节点 | 只读事实字段 |
| 并行分支 | `parallel` + `join: all/any` | 汇总后进入下一节点 |
| 会签 / 或签 / 依次 | `quorum: all / any / sequential` | 高风险至少 2 个独立主体 |
| 前加签 / 并加签 / 后加签 | `add_signer`（before/parallel/after） | 已有批准失效，重新会签 |
| 转交 | `delegate` | 人→人、TTL、审计、不得转高风险验收 |
| 减签 | `remove_signer` | 仅管理员，留原因 |
| 退回 | `rewind` | 祖先节点、原因必填、下游失效 |
| 终止 | `terminate` | 仅管理员、不可恢复 |
| 抄送 | `cc` 节点 | 只通知、不计票、不阻塞 |
| 审批人为空 | `on_empty_approver` | 升级管理员 + 阻塞 |
| 限时 / 催办 | `timer` + SLA | 只提醒/升级，不自动通过 |
| 表单字段权限 | `field_acl` | 按角色裁剪可见字段 |
| 自动化触发 | `trigger` 注册表 | 事件驱动，不写业务逻辑 |
| 高级权限角色 | `reviewer_group` | 角色组 + 字段/记录级权限 |
| OKR 打分 | `kr_score` | 只给 KR 打分，O 由加权推导 |
| 操作日志 | 事件流 | append-only、可回放 |

#### 2.6.6 OKR 内化细化

- **O 不可手工填进度**：`O.progress = Σ(KR.score × weight)`，权重和必须为 1；
- **只给 KR 打分**：0–1 四档（未达成 / 部分 / 达成 / 超额）；
- **双评分**：生产者自评 + 独立验收人评分；两者差异 >0.2 触发复核；
- **禁止自我终评**：Agent 不能作为自己任务的唯一评分人；
- **对齐必填**：任务目标必须挂到上层 KR；无对齐需显式填写理由并进入例外管理；
- **提醒**：评分截止前提醒一次，逾期进入待办中心，不自动清零。

#### 2.6.7 反模式

| 反模式 | 后果 | 约束 |
| --- | --- | --- |
| 流程即代码 | 前端可写任意逻辑，无法审计 | 只允许声明式节点 |
| 无限加签 | 审批链膨胀、责任稀释 | 单节点加签 ≤2 次 |
| 抄送当审批 | 有知情无责任 | `cc` 永不计票 |
| 超时自动通过 | 把风险变成默认 | 只提醒/升级/阻塞 |
| 角色写成人名 | 人员变动即失效 | 角色组 + 成员映射 |
| 双写流程状态 | 快照漂移 | 事件 SSoT |
| 模型票替代人工 | 黑箱放行 | 高风险必须人工票 |

---

## 三、映射矩阵：制度 → 飞书 → DreamOS 原生门禁

| 制度 | 飞书机制 | DreamOS 落地 | 关键字段 |
| --- | --- | --- | --- |
| SoD | 审批人 ≠ 发起人；角色体系 | 服务端校验 `actor != producer`；Agent 无批门权 | `sod.deny_same_actor` |
| DoA 授权矩阵 | 条件分支 + 审批人类型 | 按 `task_type / risk_level / change_class` 选策略 | `applies_to`、`approver.roles` |
| 双人复核 | 会签 / 依次审批 | 高风险门 `quorum=all`、`min_distinct=2` | `quorum`、`min_distinct` |
| Stage-Gate | 项目节点流 + 流转条件 | 五道门，交付物/判据/输出四态 | `evidence.required[]`、`outputs` |
| ITIL 变更分级 | 审批模板分级 | `standard` 可预授权，`emergency` 事后 PIR | `change_class`、`preauthorized` |
| Andon | 消息卡片 + 待办 | Worker 可 `blocked`，进入待办有人处理 | `block_reason`、`on_call` |
| 审计追踪 | 审批记录 + 表格历史 | append-only JSONL + `evidence_ref` | `decided_by`、`decided_at` |
| 例外管理 | 加签 / 转交 / 特批 | 例外带 `expires_at`，到期失效 | `exception.ttl` |
| 审批疲劳治理 | 效率诊断 + 催办限流 | 待办限流、风险排序、低风险合并 | `sla`、`batch` |
| 加签 | 前/并/后加签 | 追加审批人并使已有批准失效 | `add_signer.mode`、`invalidates_prior` |
| 转交 | 转交他人审批 | 人→人、TTL、留痕，高风险验收禁止 | `delegate.allowed`、`delegate_ttl` |
| 退回 | 退回至指定节点 | 祖先校验、原因必填、下游失效 | `rewind.target`、`rewind.reason_required` |
| 终止 | 流程管理员终止 | 仅管理员、不可恢复 | `terminate.roles` |
| 抄送 | 仅同意时抄送 | 只通知、不计票、不阻塞 | `cc.to`、`cc.when` |
| 空审批人 | 自动通过 / 指定人 / 转管理员 | 升级管理员 + 阻塞，禁止自动通过 | `on_empty_approver` |
| 限时与催办 | 节点限时、催办限流 | 提醒/升级/阻塞，禁止超时通过 | `timer.on_timeout` |
| 字段权限 | 节点级可读/可编辑 | 按角色裁剪字段，证据只读 | `field_acl` |
| 自动化触发 | 记录新增/字段变更/按钮/定时 | 事件驱动门禁生成与提醒 | `trigger.registry` |
| OKR 打分 | 仅 KR 打分，O 加权 | 禁止手工改进度，双评分 | `kr_weights`、`self_score`、`verifier_score` |

---

## 四、GatePolicy 配置模型（不写死）

```ts
type ChangeClass = "standard" | "normal" | "emergency";
type Quorum = "any" | "all" | "sequential";
type RiskLevel = "low" | "medium" | "high" | "critical";
type GateOutput = "approved" | "rejected" | "hold" | "rewind";

interface GatePolicy {
  gate_id: string;                      // 与 GateKind 对齐
  kind: GateKind;
  title: string;
  applies_to: {
    task_types: string[];               // 如 trading_analysis / code_change / research
    risk_levels: RiskLevel[];
    change_classes: ChangeClass[];
  };
  approver: {
    roles: string[];                    // 谁能批
    quorum: Quorum;
    min_distinct: number;               // 至少几个不同主体
    allow_self_approve: false;          // 默认禁止自批
    allow_delegate: false;              // 默认禁止转交
    delegate_ttl_minutes?: number;
    allow_add_signer: false;            // 默认禁止加签扩容
  };
  gate_model: {
    class: "gate";                      // 固定门禁类模型
    model_ids: string[];                // 会签模型列表
    quorum: Quorum;                     // 会签方式
    min_distinct_models: number;        // 至少几个异构模型（高风险 ≥2）
    deny_same_provider: true;           // 与生产模型同源即拒绝
    deny_same_family: true;
    allowed_capabilities: [];           // 只读，无工具
    temperature: 0;
    on_invalid_output: "needs_human";   // 不合 schema 不放行
  };
  model_tickets: {
    model_vote_weight: "advisory";      // 模型票只作预审意见
    human_ticket_required_above: "medium";
  };
  sod: {
    deny_same_actor: true;              // 生产者不得批准
    deny_same_org: boolean;             // 是否要求跨组（研究 vs 风控）
    forbidden_roles: string[];          // 如 worker / subagent 永不入审批池
  };
  evidence: {
    required: string[];                  // 如 ["spec:v{n}", "okr:krs", "backtest:report"]
    min_evidence_count: number;
    must_show_diff: boolean;             // 审批卡必须展示变更 diff
  };
  sla: {
    minutes: number;
    on_timeout: "remind" | "escalate";   // 禁止 auto_approve
    remind_max_times: number;            // 类比飞书 24h 催办 1 次
  };
  escalation: {
    after_minutes: number;
    to_roles: string[];
    on_exhausted: "block";               // 兜底永远阻塞
  };
  rejection: {
    require_comment: true;
    rewind_to: GateKind | "none";        // 默认回到上一道门，而非终止
  };
  bypass: {
    allowed: false;                      // 全局默认不允许
    roles?: string[];                    // 开启时限定角色
    max_uses?: number;
    requires_reason: true;
  };
  preauthorized: {
    enabled: false;                      // 仅 standard + low risk 可开
    ttl_hours?: number;
    max_uses?: number;
    require_regression_evidence: true;
  };
  audit: {
    immutable: true;
    retention_days: number;              // ≥ 业务审计要求（类比飞书 180 天）
    include_prompt_version: true;
  };
  notify: {
    on_request: string[];
    on_approve: string[];
    on_reject: string[];
    on_escalate: string[];
  };
}
```

**示例：量化研判任务（risk_level = high）**

```json
{
  "gate_id": "acceptance",
  "kind": "acceptance",
  "title": "验收确认",
  "applies_to": { "task_types": ["trading_analysis"], "risk_levels": ["high"], "change_classes": ["normal"] },
  "approver": { "roles": ["risk_reviewer"], "quorum": "all", "min_distinct": 2, "allow_self_approve": false, "allow_delegate": false, "allow_add_signer": false },
  "gate_model": { "class": "gate", "model_ids": ["qwen4-max", "jev-latest"], "quorum": "all", "min_distinct_models": 2, "deny_same_provider": true, "deny_same_family": true, "allowed_capabilities": [], "temperature": 0, "on_invalid_output": "needs_human" },
  "model_tickets": { "model_vote_weight": "advisory", "human_ticket_required_above": "medium" },
  "sod": { "deny_same_actor": true, "deny_same_org": true, "forbidden_roles": ["worker", "subagent", "c_drive"] },
  "evidence": { "required": ["okr:krs", "data_quality:resolved"], "min_evidence_count": 1, "must_show_diff": false },
  "sla": { "minutes": 120, "on_timeout": "escalate", "remind_max_times": 1 },
  "escalation": { "after_minutes": 240, "to_roles": ["team_lead"], "on_exhausted": "block" },
  "rejection": { "require_comment": true, "rewind_to": "dispatch" },
  "bypass": { "allowed": false },
  "preauthorized": { "enabled": false, "require_regression_evidence": true },
  "audit": { "immutable": true, "retention_days": 730, "include_prompt_version": true },
  "notify": { "on_request": ["risk_reviewer"], "on_approve": ["team_lead"], "on_reject": ["c_drive"], "on_escalate": ["team_lead"] }
}
```

**六条不可配置的硬约束**（写进代码，不给配置留口子）：

1. Agent / 子代理**永不**出现在 `approver.roles`；
2. `on_timeout` 不允许为 `auto_approve`；
3. `evidence_ref` 变化时，已批准的同一道门**必定**回到 `waiting`；
4. 门禁状态只能由 `gate.updated` 事件写入，前端不得直接改快照；
5. `gate` 模型必须与所有 `worker` / `judge` 模型异构，同源拒绝启动；
6. `gate.allowed_capabilities` 必须为空，模型票不得单独放行 high / critical 门。

---

## 五、防黑箱 / 防漂移的失效模式清单

| 失效模式 | 症状 | 对应控制 |
| --- | --- | --- |
| 橡皮图章 | 审批时长中位数 < 10s | 强制展示 diff / 证据摘要；高风险门要求填写意见 |
| 审批疲劳 | 单人待办积压 > N | 待办限流、按风险排序、低风险合并 |
| 自批 | producer == approver | `deny_same_actor` 服务端校验 |
| 过期授权 | 证据已 v3，仍按 v2 通过 | `reconcileGates` 证据版本重置 |
| 静默旁路 | 管理员手改状态 | 只接受事件写入；旁路必须走 `bypass` 且留痕 |
| 超时放行 | 超时后任务继续跑 | `on_timeout` 仅提醒/升级；兜底 `block` |
| 门禁篡改进度 | 已执行却显示"未派工" | 进度只由事实推导，门禁用 `status` 表达 |
| 驳回即终止 | 一次驳回丢掉全部上下文 | `rewind_to` 回到指定门，保留已有证据 |
| 例外永久化 | 临时放行变成长期规则 | 例外带 `expires_at` + 到期告警 |
| 黑箱推进 | 界面只显示"进行中" | 每步必须有证据与结论，缺失进 `data_quality` |
| 同模型自审 | 生产与审批是同一模型 | 模型注册表强制异构，启动即拒 |
| 假独立会签 | 同一模型多实例被当成多票 | 按 `provider + model` 去重计票 |
| 门禁模型被注入 | 证据文本诱导 gate 模型放行 | gate 只读结构化摘要，原文标记为不可信输入；输出 schema 校验 |
| 模型故障静默放行 | gate 超时 / 5xx 后任务继续 | 一律 `needs_human` 并阻塞 |

---

## 六、对 Spec 的 16 条设计要求

1. 五道门 `intent / spec / dispatch / acceptance / summary` 全部由 `GatePolicy` 驱动，策略可配、代码不写死；
2. 门禁裁决在服务端，未确认返回 409 并带 `pending_gates[]`；
3. `approver.roles` 与 `sod` 在服务端校验，前端只做展示与提交；
4. 门禁与证据版本绑定，证据变化自动失效；
5. 超时只提醒/升级，禁止自动通过；
6. 驳回必填原因，并按 `rewind_to` 回转到指定门；
7. 高风险门要求 `min_distinct >= 2`，且禁止自批、禁止 Agent 参与审批；
8. 例外与旁路必须有理由、有期限、进审计；
9. 门禁事件 append-only，可按 `seq` 回放；
10. 门禁不篡改进度，进度只由事实推导；
11. 审批入口同时存在于对话流（内联卡）与看板（GateBar），两处共享同一服务端状态；
12. 所有策略变更本身也要留痕（谁改了哪条策略、改前改后）；
13. 模型注册表至少含 `judge / worker / gate` 三类，启动期校验齐全；
14. `gate` 模型与生产模型异构，只读、无工具、`temperature=0`，不可用即阻塞；
15. 会签按 `provider + model` 去重，高风险门要求 `min_distinct_models ≥ 2`；
16. 模型票只能作为预审意见，high / critical 门必须有人工票。

---

## 七、待验证问题（下一轮）

1. **策略存储**：已定 —— 代码常量 + 启动期校验（`gate-policy.ts`），避免运行期随意改。
2. **角色来源**：已定 —— 本地角色配置表（`roles.ts`），`GATE_TEAM_LEADS / GATE_RISK_REVIEWERS / GATE_ADMINS`；未配置时 bootstrap，本地单用户可用。
3. **紧急通道**：首版是否开启？建议默认关闭，等 PIR 事件链路就绪再开。
4. **保留期**：JSONL 永久 + 快照重建，是否需要压缩策略？
5. **审批疲劳阈值**：单人待办上限取值需实测，先设 20 并观测。
6. **gate 模型接入**：已定 —— 主 `qwen4-max` + 副 `jev-latest`，异构会签；JEV 只做验收语义。
7. **加签后是否重新会签**：已定 —— 是；任何加签都使该节点既有批准失效，避免"先批后加人"绕过。
8. **转交是否可转给下级**：默认否；只允许同角色组或上级，且高风险验收门禁止转交。
9. **空审批人策略**：已定 —— 升级管理员 + 阻塞，禁止自动通过。
10. **超时升级给谁**：先按 `escalation.to_roles`，无配置则管理员；两次升级后仍无人处理则保持阻塞并进入待办中心。
11. **OKR 评分人**：生产者自评 + 独立验收人评分；差异 >0.2 触发复核，Agent 不得做自己任务的唯一评分人。
12. **流程模板数量**：首版只做 4 个（标准 / 高风险 / 紧急 / 热修），避免流程爆炸。
13. **GateFlow 是否允许前端自由编排**：允许声明式编排，但必须过 12 条编译期校验；禁止脚本与自由文本条件。

---

## 八、参考来源

- [财政部等五部委《企业内部控制基本规范》（财会〔2008〕7 号）](https://kjs.mof.gov.cn/zhengcefabu/200807/t20080704_55982.htm)
- [MAS Guidelines on Risk Management Practices – Internal Controls（Delegation of Authority）](https://www.mas.gov.sg/-/media/mas-media-library/regulation/guidelines/bd/guidelines-on-risk-management-practices--internal-controls/guidelines-on-risk-management-practices--internal-control-jul-2014.pdf)
- [Stage-Gate International: The Stage-Gate Model – An Overview](https://www.stage-gate.com/blog/the-stage-gate-model-an-overview/)
- [Stage-Gate International: Discovery-to-Launch Process（Gates 结构）](https://www.stage-gate.com/about/stage-gate-innovation-performance-framework/discovery-to-launch-process/)
- [Maker-Checker Approval Workflow: 12 Controls That Reduce Risk](https://cogniver.com/insights/maker-checker-approval-workflow)
- [A case study of separation of duty properties（four-eyes, eLaw）](https://geni.orbit-lab.org/raw-attachment/wiki/Internal/Rbac/RbacResources/p1328-schaad.pdf)
- [ITIL Change Management – CAB / ECAB](https://status.octopus-itsm.com/en/articles/change-management-itilr-process)
- [ITIL Change Categories: Standard, Normal, Emergency](https://blog.invgate.com/what-are-the-itil-change-categories)
- [Toyota Production System（Jidoka / Andon）](https://global.toyota/en/company/vision-and-philosophy/production-system/)
- [Andon Cord vs Andon Light](https://www.fabrico.io/sr/blog/andon-cord-vs-andon-light/)
- [Delegation of Authority (DoA) Framework](https://umbrex.com/resources/frameworks/organization-frameworks/delegation-of-authority-doa-framework/)
- [COSO CE-3: Organizational Structure, Authority, and Responsibility](https://learn.daydream.ai/requirements/coso-ce-3)
- [OWASP AI Agent Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html)
- [OWASP Top 10 for Agentic Applications 2026（Least Agency）](https://a3539025-c269-438f-994b-aa26ba5d5571.usrfiles.com/ugd/a35390_2f56bf1f78894de8940d6b051c54a592.pdf)
- [Self-Preference Bias in LLM-as-a-Judge](https://arxiv.org/pdf/2410.21819)
- [Replacing Judges with Juries: Panel of LLM Evaluators (PoLL)](https://arxiv.org/pdf/2404.18796)
- [Chain-of-Models: Cross-Model Auditing for Bias-Robust LLM Judges](https://arxiv.org/pdf/2607.28636)
- [TriAdReview: Triangular Adversarial Review Architecture（多模型对抗评审）](https://arxiv.org/html/2606.15074)
- [LLMs as a Jury: Cross-Model Consensus](https://arxiv.org/html/2607.10139v2)
- [飞书帮助中心：管理员设计审批流程](https://www.feishu.cn/hc/zh-CN/articles/360036163653-%E7%AE%A1%E7%90%86%E5%91%98%E8%AE%BE%E8%AE%A1%E5%AE%A1%E6%89%B9%E6%B5%81%E7%A8%8B)
- [飞书帮助中心：管理员设置审批流程并行分支](https://www.feishu.cn/hc/zh-CN/articles/046280562486-%E7%AE%A1%E7%90%86%E5%91%98%E8%AE%BE%E7%BD%AE%E5%AE%A1%E6%89%B9%E6%B5%81%E7%A8%8B%E5%B9%B6%E8%A1%8C%E5%88%86%E6%94%AF)
- [飞书帮助中心：管理员设置转交、加减签、回退审批](https://www.feishu.cn/hc/zh-CN/articles/360049067381-%E7%AE%A1%E7%90%86%E5%91%98%E8%AE%BE%E7%BD%AE%E8%BD%AC%E4%BA%A4-%E5%8A%A0%E5%87%8F%E7%AD%BE-%E5%9B%9E%E9%80%80%E5%AE%A1%E6%89%B9)
- [Lark 审批用户手册（前加签 / 并加签 / 后加签）](https://www.larksuite.com/hc/zh-CN/articles/374839901090-lark-%E5%AE%A1%E6%89%B9%E7%94%A8%E6%88%B7%E6%89%8B%E5%86%8C)
- [飞书审批更新日志 2025-07-04（加签 / 终止 / 操作记录）](https://ae.feishu.cn/hc/zh-CN/articles/447394169853)
- [飞书帮助中心：飞书 OKR 管理员操作手册（打分与提醒）](https://www.feishu.cn/hc/zh-CN/articles/360044794554-%E9%A3%9E%E4%B9%A6okr-%E7%AE%A1%E7%90%86%E5%91%98%E6%93%8D%E4%BD%9C%E6%89%8B%E5%86%8C)
- [飞书帮助中心：多维表格高级权限角色介绍](https://www.feishu.cn/hc/zh-CN/articles/539823920318-%E5%A4%9A%E7%BB%B4%E8%A1%A8%E6%A0%BC%E9%AB%98%E7%BA%A7%E6%9D%83%E9%99%90%E8%A7%92%E8%89%B2%E4%BB%8B%E7%BB%8D)
- [飞书帮助中心：多维表格工作流和自动化流程常见问题](https://www.larksuite.com/hc/zh-CN/articles/341195680493-%E5%A4%9A%E7%BB%B4%E8%A1%A8%E6%A0%BC%E5%B7%A5%E4%BD%9C%E6%B5%81%E5%B8%B8%E8%A7%81%E9%97%AE%E9%A2%98)
- [飞书帮助中心：设置点击按钮为工作流和自动化触发条件](https://www.feishu.cn/hc/zh-CN/articles/804644015036)
- [飞书帮助中心：人工任务限时处理规则设置](https://ae.feishu.cn/hc/zh-CN/articles/040278301653)
- [飞书帮助中心：使用审批效率诊断](https://www.feishu.cn/hc/zh-CN/articles/633271366142-%E4%BD%BF%E7%94%A8%E5%AE%A1%E6%89%B9%E6%95%88%E7%8E%87%E8%AF%8A%E6%96%AD)
- [飞书帮助中心：飞书 OKR 使用常见问题（O 不打分）](https://www.feishu.cn/hc/zh-CN/articles/397323596739-%E9%A3%9E%E4%B9%A6okr-%E4%BD%BF%E7%94%A8%E5%B8%B8%E8%A7%81%E9%97%AE%E9%A2%98)
- [飞书帮助中心：查看多维表格的历史记录](https://www.feishu.cn/hc/zh-CN/articles/263286036719-%E6%9F%A5%E7%9C%8B%E5%A4%9A%E7%BB%B4%E8%A1%A8%E6%A0%BC%E7%9A%84%E5%8E%86%E5%8F%B2%E8%AE%B0%E5%BD%95)
- [飞书帮助中心：高级权限的行列权限说明](https://www.feishu.cn/hc/zh-CN/articles/915018184717-%E9%AB%98%E7%BA%A7%E6%9D%83%E9%99%90%E7%9A%84%E8%A1%8C%E5%88%97%E6%9D%83%E9%99%90%E8%AF%B4%E6%98%8E)
- [飞书项目：可视化工作流与节点流](https://project.feishu.cn/home/product)
