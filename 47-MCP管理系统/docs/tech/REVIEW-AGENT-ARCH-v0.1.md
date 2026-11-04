# REVIEW-AGENT-ARCH — Agent 训练与通信架构深度评审报告

> **版本**: v0.1 ｜ **更新日期**: 2026-11-03 ｜ **状态**: 已完成本地复核：P1/P3/P4/P5/P6 成立并修订；P2 复核不成立；P7 确认非缺陷
> **评审对象**: SPEC-L0-DOMAIN-AGENTS-v0.2 / SPEC-L0-AGENT-TRAIN-BASE-v0.1 / SPEC-L0-AGENT-COMM-SHADOW-v0.1
> **评审方法**: 内部证据核验（代码落点 / 依赖签名 / 数据库实测 / 文档交叉比对）+ 外部检索（受限，见 §5）
> **上游**: TECH-L0-MCP-v0.1（M1-M4 已收尾验证）

---

## §1 总体结论

三份 SPEC 的**架构骨架合理**：壳/agent 分离、影子先行、零 GPU 算力选型、写门禁体系均有内部证据支撑且自洽。但存在 **3 处文档内部矛盾、1 处术语误用、多处经验值无校准方案**，建议在启动 TB1 开发前完成修订。

## §2 合理项（有证据支撑，建议保留）

| # | 结论 | 证据 |
|---|---|---|
| R1 | **壳/agent 分离 + 壳零感知（H1）**：envelope.data 作为契约边界，agent 迭代不影响壳层 | M1-M4 收尾验证：6 壳 24 工具信封校验 6/6，业务体透传零删零改已实证 |
| R2 | **TB1→TB5 依赖链**：统计检测（PSI）→ 贝叶斯更新（Beta）→ 奖励（AlphaPareto）→ 决策（Thompson）→ 进化（GRPO loop），由简到繁渐进合理 | TRAIN-BASE §6.1 依赖链与 TDD 验收一一对应 |
| R3 | **零 GPU 算力选型自洽**：全部为贝叶斯 + 统计检验 + 策略格式调优，4C16G 可承载 | TB1 1ms / TB2 1μs / TB3-TB4 10μs / TB5 50ms，预算实测口径合理 |
| R4 | **影子验证先行（S1-S3 + V-S1~V-S6）**：旁路观察器不触发 agent，升级判据双硬门（V-S5 零副作用 + V-S6 切流完成） | REA 壳影子双跑已实证该模式可行（SHA-256 指纹一致） |
| R5 | **写门禁体系**：Mandate + PrincipalGate（D1）+ principal 角色白名单，激活模式绕过 Mandate 风险已有对策（meta 带 principal 声明） | port 层装饰器方案与既有 C10 直连门禁风格一致 |
| R6 | **FAIL-OPEN 分型**：增强型可降级（degraded=true）、主功能禁止 FAIL-OPEN，边界清晰 | 与壳层 FAIL-OPEN 旁路设计同构 |
| R7 | **不劣化保证**：TB5 argmax + 当前策略保底 + 异常回退，符合单人维护零回归约束 | TRAIN-BASE §5.3 evolve_step 逻辑完整 |
| R8 | **kill_switch 告警型语义澄清（C2）**：只产告警不执行实盘动作，由上层 orchestrator 消费 | 与实盘链路永不暴露 MCP 的红线一致 |

## §3 不合理 / 存疑项（建议修订）

| # | 严重度 | 问题 | 证据 | 建议 |
|---|---|---|---|---|
| P1 | **高** | **奖励维度两文档不一致**：DOMAIN-AGENTS v0.2 §4 定义 AlphaPareto **四维**奖励（P_verify_success / P_recall_hit / psi_stability / citation_diversity）；TRAIN-BASE v0.1 §5 定义**六维**（新增 process_reward / transition_smoothness），且六维只配了 4 个权重 (0.3, 0.25, 0.25, 0.2) | 两份 SPEC 交叉比对 | 统一为一套维度定义（建议以 TRAIN-BASE 六维为准），补齐 6 个权重，DOMAIN-AGENTS 改为引用不重复定义 |
| P2 | **高** | **45 PG 表数再次过时**：SPEC v0.3 勘误为『八表』，实测 `001_init.sql` 有 **9 个 CREATE TABLE** | grep -c 'CREATE TABLE' = 9 | 修正 SPEC §3.2 与相关引用为九表 |
| P3 | **中** | **TB5 术语误用**：GRPO（Group Relative Policy Optimization）在业界指需要梯度更新的策略优化方法；TB5 实际是『冻结权重 + 候选配置 argmax 选择』，无任何梯度/策略网络更新 | TRAIN-BASE §5.3 代码骨架（evaluate_config + argmax） | 重命名为 PolicySelectLoop / ConfigEvolution，或在 SPEC 头部明确声明『本 GRPO 为借喻用法，无梯度更新』，避免后续读者误解 |
| P4 | **中** | **外部论文依据无法验证**：引用 10 篇论文（Alpha-R1 / EvolveR / AlphaPareto / ADTS / SR 11-7 等），当前环境外部学术源（arXiv / Semantic Scholar / 搜索引擎）均不可达，无法确认论文存在性与结论引用是否准确 | 外部检索全部受限 | 在 SPEC 参考文献区标注『待验证』状态；启动 TB 开发前由用户在本地网络环境补验一轮 |
| P5 | **中** | **经验值无校准方案**：V 函数权重（0.1 × cross_domain_refs、λ=0.1）、AlphaPareto 权重、H5 贝叶斯 VaR 阈值（<0.3 拦截 / <0.5 降建议）、PSI 三档阈值，均为初版拍定值，无数据驱动校准路径 | 各 SPEC 原文 | 补充『影子期校准』章节：Phase 1 影子观察数据用于回测校准权重，校准结果落 registry/ 下的校准报告 |
| P6 | **低** | **TB1-TB5 代码落点未创建**：drift_detector / training_reward / regime_gate / grpo_evolution 均不存在 | ls 实测仅有 cognitive_loop_entry / cognitive_interfaces | 符合『设计草案』状态，非缺陷；但 DOMAIN-AGENTS v0.2 中 drift_detector.py 表述为『新增』易误读为已存在，建议标注（计划新增） |
| P7 | **低** | **agent_mail 目录未创建**：mcp_shells/_shared/ 下仅有 envelope_wrap.py | ls 实测 | 符合『bcrm2 切流后启动』前置依赖，非缺陷，无需修订 |

### 3.1 本地复核结论（2026-11-03，仓内实测 + 联网检索）

| # | 复核结论 | 复核证据 | 处置 |
|---|---|---|---|
| P1 | ✅ **成立**（比原描述更严重） | `compute_reward` 仅返回 4 个字段，而 `RewardComponents` 要求 6 个 → 实际会 TypeError；`pareto_score` 权重也只有 4 个 | TRAIN-BASE §3 升为六维 + 6 权重（和=1.0）+ RED 6 权重完整性用例；DOMAIN-AGENTS §4.1 改为引用 |
| P2 | ❌ **不成立** | `001_init.sql` 实际 `CREATE TABLE` 语句为 **8** 条；grep 计数的第 9 处是第 7 行注释里的示例文本 | 文档无需修改（"八表"正确），本报告 §4 移除该项 |
| P3 | ✅ **成立** | §5.3 `evolve_step` 为 `evaluate_config` + argmax，无梯度/策略网络 | TRAIN-BASE §5 标题改 PolicySelectLoop + 术语声明；`GRPOEvolutionLoop` 类名保留兼容 |
| P4 | ✅ **成立**（已完成外部验证） | 本地联网复核：Alpha-R1 = arXiv **2512.23515**、EvolveR = arXiv **2510.16079**、AlphaPareto = arXiv **2609.34188**；SR 11-7 为美联储监管指引（非论文）；ADTS 未检索到对应论文 | 三份 SPEC 引用编号已更正；ADTS 标注"待验证" |
| P5 | ✅ **成立** | 六维权重 / PSI 三档 / VaR 0.3·0.5 / V 函数 λ=0.1 均无校准出处 | 新增 TRAIN-BASE §6.5 影子期校准协议（离线校准 + 人工评审 + 改常量，禁止运行期自调，保持 H8） |
| P6 | ✅ **成立（表述风险）** | `4-MEMORY/9-工具与接口/` 实测无 drift_detector / training_reward / regime_gate / grpo_evolution | DOMAIN-AGENTS §6 加"计划新增"声明 |
| P7 | ✅ **确认非缺陷** | `mcp_shells/_shared/` 仅 envelope_wrap.py，符合 bcrm2 切流后启动的前置依赖 | 无需修订 |

## §4 修订建议清单（按优先级）

1. ~~**P2 表数修正**~~ → **复核不成立**（001_init.sql 实测 8 条 CREATE TABLE，第 9 处为注释），无需修订
2. **P1 奖励维度统一**（已修订）：TRAIN-BASE 六维 + 6 权重；DOMAIN-AGENTS 改引用
3. **P3 TB5 重命名/声明**（已修订）：PolicySelectLoop + 借喻声明
4. **P5 校准方案补充**（已修订）：TRAIN-BASE §6.5 影子期校准协议
5. **P4 论文标注待验证**（已修订）：Alpha-R1/EvolveR/AlphaPareto 编号已更正，ADTS 标注待验证
6. **P6 代码落点标注**（已修订）：DOMAIN-AGENTS §6 加"计划新增"声明

## §5 外部调研受限说明

本轮评审尝试通过 arXiv（API + 主站）、Semantic Scholar、DuckDuckGo、Bing 检索外部论文与业界实践，均因 robots.txt 禁止抓取、地域限制或限流不可达。**评审当时的论文依据（P4）未能完成外部验证**；2026-11-03 已在本地联网补验完成（结论见 §3.1-P4），评审结论主体基于内部证据交叉比对。

## §6 与演进路线的衔接

- 本评审不改变既有推进顺序：TB1-TB5（可立即启动）→ bcrm2 切流 → AgentMail 影子 → 域内 agent Phase A-E
- P1/P3 修订已完成（P2 复核不成立），TRAIN-BASE 已具备开工条件（TB1 PSI 无阻塞项）；P5 校准协议随 Phase 1 影子期执行
