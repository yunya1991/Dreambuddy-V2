# Z2 范围划分 — PROP-20260829C 统一意图引擎：边界与门禁

> 2026-08-29 | 三原则切割：最小可验收 / 依赖排序 / 每阶段回滚点
> 输入：`_plan/z1-scan-report.md`（含 4 项 D4 假设修订）

---

## D4 Spec 修订记录（Z1 实测驱动，逐条留痕）

| # | 修订项 | 依据（Z1 实测） |
|:---:|:---|:---|
| R1 | Phase 3 映射工作量缩减：旧链映射已由 intent-schema 双向覆盖，仅新建 35↔6 canon→strategy | 映射无缺口实测（15 legacy 恒等 + 20 场景归并 + planner 11 型） |
| R2 | 门禁基座由 auth-runtime.ts 改为 auth.ts 服务端 auth() + Prisma User.role，首步为可用性探针 | auth-runtime.ts 仅 31 行 URL 工厂 |
| R3 | 角色×意图门禁不新设计，直接强制接入 gateAllows() 草案 | intent-schema 内置草案实测 |
| R4 | 新增 Phase 0 基线入库（D4 未预见） | 4 untracked + 2 modified 从未提交 |

---

## 阶段切分（6 阶段）

### Phase 0 — 基线入库（依赖根）
| 项 | 内容 |
|:---|:---|
| 做什么 | 提交 PROP-20260828B 产物（intent-schema/unified/command-fastpath/intent-args-repair + fallback-engine/intent-memory 修改）+ 提案文档；打基线标记 |
| 最小可验收 | 意图层 `git status` 干净；基线 commit 存在且可 diff |
| 回滚点 | git reset 可退（纯归档，无行为变更） |
| 依赖 | 无 |

### Phase 1 — 黄金集 + 回归 Harness（质量基线）
| 项 | 内容 |
|:---|:---|
| 做什么 | 手写 ≥20 条黄金集（覆盖 35 意图分布 + smart-router 门禁分支标记：developer/command/FREE 拦截/scenario_sim/环映射）；vitest harness：对 intent-unified 与旧链分别跑集合并输出一致率 |
| 最小可验收 | harness 可执行出报告；门禁分支覆盖清单逐项有 case |
| 回滚点 | 纯新增（tests/ 目录），删除即净 |
| 依赖 | Phase 0 |

### Phase 2 — P0 痕迹继承 + 影子接线（安全观察）
| 项 | 内容 |
|:---|:---|
| 做什么 | ① llm-bridge 补 `enable_thinking:false`（对齐 fallback-engine L153 P0 痕迹）② chat route 接 INTENT_METHOD=fc_shadow：新旧同跑、**旧结果为准**、差异写影子日志 |
| 最小可验收 | 影子日志采集 ≥200 样本或 3 天（取先到）；意图识别延迟实测回归正常区间（思考链关闭验证） |
| 回滚点 | INTENT_METHOD 环境变量关闭影子，零代码回滚 |
| 依赖 | Phase 0（与 Phase 1/3 **文件无交集，可并行**：仅触 chat route + llm-bridge） |

### Phase 3 — 门禁封闭（安全面，独立价值）
| 子步 | 内容 |
|:---|:---|
| 3a 探针 | auth() 可用性实测：Next 15.5 route handler 内 next-auth v5 服务端会话；不可用 → 手工验签 JWT（同 secret）兜底 |
| 3b 写门禁 | /api/intent/memory：record/feedback=登录，evolve/adopt=ADMIN；gateAllows() 接入强制（意图×角色） |
| 3c 隔离仓 | quarantine 存储（进程内互斥）；adoptCandidate 直写经验库路径移除；价值过滤（<4 字符/纯问候/无实体不落 records） |
| 最小可验收 | curl 未授权写 = 401；全仓 grep 反馈直写经验库路径 = 0；隔离仓抽样可查 |
| 回滚点 | 纯增量撤除即复原（回滚=污染面重现，限回滚期） |
| 依赖 | Phase 0（与 Phase 1/2 并行：仅触 memory route + auth + intent-memory 写路径） |

### Phase 4 — 切主 + canon→strategy 映射
| 项 | 内容 |
|:---|:---|
| 做什么 | ① 影子一致率 ≥95% → INTENT_METHOD=fc 默认（保留 llm/rule 回滚开关）② 35↔6 canon→strategy 映射表（含环归属）③ DreamOS /intent 响应加 canon 字段（增量）④ smart-router 门禁分支回归用例全绿 |
| 最小可验收 | AC2/AC6 + 黄金集全绿 + 门禁分支回归通过 |
| 回滚点 | INTENT_METHOD 一键切回旧路径（旧代码保留=结构性回滚） |
| 依赖 | Phase 1（harness）+ Phase 2（影子数据）——**硬依赖，不可提前** |

### Phase 5 — 研发域优化闭环成文（文档，非代码）
| 项 | 内容 |
|:---|:---|
| 做什么 | 黄金集回归脚本入仓；优化流程成文：调优 → 黄金集回归 → 提案 → 飞书审批 → canonical 版本晋升（单向阀）；隔离仓首批候选走完整晋升演练（**必须包含一次"拒绝"路径**） |
| 最小可验收 | 流程文档落盘；演练记录（通过+拒绝各一） |
| 回滚点 | 文档类，N/A |
| 依赖 | Phase 3（隔离仓存在） |

---

## 依赖图与并行机会

```
Phase 0 基线入库（依赖根）
   ├─→ Phase 1 黄金集+Harness ──┐
   ├─→ Phase 2 影子接线 ────────┼─→ Phase 4 切主+映射（硬依赖 1+2）
   └─→ Phase 3 门禁封闭 ────────┴─→ Phase 5 闭环成文
        （P1/P2/P3 文件无交集，可并行）
```

**关键路径**：P0 → P2（影子观察期 3 天为最长计时器）→ P4。P1/P3 在观察期内并行完成。

## 阶段×验收标准映射（对照 D4 AC）

| Phase | 覆盖 AC |
|:---:|:---|
| P1 | AC1 |
| P2 | AC5 |
| P3 | AC3, AC4, AC7（异步写可并入 3c 或降级 P2 后续） |
| P4 | AC2, AC6 |
| P5 | AC8 |

→ Z3 路径设计读取本报告：每步具体操作 + 验证 + 回滚反向操作 + token 预估；**Z3 必须处理**：3a 探针失败的兜底分支、影子期双倍 token 预算上限。

---

## 补遗 — 双轨大脑架构定位（2026-08-29 用户对齐确认，不改本提案范围）

**用户确认的完整链路**：五官（前端意图识别=是什么）→ 大脑（Hermes=怎么处理）→ 神经网络（DreamOS=组织协调）→ 执行工具（子域能力节点）→ 大模型汇总输出。

**双轨分工（本提案的架构前提）**：

| 轨 | 承担者 | 职责 | 特性 |
|:---|:---|:---|:---|
| 脊髓反射（在线快路径） | Gateway 规则快路径 + 意图映射 + LLM | 简单/高并发请求：识别→路由→执行→汇总 | 低延迟，Hermes 仅借出模型能力 |
| 大脑皮层（异步慢思考） | Hermes Agent 本体 | 复杂问题：调用**认知系统（mcp_cognitive_*）+ 知识库 + 经验 Skill + 联网搜索**提供解决方案，甚至扩展系统尚不具备的能力 | 单实例不接高并发，走异步/治理通道 |

**核实留痕（2026-08-29 实测）**：
1. Gateway 内"Hermes 记忆学习 / Hermes 记忆系统"（chat route L2461/L3926/L4323/L4909）为**本地 userPrefMemory 实现**，非真 Hermes 远程调用（无 fetch 至 hermes/cognitive 端点）；
2. `src/lib/intent/smart-router.ts` 与 `src/lib/intent-router.ts` 对 hermes/delegate/handoff/agent_session **零命中** —— 在线链路无"复杂意图→Hermes 会话"移交通道。

**结论**：大脑皮层轨目前存在于 Gateway 之外（飞书直连 + cron）。**扩展点（不在本提案范围，未来单独立项）**：复杂意图判定 → 异步委托 Hermes 会话（携带认知系统/知识库/Skill/联网能力）→ 结果回传前端。本提案 P4 的 INTENT_METHOD 开关与 35 canonical 分类已为该扩展点预留判定基础（复杂度/环归属字段）。

