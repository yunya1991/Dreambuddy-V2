# 阶段 4 云端评审报告（D1-D8）

- 评审日期：2026-10-30 22:42
- 评审对象：云端 43.160.201.117（Ubuntu 24.04.5，4C16G/180G）
- 基线 commit：f1daae77（HEAD == origin/main）
- 评审方式：只读评审（八维全查）
- 前置条件确认：P0 全量收口（C1/C2/C3/C7 完成）、评审必办项 M1/M2/M3 闭环

## 总体结论

**通过（有 1 项高优先级安全待办）**：八维中 D1/D2/D4/D5/D8 通过；D3/D6 有低风险关注点；**D7 发现 1 项高优先级问题**（dreamos/.env 含交易私钥被 git 跟踪，详见 D7）。

## 分维度结论

### D1 代码一致性 — 通过
- HEAD == origin/main == f1daae77
- 无未提交改动（仅 439 个 replay_pool 运行数据文件，属已知运行态产物，SPEC 明确『结论只以 commit 为准』）

### D2 运行健康 — 通过
- failed units：0
- 关键服务：8 个中 7 个 active；dreamos-scheduler inactive 为**预期停用**（disabled，10-29 23:00 主动停止，与 dreamos-evaluator-daily-restart 触发时间吻合）
- 端口监听：19

### D3 日志质量 — 通过（2 个低风险关注点）
- 关键服务日志活跃度：7/7 正常（0h 前更新为主）
- hermes-gateway journal 最后记录 Oct 17：为 Feishu 消息网关，active 13 天，无消息时无输出，**静默属正常**
- datacenter-scheduler 近 1000 行 err=246：实为 WARNING 级 adaptive parse 回退（有 static fallback），非致命
- timer 停摆检测（M3 已部署）：dreambuddy/dal 相关 timer 全部 OK

### D4 数据链路 — 通过
- 18→19 回填：最近 21:15:03 执行成功（『18→19 回填完成，19-DAL mm_metrics 已可用』）
- 15:15 有一次 PG 口令缺失瞬时错误（fe_sendauth），已恢复

### D5 模型质量 — 通过（空注册表）
- ml/models/registry.json 为初始空注册表（schema 1.0，无已注册模型）
- 符合预期：待模型训练流程（walk_forward 评估）产出后登记

### D6 风控行为 — 通过（1 个低风险关注点）
- 实盘交易动作：22:32 有取消旧 algo 操作，交易链路活跃
- trailing-stop-runner：总持仓 0，无止损触发（历史触发累计 0）
- **关注点**：yijing-polling-trader 22:32 DEBUG 级错误 `OKXSimulatedClient.cancel_algo_orders() got an unexpected keyword argument`（参数不匹配，建议排查 EvolutionExitEngine 调用签名）

### D7 安全面 — **发现 1 项高优先级问题**
- ufw active，对外仅 22/80/443 ✅
- /etc/dreambuddy-pg.env 600 root:root ✅
- authorized_keys 仅 1 条 ✅
- **🔴 高优先级：`1-ARCHITECTURE/dreamos/.env`（600 luke:luke）被 git 跟踪入库**，包含：
  - AGENT_DREAM_OS_HYPERLIQUID_SIGNER_PRIVATE_KEY（**交易私钥**）
  - DEEPSEEK_API_KEY / QWEN_API_KEY
  - 私钥已固化在 git 历史，泄露面与 M1 同性质
  - **建议处置**（按 M1 模式）：1）git rm --cached 移出跟踪 + .gitignore；2）轮换 HYPERLIQUID signer 私钥与 API 密钥；3）评估 git 历史清理需求

### D8 成本/资源 — 通过
- CPU：load 0.95/1.87/1.78（4C 下正常）
- 内存：4.6Gi/15Gi used，10Gi available ✅
- 磁盘：34G/178G used（21%）✅

## 问题清单

| 级别 | 维度 | 问题 | 处置 |
|---|---|---|---|
| 🔴 高 | D7 | dreamos/.env 含交易私钥被 git 跟踪 | 移出跟踪 + 密钥轮换 + 历史清理评估 |
| 🟡 中 | D6 | cancel_algo_orders 参数不匹配（DEBUG 级） | 排查 EvolutionExitEngine 调用签名 |
| 🟢 低 | D3 | datacenter-scheduler adaptive parse 回退高频 | 已有 static fallback，观察即可 |
| 🟢 低 | D2 | dreamos-scheduler 停用 | 预期行为（disabled），确认即可 |

## 结论

八维评审完成，除 D7 高优先级安全待办外全部通过。建议按问题清单优先级处置 D7（密钥轮换），随后阶段 4 评审可宣告闭环，进入 P1（C4a PG adapter）。
