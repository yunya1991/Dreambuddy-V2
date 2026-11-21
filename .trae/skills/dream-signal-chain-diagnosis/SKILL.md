---
name: dream-signal-chain-diagnosis
description: 23 交易链路出现「恒定值/不生效」症状（ri 恒 0.5、tier 恒 probe、d_star 恒 WAIT、confidence_mult 恒 1、某节点恒 skip）时的标准诊断与逐项修复流程。Invoke when a chain signal is stuck at a constant, a node never takes effect, or user reports 恒值/不生效/未触发.
---

# 信号链路恒定值诊断与逐项修复

## 适用症状

- 某信号长期等于同一个值（`ri=0.500`、`tier=probe`、`d_star=WAIT`、`R_flow=0.0`）
- 某链路节点恒 `skip`（N3/N5/N9）
- 数据不缺但下游"没反应"

## 流程（七步，不可跳步）

### 1. 先取证据，禁止猜测

- `runtime/chain_events-*.jsonl`：`N0`（数据就绪）/`N2`（R 向量）/`N5`（矛盾）/`N9`（ri·tier）
- 服务日志：`journalctl -u dreambuddy-entry23`，按节点关键词过滤
- 必须拿到**实际数值**，不接受"应该是"

### 2. 建因果链

对每个恒定值，从输出反向追溯到**最近一次赋值点**：

```
ri = max(ripple_ri, reflection_ri)
  ripple_ri = compute_ri(...) if is_source else 0.50   ← 硬编码回落？
  is_source = detect_ripple_source(ess_dir, vol_ratio, liq, scale)
    ess_dir ← ESSDirectionProvider 只取 top1 且要求 direction∈{long,short}
```

每个分叉标注：`真实计算` / `硬编码回落` / `异常捕获回落`。

### 3. 四类判定

| 判定 | 含义 | 处理 |
|---|---|---|
| 缺陷 | 逻辑/数据耦合错误 | 进 FIXLIST 修 |
| 待校准 | 阈值不适配当前周期 | 先配置化，再用分布定档 |
| 设计使然 | spec 定义，测试已固化 | 记录语义，交产品确认 |
| 正常 | 冷启动（样本不足） | 关闭，观察 |

### 4. 产出 FIXLIST

落到 `23-.../docs/FIXLIST-<症状>-<日期>.md`，表结构固定：

`# | 问题 | 根因 | 修复动作 | 验收标准 | 状态`

状态只用 `[ ] / [~] / [x] / [-] / [!]`，并保留「执行记录」表。

### 5. 逐项修复，顺序固定

1. **先补可观测**（N0/N2/N9 增加定位字段），否则修完无法验证
2. **再修逻辑**（最小改动 + 单测覆盖真实分支）
3. 每修一项，**立即**更新 FIXLIST 状态与执行记录，不批量补记

### 6. 默认值纪律

- 任何阈值/默认值改动：先加 env 覆盖、**默认值保持不变**
- 用真实分布（P50/P90/P95/P99）定档，不拍脑袋
- 语义可疑但不明确的（如 `wait=R_smooth×R_reflexivity`）→ `[!]` blocked，不擅自改

### 7. 收尾

- 单测 + 相关回归全绿
- 文档 §诊断基线（23 TD/框架文档）+ 15 TD 锚定索引同步
- 提交 → 云端 `pull --ff-only` → 重启 → 观察一轮事件复核
- 复核字段：修复项对应的 N 节点 data（如 `ess_top_direction`、`vol_ratio`、`ri`、`tier`）

## 反模式

- 看到恒定值直接改公式（先找赋值点与回落分支）
- 直接调默认阈值（先配置化 + 分布证据）
- 用 `try/except` 把异常吞成中性值后宣称"已修复"
- 一次提交修多项（清单无法逐项验证）

## 已验证案例

- 2026-11-18 `ri=0.5 / tier=probe`：ESS top1 为纯离场组合（`direction=both`）→ 方向为空 → ripple 回退 0.50。
  修复：Provider 按 ESS 降序取第一个含 long/short 的组合。清单：
  `23-四层闭环自进化交易架构/docs/FIXLIST-ri-tier-dstar-20261118.md`
- 2026-11-18 `d_star=WAIT`：不是行情问题，是量纲问题——`wait=R_smooth×R_reflectivity` 是两维乘积，
  实测 p90=0.164 → wait≈0.07，任何单维方向代价（最低 0.31）都打不过 → 结构性恒 WAIT。
  修复路径（不猜，按证据）：合成回测 + 云端真实事件分布 + 真实 K 线 walk-forward 三方对照，
  再选「翻符号 + 30% 中性区」；落地为 env 开关（默认 legacy）+ 影子字段 `d_star_shadow`，
  观察一致后再切换。可复用脚本：`23-.../scripts/backtest_ri_gate.py --events/--klines`。
- 2026-11-18 切换与监控闭环：`EVOLUTION_DSTAR_WAIT_MODE=calibrated` 一经启用，必须同时接入 15 监控
  （`signal_calibration_metrics` + `DstarCalibratedModeOff/AllWait` 等 5 条告警 + 日报项），
  否则口径回退无人发现。Prometheus 规则改动后需 `docker kill -s HUP <prometheus>` 重载。
- 2026-11-18 恒定值诊断的反例教训：`reflection_ri=0.5` 曾被判为「冷启动正常」，实为四层问题：
  ① 交易索引的已知源按 `project_root` 解析且未 `resolve()`，23 子目录启动时读不到 22 账本（真实交易全漏）；
  ② 自动发现把 `gene_data/shadow_validation/*_samples.jsonl`、`data/ess_reflection.jsonl` 当真实交易（pnl=-100 占位）；
  ③ `22-reconciled` 平仓流水 realized_pnl=0 被当亏损；
  ④ 仓库级索引混入其它子系统成交（11-易经），且 `get_coin_stats("BTC-USDT-SWAP")` 未归一化恒回退 0.5；
  ⑤ 跨源 `trade_id` 直接用各源自增 `id`，后加载源覆盖先加载源（22 账本 19 笔只剩 3 笔）。
  **判「冷启动」前必须核对三件事**：样本条数、每笔 PnL 是否非空且量级合理、样本来源路径/`record_source` 是否为真实成交。
  同理，「按目录相对路径找上游数据」在子目录启动的服务里极易静默失效，需向上定位仓库根；跨子系统战绩必须按 `OWN_SOURCES` 归属过滤；
  多源索引的主键必须带来源命名空间（`{source}:{id}`）。
  修复后若仍为 0.5，先算一遍真实战绩（胜率未达 `MIN_WIN_RATE=0.55` 即为真实值，不是缺陷）。


