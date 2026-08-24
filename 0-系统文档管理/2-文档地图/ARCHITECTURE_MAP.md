# 架构文档地图 — ARCHITECTURE_MAP

> **版本**: v2.2 | **更新日期**: 2026-08-24
> **定位（视角 B）**: **架构导航地图，不是架构内容本身**。告诉你「架构文档有哪些、到哪里找」。
> **架构唯一事实源（SSoT）**: ★ [1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md](../../1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md) **v3.0**。所有架构设计争议、硬约束、模块边界以该文档为准。
> **关联**: [SYSTEM_MAP.md](./SYSTEM_MAP.md) · [TOPIC_MAP.md](./TOPIC_MAP.md) · [INDEX.md](../INDEX.md)
> **11号子系统交易决策栈（v4.6.1 最新）**: 详见 [11-易经推理系统 TECHNICAL_DESIGN §2.2b](../../11-易经推理系统/docs/TECHNICAL_DESIGN.md)，七层：五计庙算→前置层→核心层→后置校准层→弹性放行层→策略层→持仓与离场层

---

## 0. 视角 B 文档分工（重要！）

```
★ 架构内容（你想了解系统怎么设计）→  打开 1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md v3.0
  │
  ├─ 第1-4章：三层架构 + SACG OS内核 + 能力层 + 应用层（子系统映射）
  ├─ 第5章：  三大思维链 + 三大核心闭环 + A0矛盾论
  ├─ 第6章：  认知系统 + 记忆进化（开发闭环 ↔ 交易闭环对称）
  ├─ 第7章：  公司中枢（六部门+双中台+双交易流+四层合规）
  ├─ 第8章：  数据流 + MEP协议 + 双语言桥接 + 适配器路由
  ├─ 第9章：  依赖DAG + 目录全景 + 部署拓扑 + 配置/存储映射
  ├─ 第10章： 硬约束清单（违反即 bug）+ 禁止事项 Anti-patterns
  ├─ 第11章： 技术债全景 103 项 × 8 分类 × 4 优先级 + 修复批次
  └─ 第12章： 文档索引 + 版本历史 + 演进路线图 + 术语表

📋 文档导航（你想找某个文档在哪）→  停留在本页 ARCHITECTURE_MAP / SYSTEM_MAP
  └─ 本节提供按「层级 / 专题 / 子系统 / 生命周期」四种查找方式
```

---

## 1. 架构速览（从 SSoT 提炼，详细以 v3.0 为准）

### 1.1 三层架构全景（SSoT §1.2）

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│  应用层 🟢   TradingAgent · HTTP API · CLI · 6交易子系统前端 · IDE认知入口         │
└──────────────────────────────────────┬───────────────────────────────────────────┘
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│  能力层 🟡   A_domain AI交易(A0-A9) · C_domain 经典量化 · F_domain 基本面         │
│             G_domain 通用工具 · T_domain 系统支撑  （共 35+ 模块化能力）           │
└──────────────────────────────────────┬───────────────────────────────────────────┘
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│  OS内核 🔴   S感知层 · A编排层 · C执行层 · G图存储层  +  横切服务                   │
│            (Registry / Evolution / Budget / Adapters / Errors)                   │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 11-易经推理系统 · 七层交易决策栈（v4.6.1 对齐 Spec v3.0 永不BLOCK）

> **详细实现**：[11-易经推理系统 TECHNICAL_DESIGN §2.2b](../../11-易经推理系统/docs/TECHNICAL_DESIGN.md) v4.6.1

```
                    【交易决策链纵向七层 · v4.6.1】
         ┌─────────────────────────────────────────┐
L0 战略  │  五计庙算（enable_five_domain + 7子开关）│  → war_state / cap / mask / 五维总分
         └──────────────────┬──────────────────────┘
                            ▼
L1 前置  │  市场形态演化引擎 + MorphCyclePredictor  │  → L_forecast / T_forecast / α blend / 弹簧5态（只定范围）
         └──────────────────┬──────────────────────┘
                            ▼
L2 核心  │  BCRM 2.0 辩证ML + 八卦力学 + QMM         │  → direction / confidence / hexagram
         └──────────────────┬──────────────────────┘
                            ▼
L3 校准  │  弹簧力场 + v4风险评分 + 形态乘数         │  → 仅正常开仓（conf≥eff）调仓位大小
         │  + WinProb + 做空三重收紧                 │  → ★轻仓试错（is_trial=True）全部跳过
         │  + SL/TP 价格空间下限保护（常规≥1.5%/试错≥2.0%）│  → ATR 极低时防扫损
         └──────────────────┬──────────────────────┘
                            ▼
L4 放行  │  ★ Spec v3.0 F1 永不硬拦截：BLOCK→0.10    │  P1→S_P + Elder→S_E + BCRM→S_B
         │  ElasticGate3L 三层加权（w_p/w_e/w_b）    │  → score_consensus 与 base_threshold（默认0.40）比较
         │  + CBR双闭环 / BTC自反 / 组合熔断G-02/G-04│  ① <0.40 → 不开仓（L4唯一硬门槛）
         │  + 做空三重收紧（Score_B<0.7→clip/Elder降级/w_b×0.7）│  ② ≥0.40 + conf≥eff → 正常开仓→叠加L3仓位
         │  + 动态基础阈值（30-150笔滑窗 ±0.03/-0.02）│  ③ ≥0.40 + conf<eff → is_trial→跳过L3→EG3L F1接管仓位
         └──────────────────┬──────────────────────┘
                            ▼
L5 策略  │  enable_strategy_layer + 下单确认         │  → OKXClient / SimClient 下单
         │  + G-04 权益回撤熔断 / 最大持仓 / can_trade│  → L4 不拦截，L5 最终风控确认
         └──────────────────┬──────────────────────┘
                            ▼
L6 离场  │  ExitManager 策略链 + 卦象主离场           │  → exit_strategy_log + CBR 回填
         │  已删除 Classic 兜底备用层                │  → base_threshold 盈亏样本记录
         │  + 轻仓试错评估周期（≥30min 趋势评估）     │  → 确认→加仓信号 / 逆转→平仓 / 不明→维持
         └──────────────────────────────────────────┘
```

| 层级 | 名称 | 动作类型 | 关键开关 |
|------|------|----------|----------|
| L0 | 五计庙算（战略层） | 定总基调 | enable_five_domain（默认 False，中性旁路） |
| L1 | 前置层（市场形态识别） | 生前瞻参数 | enable_morph_cycle（随前置层总开关） |
| L2 | 核心层（BCRM 2.0信号） | 生方向信号 | BCRM2Adapter enable |
| L3 | 后置校准层（只调正常仓位） | **正常开仓=调仓位大小；轻仓试错=全跳过** | SW-C3 三层权重 / SW-C4 ElasticGate / SW-C6 WinProb（默认全 True）；`if not is_trial:` 才执行弹簧做多做空分档 + v4 风险评分仓位调整 + 形态乘数 position_mult |
| L4 | 弹性放行层（Spec v3.0 永不BLOCK） | **统一共识评分 + 唯一硬门槛 + 接管试错仓仓位** | SW-C1 CBR / SW-C2 Elder / SW-C7 ContinuityObs / SW-C5 BTC自反 / SW-C8 组合熔断；唯一硬拦截=`score_consensus < _gate_base_threshold（默认0.40，边界[0.25,0.60]）`；BLOCK→0.10试错仓 |
| L5 | 策略层（最终风控+下单） | 确认下单 + 最终熔断 | enable_strategy_layer（默认 False）+ G-04 3%权益回撤熔断 / 最大持仓数 / can_trade 熔断 |
| L6 | 持仓管理与离场层 | 管持仓盈亏 + 动态阈值样本 | ExitManager 各策略独立开关 + 轻仓试错评估周期（≥30min一次性评估）+ 盈亏样本驱动 base_threshold 动态调节 |

> **核心语义修正（v4.6 → v4.6.1 仓位归属严格对齐）**：
> - **L3 后置校准层不介入试错仓**：正常开仓（conf≥eff）→ 弹簧分档/v4风险/形态乘数全部应用；轻仓试错（score_cons≥门槛但conf不足）→ 全部跳过 L3 校准，日志输出「轻仓试错(过滤层接管仓位) | 跳过L3弹簧/形态/v4分档」
> - **L4 弹性放行层接管试错仓仓位**：直接由 ElasticGate3L 弹性矩阵 + F1 下界 0.10 控制（BLOCK=0.10 / WEAK=0.30 / STANDARD=0.50 等），完全等价于 Spec F1 永不 BLOCK 语义
> - **P1/Elder/BCRM 取消硬拦截（return）**：全部产出 Score_P/Score_E/Score_B 交给 EG3L 加权综合；单因子 BLOCK 只是贡献低分，可由其他高分因子拉高 `score_consensus` 通过门槛
> - **删除 is_trial × 0.4 简单乘法**：旧实现叠加 L3 分档会非预期放大/削弱试错仓，新实现精确控制
> - **做空三重收紧严格生效**：Score_B<0.70→clip0.55 / Elder≤NEUTRAL→降级 / BCRM自身权重 w_b×0.70
> - **方案 C 8 开关（SW-C1~C8）默认全 True**：G-04 单日 3% 权益回撤触发全开关旁路 24h
> - **动态基础阈值（聚合样本、非单笔）**：近30-150笔胜<40%或亏-3%→+0.03；胜≥60%且盈>2%→-0.02；冷却30min

### 1.3 双闭环对称架构（SSoT §1.3.2, §5.4, §6.1）

| 闭环 | 定位 | 核心组件 | 结果产物 |
|------|------|----------|----------|
| 🔵 **交易决策闭环** | 解决「怎么交易」 | A0矛盾→A1调研→A9离场；A6五级放射监控；A8知行合一 | 交易信号 / 开仓 / PnL |
| 🟣 **开发认知闭环** | 解决「怎么写代码」 | daemon监听→git hook→会话→SolutionPath→记忆蒸馏 | 代码提交 / 应用模板 / 总记忆 |

> 两大闭环通过 **4-MEMORY 记忆系统** 互通：交易侧积累的经验蒸馏为 L2 总记忆原则，开发侧沉淀的方法论反哺交易策略进化。（SSoT §6.5, §6.7）

### 1.3 三大思维链范式（SSoT §5.1）

| 思维链 | 定位 | 五阶段框架 | 典型节点 |
|--------|------|-----------|----------|
| **S 链** | 主骨架·元方法论 | 调研→分析→设计→验证→执行 | A 系列节点动态填充 |
| **C 链** | 量化导向·数据说话 | 扫描→识别→匹配→回测→参数 | C 系列指标/回测节点 |
| **F 链** | 基本面导向·逻辑驱动 | 新闻→资金→情绪→链上→宏观 | F 系列新闻/链上节点 |

---

## 2. 架构文档索引

### 2.1 顶层架构文档（按优先级）

| 优先级 | 文档 | 路径 | 状态 | 说明 |
|--------|------|------|------|------|
| ★★★ SSoT | **SYSTEM_ARCHITECTURE_OVERVIEW.md v3.0** | [1-ARCHITECTURE/](../../1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md) | ✅ 草稿待评审 | **唯一事实源**。12 章全量覆盖：OS内核+能力层+应用层+认知系统+硬约束+技术债 |
| ★★☆ 专题 | TRADING_MODULES_OVERVIEW.md | [1-ARCHITECTURE/](../../1-ARCHITECTURE/TRADING_MODULES_OVERVIEW.md) | 🟡 与 v3.0 对齐 | A/C/F 链模块细节 + 三环架构 + 核心模块清单 |
| ★★☆ 专题 | THREE_CHAIN_DISPATCH_CHECKLIST.md | [1-ARCHITECTURE/](../../1-ARCHITECTURE/THREE_CHAIN_DISPATCH_CHECKLIST.md) | 🟡 与 v3.0 对齐 | 操作手册级：A0-A9 各阶段 SKILL + 核心方法论 |
| ★★☆ 专题 | SUPERPOWERS_INTEGRATION_UPGRADE.md | [1-ARCHITECTURE/](../../1-ARCHITECTURE/SUPERPOWERS_INTEGRATION_UPGRADE.md) | 🟡 参考 | 超能力集成 + SACG 流程参考 |
| 📦 归档 | WORKBUDDY_OS_MODULAR_ARCHITECTURE.md v1.1 | [1-ARCHITECTURE/](../../1-ARCHITECTURE/WORKBUDDY_OS_MODULAR_ARCHITECTURE.md) | 📦 仅迁移参考 | TS 视角早期设计（NodeRegistry/ModuleRegistry/错误码），决策以 v3.0 为准 |
| 📦 归档 | 1-ARCHITECTURE/README.md | [1-ARCHITECTURE/README.md](../../1-ARCHITECTURE/README.md) | ⚠️ 过时待替换 | 旧"六大核心系统"描述，与 10-16 号子系统不匹配，将被 v3.0 替换 |
| ★★☆ 专题 | 公司中枢设计 | [1-ARCHITECTURE/中台设计/COMPANY_CENTRAL_HUB.md](../../1-ARCHITECTURE/中台设计/COMPANY_CENTRAL_HUB.md) | 🟡 与 v3.0 §7 对齐 | 六部门矩阵 + 双中台 + 双交易流详细设计 |

### 2.2 子系统架构文档（对应 SSoT §4.2 应用层）

| 子系统 | 技术设计 | 5 文档齐全 | 核心架构（SSoT 映射） |
|--------|----------|-----------|----------------------|
| 10-经典指标 | [docs/TECHNICAL_DESIGN.md](../../10-经典指标系统/docs/TECHNICAL_DESIGN.md) | ✅ 已迁移 | 16层信号 + ClassicExitSystem → C_domain 经典量化 |
| 11-易经推理 | [docs/TECHNICAL_DESIGN.md](../../11-易经推理系统/docs/TECHNICAL_DESIGN.md) **v4.5** ✅ | ✅ 齐全 | **七层交易决策栈**（L0 五计庙算战略→L6 持仓管理与离场）· BCRM 2.0 + 辩证ML + 五角校验 + ExitManager 策略链 + 方案 C v3.0 全量上线（8 开关默认 True） → A_domain AI交易核心 |
| 12-三屏趋势 | [docs/TECHNICAL_DESIGN.md](../../12-三屏趋势系统/docs/TECHNICAL_DESIGN.md) **v4.0** | ✅ 齐全 | V4+波浪互斥融合 + 双线架构 → A/C 融合策略 |
| 13-通用风控 | [docs/TECHNICAL_DESIGN.md](../../13-通用风控模块/docs/TECHNICAL_DESIGN.md) | ✅ 齐全 | 三层风控 + L1评估 + ML → T_domain 系统支撑横切 |
| 14-V15马丁 | [docs/TECHNICAL_DESIGN.md](../../14-V15经典马丁策略/docs/TECHNICAL_DESIGN.md) **v5.1** | ✅ 齐全 | 马丁格尔 + Kelly + 仓位管理 → C_domain 经典策略 |
| 16-调控系统 | [docs/TECHNICAL_DESIGN.md](../../16-调控系统/docs/TECHNICAL_DESIGN.md) **v2.0** | ✅ 齐全 | 宏观离场 + SKILL引擎 + 进化闭环 → A8/A9 知行/离场 |
| 17-V4波浪 | [docs/TECHNICAL_DESIGN.md](../../17-v4-wave-strategy/docs/TECHNICAL_DESIGN.md) **v1.0** | ✅ 齐全 | V4减半+艾略特波浪互斥融合 → A/C_domain（依赖12号物理引擎） |

> **完整 7 子系统 × 5 文档版本对照矩阵**见 SSoT §4.2.1 表。文档债（DD-xxx）登记于 [DOC_DEBT_INDEX.md](../3-文档治理/DOC_DEBT_INDEX.md)。当前 7/7 子系统 5 文档齐全。

### 2.3 专题架构文档

| 专题 | 文档 | 对应 SSoT 章节 |
|------|------|---------------|
| SKILL 索引 | [1-ARCHITECTURE/工作索引/SKILL_INDEX.md](../../1-ARCHITECTURE/工作索引/SKILL_INDEX.md)（规划中） | §3.4 模块元数据 + §5.2 A0-A9节点 |
| 工具映射 | [1-ARCHITECTURE/工作索引/TOOL_MAPPING.md](../../1-ARCHITECTURE/工作索引/TOOL_MAPPING.md)（规划中） | §8.5 适配器路由 |
| 部门矩阵 | [1-ARCHITECTURE/工作索引/DEPARTMENT_MATRIX.md](../../1-ARCHITECTURE/工作索引/DEPARTMENT_MATRIX.md) | §7.1 六部门模型 |
| 前端架构 | [1-ARCHITECTURE/前端设计/FRONTEND_ARCHITECTURE.md](../../1-ARCHITECTURE/前端设计/FRONTEND_ARCHITECTURE.md) | §8.3 前后端分工 |
| 产物中台 | [1-ARCHITECTURE/中台设计/PRODUCT_HUB.md](../../1-ARCHITECTURE/中台设计/PRODUCT_HUB.md) | §9.5 持久化映射 |
| 网关设计 | [1-ARCHITECTURE/中台设计/GATEWAY_HUB.md](../../1-ARCHITECTURE/中台设计/GATEWAY_HUB.md)（规划中） | §9.3 部署拓扑 + Phase 3 |
| 记忆系统架构专题 | [4-MEMORY/0-元记忆/](../../4-MEMORY/0-元记忆/) | §6 认知系统 + §10.2 记忆硬约束 |

---

## 3. 已知架构文档债务（对应 SSoT §11 技术债全景）

| 债务项 | 说明 | 关联 ID | SSoT 定位 |
|--------|------|---------|----------|
| 1-ARCHITECTURE/README 过时 | 仍描述旧"六大核心系统"，与 10-16 号子系统不匹配 | DD-002 | 批次7：文档债 |
| WORKBUDDY_OS_MODULAR 定位重叠 | 与 v3.0 重叠度 60%+，TS视角早期设计 | DD-003 | 批次7：v3.0 FINAL 后归档到 `archive/` |
| 16-调控系统 TECHNICAL_DESIGN 范围错位 | v1.0 仅覆盖离场评估子模块，缺失 SKILL 引擎 + 进化闭环 | D050 (P2) | 批次5：架构规范 |
| 认知系统无独立 TECHNICAL_DESIGN | daemon/git hook/session/mcp server 四组件缺少子系统级文档 | DD-018 (P1) | 批次3：架构统一 |
| 记忆系统接口契约文档缺口 | 7+2 接口 + 质量分级 S/A/B/C/D 缺少跨应用统一 SPEC | DD-017 (P1) | 批次3：架构统一 |

> **完整技术债清单**见根目录 [DEBT_INDEX.md](../../DEBT_INDEX.md) v2.4（103 项 × 8 分类 × 4 优先级），批次规划见 SSoT §11.5。

---

## 4. 架构演进路线（对应 SSoT §12.5）

| 阶段 | 状态 | 重点 | 对应 SSoT |
|------|------|------|----------|
| Phase 0 概念验证 | ✅ 完成 | 单策略原型 + S1-S5 思维链 + TS 版 Evolution 实验 | §12.5 |
| Phase 1 工程化基础 | ✅ 完成 | 从单策略 → 六大子系统目录化；OS v1.1；核心交易链路跑通 | §12.5 |
| Phase 1+ S1 文档统一 | ✅ 完成 | 6子系统文档全A级；0号系统建立；认知系统 daemon 上线 | §12.5 |
| **Phase 2 当前：架构统一 + 资金安全** | **⏳ 进行中** | **① v3.0 架构文档评审与定稿 ② 批次1-3技术债修复（P0资金→安全→架构）③ 认知系统与记忆系统硬约束对齐** | §11.5 批次1-3 |
| Phase 3 能力完整 | 🔴 待启动 | ML训练流水线；多账户风控；前端 Dashboard；16-GATEWAY 网关 | §12.5 Phase 3 |
| Phase 4 产品化 | 🔴 更远期 | 市场化中台落地；六部门治理代码化；Studio 私有化部署 | §12.5 Phase 4 |

---

**文档版本**: v2.1（新增 11-易经推理系统七层交易决策栈总览 + 子系统 TECHNICAL_DESIGN 版本对齐 v4.5）
**最后更新**: 2026-08-24
**下一步**: 等待 SSoT v3.0 草稿 review 确认后，同步更新 SYSTEM_MAP / TOPIC_MAP / DOC_DEBT_INDEX 关联项
