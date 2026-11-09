# PLAN: NN 闭环链施工计划（基于 REVIEW-20261109 与 SPEC-M1/M2/M3）

> 版本：v0.1
> 日期：2026-11-09
> 状态：待批准；关联 SPEC-M1 v0.2（含 R0/M10-M12/G1-G4）、SPEC-M2 v0.1、SPEC-M3 v0.1、REVIEW-20261109
> 原则：**先复活、再止血、后接通、最后反射弧**；硬门禁 G1-G4 不可跳阶段。

---

## 总览（依赖图）

```text
WP-R0  信号活性        [40/43 侧，无代码依赖，运维+配置为主]
  └─> WP-R0.5 止血     [42/50 侧，小改动，当日可验]
        └─> WP-R1 宏观力量+消费侧   [50 新模块 ×3 + 42 外发 + 11/16 接入]
              └─> WP-R2 时序矛盾+回放底座  [42 归档 + 50 pit_replay + Granger]
                    └─> WP-S1 正向反射弧   [42 dispatcher + 11 shim]
                          └─> WP-S2 逆向反射弧 [sensor 服务化 + salience]
                                └─> WP-R3 闭环   [13 接入 + 48 反馈 + W6/R 校准]
```

每条 WP 独立可交付、独立验收；后续 WP 开工前必须确认前置门禁。

---

## WP-R0 信号活性（最高优先，预估 1-2 天，无开发量为主）

| # | 任务 | 改动位置 | 验证 | 退出标准 |
|---|---|---|---|---|
| R0-1 | 恢复 40 日更流水线调度：确认运行方式（launchd plist / 云端 cron），登记 `p1→p2→p3→p4` 链；失败后告警接 15 | 40 调度配置（现 cron 无记录）；15 告警规则 | 手动连跑 2 天，检查 4 份产出物 `generated_at` | cycle_state/asset_rotation/sector_transmission/fund_flow 的 generated_at ≤ 24h，连续 2 天 |
| R0-2 | 打开 43 `CYCLE_STATE_BRIDGE=1`（polling_trader daemon 环境），验证五维非默认 | daemon 启动环境；43 `cycle_state_adapter.py` | 重启后查 `five_domain_state.json` | 天/地/将三维 ≠ 50，且与 cycle_state 最新数据一致 |
| R0-3 | 43 shadow 解除条件预注册并落文档：连续 7 天五维非默认 + P3 一致性 ≥95% → shadow=false | `43-战略承接推演层/scripts/polling_cycle.py`（解除逻辑）+ 本 PLAN 附录 | 条件达成前 shadow 保持 true 且审计正常 | 解除条件写入代码+文档；解除时审计事件 |
| R0-4 | washout 模块激活：定位 trigger 永不触发原因（p3_washout 或数据源），修复至非 unknown_fallback | 40 `scripts/p3_*washout*` | `washout_verdicts.json` 出现非 unknown 标的 | 至少 3 标的有真实 verdict（含 benign），unknown 占比 <50% |
| R0-5 | 43 `element_comparison` 分歧外发：42 适配器 payload 携带分歧字段 | `42-神经网络交易协调层/adapters/strategic_extension_adapter.py` | run_bus 后 bus_state 含 element_comparison | 字段存在于 43 信号 payload |

**R0 期间红线（G1）**：50 侧 macro_force 权重保持 0；任何基于当前链路的权重/回测结论作废。

## WP-R0.5 止血（1 天，纯 42/50 小改动）

| # | 任务 | 改动位置 | 验证 |
|---|---|---|---|
| F1 | source 命名统一：42 侧 `strategic_extension` 双写过渡（canonical=`43-strategic`），registry 同步 | `strategic_extension_adapter.py` L41、`registry.yaml` | 50 `role_of("43-strategic")=constraint`；双写期两源同 path_id 只计一票 |
| F2 | 权重按 source 归一 + `DEFAULT_DIMENSION` 改 C7 | 50 `mappings.py` L76、`w4.py` L28-43、`dominance.py` L34-40 | 单测：26 条 bcrm-tactical path 总权重=0.35 而非 9.10 |
| F3 | 新鲜度源年龄校验 | 50 `path_synthesis.py` `_freshness()` | fixture：state_generated_at=14 天前 → freshness<0.1 |
| F4 | M10 degraded_events 落地：各降级点写 `42/runtime/degraded_events.jsonl`，>24h 告警 | 42/50/43 各降级点（首批 6 类） | 注入一个降级事件 → jsonl 有记录、告警触发 |
| F5 | direction_leak_check：constraint_loader 剥方向 + 审计 | 50 `constraint_loader.py` | 含方向的 strategy_mapping 输入 → 钳位只取幅度，审计有 leak_check 记录 |

**退出标准**：`python3 -m pytest 50-NN主矛盾评估器/test_*.py` 全绿 + 新增 5 个止血测试通过；总线实盘影子跑 24h 无 degraded 新增。

## WP-R1 宏观力量与消费侧（3-5 天，核心开发）

| # | 任务 | 改动位置 | 验证 |
|---|---|---|---|
| N1 | 50 新模块 `core/dimension_forces.py`（复刻 23 维度力量，M4） | 新建 + 测试 | 维度多空两面计算，空维度 neutral |
| N2 | 50 新模块 `core/contradiction.py`（复刻三步法，M5） | 新建 + 测试 | 共振 0.6/主导 0.55/次要封顶 0.3 单测 |
| N3 | 角色四分 + macro_force 权重表（上限 0.15，M12） | 50 `mappings.py`、`path_synthesis.py` | 40/43 生成 path 且进 D1；权重和=1.0 |
| N4 | 40 背离外发：42 适配器携带 divergence（`40-divergence` 源） | `cycle_state_adapter.py` + 50 mappings | 含背离 fixture → 50 收到独立 evidence |
| N5 | M11：11 param_consumer shim | `11-易经推理系统/scripts/memory_l4/`（对齐 23 契约） | 改 params_active → 11 阈值/仓位系数变化 |
| N6 | M11：16 SSoT 归口（改读 bus 或版本戳校验） | 16 `constraint_envelope.py` L19-28 | 文件与总线版本不一致时取保守值 + degraded |

**退出标准**：宏观 long/微观 short fixture 下 50 输出含宏微观矛盾对象；总线影子 48h 审计无 direction_leak；G1 解除（macro_force 权重 0→0.15）。

## WP-R2 时序矛盾与回放底座（3-5 天）

| # | 任务 | 改动位置 | 验证 |
|---|---|---|---|
| T1 | 50 新模块 `core/temporal_conflict.py`（M6） | 新建 + 测试 | horizon 分层裁决单测（≤1d/≥5d/过渡带） |
| T2 | bus 历史归档 + 50 决策落盘（M9） | 42 `run_bus.py`、50 `decision.py` | 500 份滚动上限、原子写 |
| T3 | `tools/pit_replay.py` A/B 回放（M9） | 新建 | 重放历史快照输出方向命中报告 |
| T4 | 共振矩阵离线计算 + Granger 检验（M2-P1，G2 门禁） | 40 `scripts/p3_resonance_matrix.py`（新建）+ `resonance_matrix.json` | ETH/SOL 的 corr0/lag/beta 与原型复算一致；Granger p 值入文件 |
| T5 | 矛盾去重规则落地（M2 评审增补） | 50 `contradiction.py` | 同标的同维度仅一个矛盾对象 |

**退出标准**：PIT 回放跑通（即使样本不足 200 仅作工程验证）；G2 判定结果落档（t_arrive 启用或禁用）。

## WP-S1 正向反射弧（3-4 天，依赖 R2）

| # | 任务 | 改动位置 | 验证 |
|---|---|---|---|
| D1 | 42 `task_dispatcher.py`（schema/持久化/去重/优先级/P2 保底 60%） | 新建 + 测试 | 10 并发 fixture 无重复任务；P2 时间片统计 |
| D2 | 龙头监控门（\|F_macro\|≥0.4 → P0） | 42 或 40 侧（契约冻结于 S0） | 龙头信号 fixture → P0 任务生成+P2 让渡日志 |
| D3 | 11 单标的 on-demand shim（bcrm-tactical 先行） | 11 polling_trader 暴露入口 | 任务到 → 60s 内该标的技术信号上总线 |
| D4 | 50 trigger/weight_profile 消费（三档） | 50 `mappings.py`/`decision.py` | macro_led 决策 payload.profile=0.50/0.50 |

## WP-S2 逆向反射弧（3-4 天，依赖 S1）

| # | 任务 | 验证 |
|---|---|---|
| E1 | 40/43 `resonance_sensor.py` 服务化（M3 §1.2，SLA<60s） | 任意标的请求返回 R/F_macro/t_arrive/regime_overlay；样本不足 degraded |
| E2 | salience 门（conf≥0.6 + 配额制每源 4h≤2） | 微观高置信 fixture → P1 任务；第 3 次触发被配额拦截 |
| E3 | micro_led profile + regime_overlay 叠加裁决 | trend/range fixture 分别产出对应 intent 偏向 |
| E4 | trigger_flap 防护（4h≤2 次） | 快速交替 fixture → 锁定 + 审计 |

## WP-R3 闭环与上线准备（依赖 S2，持续）

| # | 任务 | 验证 |
|---|---|---|
| C1 | 13 接入契约（消费 execution_rights/mandate/kill_switch，fail-closed）→ 解除 G3 | 契约评审 + kill-switch 演练 |
| C2 | 48 反馈网关实现（按 SPEC-NN-FEEDBACK-GATEWAY v0.1） | 决策样本回流 48，W6 样本计数增长 |
| C3 | W6/R 校准闭环（48 训练门禁；PIT ≥200 决策后启用，G4） | 权重变更走门禁审计 |
| C4 | 23/50 对照实验启动（同输入，L9/L10 已通） | 对照报告首版 |

## 硬门禁汇总（违反即停工回退）

| 门禁 | 内容 |
|---|---|
| G1 | R0 未完 → macro_force 权重=0 |
| G2 | Granger 不显著 → t_arrive 禁用 |
| G3 | 13 未接入 → 50 paper only |
| G4 | PIT <200 决策 → 禁调权重阈值 |

## 首批开工项（批准后即刻）

1. R0-1（运维：恢复 40 调度）— 无代码风险，当天可验
2. R0-2（配置：开桥）+ R0-3（shadow 条件文档化）
3. F1-F3（止血三件套，改动 <100 行，当日可测）

---

## 附录 A · R0 施工落地记录（2026-11-09）

### R0-1 40 调度恢复方案
- 定位结论：本地 crontab/LaunchAgents、云端 systemd timer/cron **均无** p1-p4 任何调度记录；40 产出物停滞于 2026-10-26（14 天）。云端 polling_trader（PID 3064801）存活但 systemd 侧因 single-instance 锁反复重启退出（属正常守护行为，非崩溃）。
- 落地：新建 `40-周期神经网络系统/scripts/run_daily_pipeline.sh`，链序按数据依赖固定为
  `p1_real_cycle → p1_ma200_anchor → p2_asset_rotation → p2_divergence → p3_sector_transmission → p3_fund_flow → p3_smart_money → p3_stovall_breadth → p3_washout_integration → p3_meme_platform_monitor → p4_strategy_mapping`；
  任一步失败即中止并接 15 飞书告警（fail-open：告警失败仅记日志）。
- 云端部署：systemd timer（每日 05:30 UTC，避开 datacenter-backfill 20:15 与 auto-archive 04:30 窗口），service 以 luke 用户 + `/home/luke/venv-trading/bin/python` 运行。
- 退出验证：连续 2 天 cycle_state/asset_rotation/sector_transmission/fund_flow `generated_at` ≤24h。

### R0-3 shadow 解除条件（预注册，代码即文档）
- 落地：`43-战略承接推演层/strategic_extension/signal_publisher.py` `_shadow_gate_decision()`；状态 `43/runtime/shadow_gate_state.json`，逐次审计 `runtime/shadow_gate_audit.jsonl`。
- 解除条件（两条件**同时**满足才解除，fail-open 保持 shadow=true）：
  1. **连续 7 天五维非默认**：`CYCLE_STATE_BRIDGE` 开启 且 crypto_usdt 天/地/将/法四维任一 ≠50（50 为 fail-open 默认值，≠50 证明 40→43 承接真实生效；同日重复发布不累加，断日清零重计）。
  2. **P3 迁移一致性 ≥95%**：`43/runtime/p3_shadow_compare_report.json` 的 `consistency_rate ≥0.95` 且测量时间 ≤30 天（报告由 `43/docs/p3_shadow_compare.py` 在**桥关闭态**产出，验证 43 与 11 原位置迁移等价）。
- 解除瞬间写 `released=true` 审计事件；信号 payload 携带 `shadow_gate` 字段（qualifying_today/consecutive_days/p3_rate/p3_ok）供 42/50 观测。
- 测试：`43/tests/test_shadow_gate.py` 8 场景（桥关不达标/默认分不达标/同日不累加/断日清零/无 P3 不解除/P3 低分不解除/双条件达成解除/P3 过期不解除）。
- ⚠️ 操作约束：P3 报告必须在**开桥前**生成并存档（桥开启后 p3_shadow_compare.py 会拒绝运行）。本次施工顺序：先在桥关闭态跑 P3 比对存档 → 再开桥（R0-2）→ 连续 7 天计数自动推进。

### F1-F3 止血落地点
- F1：42 `adapters/strategic_extension_adapter.py` 双写过渡（`SOURCE_ALIAS_MODE=1` 同发 `43-strategic`+`strategic_extension`，默认仅旧名=回滚路径，对齐 bdsm P1-05）；`registry.yaml` name→`43-strategic`；50 `SOURCE_ALIASES` 增补两旧名→canonical。
- F2：50 `DEFAULT_DIMENSION` C3→**C7**（原值不在 VALID_DIMENSIONS 属硬 bug，23-contradiction 维度同步 C7）；`path_synthesis` 末端按 source 归一权重（`weight = source_weight/该源当批 path 数`，截断 [0,1]，留 `weight_raw`/`source_path_count` 审计字段）。
- F3：`path_synthesis._freshness` 增加源年龄因子——payload `state_generated_at`/`updated_at` 按源 TTL 指数衰减（40-*=168h/43=72h/11-*=24h），>2×TTL 直接丢弃 + `degraded=source_stale`；最终 freshness=min(总线, 源)。
- 测试：50 `tests/test_r05_hemostasis.py` 10 例（F1×4/F2×3/F3×3）；全套 50 测试 63 绿 + 43 测试 70 绿。
