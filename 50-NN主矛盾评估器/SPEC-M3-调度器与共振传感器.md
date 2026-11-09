# SPEC-M3: 调度器与共振传感器（神经传导的正向/逆向反射弧）

> 版本：v0.1（设计稿）
> 日期：2026-11-09
> 状态：🟡 设计态，待评审；依赖 SPEC-M1（R0 信号活性）、SPEC-M2（共振矩阵 R(s)）
> 关联：42 SPEC（协调层）、50 SPEC §2/§4、SPEC-M2 §一（宏观力传导）
> 核心命题（用户原话）：正向神经传递——40-43 主网络围绕龙头训练计算，发现龙头交易价值信号后由**调度器**调度微观子系统针对该标的计算各维信号，经 42 给 50（宏观维权重更高、偏趋势策略）；逆向神经反馈——宏观无信号时微观子系统自动探索更广泛标的，发现价值标的时同步调用其他子系统 + **共振传感器**（40-43 用历史数据计算该标的各维度、实现共振传导给出宏观维度数据），各子系统和主链路**优先让渡资源**，最后给 50（需叠加主周期信号判定趋势/震荡）。

---

## 零 · 问题定义：当前链路没有"反射弧"

现状（2026-11-09 实证）：

| 缺失 | 实证 |
|---|---|
| 无计算任务调度 | 42 只有 `param_governor.dispatch`（参数下发给订阅者，L267-316），**没有计算任务编排**；微观系统（11 polling_trader）按自身轮询节奏扫描，**无单标的 on-demand 计算入口**（grep 无 evaluate/single_symbol 入口） |
| 宏观与微观各自孤立扫描 | 40-43 产出静态快照；11 各子池按 watchlist 轮询；两者**互不触发**——龙头出信号时微观不会加速，微观发现机会时宏观不参与 |
| 资源无优先级 | 无让渡机制；所有计算等权排队 |

后果：宏观信号的"时效价值"在轮询间隔中衰减（龙头信号到微观计算完成可能隔数小时）；微观发现的非龙头机会得不到宏观维度背书，50 只能用 D3 技术单维度裁决。

## 一 · 两个新组件

### 1.1 调度器 Dispatcher（42 侧，新模块 `task_dispatcher.py`）

职责：**计算任务的编排**，不是参数下发、不是下单（42"协调而非执行"红线不破）。

```text
task = {
  task_id, trigger: "macro_led" | "micro_led",
  symbol, reason, priority: P0|P1|P2,
  requester: "40-cycle" | "43-strategic" | "11-*",
  targets: ["11-bcrm-tactical","11-bdsm","11-washout","11-event-arbitrage","resonance_sensor"],
  ttl_sec, created_at, deadline_at,
  state: queued|running|done|expired|failed
}
```

- 持久化 `42/runtime/dispatch_tasks.jsonl`；完成状态可查询；同一标的同时只允许一个 running 任务（去重合并，新任务继承剩余 TTL）。
- 优先级：**P0 龙头正向 > P1 逆向共振 > P2 例行轮询**；P0/P1 到达时 P2 让渡（暂停/降频），P2 不阻塞 P0/P1 的资源获取。
- 失败治理：目标子系统超时未回 → 该维标记 unavailable（fail-open，50 按缺源降级）；调度器自身故障 → 全系统退回现行轮询模式（行为与今天一致），审计 `degraded=dispatcher_down`。
- **P2 饥饿防护（评审增补）**：P2 例行轮询虽可被让渡，但必须保证 **≥60% 的基础算力时间片**（滑动 24h 窗口统计）——P2 是逆向反射弧的"感觉神经"，长期饿死会导致微观探索能力萎缩、micro_led 触发源枯竭。低于下限触发告警并暂停新的 P1 任务。
- **salience 门防捕获（评审增补）**：微观各源的 conf 未校准（实测 11-bcrm-tactical 存在 path 数放大倾向）。每个子系统的 salience 触发有**配额制**：每源每 4h ≤ 2 次 P1 触发，超出排队；触发后的 sensor 结果纳入该源的校准样本（触发准确率回流，W6 学习）。防单一高置信源垄断逆向弧。

### 1.2 共振传感器 Resonance Sensor（40/43 侧，新模块 `resonance_sensor.py`）

SPEC-M2 的 `resonance_matrix.json` 从"日更离线产物"扩展为**可按需调用的计算服务**：

```text
输入:  {symbol, asof_ts?}
输出:  {
  symbol, layer: L1|L2|L3|L4|unregistered,
  upstream: "BTC" | "ETH" | ...,            # 自动选主见 §3.3
  R: {corr0, lag_profile, beta, down_corr},  # SPEC-M2 §1.2
  F_macro: {D1, D2, D4, washout},            # SPEC-M2 §1.3 四分量 [-1,1]
  t_arrive_hours,                             # 宏观力到达窗口
  regime_overlay: "trend" | "range" | "unknown",  # 主周期叠加（§2.2）
  freshness: {price_data_age_h, degraded[]}
}
```

- 计算底座：40 token_sequence + 18 数据中枢按需补数；样本 <30d → `degraded=insufficient_history`，F_macro 退化为上游层均值并标注。
- unregistered 标的（不在 L1-L4 表）：按 corr0 自动挂靠上游（§3.3），layer=unregistered 时 D4 权重取 L3 档。
- SLA：单标的计算 < 60s（P1 任务 TTL=300s 内含等待）。

## 二 · 两条反射弧

### 2.1 正向神经传递（macro_led，龙头触发）

```text
40-43 监控龙头池（L1: BTC；L2: ETH/SOL —— 池子预注册）
  │ 价值信号门（预注册，先验：|F_macro(龙头)| ≥ 0.4 且方向明确，
  │            或 regime 切换/突破 MA200/背离解除）
  ▼
Dispatcher 发 P0 任务 {symbol=龙头, targets=微观四维}
  │ P2 例行轮询让渡；微观子系统 on-demand 计算该标的各维信号
  ▼
42 bus：信号带 trigger=macro_led、task_id、macro_context（F_macro/R/t_arrive）
  ▼
50 macro_led 决策 profile：
  · 权重 profile：宏观 0.50 / 微观 0.50（vs 默认 0.30/0.70，预注册）
  · 策略偏向：trend intent 优先；reversal 轨降权（趋势市语义）
  · 时序裁决：宏观力 t_arrive≈0（龙头直连），时序矛盾规则仍适用于跟随层标的
```

### 2.2 逆向神经反馈（micro_led，探索触发）

```text
宏观无信号期（|F_macro(全部龙头)| < 0.2 持续 24h，判定宏观静默）
  │ 微观子系统按现有 watchlist 广泛探索（行为不变）
  ▼
Salience 门（任一子系统对某标的 conf ≥ 0.6 且非其例行产出，预注册阈值）
  ▼
Dispatcher 发 P1 任务：
  ① 并行调度其余子系统计算同标的（补全维度）
  ② 调用 Resonance Sensor：40-43 用历史数据计算该标的 R/F_macro/regime_overlay
  │ 资源让渡：主链路 40-43 暂停低优先任务（如离线学习），优先响应 sensor 请求
  ▼
42 bus：trigger=micro_led，宏观维度数据来自 sensor（provenance=resonance_sensor）
  ▼
50 micro_led 决策 profile：
  · 权重 profile：微观 0.60 / 宏观 0.40（预注册）
  · **叠加主周期判定策略类**（用户要点）：
      regime_overlay=trend → trend intent、允许延续性加分
      regime_overlay=range → reversal/高抛低吸语义升权，trend 降权
      unknown → 不叠加，按默认裁决
  · 时序矛盾：sensor 给出的 t_arrive 生效（宏观力按到达窗口衰减微观票，SPEC-M2 §2.2）
```

### 2.3 上游自动选主（回应 M2 遗留问题）

- L3/L4 及 unregistered 标的的 upstream 不固定注册，按**近 60d corr0 最大值**在 {BTC, ETH, SOL} 中自动选主，每周重算；
- 选主结果与 corr0 一并写入 resonance_matrix，max corr0 < 0.3 时标记 `upstream=none` → F_macro 仅保留 D1 层均值（弱宏观力），不参与宏微观矛盾（无可信传导路径）。

## 三 · 50 侧改动

1. `mappings`：evidence 增加 `trigger` 字段消费（macro_led/micro_led/例行）；`weight_profile` 按 trigger 切换（默认/0.50-0.50/0.40-0.60 三档，预注册，W6 学习区间不变）。
2. `decision.py`：输出 payload 增加 `trigger / task_id / regime_overlay / sensor_freshness`；micro_led 决策必须携带 regime_overlay 审计。
3. 矛盾对象扩展：macro_led 链路的时序矛盾以 t_arrive≈0 短路；micro_led 链路按 sensor t_arrive 全规则执行。
4. 防振荡：同一标的 4h 内 trigger 切换 ≤2 次，超出则锁定为上一 profile 并审计 `trigger_flap`（防调度风暴）。

## 四 · 与其他 SPEC 的关系

| SPEC | 关系 |
|---|---|
| SPEC-M1 R0 | 硬前置：40 复活前 sensor 无数据可算；43 桥打开前 regime_overlay 不可靠 |
| SPEC-M1 M2/M3 | 权重归一、macro_force 角色是所有 profile 的基础；本 SPEC 的三档 profile 在其上叠加 |
| SPEC-M2 | R(s)/F_macro/t_arrive 的定义复用；本 SPEC 把它从离线产物升级为 on-demand 服务，并解决 M2 遗留的自动选主问题 |
| 23 | 区别进一步拉大：23 无任务调度概念（固定流水线），本 SPEC 的反射弧是神经网络传导特有的"发现-召集-让渡"机制 |

## 五 · 阶段路线

| 阶段 | 内容 | 退出标准 |
|---|---|---|
| S0 契约 | task schema、sensor API、trigger/weight_profile 契约冻结 | schema 评审通过；42/40/43/50/11 四方确认 |
| S1 正向链 | Dispatcher 最小实现 + 龙头池监控门 + 11 单标的 on-demand shim（bcrm-tactical 先行） | 构造龙头信号 fixture：P0 任务下发→微观信号回流→50 以 macro_led profile 出决策，全链 < 5min |
| S2 逆向链 | Salience 门 + Resonance Sensor 服务化 + regime_overlay | 构造微观发现 fixture：sensor 60s 内返回 R/F_macro；micro_led 决策带 overlay 审计 |
| S3 治理+回放 | 资源让渡、防振荡、dispatch 审计接入 PIT 回放 | 调度风暴演练（10 标的并发）无重复任务；回放可复算 |

## 六 · 验收清单

1. 龙头 F_macro 越门 → P0 任务生成且 P2 轮询让渡可观测（日志含 yield 记录）。
2. 非龙头标的微观 conf=0.65 触发 → sensor 返回含 upstream/corr0/t_arrive 的完整宏观维度；corr0<0.3 时 upstream=none 且不参与宏微观矛盾。
3. 同一标的 macro_led 与 micro_led 的 50 输出权重 profile 可区分、可审计（payload.trigger 生效）。
4. 调度器 kill 后系统自动退回现行轮询模式，50 无异常决策（fail-open 演练）。
5. 资源让渡期间主链路低优先任务恢复后数据无缺口（审计补采记录）。
