# Z3 实施路径 — PROP-20260829C 统一意图引擎：边界与门禁

> 2026-08-29 | 四步推导：前置条件 → 执行步骤（做什么+怎么做+验证）→ 回滚反向操作 → token 预估
> 输入：`_plan/z2-boundaries.md` | 消费方：E1 执行者（本文件须自包含，含精确路径）
> 路径根：`~/Dreambuddy-V2-main`（前端根：`3-FRONTEND/dream-universal-gateway`，下称 GW）

---

## 1. 前置条件

| 项 | 内容 | 验证 |
|:---|:---|:---|
| 审批 | 本提案（PROP-20260829C）走飞书审批获批后方可动 Phase 1+ 代码；Phase 0 基线入库可先行（纯归档无行为变更） | 审批实例 timeline 有人工批准 |
| 提交纪律 | 共享仓库：`git add` 只圈定本任务文件，**禁 add -A / add .**；提交前 `git status` 排除他工作流变更 | 每次提交前检查 |
| 依赖 | vitest 已就位（GW/tests/ 已有用例）；手工验签兜底用 jose（next-auth 传递依赖，E1 先 `grep jose GW/package.json node_modules 确认`，缺失才装） | npx vitest --version |
| 环境变量 | 新增 `INTENT_METHOD`（fc_shadow / fc / llm / rule，缺省=现状内联）、`INTENT_ROLE_GATE`（off / shadow / on，缺省 off） | .env 登记 |
| 解释器 | 门禁脚本用 `~/.hermes/hermes-agent/venv/bin/python3` | — |

---

## 2. 执行步骤

### Phase 0 — 基线入库（可先行，~10min，~5k token）

| # | 做什么+怎么做 | 验证 |
|:---:|:---|:---|
| 0.1 | `cd GW && git status --short` 确认脏文件=Z1 清单（4 untracked + 2 modified，均在 src/lib/intent/） | 与 z1-scan-report §2 一致 |
| 0.2 | `git add src/lib/intent/intent-schema.ts src/lib/intent/intent-unified.ts src/lib/intent/command-fastpath.ts src/lib/intent/intent-args-repair.ts src/lib/intent/fallback-engine.ts src/lib/intent/intent-memory.ts`；提案文档 `../../3-EVOLUTION/proposals/PROP-20260829C-*.md` + `_plan/z1-scan-report.md z2-boundaries.md z3-implementation-plan.md` 按仓库归属分别 add | `git diff --cached --stat` 无任务外文件 |
| 0.3 | commit："chore(gateway): PROP-20260828B 统一意图引擎产物基线入库（PROP-20260829C P0）" | `git log -1` |
| 回滚 | `git reset --soft HEAD~1`（文件不丢） | — |

### Phase 1 — 黄金集 + Harness（~1-2h，~30k token）

| # | 做什么+怎么做 | 验证 |
|:---:|:---|:---|
| 1.1 | 手写 `GW/tests/intent/golden-set.json` ≥20 条，字段：`{id, input, user_role, expected_canon, expected_legacy, expected_loop, gate_branch}`。分布硬指标：15 legacy 意图各≥1；场景意图≥3；门禁分支：developer/command/execute_trade+FREE/scenario_sim+FREE+complex 各 1；环映射 4 环各 1；follow_up≥2；低价值输入（<4字符/问候语）≥2 | 分布清单逐项打勾 |
| 1.2 | 写 `GW/tests/intent/harness.test.ts` 双模式：**offline**（默认：只测 rule 快路径/command 快路径/canon 映射/canonToLegacy/gateAllows，零 LLM 零 token）+ **online**（手动触发：真 LLM 比对，跑一致率） | offline 模式 npx vitest run tests/intent 全绿 |
| 1.3 | 输出门禁分支覆盖报告（哪些 gate_branch 有 case） | 报告列出全部分支且非空 |
| 回滚 | 删 `GW/tests/intent/`（纯新增） | — |

### Phase 2 — P0 痕迹继承 + 影子接线（~1h + 观察期 ≤3 天，~15k token）

| # | 做什么+怎么做 | 验证 |
|:---:|:---|:---|
| 2.1 | `GW/src/lib/orchestration/llm-bridge.ts` 请求体构造处补 `enable_thinking: false`（dashscope/deepseek 两分支都加；对齐 fallback-engine L153 P0 痕迹） | `grep -c enable_thinking llm-bridge.ts` ≥1 |
| 2.2 | chat route（`GW/src/app/api/chat/route.ts` 意图识别段 ~L454/L633）接影子：`INTENT_METHOD=fc_shadow` 时，现有内联路径照常出结果（**旧结果为准**），并行调 `recognizeIntentUnified`，差异写 `GW/intent-shadow/shadow.jsonl`（appendFileSync 原子追加） | 本地发 3 条测试消息，shadow.jsonl 有条目且响应走旧结果 |
| 2.3 | **影子预算上限（硬编码）**：计数器满 200 样本自动停影子；影子 FC 调用 max_tokens≤50 | grep 到计数器与上限常量 |
| 2.4 | 部署观察 ≤3 天或 200 样本；期间每日看一次 shadow.jsonl 摘要 | 样本数达标 |
| 回滚 | 移除 `INTENT_METHOD` 环境变量即恢复（零代码） | — |

### Phase 3 — 门禁封闭（~2-3h，~40k token，与 P1/P2 并行）

| # | 做什么+怎么做 | 验证 |
|:---:|:---|:---|
| 3a.1 | **auth() 探针**：写临时探针路由（或 dev 环境现有受保护路由实测）调 `auth()`（GW/src/lib/auth.ts L125 导出）验证 Next 15.5 route handler 内服务端会话可用性 | 探针输出 session/null 明确 |
| 3a.2 | **分支决策**：可用 → 3b 直接用 auth()；不可用 → 写 `GW/src/lib/route-auth.ts`：jose 手工验签会话 cookie（用同一 AUTH_SECRET，算法对齐 next-auth 默认），返回 {uid, role}（role 从 Prisma User 读或 JWT claims） | 探针用例登录/未登录两种态都正确 |
| 3b.1 | `GW/src/app/api/intent/memory/route.ts` 加门禁：record/feedback 需登录；evolve/adopt 需 `role==='ADMIN'`；未授权 401/403 | curl 三连：匿名 401 / FREE evolve 403 / ADMIN adopt 200 |
| 3b.2 | `gateAllows()`（intent-schema.ts）接入 `INTENT_ROLE_GATE` 开关：shadow=只记日志，on=拦截返回 upgrade_required；缺省 off | 三种模式行为各测 1 次 |
| 3c.1 | 隔离仓：`GW/src/lib/intent/quarantine.ts` — append-only JSONL + 进程内互斥；条目含 {record_id, user_uid, role, feedback, corrected_intent, ts} | 单元级读写测试 |
| 3c.2 | **直写路径移除**：intent-memory.ts 的 `adoptCandidate` 改为非导出（仅晋升流程内部用）；/api/intent/memory 的 adopt 动作改写隔离仓（不再调 adoptCandidate）；experience-memory 写入只留"晋升流程"一条路径 | `grep -rn "adoptCandidate" GW/src/app` = 0 命中；`grep -rn writeExperienceMemory GW/src/app` = 0 |
| 3c.3 | 价值过滤：recordRecognition 前判断 —— 输入 <4 字符 / 命中问候语表 / 无实体 → 只计内存统计不落 records | 低价值样本测试不落盘 |
| 3c.4 | records 异步化：saveToDisk 改防抖批量（2s 或 50 条缓冲），消除热路径 writeFileSync | grep 热路径无同步全量写 |
| 回滚 | `git revert` 本阶段 commit（纯增量；回滚=污染面重现，限回滚期） | — |

### Phase 4 — 切主 + canon→strategy 映射（~2h，~25k token，硬依赖 P1+P2）

| # | 做什么+怎么做 | 验证 |
|:---:|:---|:---|
| 4.1 | 分析 shadow.jsonl：一致率 = 一致样本/总样本；**≥95% 才继续**；<95% → 差异归因（映射缺口/规则缺口/提示词），修复后重新观察，不切流 | 一致率报告落盘 |
| 4.2 | `INTENT_METHOD=fc` 设为默认（.env）；chat route 按开关走 intent-unified 主路径 | 实测对话走 FC（日志 method=fc） |
| 4.3 | 35↔6 映射：intent-schema.ts 增 `CANON_TO_STRATEGY` 表（35 → DreamOS 6 战略意图 + 环归属），数据源=smart-router L575-587 环映射 + DreamOS core/sense 6 意图 | 映射表无悬空键 |
| 4.4 | DreamOS `1-ARCHITECTURE/dreamos/apps/api_server.py` /api/v1/intent 响应加 `canon` 字段（增量，不动既有字段） | curl /intent 见 canon 字段 |
| 4.5 | smart-router 门禁分支回归：跑 P1 online harness + 手工过 developer/command/FREE 拦截/scenario_sim 各 1 例 | 全绿 |
| 回滚 | `INTENT_METHOD` 切回 llm（旧路径代码保留=结构性回滚）；canon 字段为增量无需回滚 | — |

### Phase 5 — 优化闭环成文（~1h，~10k token，依赖 P3）

| # | 做什么+怎么做 | 验证 |
|:---:|:---|:---|
| 5.1 | 写流程文档 `GW/docs/intent-optimization-loop.md`：调优 → 黄金集回归（命令）→ 提案 → 飞书审批 → canonical 版本晋升（单向阀：前端隔离仓数据跨域进认知系统须治理审批，对齐认知边界四规则） | 文档落盘 |
| 5.2 | 晋升演练：隔离仓取首批候选，ADMIN 审核 → 通过 1 条 + **拒绝 1 条**（两条路径都必须走） | 演练记录（含拒绝理由） |
| 回滚 | 文档类 N/A | — |

---

## 3. 回滚预案总表

| Phase | 回滚方式 | 耗时 |
|:---:|:---|:---:|
| P0 | git reset --soft | <1min |
| P1 | 删 tests/intent/ | <1min |
| P2 | 移除 INTENT_METHOD env | <1min |
| P3 | git revert commit | <5min |
| P4 | INTENT_METHOD 切回 llm | <1min |
| P5 | N/A | — |

## 4. Token/预算预估

| Phase | 开发 token | 运行时消耗 |
|:---:|:---:|:---|
| P0 | ~5k | 无 |
| P1 | ~30k | offline harness 零 LLM |
| P2 | ~15k | 影子 ≤200 次小调用（max_tokens≤50），约 ¥1-2 |
| P3 | ~40k（auth 探针为主要不确定项） | 无 |
| P4 | ~25k | online harness 1 次 |
| P5 | ~10k | 无 |
| **合计** | **~125k** | 影子预算硬上限已编码 |

---

→ Z4 验收方案读取本文件：按 Phase 产出 P0-P3 四级验收矩阵（P0 不过=阻塞不进 E3）。
