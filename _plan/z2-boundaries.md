# 修改范围与依赖表（Z2）：DreamOS OS自进化三缺口 — Phase切割

> **任务**: G-A Hermes监督 / G-B 自动回滚执行 / G-C 编排审计补全
> **Z2身份**: 规划师 · 三原则切割法(依赖优先/风险隔离/可交付) · 工具 read_file/write_file
> **前置引用**: `_plan/z1-scan-report.md`(四维扫描+5冲突) · **覆盖** 8-29旧 z2-boundaries.md
> **核心任务**: 先改什么、后改什么、每步能不能独立回退

---

## 〇、切割结论（先给答案）

**三块缺口按「进化域 + 审批需求 + 风险」切成 3 个独立 Phase，审批门禁只锁 P3：**

| Phase | 缺口 | 进化域(MEMORY三域) | 审批 | 风险 |
|:---:|:---|:---|:---:|:---:|
| **P1** | G-A Hermes旁路只读监督器 | Hermes监督层(跨域旁路) | **不需**(监督者非审批者) | 🟢低 |
| **P2** | G-C OS编排进化审计补全 | ①OS编排自进化域 | **不需**(evolve自动上线) | 🟡中 |
| **P3** | G-B bcrm2回滚执行器 | ②子系统交易参数进化域 | 🔴**需审批门禁**(涉交易+V9) | 🔴高 |

> **关键切分**：G-B 回滚 = 切换 active 模型 → auto_trader 实盘交易 → 属"子系统交易域"，**必须审批**；G-A/G-C 属"OS编排域+只读监督"，**自动不需审批**。三者风险层级根本不同，不可混 Phase。

---

## 一、阶段划分

| 阶段 | 内容 | 风险 | 依赖 | 回滚点 | 回滚成本 | 工时 |
|:---:|:---|:---:|:---:|:---|:---:|:---:|
| **P1** | G-A: Hermes 新模块旁路**只读**观测 orchestration_memory.json + bcrm_trades.db(model_evolution/performance_snapshots) + evolve输出 → 审计闸/告警；**聚合两套审计为统一视图** | 🟢低 | 无(叶节点) | git revert 删新模块(零状态) | 🟢低 | 4-6h |
| **P2** | G-C: `orchestration_memory.update_from_evolution`(L332) 进化时落**OS侧独立审计**(json内嵌audit_log 或 OS层新表)，**不碰bcrm2**(避免分层倒置+Phase交叉) | 🟡中 | P1(审计被监督观测,弱依赖非阻塞) | git revert + feature flag(写审计开关) + 已写条目无害保留 | 🟡中 | 2-3h |
| **P3** | G-B: `bcrm2_scheduler.py` 补回滚执行器 restore/activate(version_from→version_to 切换 model_versions.status) + **飞书审批门禁集成**(复用现有approval链路,不改造) | 🔴高 | P1+P2(回滚动作须被监督+被审计) | feature flag(rollback_execute_enabled默认False) + git revert + status手动恢复 | 🔴高 | 5-7h |

---

## 二、依赖图

```
  P1 (G-A Hermes只读监督, 🟢, 叶节点)
   │  建立监督基座 — 独立先行, 不依赖任何改动
   │
   ├──弱依赖──► P2 (G-C OS编排审计, 🟡)
   │              │  update_from_evolution 落OS侧独立审计
   │              │  (P1做完→P2审计自动被监督观测, 但P2不阻塞于P1)
   │              │
   └──────────────┴──强依赖──► P3 (G-B 回滚执行, 🔴, 审批门禁)
                                  回滚动作必须: 被P1监督 + 被P2审计 + 过审批闸
                                  → P3 强制最后, 独占Phase

并行可能: P1 独立先做; P2 可与 P1 后期并行(弱依赖)
阻塞条件: P3 阻塞于 ①P1+P2就位 ②审批门禁设计(Z3细化)
风险标记: 🔴P3涉auto_trader(L392)实盘交易 → feature flag默认关闭, 审批通过才执行
```

---

## 三、审批门禁边界（Z1冲突#3 — Z2核心切分）

| Phase | 是否需审批 | 依据(MEMORY) | 门禁机制 |
|:---:|:---:|:---|:---|
| P1 G-A | ❌不需 | "Hermes在OS自进化=监督者非审批者(旁路观测/审计闸/告警,不阻断上线)" | 纯只读, 无写操作, 无需门禁 |
| P2 G-C | ❌不需 | "DreamOS OS编排自进化=evolve影子验证→自动上线,不需审批" | 审计仅记录, 不阻断编排进化 |
| P3 G-B | 🔴**需审批** | "子系统交易参数进化=trading审批,V9基线不可改" + 回滚→auto_trader实盘 | **飞书审批门禁**: 触发回滚→创建审批实例→用户批准→才执行activate切换 |

> **进化域不可混层**(MEMORY用户2026-09-09纠偏): P3回滚是"子系统模型版本切换"(②域,需审批)，**不是**"OS编排自进化"(①域,自动)。Z2严格隔离: P3只动bcrm2模型版本层，**绝不动V9规则/OS编排evolve**。

---

## 四、边界声明

### ✅ 在本阶段范围内
- **P1**: Hermes侧新建只读观测器(读3数据源→审计闸/告警/聚合视图)；接入Hermes cron或gateway
- **P2**: orchestration_memory.update_from_evolution(L332)增加OS侧审计落点(json内嵌或OS新表)
- **P3**: bcrm2新增restore/activate回滚执行方法 + 飞书审批门禁接入(复用现有approval_sync链路)

### ❌ 明确不在本阶段范围内
- ❌ **不改V9基线**(8%×vol加仓/4%止盈/3次加仓 — 回滚只在模型版本层, 不动V9规则)
- ❌ **不改evolve自动上线机制**(OS编排进化仍影子验证→自动, G-A只监督不阻断)
- ❌ **不改子系统进化算法**(self_evolution_engine逻辑不变, G-B只补"执行回滚"动作)
- ❌ **不改造飞书审批链路本身**(P3只接入复用, 不动approval_sync.py架构)
- ❌ **不动auto_trader交易执行核心**(G-B只切model_versions.status, auto_trader加载逻辑不变)
- ❌ **G-A不做任何写操作**(纯只读旁路, 监督不干预DreamOS运行)
- ❌ **G-C不碰bcrm2文件**(避免OS编排→子系统分层倒置 + P2/P3文件交叉)
- ❌ **不引入新config/env**(G-A旁路读现有文件)

---

## 五、Z1 五冲突的 Z2 回应

| Z1冲突 | Z2处理 |
|:---|:---|
| #1 认知修正(审计LIVE非死代码) | 已纳入: G-B是"补回滚执行"非"补建表"; G-C是"补编排审计"非"修崩溃" |
| #2 _plan残留(8-29旧产物) | 本报告覆盖z2; z3/z4旧文件待各阶段覆盖 |
| #3 🔴G-B审批边界冲突 | **核心切分**: P3独占+飞书审批门禁锁(见§三); P1/P2不需审批 |
| #4 双进化审计不统一 | G-C落**OS侧独立审计**(不复用bcrm2表,避免分层倒置); **P1(G-A)聚合两套审计为统一视图** |
| #5 G-A方向反转 | P1新模块只读旁路(Hermes→DreamOS观测), 不复用现有T3委托路径(DreamOS→Hermes) |

---

## 六、回滚点设计

| Phase | 回滚类型 | 方案 | 成本 |
|:---:|:---|:---|:---:|
| P1 | git revert | 删除Hermes新模块, 零状态残留(纯只读未写任何DreamOS数据) | 🟢低 |
| P2 | feature flag + git revert | `audit_orchestration_enabled`默认True, 异常时关flag停写; 已写审计条目无害保留 | 🟡中 |
| P3 | feature flag + git revert + 数据恢复 | `rollback_execute_enabled`**默认False**(回滚执行不自动触发); 异常时关flag→git revert→model_versions.status手动恢复active版本 | 🔴高(影响交易状态, 须验证恢复后auto_trader加载正确版本) |

---

## Z2 自检
- [x] 每Phase边界一句话说清（P1只读监督 / P2编排审计 / P3回滚执行+审批）
- [x] 无Phase交叉（P1=Hermes侧新模块 / P2=orchestration_memory / P3=bcrm2_scheduler，**改不同文件**；G-C明确不碰bcrm2）
- [x] 每Phase可操作回滚（P1 revert / P2 flag+revert / P3 flag默认关+revert+status恢复）
- [x] 高风险没混在低风险Phase（🔴P3独占 / 🟡P2单独 / 🟢P1先行）
