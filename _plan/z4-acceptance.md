# Z4 验收方案 — PROP-20260829C 统一意图引擎：边界与门禁

> 2026-08-29 | P0-P3 四级验收矩阵 | 输入：`_plan/z3-implementation-plan.md`
> E3 门禁规则：**P0 任一项不过 = 阻塞，不得进入 E3 后续阶段**；P1 一致率不达标禁止切流。
> 证据留存：每项验收的命令输出存 `_plan/z4-evidence/<编号>.txt`。
> 验收环境：dev 环境 Gateway（next dev）+ DreamOS 本地实例；最终批准人：用户。

---

## P0 阻塞级 — 静态基线（不过=不进 E3）

| # | 验收项 | 方法 | 通过判据 |
|:---:|:---|:---|:---|
| 0.1 | 基线提交范围干净 | `git show --stat <baseline-commit>` | 仅含任务文件（src/lib/intent/ 6 文件 + 提案/计划文档），**任务外文件 0 个** |
| 0.2 | 意图层编译 | `npx tsc --noEmit`（GW 根） | 0 error |
| 0.3 | 黄金集分布达标 | 校验脚本读 `tests/intent/golden-set.json` | ≥20 条 且：15 legacy 各≥1、场景≥3、门禁分支 4 类（developer/command/execute_trade+FREE/scenario_sim+FREE+complex）、4 环映射、follow_up≥2、低价值≥2，全部满足 |
| 0.4 | offline harness 全绿 | `npx vitest run tests/intent`（offline 模式） | 全绿，零 LLM 调用（日志无模型请求） |

## P1 核心功能 — 影子期（切流前置）

| # | 验收项 | 方法 | 通过判据 |
|:---:|:---|:---|:---|
| 1.1 | 影子一致率 | 统计脚本跑 `intent-shadow/shadow.jsonl` | **一致率 ≥95%**（一致样本/总样本，样本≥200 或观察满 3 天） |
| 1.2 | 影子预算上限生效 | 代码审查 + 单测模拟计数 | 200 样本自动停影子；影子调用 `max_tokens≤50` |
| 1.3 | 旧路径零回归 | 影子期请求日志抽查 | 所有响应用旧结果（method=legacy 为准），影子只记日志不干预 |
| 1.4 | P0 痕迹继承 | `grep -c enable_thinking src/lib/orchestration/llm-bridge.ts` | ≥1（dashscope/deepseek 分支均有） |

## P2 安全门禁 — 记忆污染封闭

| # | 验收项 | 方法 | 通过判据 |
|:---:|:---|:---|:---|
| 2.1 | 写入门禁三连 | curl：匿名 record / FREE evolve / ADMIN adopt | 401 / 403 / 200 且候选进隔离仓（不落 experience-memory） |
| 2.2 | 直写路径零命中 | `grep -rn "adoptCandidate" GW/src/app`；`grep -rn "writeExperienceMemory" GW/src/app` | 两者均 **0 命中** |
| 2.3 | 隔离仓完整性 | 单测：并发追加 + 只追加语义 | append-only 成立，无覆盖写，互斥生效 |
| 2.4 | 价值过滤 | 发 <4 字符/问候语/无实体输入 | 不落 records 盘（仅内存统计） |
| 2.5 | 热路径异步化 | `grep -n "writeFileSync" src/lib/intent/intent-memory.ts` 热路径段 | 同步全量写已移除，防抖批量 flush 生效（2s/50 条） |
| 2.6 | 角色门禁三态 | INTENT_ROLE_GATE=off/shadow/on 各测 1 次 | off=不拦 / shadow=放行+记日志 / on=拦截+upgrade_required |

## P3 集成切流 — 主路径切换

| # | 验收项 | 方法 | 通过判据 |
|:---:|:---|:---|:---|
| 3.1 | FC 主路径实测 | `INTENT_METHOD=fc` 后发对话 | 日志 method=fc，响应正常 |
| 3.2 | canon→strategy 映射 | 校验脚本遍历 `CANON_TO_STRATEGY` | 35 canonical 全覆盖，无悬空键，均落到 6 战略意图+环 |
| 3.3 | DreamOS canon 字段 | `curl /api/v1/intent` | 响应含 `canon` 字段，既有字段不变 |
| 3.4 | 门禁分支回归 | online harness + 手工 4 例（developer/command/FREE 拦截/scenario_sim） | 全绿 |
| 3.5 | **回滚演练（必做）** | fc → llm 切回 | <1 分钟完成，行为与基线一致，无报错 |
| 3.6 | 闭环成文 | 检查文档 + 演练记录 | `intent-optimization-loop.md` 存在；晋升演练含通过 1 条 **+ 拒绝 1 条** |

---

## 验收时序与门禁链

```
P0 全过 ──► E3 启动 P1/P2/P3 实施
P1 一致率≥95% ──► 才允许 P3 切流（3.1-3.4）
P2 全过 ──► 才允许对外开放任何记忆写入
3.5 回滚演练通过 ──► 交付前置条件
全部通过 + 用户批准 ──► E3 关闭，进入 Step 3（知识库）
```

**失败处置**：任何一级不过 → 回 E1 修复 → 重验该级全项（不只验单项）。一致率<95% → 差异归因→修复→重新观察，禁止带病切流。

→ E1 读取 Z3 执行、E3 读取本文件验收；本矩阵与 Z3 Phase 一一对应（P0↔Phase0、P1↔Phase1+2、P2↔Phase3、P3↔Phase4+5）。
