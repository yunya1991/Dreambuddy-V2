# 验收报告 — 52-LobeHub 协议集成（本轮功能 + 架构协同性）

## 基本信息

- 验收对象：蒸馏桥去重、T1 跨侧判定、supervisor 调度、ADR-001 实盘出关、五文档标准
- 验收时间：2026-11-11
- 验收人：AI（用户要求：功能验收 + 与原架构协同性核查）
- 关联 commit：`a68814f0a3`、`6dfa700c59`、`a78f240c12`（基线 `99b0fb5e01`）
- 验收包：`acceptance_bundles/20261111_52_lobehub_round1/`

## 五维证据矩阵

| 维度 | 状态 | 证据 | 备注 |
|---|---|---|---|
| 症状复测（功能运行） | ✅ | `repro_after.log`：shadow 实跑 T1 `gap=0.182 basis=cross_side fired=false`；桥 `written=1/skipped=2`，游标回退重跑 `written=0/skipped=3` | 均为本次会话现场执行 |
| 日志证据（SPEC→代码→运行→日志） | ✅ | 真实 trace `bs-1794397691456-661708`、ledger 1 行、`trace.live.allowed=true`、`execution.ok=true`、桥 stderr `跳过不合规条目 line=3` | 功能验收追溯 SPEC §Phase 3/5 与 ADR-001 |
| 回归测试 | ✅ | `test.log`：orchestrator **84**、bridge **20**、debate 壳 **22**，三套 exit=0 | `pytest_exit=0` / `debate_exit=0` |
| 影响面 | ✅ | `fix.diff`：仅 `52-lobehub协议集成/` + `0-系统文档管理/INDEX.md`，24 文件 / +3028 −436 | 未触碰交易、数据、DSH、L0 源码 |
| 边界验证 | ✅ | 5 场景：策略关闭 exit2、角色不符 exit2、预算耗尽 exit2、放行执行 exit0、非法 outbox type 拒写 | 另含 45 缺产物 → `INCONCLUSIVE` 不编造 |

## 架构协同性核查（新功能 vs 原架构）

| 维度 | 原架构 | 52 本轮新增 | 结论 | 证据 |
|---|---|---|---|---|
| 唯一前端 | 3.1-FRONTEND | 新增 `/api/agent/{chat,plan,brainstorm}`，无第二 UI | 一致 | `3.1-FRONTEND/src/app/agent/` 仅 `.DS_Store` |
| 规划入口 | DreamOS 单链 intent | 双链 A(3.1)/B(DreamOS)，确定性评分 | 补充，不替换 | 真实 trace 两侧卡 + `side_a/side_b` |
| 裁决权 | 45 评测器 | 只消费 45 verdict，结构分兜底 | 一致，未越权 | `evaluators=7`、`INCONCLUSIVE/missing_artifacts` |
| 执行权 | DreamOS 链路 | live 仅执行 dispatch 胜方，前置三道门 | 一致，未绕过 | case1-4 门禁与 `execution.ok` |
| 交易铁律④ | trade-exec 永禁 | G3/G4 + 路由 `trade_deny` 双重拦截 | 更严格 | `G3:trade_exec_forbidden`、`G4` BLOCK |
| 能力事实源 | 47 registry | 只读加载 `mcp_capabilities.yaml`，注释「绝不写回」 | 一致 | 54 工具 / 8 域，无写回代码 |
| 认知写入 | C1-C4 权威库、本地只读 | 桥唯一出口，`MODE=ssh` + `WRITE_ENABLED` + `principal=orchestrator`，`ALLOWED_TOOLS={record,verify}` | 一致 | 52 内无 sqlite/psycopg/sqlalchemy 直连 |
| 核心模块依赖 | 分层调用 | 52 不 import `dreambuddy/dreamos/dsh` 内部模块，仅访问 HTTP/stdio | 一致 | Grep 仅命中 `dreamos.*` 证据字符串 |
| 调度 | 18 采集调度器 | 52 `supervisor.py` 独立任务（22:30），与 18 无任务重叠 | 并存，无冲突 | 18 目录无 52 引用；守护已运行 44 分钟 |
| 文档体系 | 0-INDEX / 2-KNOWLEDGE | 52 五文档 + INDEX 登记 + doc_coverage 5/5 | 一致 | lint 0 违规、10 链接 0 断链 |
| 三端协作 | 44 拓扑与角色 | 52 Phase 2 云端未开工，44 未登记 | **缺口（非冲突）** | `grep 44-... 52` 为空 |

### 与原架构的对比评估（定性）

1. **职责边界更清晰而非重复建设**：52 不复制 DreamOS 的执行、DSH 的编排、L0 的能力，只补「候选方案生成 + 确定性裁决前置」这一层；评测权与执行权仍归原架构。
2. **治理强度高于原架构**：原架构仅约束交易工具不可用；52 额外引入 G1-G4、多样性 fail-closed、live 三道门 + 周预算，属于收紧而非放松。
3. **认知链路唯一化**：原架构多入口可写认知；52 明确「桥是唯一出口」，且强制 ssh 权威库，避免本地只读镜像被直写。
4. **观测面新增但未侵入**：`trace.jsonl` / `outbox.jsonl` 为文件级旁路，不参与交易热路径，也不替代 DSH 事件总线。
5. **主要风险是「规则误伤」而非「越权」**：G4 子串匹配会把包含「实盘/live」的**风险描述**判为实盘交易，降低 dispatch 率（见红旗 R1）。

## 红旗清单

| # | 级别 | 红旗 | 证据 | 处置建议 |
|---|---|---|---|---|
| R1 | P1（需评审） | G4 关键词匹配不识别否定语境：`no_live_trading`、`回测样本期与实盘波动率分布可能不一致` 均被 BLOCK | `repro_after.log` F1（T2 blocked_max=0.918）、case4 首轮被拦 | 建议改为「结构字段判定 + 否定词豁免」，或把自然语言风险移出 G4、交由 45/裁决器处理；需 SPEC 评审后实施 |
| R2 | P3（观测） | `--force` 时 summary 出现 `route=workers` 与 `mode=debate` 并存 | case4 输出 | 明确 mode 语义或在 force 下同步 route |
| R3 | P3（观测） | trace `executed=null`，summary `executed=true` | case4 trace vs summary | trace 回填 `executed` 布尔，便于审计 |
| R4 | P2（架构登记） | 44 三端协作未登记 52 拓扑；Phase 2 云端未开工 | grep 44 无 52 | 随 Phase 2 一并登记 |
| R5 | P2（已知限制） | 守护进程不跨重启（macOS TCC） | 文档 §5 / pinned 局限 | 重启后 `nohup` 重拉，或换有 launchd 权限环境 |

## 验收结论

- 五维证据：**全部通过**（无 FAIL，无缺维）。
- 架构协同：**无硬冲突**；10 项边界一致/更严格，1 项缺口（44 未登记，已知）。
- 需评审项：**R1（G4 否定语境误伤）** 建议下一轮修正；R2/R3 为观测一致性的小修。
- 结论：**验收通过（附 1 个 P1 待评审项 + 4 个非阻塞项）**。

## 签字

AI 验收：2026-11-11
用户确认：待确认
