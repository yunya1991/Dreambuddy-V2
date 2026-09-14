# Z1 扫描报告 — PROP-20260829C 统一意图引擎：边界与门禁

> 2026-08-29 | 四维扫描法（入口/结构/数据/历史）| 范围：3-FRONTEND/dream-universal-gateway 意图层 + 鉴权基座 + DreamOS 契约面
> 路径根：`~/Dreambuddy-V2-main/3-FRONTEND/dream-universal-gateway`

---

## 1. 入口扫描

| 类型 | 入口 | 位置 | 状态 |
|:---|:---|:---|:---:|
| 识别 | chat route 内联（9 意图，rule+LLM） | app/api/chat/route.ts L454/L633 | 现网主链 |
| 识别 | fallback-engine `recognizeIntent` | lib/intent/fallback-engine.ts L584 | 仅 task-manager 消费 |
| 识别 | llm-planner `recognize_intent` FC（5 意图） | lib/orchestration/llm-planner.ts L232 | /api/orchestrate |
| 识别 | **intent-unified `recognizeIntentUnified`** | lib/intent/intent-unified.ts L125 | **零接线** |
| 写入 | /api/intent/memory 4 动作（record/feedback/evolve/adopt） | app/api/intent/memory/route.ts | 🔴 零鉴权 |
| 门禁 | smart-router `routeIntent`：developer L335 / command L364 / FREE 拦截 L384,L411 / scenario_sim L441 / 环映射 L575-587 | lib/intent/smart-router.ts | 现网消费 |
| 契约 | intent-schema.ts：INTENT_CANON(35) / PLANNER_ALIASES / LEGACY_VIEW / CANON_TO_LEGACY / **gateAllows() 草案** | lib/intent/intent-schema.ts | 已建未强制 |
| 鉴权 | auth.ts L125 `export { handlers, auth, signIn, signOut } = NextAuth(authConfig)` | lib/auth.ts | 服务端 auth() 可用待实测 |

## 2. 结构扫描（含多副本漂移检测）

**依赖图（intent-unified 管道）**：
```
recognizeIntentUnified
 ├─ detectFollowUp / matchCommandFastpath（零 LLM 快路径）
 ├─ callLLM ← @/lib/orchestration/llm-bridge（⚠️ 非 fallback-engine 的 callLLM）
 │    └─ repairIntentArgs（修复级联，已内置）
 ├─ matchRuleEngine / defaultFallback ← fallback-engine 复用
 └─ finalize → canonToLegacy → routeIntent（smart-router，门禁保留）
```

**多副本漂移检测结果**：
| 项 | 状态 |
|:---|:---|
| LLM 配置 | 部分收敛：fallback-engine 已迁 `getGatewayLLMConfig()`（lib/llm-config.ts L26 共享模块）；chat route L147-150 仍内联 env（有 08-28 P0 修复注释）；llm-bridge 保留 PROVIDER_DEFAULTS（dashscope=qwen3.8-max / deepseek=deepseek-chat） |
| 命名分歧 | 契约层已修：risk_alert ↔ risk_alert_response 双向映射（PLANNER_ALIASES + CANON_TO_PLANNER） |
| 同名导出冲突 | 仍存在：fallback-engine 与 llm-planner 同名 `recognizeIntent`（统一后仅留一个公开导出） |
| 意图集覆盖 | chat 内联 9 意图 + fallback 15 意图**全部**在 canon/legacy 视图内（concept_explain、market_sentiment 为 canon 场景意图；developer/triple_chain/need_clarification/clarification_result 在 LEGACY_VIEW）→ 映射无缺口 |

**🔴 关键结构事实**：PROP-20260828B 产物**从未入库**——`git status`：
- untracked：intent-schema.ts / intent-unified.ts / command-fastpath.ts / intent-args-repair.ts
- modified：fallback-engine.ts / intent-memory.ts
- 意图层 git 历史仅 3 个提交（初始上传 / P0-P3 修复 / 前端桥）

## 3. 数据扫描（含可用性验证）

| 数据 | 现状 | 可用性结论 |
|:---|:---|:---|
| intent-memory/records.json | 11 条，字段全空（intent='?'） | ❌ 黄金集不可依赖存量 |
| experience-memory.json v1.1 | 6 patterns，含"当前美"类截断垃圾 | ❌ 质量不足，晋升基准需重建 |
| quarantine 隔离仓 | 不存在 | 待建 |
| 黄金集 | 不存在 | 手写 ≥20 条 |
| **Prisma User.role** | 字段存在，`enum UserRole { FREE PRO ADMIN }` | ✅ 门禁数据基础就绪 |
| gateAllows() 角色×意图表 | intent-schema.ts 内置草案，注释"未接入强制" | ✅ 可直接接入 |

## 4. 历史扫描（P0 痕迹，迁移必须显式保留）

| 痕迹 | 位置 | 内容 |
|:---|:---|:---|
| P0 | fallback-engine.ts L153 | `enable_thinking:false`（qwen3 思考链 15s 超时修复）；llm-bridge 无此参数 → intent-unified 主路径风险敞口 |
| P0 | chat route L147 | "优先 DashScope key 兼容旧 DEEPSEEK_API_KEY"修复注释 |
| P0 | chat route callDeepSeekAPI | 60s 超时 / max_tokens=2000 / enable_thinking:false |
| 增强 | intent-unified L182 | repairIntentArgs 修复级联已接（Hermes 迁移映射 08-28 落地） |
| 增强 | intent-unified L176 | timeoutMs 默认 30s |

---

## ⚠️ Z1 推翻/修订 D4 假设（显式记录）

| # | D4 假设 | Z1 实测 | 修订 |
|:---:|:---|:---|:---|
| 1 | 映射层需新建 | intent-schema 已有双向无损映射（15 legacy 恒等 + 20 场景归并父类 + planner 11 型双向），chat/fallback 意图集全覆盖无缺口 | Phase 3 映射工作量大幅缩减，仅剩 **35↔6（DreamOS 战略意图）canon→strategy 映射** + 环归属验证 |
| 2 | 基于 auth-runtime.ts 建门禁 | auth-runtime.ts 仅 31 行 URL/trustHost 选项工厂，**不可用** | 门禁基座改为 auth.ts 服务端 `auth()`（next-auth v5）+ Prisma User.role；**先实测** Next 15.5 下 route handler 内 auth() 可用性，不可用则手工验签 JWT（同 secret）兜底 |
| 3 | 角色门禁需设计 | intent-schema 已内置 gateAllows() 草案（角色×意图最小角色表） | Phase 2 直接接入强制，省设计工作 |
| 4 | （未预见） | PROP-20260828B 产物全部未提交（4 untracked + 2 modified） | **Phase 0 前置动作**：先提交/归档现有产物建立基线，再开新工作 |

## 产出交接
→ Z2 范围划分读取本报告；重点切分：基线入库 / 黄金集+影子 / 门禁（auth 实测先行）/ 切主+canon→strategy / 优化闭环成文
