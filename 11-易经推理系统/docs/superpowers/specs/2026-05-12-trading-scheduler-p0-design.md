# Trading Scheduler P0 Design (A0-A9 定时调度层落地)
 
文档版本: v0.1  
更新时间: 2026-05-12  
范围: dream-multiskill-v2 主干（GitHub Actions 定时调度层）
 
## 1. 背景
 
约束层文档 [trading-communication-protocol-v2.md](file:///Users/zhangjiangtao/WorkBuddy/_tmp_merge_dream_v2/constraints/workflows-spec/trading-communication-protocol-v2.md) 已定义 A0-A9 的三环架构与定时触发节奏，但主干尚缺“可直接运行的定时调度层”工作流，导致协议落地停留在示例与本地函数调用。
 
当前仓库已具备：
 
- A0-A9 阶段入口（`workflows/trading-decision/A*/entrypoint.py`）
- 协议与契约（`workflows/trading-decision/protocol/message.py`）
- 编排器（`workflows/trading-decision/orchestrator/*`）
- 传输适配器（`workflows/trading-decision/transports/adapters.py`）
- 系统级测试（`tests/test_trading_*`）
 
P0 的目标是把定时触发节奏落成 GitHub Actions `schedule`，并保证“触发能力”在同一个 workflow run 内即可完成（不依赖跨 workflow dispatch）。
 
## 2. 目标与非目标
 
### 2.1 目标（P0）
 
- 落地可直接运行的定时工作流：
  - A4 每 4h
  - A5 每 8h
  - A6 每 1h
  - A8 每日 14:00（北京时间）
- 新增“阶梯执行”调度：
  - 每日 00:00（北京时间）触发一次，在同一工作流内串行执行 A1 → A2 → A3
- 同 run 内触发能力：
  - A4 若通过可在同 run 内继续驱动 A5（至少具备此能力）
  - A5 产出后在同 run 内通知 A6（至少具备此能力）
  - A6 输出 `routed_events` 后，在同 run 内按目标触发 A2/A4/A9 与 L3 的 A1+A3（必要时串联补齐中间阶段）
  - A8 定时触发治理环（A7 → A8 → 路由到 A1/A2/A3）
- 产物留痕：
  - 每次运行上传 `artifacts/trading/*.json` 为 Actions artifact
  - `trace_id` 全链路可追踪
 
### 2.2 非目标（P0 不做）
 
- 不接入真实 HTTP 服务端、JWT 鉴权、真实 MQ 中间件（仅维持适配器与 mock）
- 不引入跨工作流 dispatch 作为触发机制（避免权限/调试复杂度）
- 不引入外部状态存储（数据库/redis）；P0 以“可运行 + 可审计 + 可触发”优先
 
## 3. 时间口径与 cron 换算
 
GitHub Actions `schedule.cron` 按 UTC 解释。本设计按北京时间对齐，换算如下：
 
- A1/A2/A3 阶梯（北京时间 00:00）→ UTC 16:00：`0 16 * * *`
- A4 每 4h：`0 */4 * * *`
- A5 每 8h：`0 */8 * * *`
- A6 每小时：`0 * * * *`
- A8 每日 14:00（北京时间）→ UTC 06:00：`0 6 * * *`
 
## 4. 工作流设计（方案 A 扩展版）
 
新增 5 个独立 workflow，均支持 `workflow_dispatch` + `schedule`，并在同一个 workflow run 内完成下游触发。
 
### 4.1 trading-ladder-a1-a3.yml（每日 00:00 北京时间）
 
触发：
 
- `schedule: 0 16 * * *`（UTC）
- `workflow_dispatch`
 
执行：
 
- 在单 job 内串行执行 A1 → A2 → A3
- 统一 `trace_id = trade-${{ github.run_id }}`
- 将 A1/A2/A3 的输出写入 `artifacts/trading/` 并上传 artifact
 
输入（workflow_dispatch）：
 
- `signals`（默认 `["macro"]`）
- `confidence`（默认 `0.8`）
- A2/A3 所需的最小字段（提供默认值，可覆盖）
 
### 4.2 trading-a4-validation.yml（每 4 小时）
 
触发：
 
- `schedule: 0 */4 * * *`
- `workflow_dispatch`
 
执行：
 
- 运行 A4（风控门禁），产出 `risk_gate`
- 若 `risk_gate == PASS`，在同 job 内继续运行 A5（满足 “A4 驱动 A5” 的触发能力）
- 上传 `artifacts/trading/` 产物
 
输入（workflow_dispatch）：
 
- `max_drawdown_pct` / `position_ratio` / `stop_loss_pct`
- A5 所需的最小字段（例如 `direction/entry_price/leverage`，提供默认值，可覆盖）
 
### 4.3 trading-a5-execution.yml（每 8 小时）
 
触发：
 
- `schedule: 0 */8 * * *`
- `workflow_dispatch`
 
执行：
 
- 运行 A5 生成 `order_plan`
- 在同 job 内运行一次 A6（以执行结果为输入的情报通知），满足 “A5 → A6” 能力
- 上传 `artifacts/trading/` 产物
 
### 4.4 trading-a6-intelligence.yml（每小时）
 
触发：
 
- `schedule: 0 * * * *`
- `workflow_dispatch`
 
执行：
 
- 运行 A6，产出 `routed_events` 与 `route_summary`
- 在同一个 workflow run 内消费 `routed_events` 并触发对应阶段：
  - `A2`：执行 A2，随后补跑 A3（满足 “A2 → A3” 的阶梯能力）
  - `A4`：执行 A4；若 `risk_gate == PASS`，继续执行 A5
  - `A9`：执行 A9
  - `A1 + A3`：先执行 A1，再执行 A3（满足 L3 重启）
  - `OBSERVE`：仅记录，不触发阶段
- 上传 `artifacts/trading/` 产物
 
### 4.5 trading-a8-governance.yml（每日 14:00 北京时间）
 
触发：
 
- `schedule: 0 6 * * *`（UTC）
- `workflow_dispatch`
 
执行：
 
- 在单 job 内运行治理环编排器：A7 → A8 → 路由到 A1/A2/A3
- 上传 `artifacts/trading/` 产物
 
## 5. 实现方式（复用现有模块，不新增 CLI）
 
工作流内用 Python `importlib.util.spec_from_file_location` 动态加载并调用函数，复用仓库既有实现。
 
核心复用点：
 
- A0-A9 入口：`workflows/trading-decision/A*/entrypoint.py`
- 治理环编排：`workflows/trading-decision/orchestrator/governance_loop.py`
- 协议与契约：`workflows/trading-decision/protocol/message.py`
 
契约约束：
 
- 每个阶段输出都必须满足 `require_contract_fields`（缺字段 fail-closed）
- 每个工作流 run 统一生成 `trace_id` 并贯穿各阶段输入
 
## 6. 并发控制与权限
 
并发控制：
 
- 每个 workflow 设置 `concurrency`，避免同一分支同一 workflow 重叠触发
 
权限：
 
- 默认 `contents: read` 即可（P0 不需要写回仓库）
 
## 7. 测试与验收
 
### 7.1 本地/CI 测试
 
- 既有测试已覆盖协议、编排、回放、L4 契约等：`pytest -q tests/test_trading_*`
 
### 7.2 P0 验收标准
 
- 5 个 workflow 在主干可被 `workflow_dispatch` 触发并成功运行
- 每个 workflow 上传 `artifacts/trading/*.json` artifact（至少 1 个文件）
- A6 的 `routed_events` 可被同 run 内消费并触发对应阶段执行
- A4 的 `risk_gate` 为 PASS 时可同 run 内继续跑 A5
- A5 运行后可同 run 内调用 A6 完成“执行结果通知”
 
## 8. 风险与后续演进
 
- P0 的 payload 使用默认值并允许 dispatch 覆盖，不代表真实交易状态持久化；后续需引入状态存储与真实数据源
- P1 再考虑：
  - 真实 HTTP 服务端与 JWT
  - MQ topic/endpoint 真实接入与消费端
  - 以 artifacts 或外部存储作为“上一轮策略/风险状态”的输入源
 
