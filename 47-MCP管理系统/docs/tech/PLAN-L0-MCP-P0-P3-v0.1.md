# PLAN-L0-MCP-P0-P3 — L0 MCP 封装实施计划

> **版本**: v0.3 ｜ **日期**: 2026-11-03 ｜ **状态**: 🟡 主体落地（M1-M4 全部七壳已建成 + TRAIN-BASE 48/48 全绿；REA shadow 双跑 + bcrm2 切流 + bulk-read 三项待窗口）
> **范围**: 本计划仅覆盖 **47-MCP管理系统** 侧实施；46-DSH架构 侧（事件网关/Router/Ticket 翻译器等）见 [DESIGN-DSH-ARCH-UPGRADE v0.2](../../../46-DSH架构/docs/tech/DESIGN-DSH-ARCH-UPGRADE-v0.2.md) §五 演进路径
> **依据**: [SPEC-L0-MCP-PACKAGING v0.3](./SPEC-L0-MCP-PACKAGING-v0.3.md)（决议落定：B1-B6/G1-G3/D1-D6）+ [ALIGNMENT-46-47-v1.0](./ALIGNMENT-46-47-v1.0.md) §六 合并开工顺序
> **对齐**: [SPEC-L0-three-layer-architecture v0.5](../../../44-三端协作架构系统/docs/tech/SPEC-L0-three-layer-architecture.md) C 系列进度（§一）+ [SPEC-L0-DOMAIN-AGENTS v0.2](./SPEC-L0-DOMAIN-AGENTS-v0.2.md) Phase 0/Phase A
> **约束**: 单人维护、FAIL-OPEN、云端 4C16G、零回归（C 系列既有阻断 job 全绿为每里程碑前置）、实盘写路径不触碰
> **v0.2 修订**: 任务①合并原任务②——mcp_capabilities.yaml 为 B4 唯一载体，包含完整的**角色→能力标签→工具**三层映射；删除多余的 l0_capability_set.v1.yaml（与 ALIGNMENT B4 "单一载体" 冲突）
> **v0.3 修订**: M1-M4 里程碑任务状态全量刷新；registry 升级至 v0.2（7 壳 24 工具 7 port，本地/云端双校验 EXIT=0）；TRAIN-BASE Phase 0+A 48/48 测试落地；REA shadow / bulk-read / 写面开放三项待窗口；壳后新锚点①静态 domain_transmission + ②observe() 消费入口已落地（2026-11-03，19 测试），下一锚点=③ training_reward.py 聚合 + ④ 标注管线 MVP

---

## 一、L0 改造线（C 系列）进度对齐基线

| 系列 | 状态 | 与本计划关系 |
|---|---|---|
| G0-8 幂等字段 / C6 能力声明 / C8 事件互通 / C9 任务注册表+job_runs / C10 直连门禁 / C11 检索触发 / C12 健康聚合 / C13 OS 旁路 | ✅ 已落地（本地+云端） | **地基**：`dreambuddy_l0/ports` 六 port、job_runs、capabilities.yaml、unified_search、health 聚合均已具备 |
| C5 直连收编（九批） | ✅ 收编收官（11 系统业务代码直连清零） | 同向：C5 收内部到 port，本计划把 port 壳化对外 |
| **registry v0.2 壳+工具面** | ✅ 已落地（本地+云端双校验 EXIT=0，7 壳 24 工具 7 port） | **本计划主体**：`mcp_capabilities.yaml` 为 B4 SSoT；`validate_mcp_registry.py` 已挂入 CI |
| **M1-M4 七壳全量建成** | ✅ `mcp_shells/{l0_data,l0_eval,l0_rea,l0_store_admin}/server.py` + `cognitive_mcp_server` + `semantic-39`（39 现有 MCP 路径）+ REA client（deprecated） | **壳后分工**：壳只做协议转换+信封+Mandate 拦截；agent 在壳后自然生长（SPEC-L0-DOMAIN-AGENTS v0.2） |
| **TRAIN-BASE TB1-TB5 + Phase A** | ✅ 48/48 测试全绿，2026-11-02—11-03 落地 | **壳后第一波 agent 基座**：PSI drift（drift_detector.py）+ Beta verify + AlphaPareto 六维奖励 + Thompson Sampling regime gate + GRPO evolution + P4 回执消费 + recall sort_mode=train_base |
| bcrm2 实盘切流（`BCRM_*_STORE_PORT=1`） | ⏸ 挂起，等用户给重启窗口 | 本计划全程不触碰实盘写路径；M2 数据壳上线建议与切流**不同日**（便于归因） |
| P3 长期项：Memory port bulk-read、非调度来源事件表 | 📋 未排期 | bulk-read 并入 M4⑪；C5 第九批定性为"有意解耦"，补齐契约后再议收编 |

## 二、冲突点清单与对策（K1-K5）

| # | 冲突点 | 对策 |
|---|---|---|
| K1 | `cognitive_mcp_server.py` 三线交汇：C7 unified_search 注册 + C12 health 挂接（16 条契约）+ 本计划 M1② 包信封/拆 scope | **一次 PR 改完**，C7/C12 契约测试同 PR 同步更新；信封映射只包外层，工具语义零变化 |
| K2 | bcrm2 切流窗口未定 | 数据壳只读先行，写面 Ban 类默认禁；19-DAL 周边改动避开实盘重启窗口 |
| K3 | Memory bulk-read 是 34 collector / skill_candidate_miner 收编前置（C5 第九批定性"有意解耦"） | 并入 M4⑪ 统一排期 |
| K4 | 45 评测壳连 PG | 走既定 `EVAL_PG_DSN`/env 通道（2026-11-02 密码漂移已修复），禁新建凭据 |
| K5 | registry CI 校验（新建）vs `validate_capabilities`（C6 既有） | 双校验器并存进 CI；职责切分按 B4：registry=壳/工具面，capabilities=能力提供面，只引用不合并 |

## 三、里程碑（M1-M4）

### M1【P0 基座】— 无外部依赖，可立即开工 ✅ 已全部落地（2026-11-02 收口）

| # | 任务 | 产出 | 验收 |
|---|---|---|---|
| ① ✅ | `47-MCP管理系统/registry/mcp_capabilities.yaml` v1 → **v0.2**（**B4 唯一载体**） | 注册表含三层：**角色→能力标签**（46 定，B4）+ **能力标签→工具集**（47 定）+ 存量三面登记（认知壳 6 工具 / 39 语义壳 4 工具 / REA client 3）+ 新增 3 壳（data 4 / eval 2 / store-admin 2）+ schema 校验器 + CI 阻断 | V1→V0.2：本地/云端双校验 `validate_mcp_registry.py` EXIT=0；7 壳 24 工具 ≤ 40 上限 |
| ② ✅ | 信封映射层 + 认知壳 tools 拆 scope（K1 一次 PR） | `cognitive_mcp_server` 返回包统一信封（ok/data/source/timestamp/degraded/meta/version/trace_id/idempotency_key/error_code）；tools 按域拆 scope 声明 | V2/V3 + C7/C12 契约同步更新全绿；`mcp_shells/_shared/envelope_wrap.py` 已接入 5 壳 return 路径 |
| ③ ✅ | 基线测量 | in-process 直调 vs stdio 壳各 100 次 P50/P95 → `registry/latency_baseline.md`（先基线后生效，§3.8） | V4 基线报告落档；云端 P50 recall 18.4ms / record 53.6ms / verify 197.35ms |

**出口判据**：✅ V1-V4 + C 系列既有阻断 job（l0-contracts）全绿

### M2【P1 数据+评测壳】— 依赖 M1 + B3 ✅ 已全部落地（2026-11-02 收口，B3 已解）

| # | 任务 | 产出 | 验收 |
|---|---|---|---|
| ④ ✅ | B3 前置：19-DAL 连接上限治理方案 | DAL 连接上限/方言能力集声明（SPEC-L0 §3.1 两层模型落地） | DAL 声明文档 + 壳不感知数值（云端 C2） |
| ⑤ ✅ | 数据壳（18/19/20/21 → Collector+Store 读面先行） | `mcp_shells/l0_data/server.py`，4 工具（data_fetch / data_collect_once / data_store_read / data_store_write）+ test_l0_data_server.py；写面 `requires_mandate=true` 禁默认 | V5 + 只读契约测试全绿 |
| ⑥ ✅ | 评测壳（45 gateway/runner 薄包，K4） | `mcp_shells/l0_eval/server.py`，2 工具（eval_analyze / eval_report）+ test_l0_eval_server.py | V5 + 评测契约测试全绿 |

**出口判据**：✅ V5 + 数据/评测壳契约测试全绿；与 bcrm2 切流不同日（壳已就绪，但**未上线**——切流需用户窗口）

### M3【P2 REA+认知双模】— 依赖 M1 🟡 主体落地（⑦⑧ ✅；⑨ 待 bcrm2 窗口）

| # | 任务 | 产出 | 验收 |
|---|---|---|---|
| ⑦ ✅ | REA 壳（包 `dsh_nodes.py`，REA 域 JSONL 状态持久化先行——同行评审 DA1） | `mcp_shells/l0_rea/server.py`，6 工具（submit/poll × analyze/trace/compare 三段式异步）+ test_l0_rea_server.py；异步工具强制配 JSONL job store | V6；`REA_MCP_SHADOW=1` 开关预留 |
| ⑧ ✅ | 认知壳双模（D5：ssh 云端默认 + 本地只读降级，本地禁写） | registry `l0.cognition.mcp` 的 `transport: ssh-stdio`；本地 profile 切 stdio；壳内写工具 `requires_mandate=true` 拦截 | V6 + 本地模式写工具拒绝测试 |
| ⑨ 📋 | REA shadow 双跑一窗口 | `REA_MCP_SHADOW=1`，逐字节比对 | shadow 报告（**阻塞项 B4：需 bcrm2 不重启窗口，当前 shell 已就绪，窗口到即可跑**） |

**出口判据**：V6 + shadow 报告无差异（**部分已达**：V6 就绪，shadow 窗口待定）

### M4【P3 收口】— 依赖 M2/M3 🟡 主体落地（⑩ ✅；⑪ 待定）

| # | 任务 | 产出 | 验收 |
|---|---|---|---|
| ⑩ ✅ | 库管壳只读（38） | `mcp_shells/l0_store_admin/server.py`，2 工具（store_admin_status / store_admin_query）+ test_l0_store_admin_server.py | V7 |
| ⑪ 📋 | Memory port bulk-read（export/list）评估落地 → 联动 34 collector / skill_candidate_miner 收编（K3） | port 契约扩展 + 消费方迁移 | bulk-read 契约测试；两消费方白名单条目移除（**决策背景**：C5 第九批定性为"有意解耦"，补齐 bulk-read 契约后再议收编；当前 34 collector / skill_candidate_miner 直接连 cognitive_memory.db 是有意设计——零 IPC 开销、不依赖 MCP server 运行态） |

**出口判据**：✅ V1-V7 全量 + 端口清单较 D7 基线零新增（stdio 壳验收隐含项）；bulk-read 待决策

## 四、调度与风险

- **资源**：单人维护；M1 全本地/云端开发机作业，无需实盘窗口
- **风险登记**（承接 SPEC R1-R8 新增）：
  - **R9（新）三线交汇文件回归**（K1）→ 对策：一次 PR + 契约同步，C 系列阻断 job 兜底
  - R1 工具面膨胀 → 聚合 2-3 server（G2）；R2 写污染 → Ban+Mandate（§3.3）
- **FAIL-OPEN**：每里程碑出口判据不满足即停，不带病推进
- **回滚**：每里程碑独立 PR，开关默认关，回滚=revert + 关开关

## 五、壳后锚点（v0.3 方向变更）

**M1-M4 全部七壳已建成 → 壳层"协议门"搭建完毕，agent 可以在门后自然生长（SPEC-L0-DOMAIN-AGENTS v0.2）。**
以下为壳后零阻塞锚点，按优先级排序：

| 锚点 | 性质 | 产出 | 依赖 | 阻塞 |
|---|---|---|---|---|
| ① ✅ 静态 `domain_transmission.json` v0.0 | COMM-SHADOW Phase 0 + L1 Phase 0 基石 | `mcp_shells/_shared/assets/domain_transmission_static.json`：6 域 × 15 对传播矩阵（coupling/lags_min），`source=static` 明确标注，psi_corr/verify_corr 留待 Phase B | 无 | ✅ 2026-11-03 落地 |
| ② ✅ observe() 消费静态版本 | COMM-SHADOW P0 入口 | `mcp_shells/_shared/agent_mail_shadow.py`：`AgentMailShadow(l1_transmission_path=)` + `observe()` 追加 `l1_insights`（coupling_consistency / l1_regime_match / l1_state）；S1-S3 硬约束 + FAIL-OPEN + 19 测试 | ① | ✅ 2026-11-03 落地 |
| ③ `training_reward.py` 聚合 | 壳后 TRAIN-BASE 常量收敛 | V_ALPHA + 六维权重 + AlphaPareto 定义收敛到单一模块 | 无 | 无 |
| ④ 标注数据管线 MVP | TRAIN-BASE Phase A → L1 训练闭环 | `collect_domain_discovery_data.py` 20 行 + JSONL schema | TB1-TB5 已落地 ✅ | 无 |
| ⑤ BTCRegimeDetector + NeuralSDE dim64 regime 输入 | L1 Phase 0 静态架构 | regime 检测 k=3 + drift_net in_dim 18→21 真实接线 | ③ 静态 JSON | 无 |

**SPEC 原开工入口（已完成）**：`47-MCP管理系统/registry/mcp_capabilities.yaml` v1（schema 复用 C6 capabilities.yaml 字段 + SPEC §3.7 扩展字段：server/transport/scope/tools/annotations/写治理类别）
