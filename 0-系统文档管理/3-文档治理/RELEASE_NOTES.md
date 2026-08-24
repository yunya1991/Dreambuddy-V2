# 文档体系版本日志 — RELEASE_NOTES

> **版本**: v1.5 | **更新日期**: 2026-08-24
> **定位**: 记录 0-系统文档管理 体系本身的版本变更
> **关联**: [INDEX.md](../INDEX.md) · [DOC_DEBT_INDEX.md](./DOC_DEBT_INDEX.md)

---

## [v1.5] - 2026-08-24

### 修改

- **变更内容**: 11-易经推理系统 **v4.6 过滤层统一基础阈值门控** + **v4.6.1 L3/L4 仓位归属语义重构** 架构文档同步
- **影响范围**: 11-易经推理系统 技术文档 · 0-系统文档管理/2-文档地图
- **验证方式**: 代码锚点对齐 polling_trader.py L7936-L8038（基础阈值判定）+ L8224-L8292（L3/L4 仓位流向分流）+ L9170-L9224（动态阈值调节）+ trading_utils.py L57-63（TradeRecord 新增字段）
- **触发原因**: ①v4.5 中「P1=BLOCK→is_trial=True」单因子绑定语义与 Spec F1「永不 BLOCK」冲突；②旧实现中 is_trial×0.4 简单乘法同时叠加 L3 弹簧/形态分档，导致试错仓仓位基线非保守、非预期

#### 11-易经推理系统 TECHNICAL_DESIGN v4.6 → v4.6.1 架构升级
- [TECHNICAL_DESIGN.md](../../11-易经推理系统/docs/TECHNICAL_DESIGN.md) v4.5→v4.6→v4.6.1
- **v4.6 过滤层统一基础阈值门控（§2.2b.3 新增）**：
  - 核心修正：删除「P1=BLOCK → is_trial=True」单因子绑定，改为 P1/Elder/BCRM 三层均产出 Score_P/Score_E/Score_B → ElasticGate3L 三层加权（ThreeLayerWeighter 动态权重 w_p:w_e:w_b）→ `score_consensus` 与 `_gate_base_threshold（默认0.40，边界[0.25,0.60]）` 统一比较
  - L4 唯一硬拦截：`score_consensus < base_threshold`；≥门槛但 confidence<eff→统一轻仓试错 is_trial=True（P1=WEAK/STANDARD/BLOCK 全走同一通道）
  - 动态阈值调节（30-150 笔聚合样本、非单笔）：胜率<40%或亏-3%→+0.03；胜≥60%且盈>2%→-0.02；冷却 30min
  - 方案 C 子系统生效审计增强：PhaseC 仓位调控日志输出 S_P/S_E/S_B/cons/w_p/w_e/w_b/w_src/src 明细，可直接判断 ThreeLayerWeighter（fail_open→需≥30 BCRM盈亏样本）、WinProb（sample_count≥20 才≠1.00）、做空收紧（src=short_tightened）是否真实生效
  - TradeRecord 新增 `score_consensus` / `gate_base_threshold` 两字段用于审计和动态调节
- **v4.6.1 L3/L4 仓位归属语义重构（§2.2b.4 新增）**：
  - **L3 后置校准层不介入试错仓**：`if not is_trial:` 才执行弹簧做多做空分档 + v4 风险评分仓位调整 + 形态乘数 position_mult；`is_trial=True` 时日志输出「轻仓试错(过滤层接管仓位) | 跳过L3弹簧/形态/v4分档 → 交由 ElasticGate3L/F1 弹性闸门控制最终仓位」
  - **L4 过滤层接管试错仓仓位**：删除旧实现 `is_trial: position_usdt ×= 0.4` 简单乘法；直接由 ElasticGate3L 弹性矩阵 + F1 下界 0.10 控制（BLOCK=0.10 / WEAK=0.30 / STANDARD=0.50 等），完全等价于 Spec F1 永不 BLOCK 语义
  - 七层职责速查表重写：L3 标注「正常开仓=调仓位大小；轻仓试错=全跳过」；L4 标注「统一共识评分 + 唯一硬门槛 + 接管试错仓仓位」
  - 分层关键边界 8 条明确：P1/Elder/BCRM 取消硬拦截 return；G-04/最大持仓/can_trade 熔断归 L5；做空三重收紧严格生效；方案 C 8 开关默认全 True；动态阈值基于聚合样本
- 七层架构 ASCII 图更新：L4 改名「弹性放行层」；三分支判定（①<0.40不开仓 ②≥+conf达标→正常 ③≥+conf不够→试错跳过L3）
- §16 变更日志顶部新增 v4.6 / v4.6.1 两条目

#### 0-系统文档管理 地图同步
- [ARCHITECTURE_MAP.md](../2-文档地图/ARCHITECTURE_MAP.md) v2.1→v2.2：
  - §1.2 标题更新为「七层交易决策栈（v4.6.1 对齐 Spec v3.0 永不BLOCK）」；关联 TECHNICAL_DESIGN 版本 v4.6.1
  - ASCII 架构图升级：L4 改名「弹性放行层」；标注三分支判定和 L3/L4 仓位流向差异；L5 明确 G-04/最大持仓/can_trade 熔断；L6 增加 base_threshold 盈亏样本记录
  - 分层速查表 L3/L4 动作类型和关键开关升级：L3 标注「正常开仓=调仓位大小；轻仓试错=全跳过」；L4 标注「统一共识评分 + 唯一硬门槛 + 接管试错仓仓位」；唯一硬拦截=`score_consensus < _gate_base_threshold(默认0.40，边界[0.25,0.60])`
  - 实战修正升级为「核心语义修正（v4.6 → v4.6.1 仓位归属严格对齐）」7 条要点（L3 不介入试错仓 / L4 接管试错仓位 / P1ElderBCRM 取消硬拦截 / 删除 is_trial×0.4 / 做空三重收紧 / 方案 C 8开关全启 / 动态阈值聚合）

---

## [v1.4] - 2026-08-24

### 新增

- **变更内容**: 11-易经推理系统 **七层交易决策栈（v4.5）** 架构梳理与文档同步 + 方案 C 全量上线记录
- **影响范围**: 11-易经推理系统 技术文档 · 0-系统文档管理/2-文档地图 · 3-文档治理
- **验证方式**: 代码锚点对齐 polling_trader.py _execute_trade()（L7652-L7802 趋势过滤层）+ _open_position()（L7974-L8003 策略层）+ 方案 C 8 开关默认 True（L307-L320 init 参数）
- **触发原因**: 2026-08-23~24 COIN（做空方向错误被 OKX SL 触发）/ SOL（29H 超时平仓）/ HYPE（做空阈值>1.0硬禁）实战暴露的分层语义模糊 → 明确「过滤层拦截 vs 校准层调仓位」边界

#### 11-易经推理系统 TECHNICAL_DESIGN v4.5 架构升级
- [TECHNICAL_DESIGN.md](../../11-易经推理系统/docs/TECHNICAL_DESIGN.md) v4.4→v4.5
- 新增 **§2.2b 七层交易决策栈（纵向交易决策链）**：
  - L0 五计庙算（战略层）：enable_five_domain + 7 子开关；道/天/地/将/法 五维加权；三档决策（≥75进攻 / 60-74低仓 / <60防守）+ 仓位四档映射 + 维度否决规则
  - L1 前置层（市场形态识别）：市场形态演化引擎 + MorphCyclePredictor + α blend → 前瞻参数
  - L2 核心层（BCRM 2.0信号）：辩证ML + 八卦力学 + QMM → direction/confidence/hexagram
  - L3 后置校准层（调仓位不拦截）：弹簧力场 5 态 + 五维权重 w_p:w_e:w_b + WinProb + **做空三重收紧**（Score_B<0.70→clip0.55 / Elder≤NEUTRAL降级 / w_b×0.70）
  - L4 过滤层（P1升级版，不通过直接拦截）：三道并行拦截（原均线过滤 + Elder-ray日线 + BCRM N=5连续），SHORT 要求更严（≥ALIGN_BASIC）；后续 CBR/ElasticGate3L/BTC自反/WinProb/组合熔断 G-02/G-04 全链路
  - L5 策略层：enable_strategy_layer + SL/TP 写入 + 下单接口调用 + **SL/TP 价格空间下限保护**（ATR 极低时 SL≥1.5%/试错≥2.0%）
  - L6 持仓管理与离场层：ExitManager 策略链 + 卦象主离场（已删除 Classic 兜底备用层）+ **轻仓试错评估周期**（持仓≥30min 趋势评估：确认→加仓 / 不明→维持 / 逆转→平仓）
- §2.2 四层功能架构补充 v4.5 视角说明（横向系统视角 vs 纵向交易决策链互补）
- **新增 §2.2b.1 SL/TP 价格空间下限保护**（XAG 案例修复）：ATR 极低时 SL 最低 1.5%（试错仓 2.0%）、TP 最低 3.0%（试错仓 4.0%）
- **新增 §2.2b.2 轻仓试错评估周期**：TradeRecord 新增 is_trial/trial_eval_done/trial_open_ts 三字段；持仓≥30min 后触发趋势评估（仅一次）
- §16 变更日志顶部新增 v4.5 条目（方案 C 8 开关全启 + 删除 classic 备用离场层 + VOLATILE_DROP 阈值优化 + confidence 阈值分层 + SL 下限保护 + 试错评估周期 + COIN/SOL/XAG 案例教训）

#### 0-系统文档管理 地图同步
- [ARCHITECTURE_MAP.md](../2-文档地图/ARCHITECTURE_MAP.md) v2.0→v2.1：新增 §1.2「11-易经推理系统 · 七层交易决策栈」架构总览图 + 分层速查表 + 实战修正要点（过滤层 L4 拦截 vs 校准层 L3 调仓位）；子系统矩阵 TECHNICAL_DESIGN 版本对齐 v4.5
- [SYSTEM_MAP.md](../2-文档地图/SYSTEM_MAP.md) v2.0→v2.1：11-易经推理系统定位更新为含七层交易决策栈 + 方案 C 8 子系统；文档版本对齐 v4.5；关联方案 C Spec v3.0 链接

---

## [v1.3] - 2026-08-02

### 新增

- **变更内容**: 文档管理自动化工具建成 + L3 缺失文档补齐 + 审计机制落地
- **影响范围**: 0-系统文档管理/4-工具与自动化、3-文档治理、L3 辅助模块、10-经典指标系统
- **验证方式**: 4 工具实跑验证 + link_checker 元层 0 断链 + doc_coverage L2 100%

#### 4-工具与自动化建成（P2→已完成）
- [doc_lint.py](../4-工具与自动化/doc_lint.py) — 文档命名/格式/版本头/README-INDEX 冲突检查
- [doc_coverage.py](../4-工具与自动化/doc_coverage.py) — L2/L3 文档覆盖率统计
- [index_generator.py](../4-工具与自动化/index_generator.py) — 目录树自动生成
- [link_checker.py](../4-工具与自动化/link_checker.py) — 跨文档链接校验（含内联代码剥离）
- [4-工具与自动化/README.md](../4-工具与自动化/README.md) 升级为已建设，含 CI 集成示例

#### L3 缺失文档补齐（DD-008 部分关闭）
- [15-监控告警系统/docs/ENGINEERING_INDEX.md](../../15-监控告警系统/docs/ENGINEERING_INDEX.md) v1.0 — 138 函数/38 配置项从代码提取
- [15-监控告警系统/docs/TECHNICAL_DESIGN.md](../../15-监控告警系统/docs/TECHNICAL_DESIGN.md) v1.0 — 6 层架构 + 5 段核心算法伪代码
- [7-产物中台/docs/TECHNICAL_DESIGN.md](../../7-产物中台/docs/TECHNICAL_DESIGN.md) v1.0 — 12 章节/58 接口，修正原文档 5 处与代码不一致
- [3-EVOLUTION/README.md](../../3-EVOLUTION/README.md) v0.1→v0.2 — 补设计概述（9 阶段流水线+三桥接）
- [6-图结构上下文压缩/README.md](../../6-图结构上下文压缩/README.md) v0.1→v0.2 — 补设计概述（双维度编排 5 理念）
- [10-经典指标系统/README.md](../../10-经典指标系统/README.md) v1.0 — 补建缺失 README，L2 覆盖率 97%→100%

#### 审计机制落地
- [AUDIT_REPORT_TEMPLATE.md](./AUDIT_REPORT_TEMPLATE.md) v1.0 — 月度审计报告标准模板
- [audits/2026-08_月度审计报告.md](./audits/2026-08_月度审计报告.md) — 首份基线审计报告

### 修改

- **变更内容**: 元层断链修复 + 文档债刷新
- [DOC_DEBT_INDEX.md](./DOC_DEBT_INDEX.md) 链接 `../../../` → `../../`（修 2 处断链）
- [INDEX.md](../INDEX.md) 4-工具与自动化 状态刷新、L3 模块状态刷新
- [L3_MODULE_DOC_PLAN.md](./L3_MODULE_DOC_PLAN.md) 现状表刷新（3/6 号 README 已存在）

### 新增文档债务

| ID | 优先级 | 说明 |
|----|--------|------|
| DD-022 | P2 | 全项目 1440 断链需分流排查 + link_checker 增代码白名单 |
| DD-023 | P3 | L3_MODULE_DOC_PLAN 现状过时（已本期修复） |
| DD-024 | P3 | 0-系统文档管理根 README/INDEX 并存（L0 豁免，建议 doc_lint 加豁免规则） |

---

## [v1.2] - 2026-07-31

### 修改

- **变更内容**: P0/P1 文档债批量修复，消除双 v3.0 架构冲突，刷新 17 号导航信息
- **影响范围**: 根目录核心文档 + 0-系统文档管理 全量
- **验证方式**: 链接有效性抽查 + 版本一致性检查

#### P0 权威冲突修复
- 根 [TECHNICAL_DESIGN.md](../../TECHNICAL_DESIGN.md) 降级为 LEGACY 归档，重定向到 SSoT v3.0
- 根 [ENGINEERING_INDEX.md](../../ENGINEERING_INDEX.md) 升级到 v3.0，SSoT 层级表消除双 v3.0 冲突

#### P1 导航信息刷新
- [INDEX.md](../INDEX.md) 17 号从"待建立"改为已建立（v1.0），L2 覆盖率 86%→100%
- [SYSTEM_MAP.md](../2-文档地图/SYSTEM_MAP.md) 新增 17 号子系统条目，6→7 子系统
- [ARCHITECTURE_MAP.md](../2-文档地图/ARCHITECTURE_MAP.md) 修复链接格式错误，17 号标为已建立
- [INDEX.md](../INDEX.md) 修复不存在的 MEMORY_SYSTEM_ARCHITECTURE.md 引用
- 16 号 TECHNICAL_DESIGN 评级从 C（范围错位）改为 A（DD-004 已修复 v2.0）
- [DOC_QUALITY_AUDIT.md](./DOC_QUALITY_AUDIT.md) 升级到 v1.1，质量状态表纳入 17 号，修正 16 号评级

#### 文档债关闭
- DD-002/003（架构文档过时/散落）— 已关闭
- DD-004（16 号 TECHNICAL_DESIGN 范围错位）— 已关闭
- DD-005（13 号 ENGINEERING_INDEX 缺版本号）— 已关闭
- DD-017（记忆系统接口契约 SPEC）— 已关闭
- DD-018（认知系统 TECHNICAL_DESIGN）— 已关闭

---

## [v1.1] - 2026-07-31

### 新增

- **变更内容**: 记忆系统与认知系统文档补齐
- **影响范围**: 4-MEMORY 子系统

#### 新增文档
- [4-MEMORY/6-应用记忆索引/MEMORY_INTERFACE_SPEC.md](../../4-MEMORY/6-应用记忆索引/MEMORY_INTERFACE_SPEC.md) — 记忆系统接口契约统一 SPEC（关闭 DD-017）
- [4-MEMORY/9-工具与接口/docs/TECHNICAL_DESIGN.md](../../4-MEMORY/9-工具与接口/docs/TECHNICAL_DESIGN.md) — 认知系统技术设计（关闭 DD-018）

### 修改
- [DOC_DEBT_INDEX.md](./DOC_DEBT_INDEX.md) 升级到 v1.2，文档债务率 35%→24%

---

## [v1.0] - 2026-07-25

### 新增

- **变更内容**: 0-系统文档管理 元层建立
- **影响范围**: 全项目文档体系
- **验证方式**: 检查 0-系统文档管理/ 目录结构完整性
- **回滚策略**: 删除 0-系统文档管理/ 目录，恢复 PROJECT_DOC_STANDARD.md 原位

#### P0 骨架
- 建立 [0-系统文档管理/README.md](../README.md) 总入口
- 建立 [0-系统文档管理/INDEX.md](../INDEX.md) 全项目文档索引（L0/L1/L2/L3 分层 + 主题索引 + 覆盖率统计）

#### P1 规范体系
- 迁移 PROJECT_DOC_STANDARD.md v1.1 → [1-规范体系/DOC_STANDARD.md](../1-规范体系/DOC_STANDARD.md) v2.0
- 新增 [1-规范体系/DOC_CLASSIFICATION.md](../1-规范体系/DOC_CLASSIFICATION.md) 文档分类体系（L0-L3 分级 + 7 类角色 + 命名规范）
- 新增 5 份文档模板：
  - [TEMPLATES/README_TEMPLATE.md](../1-规范体系/TEMPLATES/README_TEMPLATE.md)
  - [TEMPLATES/ENGINEERING_INDEX_TEMPLATE.md](../1-规范体系/TEMPLATES/ENGINEERING_INDEX_TEMPLATE.md)
  - [TEMPLATES/TECHNICAL_DESIGN_TEMPLATE.md](../1-规范体系/TEMPLATES/TECHNICAL_DESIGN_TEMPLATE.md)
  - [TEMPLATES/API_SPEC_TEMPLATE.md](../1-规范体系/TEMPLATES/API_SPEC_TEMPLATE.md)
  - [TEMPLATES/CHANGELOG_TEMPLATE.md](../1-规范体系/TEMPLATES/CHANGELOG_TEMPLATE.md)

#### P2 文档地图
- 新增 [2-文档地图/SYSTEM_MAP.md](../2-文档地图/SYSTEM_MAP.md) 全系统文档地图（1 元层 + 7 顶层 + 6 子系统 + 6 辅助）
- 新增 [2-文档地图/TOPIC_MAP.md](../2-文档地图/TOPIC_MAP.md) 主题索引（10 个主题跨系统导航）
- 新增 [2-文档地图/ARCHITECTURE_MAP.md](../2-文档地图/ARCHITECTURE_MAP.md) 架构文档地图（当前实际架构 + 债务）

#### P3 文档治理
- 新增 [3-文档治理/DOC_DEBT_INDEX.md](./DOC_DEBT_INDEX.md) 文档技术债清单（9 项待修复 + 6 项已关闭）
- 新增 [3-文档治理/DOC_LIFECYCLE.md](./DOC_LIFECYCLE.md) 文档生命周期管理（5 阶段 + 状态定义 + 审计流程）
- 新增 [3-文档治理/DOC_QUALITY_AUDIT.md](./DOC_QUALITY_AUDIT.md) 文档质量审计标准（5 维度 + 评分标准 + 检查项）

### 修改

- **变更内容**: PROJECT_DOC_STANDARD.md 改为重定向到 0-系统文档管理/1-规范体系/DOC_STANDARD.md
- **影响范围**: 根目录 PROJECT_DOC_STANDARD.md
- **验证方式**: 访问根目录 PROJECT_DOC_STANDARD.md 应看到重定向提示
- **回滚策略**: 恢复 PROJECT_DOC_STANDARD.md 原内容

### 关联变更

#### P4 衔接（根目录与元层对齐）
- **README.md** 瘦身为极简入口（257 行 → 80 行），文档导航统一指向 0-系统文档管理
- **PROJECT_DOC_STANDARD.md** 替换为重定向锚点，指向 0-系统文档管理/1-规范体系/DOC_STANDARD.md
- **DEBT_INDEX.md** 升级到 v2.3，新增与 0-系统文档管理/DOC_DEBT_INDEX.md 的双向引用，补充 S4 步骤记录
- **ENGINEERING_INDEX.md**（根）SSoT 层级表新增 0-系统文档管理 与 DOC_STANDARD.md 条目
- **0-系统文档管理/README.md** 修正 SSoT 引用，从 PROJECT_DOC_STANDARD.md 改为 DOC_STANDARD.md

---

## 版本策略

- **主版本号**（X.0）：重大结构变更（如新增子目录、改变分级体系）
- **次版本号**（X.X）：内容增补或修订（如新增模板、更新地图）
- **修订号**（X.X.X）：小幅修正（如修复链接、错别字）

---

**文档版本**: v1.5（同步 11-易经推理系统 v4.6 基础阈值门控与 v4.6.1 L3/L4 仓位归属重构）
**最后更新**: 2026-08-24
