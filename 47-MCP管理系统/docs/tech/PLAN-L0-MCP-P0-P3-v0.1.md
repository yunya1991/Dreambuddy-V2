# PLAN-L0-MCP-P0-P3 — L0 MCP 封装实施计划

> **版本**: v0.2 ｜ **日期**: 2026-11-02 ｜ **状态**: 待用户确认后开工
> **范围**: 本计划仅覆盖 **47-MCP管理系统** 侧实施；46-DSH架构 侧（事件网关/Router/Ticket 翻译器等）见 [DESIGN-DSH-ARCH-UPGRADE v0.2](../../46-DSH架构/docs/tech/DESIGN-DSH-ARCH-UPGRADE-v0.1.md) §五 演进路径
> **依据**: [SPEC-L0-MCP-PACKAGING v0.3](./SPEC-L0-MCP-PACKAGING-v0.3.md)（决议落定：B1-B6/G1-G3/D1-D6）+ [ALIGNMENT-46-47-v1.0](./ALIGNMENT-46-47-v1.0.md) §六 合并开工顺序
> **对齐**: [SPEC-L0-three-layer-architecture v0.5](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/44-三端协作架构系统/docs/tech/SPEC-L0-three-layer-architecture.md) C 系列进度（§一）
> **约束**: 单人维护、FAIL-OPEN、云端 4C16G、零回归（C 系列既有阻断 job 全绿为每里程碑前置）、实盘写路径不触碰
> **v0.2 修订**: 任务①合并原任务②——mcp_capabilities.yaml 为 B4 唯一载体，包含完整的**角色→能力标签→工具**三层映射；删除多余的 l0_capability_set.v1.yaml（与 ALIGNMENT B4 "单一载体" 冲突）

---

## 一、L0 改造线（C 系列）进度对齐基线

| 系列 | 状态 | 与本计划关系 |
|---|---|---|
| G0-8 幂等字段 / C6 能力声明 / C8 事件互通 / C9 任务注册表+job_runs / C10 直连门禁 / C11 检索触发 / C12 健康聚合 / C13 OS 旁路 | ✅ 已落地（本地+云端） | **地基**：`dreambuddy_l0/ports` 六 port、job_runs、capabilities.yaml、unified_search、health 聚合均已具备 |
| C5 直连收编（九批） | ✅ 收编收官（11 系统业务代码直连清零） | 同向：C5 收内部到 port，本计划把 port 壳化对外 |
| bcrm2 实盘切流（`BCRM_*_STORE_PORT=1`） | ⏸ 挂起，等用户给重启窗口 | 本计划全程不触碰实盘写路径；M2 数据壳上线建议与切流**不同日**（便于归因） |
| P3 长期项：Memory port bulk-read、非调度来源事件表 | 📋 未排期 | bulk-read 并入 M4⑪ |

## 二、冲突点清单与对策（K1-K5）

| # | 冲突点 | 对策 |
|---|---|---|
| K1 | `cognitive_mcp_server.py` 三线交汇：C7 unified_search 注册 + C12 health 挂接（16 条契约）+ 本计划 M1② 包信封/拆 scope | **一次 PR 改完**，C7/C12 契约测试同 PR 同步更新；信封映射只包外层，工具语义零变化 |
| K2 | bcrm2 切流窗口未定 | 数据壳只读先行，写面 Ban 类默认禁；19-DAL 周边改动避开实盘重启窗口 |
| K3 | Memory bulk-read 是 34 collector / skill_candidate_miner 收编前置（C5 第九批定性"有意解耦"） | 并入 M4⑪ 统一排期 |
| K4 | 45 评测壳连 PG | 走既定 `EVAL_PG_DSN`/env 通道（2026-11-02 密码漂移已修复），禁新建凭据 |
| K5 | registry CI 校验（新建）vs `validate_capabilities`（C6 既有） | 双校验器并存进 CI；职责切分按 B4：registry=壳/工具面，capabilities=能力提供面，只引用不合并 |

## 三、里程碑（M1-M4）

### M1【P0 基座】— 无外部依赖，可立即开工

| # | 任务 | 产出 | 验收 |
|---|---|---|---|
| ① | `47-MCP管理系统/registry/mcp_capabilities.yaml` v1（**B4 唯一载体**） | 注册表含三层：**角色→能力标签**（46 定，B4）+ **能力标签→工具集**（47 定）+ 存量三面登记（认知壳 6 工具 / 39 语义壳 4 工具 / REA client）+ schema 校验器 + CI 阻断 | V1：schema 校验 + 漂移拦截测试；46 grep 无第二份能力集定义 |
| ② | 信封映射层 + 认知壳 tools 拆 scope（K1 一次 PR） | `cognitive_mcp_server` 返回包统一信封（ok/data/source/timestamp/degraded/meta/version/trace_id/idempotency_key/error_code）；tools 按域拆 scope 声明 | V2/V3 + C7/C12 契约同步更新全绿 |
| ③ | 基线测量 | in-process 直调 vs stdio 壳各 100 次 P50/P95 → `registry/latency_baseline.md`（先基线后生效，§3.8） | V4 基线报告落档 |

**出口判据**：V1-V4 + C 系列既有阻断 job（l0-contracts）全绿

### M2【P1 数据+评测壳】— 依赖 M1 + B3

| # | 任务 | 产出 | 验收 |
|---|---|---|---|
| ④ | B3 前置：19-DAL 连接上限治理方案 | DAL 连接上限/方言能力集声明（SPEC-L0 §3.1 两层模型落地） | DAL 声明文档 + 壳不感知数值（云端 C2） |
| ⑤ | 数据壳（18/19/20/21 → Collector+Store 读面先行） | `mcp_shells/l0_data/`，fetch(scope) 映射 facade 注册表 | V5 + 只读契约测试；写面 Ban 默认禁 |
| ⑥ | 评测壳（45 gateway/runner 薄包，K4） | `mcp_shells/l0_eval/`，复用 45 既有库，不替代 :8790 HTTP 服务 | V5 + 评测契约测试 |

**出口判据**：V5 + 数据/评测壳契约测试全绿；与 bcrm2 切流不同日

### M3【P2 REA+认知双模】— 依赖 M1

| # | 任务 | 产出 | 验收 |
|---|---|---|---|
| ⑦ | REA 壳（包 `dsh_nodes.py`，REA 域 JSONL 状态持久化先行——同行评审 DA1） | `mcp_shells/l0_rea/` | V6；无持久层不得暴露异步工具 |
| ⑧ | 认知壳双模（D5：ssh 云端默认 + 本地只读降级，本地禁写） | `mcp.json` profile + 壳内只读拦截 | V6 + 本地模式写工具拒绝测试 |
| ⑨ | REA shadow 双跑一窗口 | `REA_MCP_SHADOW=1`，逐字节比对 | shadow 报告 |

**出口判据**：V6 + shadow 报告无差异

### M4【P3 收口】— 依赖 M2/M3

| # | 任务 | 产出 | 验收 |
|---|---|---|---|
| ⑩ | 库管壳只读（38） | `mcp_shells/l0_store_admin/` 只读工具面 | V7 |
| ⑪ | Memory port bulk-read（export/list）评估落地 → 联动 34 collector / skill_candidate_miner 收编（K3） | port 契约扩展 + 消费方迁移 | bulk-read 契约测试；两消费方白名单条目移除 |

**出口判据**：V1-V7 全量 + 端口清单较 D7 基线零新增（stdio 壳验收隐含项）

## 四、调度与风险

- **资源**：单人维护；M1 全本地/云端开发机作业，无需实盘窗口
- **风险登记**（承接 SPEC R1-R8 新增）：
  - **R9（新）三线交汇文件回归**（K1）→ 对策：一次 PR + 契约同步，C 系列阻断 job 兜底
  - R1 工具面膨胀 → 聚合 2-3 server（G2）；R2 写污染 → Ban+Mandate（§3.3）
- **FAIL-OPEN**：每里程碑出口判据不满足即停，不带病推进
- **回滚**：每里程碑独立 PR，开关默认关，回滚=revert + 关开关

## 五、开工入口

M1①：`47-MCP管理系统/registry/mcp_capabilities.yaml` v1（schema 复用 C6 capabilities.yaml 字段 + SPEC §3.7 扩展字段：server/transport/scope/tools/annotations/写治理类别）
