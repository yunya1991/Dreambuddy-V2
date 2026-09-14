# PROP-20260829C — 统一意图引擎：前后端边界与门禁

> 状态：Z 链完成（Z1 扫描/Z2 边界+双轨补遗/Z3 路径/Z4 验收），飞书审批 PENDING 等人工批准 → 批准后 E 链执行
> 前置提案：PROP-20260828B（统一意图引擎 FC 化，intent-unified.ts 已建未接线）
> 调研依据：2026-08-29 D 系列调研（D1 四准则实测 + D2 三问 + D3 三景推演）
> 用户指令锚点：①旧引擎作回退 ②前后端统一引擎 ③前端多用户并行 ④升级反馈严格过滤防污染 ⑤后端研发域做优化 ⑥边界门禁隔离清晰

---

## 第一段：背景与目标

### 问题
前端意图识别 4 套实现并存（5/9/15 意图语义不互通），统一层 intent-unified（35 canonical）已建但零接线；反馈写入路径**零门禁**（/api/intent/memory 无鉴权 + middleware 不拦 + adoptCandidate 无角色/次数门槛），任何可达用户可直接污染经验库；前后端（前端应用域 × Hermes 研发域）意图形态异构、两套统一 schema（35 canonical vs DreamOS 6 战略意图）无映射。

### 为什么要做
- 意图层是全部下游业务门禁的入口（smart-router 角色门禁依赖意图枚举）——枚举漂移 = 门禁绕过 = 安全级风险
- 污染面已实测存在（D1 准则三），前端进入多用户阶段前必须封闭
- 无统一契约则研发域优化无法安全回流（改了不知道破没破）

### 成功标准（可量化）
| # | 标准 | 等级 |
|:---:|:---|:---:|
| AC1 | 黄金集 ≥20 条（手写，覆盖 35 意图 + smart-router 全门禁分支） | P0 |
| AC2 | 影子比对一致率 ≥95% 后切主；INTENT_METHOD=fc 为默认，旧引擎为降级层 | P0 |
| AC3 | /api/intent/memory：record/feedback 需登录，evolve/adopt 需 ADMIN；未授权写 = 401（curl 实测） | P0 |
| AC4 | 用户反馈 100% 进隔离仓，adoptCandidate 直写经验库路径代码级消除（grep=0） | P0 |
| AC5 | llm-bridge 补 `enable_thinking:false`（继承 fallback-engine L153 P0 修复痕迹） | P0 |
| AC6 | 35↔6 映射层落地：canon→strategy（含环归属）映射表，DreamOS /intent 响应带 canon 字段 | P1 |
| AC7 | records 写入异步批量/队列化，热路径无 writeFileSync 全量重写 | P1 |
| AC8 | 研发域优化闭环成文：黄金集回归脚本 + 晋升走提案审批 | P1 |

### 不做范围
- ❌ 不动 Hermes 运行时（L0/L1/L2/clarify 架构保持原样）
- ❌ 不修全站 next-auth（仅基于 lib/auth-runtime.ts 建轻量路由级门禁；全站修复另立提案）
- ❌ 不建独立意图微服务（D2 方案 B 否决）
- ❌ 不做前端多实例部署支持（记录为已知限制；SQLite 化列为 P2）
- ❌ 不动 A 系列 cron / DreamOS 编排链 / 交易执行链

---

## 第二段：6 要素方案描述（方案 A：分层统一 + 隔离仓）

### 架构

```
┌─ 应用域（前端，多用户，低信任）─────────────────────────┐
│  /api/chat ──→ intent-unified（canonical 管道，唯一主路径） │
│                 ① follow_up 快路径（零 LLM）                │
│                 ② command 快路径（零 LLM，确定性）          │
│                 ③ FC 主路径（llm-bridge + thinking 关闭）   │
│                 ④ 规则引擎（吸收旧 A/B 实现 = 回退层）      │
│                 ⑤ default 兜底                              │
│  用户反馈 ──→ 价值过滤 ──→ 隔离仓(quarantine)              │
│                 （永不直写经验库）                          │
│      晋升门禁: occurrences≥5 ∧ 跨用户≥3 ∨ ADMIN 纠正       │
│                → ADMIN 审核 → experience-memory.json        │
└────────────────────────────────────────────────────┘
        ↕ 契约层（35 canonical = SSoT，冻结）
        ↕ aliasToCanon / canonToLegacy（旧链兼容）
        ↕ canon→strategy 映射（环归属 → DreamOS 6 意图）
┌─ 研发域（Hermes，单用户，高信任）──────────────────────┐
│  LLM 原生意图（L0/L1/L2 不变）+ 同一契约词表             │
│  优化闭环: 黄金集回归 → prompt/规则调优 → 提案审批        │
│            → canonical 引擎版本晋升（单向阀）            │
└────────────────────────────────────────────────────┘
```

### 关键实现路径
1. **契约冻结**：intent-schema.ts 35 canonical 为唯一词表；任何增删走提案审批
2. **引擎收敛**：intent-unified 为唯一识别代码路径；旧 4 套降级为管道内回退层/别名映射
3. **写路径设卡**：读开放、写必须鉴权（默认拒绝）；反馈隔离仓单向阀
4. **域隔离**：前端低信任域只产隔离仓数据；研发域高信任但晋升走审批；跨域无直写

### 依赖
- lib/auth-runtime.ts（轻量鉴权基座；若不可用需先评估其能力——Z1 核实）
- PROP-20260828B 产物（intent-unified.ts / intent-schema.ts / repairIntentArgs 修复级联）
- vitest 既有测试框架（意图层零覆盖，需新建 harness）

### 风险项（D3 事实锚点）
| 风险 | 锚点 | 缓解 |
|:---|:---|:---|
| legacy 映射丢意图 → smart-router 门禁绕过 | 意图层零测试；门禁分支零回归 | 影子模式先于切流；门禁分支逐一回归用例 |
| qwen3 思考链延迟复发 | llm-bridge 无 enable_thinking:false（实测） | Phase 1 强制补上 + 30s 超时兜底已存在 |
| 隔离仓并发写覆盖 | intent-memory 文件写无锁（实测） | 单进程前提 + 进程内互斥；SQLite 化 P2 |
| 影子期双倍 token | orchestrate 链已有同类前科 | 观察期限额（≥200 样本或 3 天，取先到） |

### 里程碑
M0 黄金集 → M1 影子接线 → M2 门禁封闭 → M3 切主+映射 → M4 优化闭环成文

---

## 第三段：多方案对比

| 方案 | 核心思路 | 收益 | 风险 | 工作量 | 结论 |
|:---|:---|:---|:---|:---:|:---:|
| **A 分层统一+隔离仓** | 契约统一+引擎收敛+runtime 隔离+反馈四层闸门 | 贴合全部 6 点要求；复用已建产物；回滚结构性良好 | 映射缺口需迭代 | ⭐⭐⭐ | **推荐** |
| B 独立意图微服务 | 引擎抽独立 HTTP 服务 | 字面单引擎 | 新运维面；可用性耦合；延迟+1 跳 | ⭐⭐⭐⭐ | 否决 |
| C DreamOS /intent 承载 | S 层扩 35 schema 供前端调用 | 复用线程安全服务 | 前端硬依赖 Python 进程（小时级守护扛不住前端流量）；TS 规则库重写 | ⭐⭐⭐⭐ | 否决 |
| D Hermes LLM 作引擎 | 前端调 Hermes | — | 单会话无法多用户并行+上下文污染 | — | 不可行 |

---

## 第四段：实现路径与验收

### Phase 0 — 黄金集（P0）
- 手写 `tests/intent/golden-set.json` ≥20 条：每条含 input/期望 canon/期望 legacy/期望环归属/覆盖的 smart-router 门禁分支标记
- 建 vitest harness：可分别对 intent-unified / 旧链跑集合并输出一致率
- 验收：harness 跑通；门禁分支覆盖清单（developer/command/FREE 拦截/scenario_sim/环映射）逐项有 case

### Phase 1 — P0 痕迹继承 + 影子接线（P0）
- llm-bridge 请求体补 `enable_thinking:false`（对齐 fallback-engine L153 修复）
- chat route 接影子模式：INTENT_METHOD=fc_shadow，新旧同跑、以旧结果为准、差异写影子日志
- 验收：影子日志采集 ≥200 样本或 3 天；思考链关闭实测（响应延迟回归正常区间）

### Phase 2 — 门禁封闭（P0）
- 基于 lib/auth-runtime.ts 建路由级门禁：record/feedback=登录，evolve/adopt=ADMIN
- adoptCandidate 直写路径移除 → 全部入隔离仓（quarantine 存储 + 进程内互斥）
- 价值过滤：输入 <4 字符/纯问候/无实体 → 不落 records
- 验收：curl 未授权写 = 401；全仓 grep 反馈直写经验库路径 = 0；隔离仓抽样可查

### Phase 3 — 切主 + 映射层（P0/P1）
- 影子一致率 ≥95% → INTENT_METHOD=fc 默认；INTENT_METHOD=llm|rule 保留为回滚开关
- canon→strategy 映射表（含环归属）；DreamOS /intent 响应加 canon 字段（增量不破坏）
- smart-router 门禁分支回归用例全绿
- 验收：AC2/AC6 + 黄金集全绿

### Phase 4 — 研发域优化闭环成文（P1）
- 黄金集回归脚本入仓；优化流程成文：调优 → 回归 → 提案 → 飞书审批 → 版本晋升
- 验收：流程文档落盘；隔离仓首批候选走一次完整晋升演练（含"拒绝"路径）

### 验收清单汇总
| 验收项 | 验证方式 | 等级 |
|:---|:---|:---:|
| 一致率 ≥95% | 影子日志统计 | P0 |
| 未授权写 401 | curl 实测 | P0 |
| 直写路径消除 | grep 全仓 | P0 |
| thinking 链关闭 | 延迟实测 | P0 |
| 门禁分支回归 | vitest 用例 | P0 |
| 35↔6 映射可用 | /intent 响应校验 | P1 |
| records 异步写 | 热路径无 writeFileSync | P1 |
| 优化闭环成文 | 文档 + 演练 | P1 |

### 回滚预案
| 阶段 | 回滚方式 | 影响 |
|:---|:---|:---|
| Phase 1-3 | INTENT_METHOD 一键切回旧路径（旧代码保留） | 无感 |
| Phase 2 门禁 | 纯增量，撤除即恢复 | 污染面重现（仅限回滚期） |
| Phase 3 映射 | 增量字段，不影响旧链 | 无 |

---

> 执行产物：`_plan/z1-scan-report.md` | `_plan/z2-boundaries.md`（含双轨大脑补遗）| `_plan/z3-implementation-plan.md` | `_plan/z4-acceptance.md`

---

## 审批记录

| 项 | 值 |
|:---|:---|
| 审批模板 | 096DC318-681B-478A-90CC-BD9701FC732C（交易系统优化提案验收，旧V1） |
| 实例码 | `0D558400-61B4-4F27-9525-AC2006495AF3` |
| 创建时间 | 2026-08-29 |
| 状态 | **已批准**（2026-08-29 用户聊天中明示"批准，开始吧"；飞书实例侧未点击，timeline 仅 START，按仲裁规则用户明示>飞书状态） |
| 登记 | approval_sync.py known-codes 已注册 |
| 批准后动作 | E1 按 `_plan/z3-implementation-plan.md` 顺序执行（P0 可先行，P1+ 以批准为前提） |
