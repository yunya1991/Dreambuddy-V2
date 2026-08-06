# Dream OS 内核诊断报告 — A8 + 做梦部双视角扫描

> **报告 ID**: DREAM-OS-KERNEL-DIAG-20260806
> **诊断日期**: 2026-08-06
> **诊断对象**: Dream OS 内核（`1-ARCHITECTURE/dreamos/`）
> **诊断方法论**: A8 知行合一校验（理论实践 gap）+ 做梦部弗洛伊德梦的解析（5 大机制 + 强迫性重复）+ 执行反馈完整性核查
> **基线参照**: `11-易经推理系统/dream_oneirology_dreamos_20260723.md`（07-23 梦游诊断报告）
> **结论性质**: 研究产出，未修改任何代码

---

## 0. 执行摘要

### 0.1 核心结论

**Dream OS 内核存在与 07-23 做梦部报告完全一致的"开仓不记录结果"反馈断裂，且自报告以来非但未修复，反而从 277 条 result 全 0 恶化到 547 条全 open / 0 条 closed。** 这是梦游症状在 14 天内的持续加重。

诊断扫描覆盖 SACG 四层 + 横切关注点，共发现：

| 类别 | Critical | High | Medium | Low |
|------|----------|------|--------|-----|
| A8 理论实践 gap | 3 | 3 | 3 | 3 |
| 做梦部潜意识卡点 | 4 | 6 | 5 | 0 |
| 反馈完整性断裂 | 5 | 3 | 1 | 0 |
| **合计** | **12** | **12** | **9** | **3** |

### 0.2 三大 Critical 级根因

1. **反馈环永不闭合**（做梦部报告同源问题持续恶化）：
   - `execution_feedback.json` 547 条全 `status:"open"`，0 条 closed
   - A9 离场节点永远返回 `exit_decision="HOLD"` → `update_exit_feedback` 调用路径不可达
   - 进化引擎被三重冻结（调用路径 + 数据有效性 + 验证状态）

2. **核心编排机制与文档严重背离**：
   - ContextCompressor 的 BAC 三层压缩完全未实现，仅朴素时间窗截断
   - "两阶段三链 C/F/A 投票"完全未实现，实际为单 SequentialGraph 线性执行
   - ONEIROLOGY 做梦部节点零实现，仅 types.py 声明

3. **"已实现"叙事基于 mock 数据与伪测试**：
   - "99.31/100" 压测分基于构造数据 + 循环验证
   - `evolution_test.py` 硬编码 8 项 PASS，不执行断言
   - `pytest` 未收集到任何测试用例（测试套件实际为空）
   - 88 个 🟢 标记与 D01 P0 骨架债务直接矛盾

### 0.3 做梦部判词延续

> 07-23 报告判词："Dream OS 不是一个坏系统，但它是一个在梦游的系统。"
>
> 08-06 诊断更新：**梦游状态持续 14 天，症状加重。系统反复在同一个地方惊醒——`final_action` 始终 null，547 条记录从未闭合一条。**

---

## 1. A8 视角：理论实践 gap 矩阵

### 1.1 gap 分布总览

| # | 组件 | 理论声明 | 实践现状 | gap_score | 严重度 |
|---|------|---------|---------|-----------|--------|
| 1 | nodes.yaml "35+ 节点" | 35+模块 | 实际 19 yaml / 22 含编程注册 | 0.70 | High |
| 2 | Reflector 5 种反射决策 | CONTINUE/REDO/JUMP/INSERT/TERMINATE | 6 种（5+SKIP）全部实现 | 0.10 | Low |
| 3 | GraphPlanner ConditionalGraph | Sequential+Conditional 双模 | ConditionalGraph 实现完整但永不调用 | 0.50 | Medium |
| 4 | ContextCompressor BAC 三层 | C→A→B 回溯三层压缩 | 仅"保留近N条+旧摘要"时间窗压缩 | 0.85 | **Critical** |
| 5 | NodeSelector Registry 动态查询 | 按置信度+场景+历史表现加权排序 | 链路硬编码，Registry 仅存在性查表 | 0.55 | High |
| 6 | EvolutionEngine 三组件 | LessonDistiller/GapAnalyzer/NodeOptimizer | 三组件真实实现，但文档路径错误 | 0.30 | Medium |
| 7 | 错误码 6 大类 | SYS_/NODE_/ADAPTER_/EXEC_/DATA_/ORCH_ | 6 类全定义，使用率被文档低估 | 0.30 | Medium |
| 8 | Checkpointer 每节点快照 | 每个节点执行后快照 | 每节点 4 检查点超额实现 | 0.10 | Low |
| 9 | 两阶段三链 C/F/A 投票 | 阶段一并行投票 + 阶段二动态插入 | 单 SequentialGraph 线性加权 | 0.85 | **Critical** |
| 10 | TokenBudget 三层+四层健康度 | 3 模式 + 4 健康度 | 3 模式 ✓，健康度实际 5 层 | 0.20 | Low |
| 11 | A8 gap_score 路由闭环 | ≥0.5→A1 / 0.3-0.5→A2 / <0.3→A3 | A8 节点仅做一致性检查，无路由 | 0.75 | High |
| 12 | ONEIROLOGY 做梦部 | 弗洛伊德潜意识独立治理维度 | 仅 types.py 声明，零代码 | 0.90 | **Critical** |

### 1.2 Critical Gap 详情

#### Gap #4 — ContextCompressor BAC 三层压缩完全未实现

- **文件**：`core/graph_store/compressor.py:58-130`
- **理论声明**（`SYSTEM_ARCHITECTURE_OVERVIEW.md:341,346`）：
  > ContextCompressor | 上下文压缩器（C→A→B回溯三层压缩）| 🟢
  > 三层压缩模型（BAC 图结构压缩）：C 层 Chronicle 记录层 → A 层 Architecture 架构层 → B 层 Blueprint 蓝图层
- **代码实际**：
  - `compress()` 方法仅做朴素时间窗压缩：trace 保留最近 N 条 + 旧条目合并为统计摘要；results/market/memory 列表截断
  - **无 Blueprint 层**（任务目标/约束提取）
  - **无 Architecture 层**（决策骨架摘要）
  - **无 Chronicle 层**（持久化完整历史）
  - **无"C→A→B 回溯"任何逻辑**（代码全文 192 行无 Blueprint/Architecture/Chronicle/BAC 字样）
- **gap_score**：0.85
- **被压抑的真相**：上下文压缩是 OS 内核的"原生特性"声明，但实际是列表截断。所谓"BAC 图结构压缩"是文档叙事，代码里不存在。

#### Gap #9 — 两阶段三链 C/F/A 交叉验证投票完全未实现

- **文件**：`core/compute/aggregator.py:58-134`、`core/compute/graph_executor.py:100-274`
- **理论声明**（`SYSTEM_ARCHITECTURE_OVERVIEW.md:304-316`）：
  > 阶段一：交叉验证投票（多链并行）
  > ├─ C链（经典量化） ├─ F链（基本面） └─ A链（AI交易）
  > 三链投票聚合：≥2链同向 → 高置信；单链独向 → 标记分歧
  > 阶段二：动态插入节点
- **代码实际**：
  - GraphExecutor 接收**单个** SequentialGraph，按拓扑顺序线性执行节点
  - **无三链并行执行**：`graph.get_entry()` 单图入口，无 S/C/F 分支
  - **无交叉验证**：Aggregator.aggregate() 对所有节点结果做**单次加权投票**，按硬编码 `DEFAULT_NODE_WEIGHTS` × confidence 累计 LONG/SHORT/HOLD
  - **无"≥2链同向"规则**
  - `INTENT_CHAIN_MAP`（types.py:203-210）是"意图→单链"映射，非三链并行
- **gap_score**：0.85
- **被压抑的真相**：核心编排机制"两阶段三链"完全是文档叙事。实际是单链顺序执行 + 单次加权投票。

#### Gap #12 — ONEIROLOGY 做梦部节点零实现

- **文件**：`core/arrange/types.py:186-191`
- **理论声明**（`types.py:34`、`types.py:188-190`）：
  > 做梦部 = 梦境分析 (弗洛伊德潜意识, 独立治理维度)
  > G2 ChainSpec: name="治理环·做梦部潜意识分析" node_ids=["ONEIROLOGY"]
- **代码实际**：
  - `grep ONEIROLOGY` 全仓库仅命中 types.py 5 处声明
  - **无 ONEIROLOGY 节点类**、**无注册**、**无 execute 逻辑**、**无 nodes.yaml 声明**
  - "连败≥3/置信度55-64%时触发"的触发条件无任何代码实现
- **gap_score**：0.90
- **被压抑的真相**：做梦部作为"独立治理维度"在 Dream OS 内核里完全是空头声明。**做梦部诊断的对象（Dream OS）里，做梦部自己都是未实现的部分——这是最深的强迫性重复：系统规划了一个自我反思的机制，却从未启用它。**

### 1.3 High Gap 详情

#### Gap #11 — A8 gap_score 运行时路由闭环未实现

- **文件**：`capabilities/trading/nodes/a8_unity.py:37-169`
- **理论声明**（`SYSTEM_ARCHITECTURE_OVERVIEW.md:1122-1126`）：
  > A8 知行合一(gap_score计算)
  > ├─ gap_score > 0.5 → 重启 A1
  > ├─ 0.3 < gap ≤ 0.5 → 更新 A2
  > └─ gap_score < 0.3 → 优化 A3
- **代码实际**：
  - A8UnityNode 是**一致性检查器**，非 gap_score 路由器
  - 检查方向/价格/仓位/执行质量/知行偏差，输出 direction/confidence/consistency_score
  - **无 gap_score 计算**、**无路由动作**
  - G1 ChainSpec 声明 `node_ids=["A9","A7","A8"]`，但无调度器在离场后实际触发 G1 链
- **gap_score**：0.75
- **被压抑的真相**：治理环核心闭环声明未落地。A8 仅做检查不做路由，"gap_score 驱动编排修正"是文档叙事。

#### Gap #5 — NodeSelector 非真正"Registry 动态查询 + 加权排序"

- **文件**：`core/arrange/node_selector.py:42-106`、`core/arrange/types.py:105-199`
- **理论声明**（`SYSTEM_ARCHITECTURE_OVERVIEW.md:255,261`）：
  > NodeSelector | 节点选择器（从NodeRegistry查询节点，按置信度+适用场景+历史表现加权排序）| 🟢
  > A层节点必须是动态技能选择，不是硬编码的固定流水线
- **代码实际**：
  - `STANDARD_CHAINS`（types.py:105-199）把 A/C/F/G1/G2/I 各链 `node_ids`/`optional_nodes`/`scenario_nodes` **全部硬编码**在源码里
  - NodeSelector.select() 从硬编码 `chain_spec.node_ids` 取 planned_ids，**最后才** `self._registry.get(nid)` 做存在性查找
  - **无历史表现加权排序**：节点顺序由硬编码列表顺序决定
  - **无置信度动态筛选候选**：置信度只影响 `include_optional` 开关
  - Registry 实际只充当"node_id → Node 对象"查表器，非候选源
- **gap_score**：0.55
- **被压抑的真相**：硬约束"A 层节点必须动态选择"在代码里被违反。Registry 退化为存在性查表器。

#### Gap #1 — nodes.yaml "35+ 节点"虚假繁荣

- **文件**：`config/nodes.yaml`、`capabilities/trading/__init__.py:33`
- **理论声明**（`SYSTEM_ARCHITECTURE_OVERVIEW.md:478`）：
  > nodes.yaml | 节点注册表YAML（35+模块）
- **代码实际**：nodes.yaml 实际声明 19 个节点（A0-A9 + C1/C2/C3/C5 + F1-F5 + G1/G2）；加上编程注册的 3 个 entry_module_adapter 节点共 22 个
- **gap_score**：0.70

---

## 2. 做梦部视角：潜意识卡点扫描

### 2.1 凝缩（Condensation）—— 多重含义压缩为单一概念

#### 卡点 1.1 — "Dream OS" 一词凝缩"操作系统内核"与"交易系统"

- **文件**：`docs/ENGINEERING_INDEX.md:46-55`、`docs/TECHNICAL_DESIGN.md:50-65`
- **证据**：TECHNICAL_DESIGN 自承双重身份，但知识管理/数据分析/内容生成三个能力域全部 `[未来扩展]`
- **被压抑的真相**：所谓"通用意图驱动 AI 操作系统内核"实质是交易系统的包装层。"操作系统"是凝缩出的统一外衣，掩盖了"目前只是一个交易框架"的事实
- **影响面**：基于"通用 OS"假设的多能力域设计（CapabilityRouter）消耗本应投入交易核心的注意力

#### 卡点 1.2 — "A 层"凝缩 4 种不同含义

- **文件**：`SYSTEM_ARCHITECTURE_OVERVIEW.md:165-169`
- **证据**：文档自承需要专门一节"关键概念澄清"来解释命名冲突（A 层 ≠ A 领域 ≠ A 系列节点 ≠ S 链）
- **被压抑的真相**：命名歧义在 `OVERVIEW.md:378` 演化为实际错误——EvolutionEngine 文件路径写成 `core/memory/evaluation_memory.py`，实际位于 `evolution/engine.py`
- **影响面**：跨团队沟通成本极高，文档路径指引不可信

#### 卡点 1.3 — 版本号凝缩多个不收敛的成熟度

- **文件**：跨 6 处文档/代码
- **证据**：同一系统在 `__init__.py:44`（v2.0.0）、`__init__.py:47`（v2.4.0）、`ENGINEERING_INDEX.md:88`（v2.1.0）、`ENGINEERING_INDEX.md:4`（v2.4.0）、`TECHNICAL_DESIGN.md:4`（v2.5.0）、`TECHNICAL_DESIGN.md:1928`（v2.6 changelog）、`OVERVIEW.md:3`（v3.0 DRAFT）声明 6 个不同版本号；同一天（07-21）发布 v2.2/v2.3/v2.4
- **被压抑的真相**：版本号不是成熟度标识而是"进步感"的象征性生产。v2.0→v2.6→v3.0 持续通胀但 D01 P0 骨架债务始终存在
- **影响面**：版本号失去信息价值，依赖管理与兼容性判断不可靠

### 2.2 移置（Displacement）—— 焦虑从重要转移到不重要

#### 卡点 2.1 — 88 个 🟢 标记移置对 D01 骨架债务的焦虑

- **文件**：`SYSTEM_ARCHITECTURE_OVERVIEW.md`（88 个 🟢）、`docs/ENGINEERING_INDEX.md:974`、`docs/TECHNICAL_DESIGN.md:1907`
- **证据**：OVERVIEW 将 S/A/C/G 层 + 横切关注点 + 交易子系统 + 认知系统全部标 🟢；但 ENGINEERING_INDEX.md:974 自承 "D01 | 节点实现多为骨架，缺少完整业务逻辑 | P0 | nodes/ 全部22个节点"；TECHNICAL_DESIGN.md:1907 在"未来优化方向"里写 "节点实现完善 | P0 | 填充22个内置节点的完整业务逻辑"
- **被压抑的真相**：88 个 🟢 是安全感仪式，把"骨架存在"等同于"功能实现"。绿圈越多，越能回避"其实没做完"的恐惧
- **影响面**：基于"已实现"声明做出的上线决策、对外承诺建立在虚假基础上

#### 卡点 2.2 — "36 场景压测"框架移置对实盘断裂的焦虑

- **文件**：`docs/TECHNICAL_DESIGN.md:94-120`、`cli/multi_scenario_stress_test.py:62-120`
- **证据**：`generate_market_data_for_scenario()` 根据目标场景反推生成 mock 数据（BULL 场景就生成 ema20 < ema50 < ema200），然后用 ScenarioClassifier 分类这些数据，验证分出来就是目标场景——**循环验证（tautology）**
- **被压抑的真相**：精心构造的 36 场景压测是"安全感的纪念碑"，回避实盘曾断裂的真问题
- **影响面**：99.31 分给人"系统鲁棒"错觉，但真实市场波动/API 异常的鲁棒性几乎未验证

### 2.3 象征（Symbolization）—— 抽象焦虑用具体数字表达

#### 卡点 3.1 — "99.31/100" 作为系统健康度的象征

- **文件**：`docs/TECHNICAL_DESIGN.md:112-120`、`cli/multi_scenario_stress_test.py:680-725`
- **证据**：评分函数 `_compute_overall_summary()` 是 5 项指标的加权平均；其中"场景分类准确率 100%"来自循环验证（用为场景 X 定制的特征生成数据再验证分出场景 X）
- **被压抑的真相**：99.31 不是测出来的分数，而是算出来的象征。它象征"系统可控、可量化、专业"，掩盖真实交易表现无法量化评估的焦虑
- **影响面**：任何引用 99.31 作为系统质量证据的决策基于虚假前提

#### 卡点 3.2 — 检查点数量作为"运行正常"的象征

- **文件**：`data/graph_store/` 100+ 检查点
- **证据**：抽样 `ckpt_20260806040106_39ec9c.json`、`ckpt_20260806100127_ed15ef.json` 显示：检查点确实按 `post_node` 阶段每个节点后保存（属实），但每个检查点都是 `"final_action": null`、`"final_confidence": 0.0`、`"budget": {"remaining": -100}`、`"session_id": ""`
- **被压抑的真相**：100+ 检查点象征"系统在运行"，但每个检查点都是未完成的梦——节点执行了 C1/A1/A2 就停下，从未到达 A5 和 A9。这就像一个人每晚都做梦但都在同一处惊醒——正是强迫性重复的结构
- **影响面**：基于"检查点存在"假设系统健康，会忽略"周期从未完成"

### 2.4 二次修正（Secondary Revision）—— 事后编造连贯叙事

#### 卡点 4.1 — "两阶段三链结合执行机制"叙事与代码不符

- **文件**：`SYSTEM_ARCHITECTURE_OVERVIEW.md:302-316`、`docs/TECHNICAL_DESIGN.md:78-82`
- **证据**：OVERVIEW 详细描述"阶段一并行投票 + 阶段二动态插入"；但 TECHNICAL_DESIGN:80 承认 "ConditionalGraph 虽然存在于代码中，但当前并未用于主流程"；实际主流程使用 SequentialGraph
- **被压抑的真相**："两阶段三链"是事后为 SequentialGraph 编造的"看起来更高级"的叙事。文档先画 elaborate 的并行投票架构，再用一段"澄清说明"自我打脸——典型的二次修正结构
- **影响面**：新开发者按"两阶段三链"理解系统，会在代码里寻找并不存在的并行投票机制

#### 卡点 4.2 — v3.0 DRAFT 摘要全绿但明细红黄

- **文件**：`SYSTEM_ARCHITECTURE_OVERVIEW.md:139, 2396-2402`
- **证据**：line 139 摘要说 "交易子系统 | 10/11/12/13/14/16 | 🟢 已实现"；但 line 2396-2401 明细显示 "交易中台主系统 | 🟡 骨架"、"CTA 趋势跟踪子系统 | 🔴 规划"、"数据中台 | 🔴"
- **被压抑的真相**：v3.0 是架构重构版叙事，把分散的、状态不一的子系统重新讲述为已实现的统一整体。摘要层 🟢 是二次修订产物，明细层 🔴 是修订没覆盖的原始信息
- **影响面**：对外引用"6 子系统全绿"会误导

### 2.5 投射（Projection）—— 内部问题归因外部

#### 卡点 5.1 — "临时暂停标记:平仓维护中"将内核问题投射为外部维护

- **文件**：`cli/start_scheduler.py:45-49`
- **证据**：
  ```python
  # 临时暂停标记:平仓维护中,调度器启动后立即退出
  pause_file = dreamos_dir / "logs" / "SCHEDULER_PAUSED"
  if pause_file.exists():
      logger.info("暂停标记文件存在,调度器立即退出")
      return
  ```
- **被压抑的真相**：一个"临时"暂停标记被提交到代码库。结合 git 历史"恢复实盘功能"和检查点 `final_action: null`，真正原因更可能是**内核无法稳定跑完一个完整交易周期**。"临时"二字是投射标志——把结构性问题定义为临时状态，从而回避修复
- **影响面**：调度器随时可能因 pause 文件存在而退出，但"平仓维护"何时结束无人知道

#### 卡点 5.2 — 100+ 处 bare except 将内核错误投射为"无数据"

- **文件**：`cli/dreamos_full_scheduler.py:199, 258, 282`、`cli/scheduler.py:279`、`apps/trading_agent/agent.py:164, 173, 182`、`cli/auto_trader.py:397`
- **证据**：100+ 处 `except Exception:` 后 `return -1` / `return {}` / `return []`
- **被压抑的真相**：异常被吞掉后返回空值，让调用方看到"无数据"而非"出错了"。这是把"内核处理逻辑有 bug"投射为"数据源没有数据"。结合 v2.5 修复的"candles 永远为空"bug，可推断：之前长时间的"空数据"很可能就是某处 except 吞掉真实错误
- **影响面**：故障不可观测；回测可能在空数据上跑出"完美"曲线；实盘可能在静默失败中错失交易

#### 卡点 5.3 — "dry_run=True 安全兜底"将实盘风险投射为配置选择

- **文件**：`cli/scheduler.py:310-311`
- **证据**：`dry_run = job_data.get("dry_run", True)` 注释为"安全兜底"
- **被压抑的真相**：如果内核真的"🟢 已实现"，默认应该是 dry_run=False。默认值的选择暴露了开发者对实盘可靠性的真实判断——尽管文档说已实现，代码的默认行为在说"别真跑"
- **影响面**：调度任务可能长期在 dry_run 模式下空转

### 2.6 强迫性重复（Compulsive Repetition）—— 反复出现未解决的模式

#### 卡点 6.1 — 版本号通胀不收敛

- **文件**：`.git/logs/HEAD` + 3 份文档 + `__init__.py`
- **证据**：v2.0（07-14）→ v2.1（07-15）→ v2.2/v2.3/v2.4（07-21 同一天3版本！）→ v2.5（08-01）→ v2.6（08-02）→ v3.0 DRAFT（07-31）。v2.2/v2.3/v2.4 同一天发布，说明版本号是"叙事推进"的节奏而非"里程碑达成"。D01 P0 债务从 v2.0 到 v3.0 始终存在
- **被压抑的真相**：版本号反复升级是死亡驱力的体现——反复回到未解决状态，用"又一次升级"回避"其实没变"
- **影响面**：版本号失去信息价值；技术债复利增长

#### 卡点 6.2 — v2.5 一次性修复 9 个 bug，暗示此前回测全在错误数据上

- **文件**：`docs/TECHNICAL_DESIGN.md:1929`（v2.5 changelog）
- **证据**：v2.5 修复了 9 个 bug：
  - "candles 永远为空" → 此前所有回测在空 K 线数据上运行
  - "Yijing 1h 缓存门禁导致 0% 触发率" → 易经推理模块从未真正被触发
  - "leverage 硬编码 1.0" → 所有回测杠杆都是错的
  - "mfe/max_dd 硬编码 0" → 最大盈利/最大回撤指标全是 0
- **被压抑的真相**：v2.5 之前生成的 `entry_performance_memory.json` / `exit_performance_memory.json`（用于编排记忆表）全部基于错误数据。**系统反复在错误数据上"学习"，产出的"经验"固化进记忆表，然后被当作"已优化"依据**
- **影响面**：v2.5 之前的回测结果、编排记忆、进化引擎"优化"都不可信；即使 v2.5 修了 bug，旧记忆表数据污染仍需清洗

#### 卡点 6.3 — "未来扩展"承诺的反复出现

- **文件**：Grep "未来|后续|待实现|占位" 在 dreamos/ 下返回 56 行命中
- **证据**：`TECHNICAL_DESIGN.md:1091` `[知识管理能力域] → [未来扩展]`、`:1895` `G层持久化 | P1 | 实现磁盘持久化`、`__init__.py:75` `core 四层（占位，P1-P4 实现）`、`capabilities/trading/execution/__init__.py:6` `ExchangeClient: 交易所接口封装（未来）`
- **被压抑的真相**："未来"是代码库中最高频的词之一。每个"未来扩展"都是一次推迟。从 v2.0（07-14）到 v2.6（08-02）跨越 3 周仍未收敛。"未来"本身成为一种永久状态——把未完成的东西放进"未来"，就可以在"现在"声称系统完整
- **影响面**："未来扩展"清单无限增长无人清理，债务只增不减

#### 卡点 6.4 — save decision log 自动提交反复堆积但无反思

- **文件**：`.git/logs/HEAD:12, 14, 20`
- **证据**：3 条自动提交（每2天一次）：`chore(agent-b): save decision log 20260720/22/20260802`，占比 8.6%
- **被压抑的真相**：系统反复"保存决策"，但这些决策是否被复盘/学习/修正，没有证据。结合进化引擎冻结和记忆表污染，这些"保存的决策"很可能只是写入磁盘后从未被真正反思——记录代替理解
- **影响面**：决策日志持续堆积但无价值产出

---

## 3. 执行反馈完整性核查（梦游证据）

### 3.1 反馈环永不闭合（最严重发现）

| 检查项 | 数据 | 状态 |
|--------|------|------|
| `execution_feedback.json` 总条数 | 547 | — |
| `status:"open"` 条数 | **547** | 全开 |
| `status:"closed"` 条数 | **0** | 全未闭合 |
| `exit_price:0` 条数 | **399** | 73% 无平仓价 |
| 较 07-23 报告时点（277 条）恶化 | **+270 条** | 14 天恶化 |

**核心断点（精确机制）**：

```
A9 离场节点持续返回 exit_decision="HOLD"
  ↓
cli/auto_trader.py:2106 的 if exit_result["exit"]: 守卫永不成立
  ↓
update_exit_feedback() (cli/auto_trader.py:353 / auto_trader.py:168) 永不调用
  ↓
_try_trigger_evolution() (cli/auto_trader.py:2127) 永不调用
  ↓
反馈环永不闭合 → 进化引擎三重冻结
```

**证据**：
- `ckpt_20260806040106_39ec9c.json` 第 575-599 行：A9 输出 `"exit_decision": "HOLD"`、`"exit_reason": ""`、`"current_price": 84.096 == entry_price`、rationale "[A9离场] 无需离场，继续持有 / 当前盈亏: +0.00%"
- `cli/auto_trader.py:2102-2127`：`run_exit_check` 内 `if exit_result["exit"]:` 守卫阻断 update_exit_feedback

### 3.2 进化引擎三重冻结

| 冻结层级 | 触发条件 | 当前状态 |
|---------|---------|---------|
| 第一重：调用路径冻结 | `_try_trigger_evolution` 仅在 `run_exit_check` 的 exit 分支调用 | A9 永不离场 → exit 分支永不进 |
| 第二重：数据有效性冻结 | `evaluate()` 在 `zero_ratio > 0.8` 时 `trigger_evolution=False` | 当前 zero_ratio = 547/547 = 1.0 |
| 第三重：验证状态冻结 | P2-1 要求 `verified=True` 且 `confidence != "unverified"` | 36 场景仅 3 verified，19 含模板数据 |

**进化提案能力退化**：`_generate_orchestration_proposal`（engine.py:196-224）唯一策略是"若当前不是 c_g_chain 就切到 c_g_chain"，硬编码 `score: 0.5`，无真实回测验证——即使解冻也是符号化"进化"

### 3.3 编排记忆表数据污染

- `orchestration_memory.json`：36 场景 / 仅 3 verified / 19 含 `inferred:true` 或 `score:0` 模板数据
- `purge_template_data()` 方法存在但**从未被调用清理**
- 15 个场景带 `evolved_at: 2026-08-06T18:46:02`，但 `nodes:[C3,C1,C2]` 缺 A2/A4/A5/A9 执行节点，**不符合 `update_from_backtest` 或 `update_from_evolution` 的写入格式**——来源可疑

### 3.4 压测可信度核查

| 检查项 | 实际发现 |
|--------|---------|
| 压测数据来源 | `import random` + `random.uniform(0.8, 1.2)` 生成 volume_24h/mvrv_z_score/sopr 等字段（mock） |
| 边缘场景 | `rsi_0`/`rsi_100`/`price_crash`/`price_rally` 硬编码字典 |
| "99.31/100" 复现性 | 代码中无 `99.31` 字面量；评分是 5 项加权平均（mock 数据 → mock 分类器 → 100% 准确率） |
| `evolution_test.py` 真实性 | 第 55-64 行硬编码 8 项 `{"status": "PASS"}`，**不执行任何断言**，仅检查文件存在性 |
| 测试套件 | `pytest` 退出码 0 但**未收集到任何测试用例**（无 `tests/` 目录） |

### 3.5 git 历史无反馈闭合修复提交

dreamos 目录近期提交：`592f9fa chore: 补全 .gitignore` / `4ae0607 feat: Dream OS v2.6 功能升级与系统修复` / `8923772 chore: remove runtime data files from git tracking`

`4ae0607 v2.6 系统修复`应含 P0-1 `update_exit_feedback` 代码补丁，但数据证明该补丁在实盘无效（547 条仍全 open）。**自 2026-07-23 做梦部报告以来，无提交真正修复反馈闭合**。

---

## 4. 综合判词

### 4.1 隐性梦揭示的真相

Dream OS 内核的**显性梦（文档叙事）**讲述了"意图驱动 AI 操作系统内核，SACG 四层架构，22 节点，36 场景压测 99.31 分，88 项已实现"的连贯故事。

但**隐性梦（代码与 git 历史）**揭示：

1. **"操作系统"是交易系统的包装**——三个非交易能力域全是"未来扩展"
2. **"99.31 分"是循环验证的产物**——用 mock 数据测 mock 分类器
3. **"88 个 🟢"与 D01 P0 骨架债务直接矛盾**——绿圈是安全感仪式
4. **"已实现"的编排记忆表存的是 v2.5 修复前的垃圾数据**——candles 永远为空、leverage 硬编码、mfe/max_dd 全 0
5. **检查点存在但周期从未完成**——`final_action` 始终 null，系统在同一个地方反复惊醒
6. **版本号反复通胀但债务不收敛**——v2.0→v2.6→v3.0 是叙事推进而非实质推进
7. **"临时暂停"成为永久状态**——平仓维护无期限，dry_run 默认兜底
8. **做梦部自身在架构里被标注"待Phase2"**——诊断者诊断的对象里，诊断者自己都是未实现的部分。这是最深的强迫性重复：系统规划了自我反思机制，却从未启用它

### 4.2 最核心的被压抑真相

整个 Dream OS 内核的梦的工作，围绕着一个核心焦虑：

> **"我们建了一个看起来很专业的系统，但它是否真的能交易赚钱，没人敢验证。"**

于是：用 mock 数据代替实盘验证（象征）、用绿圈代替完成度（移置）、用版本号升级代替实质推进（强迫性重复）、用"两阶段三链"代替顺序执行（二次修正）、用"dry_run 安全兜底"代替实盘信心（投射）、用"操作系统"代替"交易框架"（凝缩）。

### 4.3 不解决的后果

系统会继续在"看起来在运行"和"实际未完成"的裂缝间反复摆动，每个版本修复几个 bug 又引入几个新假设，记忆表持续被污染，直到某次实盘尝试用基于错误数据优化的编排做出不可逆的错误交易决策。那个时刻，梦会醒来——但醒来的代价可能是真金白银的损失。

### 4.4 做梦部建议（沿用 07-23 报告框架）

**第一步：醒来**
- 停止版本号升级（v2.6/v3.0 等）
- 接受"系统未真正闭环"的事实
- 检查当前实盘状态：547 条 open 记录涉及哪些 symbol、多少浮盈浮亏

**第二步：补全记忆**
- 修复 A9 离场节点的 HOLD 死锁（让 exit_decision 不再永远 HOLD）
- 让 `update_exit_feedback` 调用路径可达（去除 `if exit_result["exit"]:` 守卫或在 HOLD 时也回填）
- 让进化引擎解冻（zero_ratio 从 1.0 降下来）

**第三步：清理幻觉**
- 清除 `orchestration_memory.json` 中 19 个模板假数据（调用 `purge_template_data()`）
- 删除 `evolution_test.py` 硬编码 PASS，写真实测试断言
- 将 88 个 🟢 中"骨架存在但功能未完成"的降级为 🟡 或 🔴

**第四步：面对现实**
- 用真实反馈数据重新评估编排记忆表
- 在真实实盘数据上重跑回测（v2.5 之前的回测结果作废）
- 让"实践是检验真理的唯一标准"真正落地

---

## 附录 A：关键文件路径索引

### A8 视角关键文件
- `1-ARCHITECTURE/dreamos/core/graph_store/compressor.py`（BAC 未实现）
- `1-ARCHITECTURE/dreamos/core/compute/aggregator.py`（无三链投票）
- `1-ARCHITECTURE/dreamos/core/arrange/types.py:186-191`（ONEIROLOGY 空声明）
- `1-ARCHITECTURE/dreamos/capabilities/trading/nodes/a8_unity.py`（无 gap_score 路由）
- `1-ARCHITECTURE/dreamos/core/arrange/node_selector.py`（硬编码非动态查询）
- `1-ARCHITECTURE/dreamos/core/arrange/types.py:105-199`（STANDARD_CHAINS 硬编码）

### 做梦部视角关键文件
- `1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md:302-316`（两阶段三链叙事）
- `1-ARCHITECTURE/dreamos/docs/TECHNICAL_DESIGN.md:78-82`（自我打脸澄清）
- `1-ARCHITECTURE/dreamos/cli/start_scheduler.py:45-49`（"平仓维护中"投射）
- `1-ARCHITECTURE/dreamos/cli/scheduler.py:310-311`（dry_run 默认兜底）
- `1-ARCHITECTURE/dreamos/__init__.py:44,47,75,81`（版本号+占位）

### 反馈完整性关键文件
- `1-ARCHITECTURE/dreamos/core/memory/execution_feedback.json`（547 open / 0 closed）
- `1-ARCHITECTURE/dreamos/core/memory/orchestration_memory.json`（36 / 3 verified）
- `1-ARCHITECTURE/dreamos/cli/auto_trader.py:2102-2127`（exit 守卫阻断 update）
- `1-ARCHITECTURE/dreamos/evolution/engine.py:136-194`（三重冻结）
- `1-ARCHITECTURE/dreamos/cli/multi_scenario_stress_test.py:62-120`（mock 数据）
- `1-ARCHITECTURE/dreamos/cli/evolution_test.py:55-64`（硬编码 PASS）
- `1-ARCHITECTURE/dreamos/data/graph_store/ckpt_20260806040106_39ec9c.json`（A9 HOLD 证据）

---

## 附录 B：与 07-23 做梦部报告的对照

| 07-23 报告假说 | 08-06 诊断验证 |
|---------------|---------------|
| 假说 1：从未真正在实盘中验证过任何改造 | **确认**：547 条 result 全 0，0 条 closed |
| 假说 2：编排记忆表修复让系统更危险 | **部分确认**：19 个模板数据未被清理，`purge_template_data()` 从未调用 |
| 假说 3：进化引擎从未进化过任何东西 | **确认升级**：进化引擎被三重冻结，提案能力退化 |
| 假说 4：系统用"功能开发"回避"效果验证" | **确认持续**：v2.5/v2.6/v3.0 持续升级但反馈断裂未修 |
| 假说 5：整个系统在"假装运行" | **确认升级**：测试套件实际为空，evolution_test 硬编码 PASS |

**梦游状态持续 14 天，症状从 277 条恶化到 547 条。**

---

**报告生成时间**：2026-08-06
**诊断方法**：A8 知行合一校验（gap_score 矩阵）+ 做梦部弗洛伊德梦的解析（凝缩/移置/象征/二次修正/投射 + 强迫性重复）+ 执行反馈完整性核查（数据抽样 + git 历史）
**报告版本**：v1.0
**研究对象**：Dream OS 内核（`1-ARCHITECTURE/dreamos/`）
**未修改任何文件**
