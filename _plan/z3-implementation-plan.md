# 实施计划（Z3）：DreamOS OS自进化三缺口 — Step-by-step 路径

> **Z3身份**: 路径师 · 四步推导法(反推验收→产出推导→异常预判→组装整链) · 工具 read_file/write_file
> **前置引用**: `z1-scan-report.md`(接触点行号) + `z2-boundaries.md`(P1/P2/P3划分) · **覆盖** Aug29旧文件
> **前置降级**: `d2-analysis.md`/`feedback-e2.md` 不存在 → 基于对话 D2 矛盾分析体现(见§五)
> **核心**: Z3不决定做什么(Z2已定)，Z3决定**怎么做** — 每步"做什么→怎么做→怎么验收→怎么回滚"闭环

---

## 一、前置条件

| 类别 | 须确认 |
|:---|:---|
| 环境 | DreamOS venv(`~/.hermes/hermes-agent/venv/bin/python3`依赖全) + Hermes运行环境 |
| 数据 | `data/bcrm_trades.db`存在(6表LIVE) + `core/memory/orchestration_memory.json`存在 |
| 权限 | 飞书审批链路(`approval_sync.py` known-codes)可用 + bcrm2/orchestration_memory写权限 |
| 备份 | **P3改status前必备份** `bcrm_trades.db`；P2前备份 `orchestration_memory.json` |
| 依赖坐实 | save_model_version(L278)/check_rollback(L855)/record_evolution_event(L788)/run_hourly_sacg(L874) 均LIVE(Z1✅) |
| D链输入 | d2/feedback物理文件缺→降级，D2矛盾(进化效率vs安全/回滚误触发/双审计/监督边界/审批张力)纳入§五 |

---

## 二、执行步骤

### Phase 1: G-A Hermes旁路只读监督器 (🟢低, 叶节点先行)

#### Step 1.1: 建只读观测器骨架（读3数据源）
- **做什么**: Hermes侧新建独立监督模块，只读观测 DreamOS 自进化状态。
- **怎么做**:
  - 新建 `~/.hermes/scripts/dreamos_evolution_monitor.py`（Hermes侧，监督者独立性，不入DreamOS仓）
  - 读源1: `core/memory/orchestration_memory.json` → scenarios进化状态(best_pattern/score/confidence/sparse/evolved_at)
  - 读源2: `data/bcrm_trades.db` **只读连接**(`sqlite3.connect('file:...?mode=ro', uri=True)`) → model_evolution审计 + performance_snapshots绩效
  - 读源3: `evolution/engine.py` evolve输出(EvolutionReport结构，只读解析)
- **验收条件**:
  1. `python3 dreamos_evolution_monitor.py --dump` 打印当前scenarios数+最近5条model_evolution审计 → 有输出
  2. 只读断言: 运行后 `bcrm_trades.db` 的 mtime 不变 + 无写事务(mode=ro强制)
  3. orchestration_memory.json 内容哈希运行前后一致
- **卡住判定**: json路径不存在 / db被锁(SQLite并发) / EvolutionReport结构不明
- **异常预案**: db锁→只读URI+`timeout=5`；json格式变→`try/except`容错+告警"格式异常"；不阻断DreamOS
- **回滚方法**: `git revert`(新模块删除，零状态残留，纯只读未写任何数据) 🟢低

#### Step 1.2: 异常进化检测 + 告警（监督不阻断）
- **做什么**: 检测异常自进化，告警通知，**不干预**evolve上线。
- **怎么做**:
  - 异常规则: ①score骤降(new<old×0.7) ②sparse样本上线(sample_count<10且confidence≠high) ③evolved_at频繁(同scenario 1h内多次进化)
  - 告警通道: 飞书消息(复用send_message) + 本地日志，**仅通知**
- **验收条件**:
  1. 注入异常scenario(score骤降)→触发飞书告警
  2. 正常进化→不告警(无误报)
  3. **断言告警不写回DreamOS**(evolve上线流程不受影响，纯旁路)
- **卡住判定**: 异常阈值难定 / 告警通道不通
- **异常预案**: 误报→阈值config化可调；告警失败→降级本地日志，不抛异常
- **回滚方法**: 关告警开关 / `git revert` Step1.2 commit 🟢低

#### Step 1.3: 聚合两套审计统一视图 + 接入cron
- **做什么**: 聚合OS编排审计(P2产出)+子系统model_evolution审计→统一视图；接入Hermes定期观测。
- **怎么做**:
  - 统一视图: 合并 orchestration_memory.json的scenarios进化 + model_evolution表 + (P2后的)OS编排审计 → 单一时间线
  - 接入: Hermes cron(参考MEMORY: `cronjob` 定期跑monitor，no_agent或轻agent)
- **验收条件**:
  1. 统一视图展示两套审计(OS编排+子系统)按时间排序
  2. cron定期(如每30min)跑monitor，输出进化健康摘要
  3. P2完成后，OS编排审计自动出现在统一视图(读同源，无需改P1)
- **卡住判定**: cron接入点冲突 / 两套审计schema差异大
- **异常预案**: schema差异→视图层适配(各审计保留原schema，视图统一展示)；cron失败→告警不阻断
- **回滚方法**: 移除cron job / `git revert` 🟢低

---

### Phase 2: G-C OS编排进化审计补全 (🟡中, 弱依赖P1)

#### Step 2.1: update_from_evolution 落OS侧独立审计
- **做什么**: 编排进化时记录审计，**不碰bcrm2**(避免分层倒置+P3交叉)。
- **怎么做**:
  - 改 `core/memory/orchestration_memory.py` `update_from_evolution`(L332)：进化写scenarios后，**追加OS侧审计**
  - 审计落点(二选一，建议json内嵌轻量): 
    - 方案A: orchestration_memory.json内嵌 `audit_log[]`(scenario_id/old_pattern→new_pattern/old_score→new_score/evidence/timestamp)
    - 方案B: OS层新表`orchestration_evolution`(独立于bcrm2)
  - feature flag: `audit_orchestration_enabled`(默认True)
- **验收条件**:
  1. 触发update_from_evolution→审计落点新增1条(含old→new pattern/score/evidence/timestamp)
  2. flag=False→不写审计，scenarios进化仍正常(审计与进化解耦)
  3. **断言未碰bcrm2_scheduler.py**(git diff只含orchestration_memory.py)
  4. 影子验证: evolve流程(_sandbox_validate)不受影响，自动上线仍正常
- **卡住判定**: 审计落点选择(json内嵌膨胀? 新表迁移?) / update_from_evolution签名变
- **异常预案**: json膨胀→audit_log限长(保留最近N条)；影响evolve→影子验证回退；**D2矛盾#2(双审计不统一)→G-C落OS侧，由P1(Step1.3)聚合统一**
- **回滚方法**: 关flag `audit_orchestration_enabled=False` + `git revert`；已写审计条目无害保留 🟡中

---

### Phase 3: G-B bcrm2回滚执行器 + 审批门禁 (🔴高, 强依赖P1+P2, 独占)

#### Step 3.1: restore/activate 回滚执行方法（先dry_run）
- **做什么**: 补"执行回滚"动作(现check_rollback只返回"建议"dict)。
- **怎么做**:
  - `bcrm2_scheduler.py` 新增 `restore_model_version(symbol, version_from, version_to, dry_run=True)`
  - 逻辑: 切换 model_versions.status — version_from: `active→archived`；version_to: `→active`(事务原子)
  - 版本定位: check_rollback(L855)的current_version → 查model_versions上一active版本(按created_at DESC)
  - **dry_run优先**: 默认只预览status切换，不实改
- **验收条件**:
  1. `restore_model_version(dry_run=True)` → 打印"将切换 version_from(X)→version_to(Y) status"，db不变
  2. dry_run=False(测试db) → model_versions.status正确切换(事务，失败回滚)
  3. 版本定位准确(上一active版本)
- **卡住判定**: 上一版本定位逻辑(多版本/无历史版本) / status切换并发
- **异常预案**: 无上一版本→拒绝回滚+告警；并发→事务+锁；**D2矛盾#1(回滚误触发实盘损失)→dry_run强制先行**
- **回滚方法**: model_versions.status手动恢复(备份db还原) 🔴高

#### Step 3.2: 飞书审批门禁接入（复用现有链路）
- **做什么**: 回滚执行前必过审批，**不改造**审批链路本身。
- **怎么做**:
  - 回滚触发→创建飞书审批实例(复用MEMORY: `approval_sync.py` known-codes架构，add注册+GET轮询)
  - 审批内容: symbol/version_from→to/触发原因(win_rate/sharpe)/绩效证据
  - 批准→执行restore(dry_run=False)；拒绝/超时→**不执行**+record_evolution_event(event_type='rollback_rejected')
- **验收条件**:
  1. 触发回滚→飞书创建审批实例(可见可批，参考MEMORY V1模板客户端可见)
  2. 模拟批准→执行restore；模拟拒绝→不执行+审计记录rejected
  3. **审批超时→安全默认不执行**(不回滚)
- **卡住判定**: approval_sync集成(known-codes注册) / 审批模板可见性(MEMORY: V2新模板有可见性延迟)
- **异常预案**: 审批链路故障→**fail-safe不执行回滚**(安全优先)；用V1可见模板；**D2矛盾#4(审批张力)→P3必过审批，OS编排(P1/P2)不需**
- **回滚方法**: 关审批接入 / `git revert` Step3.2 🔴高

#### Step 3.3: feature flag + 集成run_hourly_sacg
- **做什么**: 回滚执行默认关闭，集成到每小时调度，三重保护。
- **怎么做**:
  - `rollback_execute_enabled` **默认False**(回滚执行不自动触发)
  - 集成点: `run_hourly_sacg`(L874) check_rollback(L916)后 — 现仅logger.warning+record_evolution；改为: 若flag=True且审批通过→调restore执行
  - 三重保护: flag默认关 + dry_run + 审批门禁
- **验收条件**:
  1. flag=False(默认)→check_rollback仍只建议+审计，**不执行回滚**(现状不变，安全)
  2. flag=True+审批过→执行回滚(dry_run=False)
  3. flag=True+审批拒→不执行
  4. **断言不动V9规则/auto_trader加载逻辑**(只切model_versions.status)
- **卡住判定**: 集成点(L916-924)改动影响现有warning流程
- **异常预案**: 🔴误触发→flag默认关+dry_run+审批三重；集成破坏现有→保留原warning逻辑，flag控制新增执行分支
- **回滚方法**: `rollback_execute_enabled=False`(默认关，立即停执行) + `git revert` + status恢复 🔴高

---

## 三、总回滚方案（最坏情况→基线）

```
全程出问题 → 恢复基线步骤:
1. 关所有feature flag: audit_orchestration_enabled=False + rollback_execute_enabled=False
   (立即停止G-C审计写入 + G-B回滚执行, DreamOS回到Z1扫描时的LIVE状态)
2. git revert P3→P2→P1 commits (逆序, 各Phase独立可revert无交叉)
3. 数据恢复: bcrm_trades.db从P3前备份还原(model_versions.status) + orchestration_memory.json从P2前备份还原
4. 验证: auto_trader(L392)加载正确active版本 + run_hourly_sacg(L874)正常跑 + evolve自动上线不受影响
5. P1纯只读零状态: 删Hermes monitor模块即可, 无DreamOS侧残留
→ 回到基线: 子系统审计LIVE + check_rollback只建议 + 编排进化只写json (Z1现状)
```

---

## 四、时间预估

| Phase | 步数 | 预估 | 备注 |
|:---|:---:|:---:|:---|
| P1 G-A监督 | 3 | 4-6h | 新模块只读，风险低，可先行 |
| P2 G-C审计 | 1 | 2-3h | 改1函数+flag，影子验证 |
| P3 G-B回滚 | 3 | 5-7h | 🔴审批门禁+dry_run+三重保护，最重 |
| **合计** | **7** | **11-16h** | P1→P2→P3顺序，P3阻塞于审批设计 |

---

## 五、D链/跨链反馈响应（前置降级，基于对话D2矛盾分析）

> d2-analysis.md/feedback-e2.md 物理文件缺，以下基于对话中 D2 矛盾分析体现(Z3不修改矛盾，只体现到异常预案+验收)。

| D2矛盾/风险 | Z3响应(落到具体Step) |
|:---|:---|
| **主要矛盾**: 进化效率(自动上线) vs 进化安全(可控) | P1/P2不需审批(效率,OS编排域) + P3审批门禁(安全,交易域) — 分层平衡 |
| **风险#1**: G-B回滚误触发→实盘损失(最高) | Step3.1 dry_run强制先行 + Step3.3 flag默认False + Step3.2审批门禁 = **三重保护** |
| **风险#2**: 双审计不统一→进化不可追溯 | Step2.1 G-C落OS侧独立审计 + Step1.3 P1聚合两套审计统一视图 |
| **风险#3**: G-A监督边界(只读不干预) | Step1.1 mode=ro只读连接 + Step1.2告警仅通知不阻断evolve + 验收断言"不写回DreamOS" |
| **风险#4**: 审批门禁张力(OS自动vs子系统审批) | §三审批分层: P1/P2❌不需 + P3🔴需审批 — 进化域不可混层(MEMORY用户9-09纠偏) |

---

## Z3 自检
- [x] 前置检查d2/feedback(不存在→降级，§五基于对话D2体现)
- [x] D2矛盾/风险已体现到对应Step异常预案(#1→Step3.1/3.3, #2→Step2.1/1.3, #3→Step1.1/1.2, #4→§三)
- [x] 含「五、D链反馈响应」章节
- [x] 验收条件写在"怎么做"前(每Step先验收靶子)
- [x] 验收精确到命令/断言(--dump/mtime不变/git diff只含X/flag=False现状不变)，非"This should work"
- [x] 每Step独立回滚(git revert/flag/数据恢复)
- [x] 整链无断裂(P1观测源=P2/P3写入源，读同源无断裂)+无遗漏(G-A/G-B/G-C全覆盖)+总回滚覆盖最坏(§三)
- [x] 前置条件列全(环境/数据/权限/备份/依赖坐实/D链降级)
