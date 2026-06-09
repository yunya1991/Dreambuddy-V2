---
name: dream-data-analysis
description: 将每轮多维输出沉淀为可统计时间序列并产出趋势/阻力/归因图与校准建议。Invoke when 需要把长期记忆与数学统计用于趋势惯性与阻力最小原则落地。触发词：数据分析、趋势图、阻力分析、校准建议、雷达图、图表展示、可视化、Dashboard、MA/EMA、趋势强度、阻力分解、长期记忆统计、episode分析
license: Internal
version: 1.0.0
---

# Dream-Data-Analysis: 长期记忆 × 数学统计的趋势与阻力分析

## 版本历史
- v1.0.0 (2026-04-18): 初始部署，包含 renderer.py + 配置文件

## 目标
- 将每轮 Step3/Step4/Step6 的结构化输出沉淀为时间序列，做平滑、变化率、加速度与"阻力项"计算。
- 输出可归因的子图清单与综合评估图清单，为后续参数校准（E[R] 映射、λ、阈值）提供证据。
- 不直接影响门禁与下单；输出仅供研究与复盘治理链路使用。

## 目录结构
```
dream-data-analysis/
├── SKILL.md                          # 本文件
├── renderer.py                       # 可视化渲染器 (Chart.js / Plotly)
├── config/
│   ├── resistance_weights.yaml       # 阻力权重配置
│   └── calibration_lag_policy.yaml   # 归因时滞策略
└── templates/                        # HTML 模板 (预留)
```

## 输入（建议字段）
- `trace_id`: string
- `ts`: string
- `inst_id`: string
- `episodes_window`
  - `lookback_count`: number
  - `timeframe_hint`: "15m" | "1h" | "4h" | "1d" | "mixed"
- `episode_series[]`（来自 `learning-episode-writer` 的可回放数据）
  - `ts`: string
  - `price_ref`: { `close`: number } | null
  - `scores`: object | null
  - `edge_eval`: object | null
  - `costs`: object | null
  - `microstructure`: object | null
  - `regime`: object | null
  - `odaily_research`: object | null
- `smoothing_policy`
  - `ma_windows`: number[] (例如 [5, 20, 60])
  - `ema_windows`: number[] (例如 [8, 21])
- `physics_policy`
  - `use_log_price`: boolean (默认 true)
  - `dt_unit`: "per_step" | "minutes" | "hours"

## 输出（必须结构化）
- `trend`
  - `direction`: "up" | "down" | "flat" | "unknown"
  - `velocity`: number | null
  - `acceleration`: number | null
  - `trend_confidence`: 0-1
- `resistance`
  - `resistance_score`: 0-100
  - `components`: { `cost_friction`: number, `crowding_friction`: number, `vol_friction`: number, `liquidity_friction`: number }
  - `notes`: string[]
- `timeseries_features`
  - `feature_names`: string[]
  - `feature_series_refs`: string[]（指向 episode 字段或派生序列名称）
- `charts`
  - `subplots`: string[]（各维度子图清单）
  - `overview_plots`: string[]（综合评估图清单）
- `calibration_suggestions`
  - `expected_return_mapping`: { `status`: "keep" | "tighten" | "loosen" | "rebuild", `evidence_refs`: string[] }
  - `lambda_risk`: { `status`: "keep" | "up" | "down", `evidence_refs`: string[] }
  - `thresholds`: { `edge_min_bps`: string, `max_worst_slippage_bps`: string, `blackout_windows`: string }
- `reason_codes`: string[]
- `evidence_refs`: string[]

## 核心方法（落地规则）

### 1. 趋势惯性（多周期平滑）
- 对 `price_ref.close`（或 `log(close)`）计算 MA/EMA 平滑曲线。
- 方向：以长窗平滑的斜率符号为主；中短窗作为"回调/突破"辅助。
- 速度：`v = Δx/Δt`（x 为平滑后的价格或 log 价格）。
- 加速度：`a = Δv/Δt`，用于识别趋势增强/衰减与拐点候选。

### 2. 阻力最小（阻力项显式化）
- 以 `edge_eval` 与 `costs/microstructure` 组合构造阻力：
  - `cost_friction`：`costs.total_cost_bps_est` 与 `worst_case_slippage_bps`
  - `liquidity_friction`：`spread_bps`、`depth_1pct_usdt`、`orderbook_imbalance`
  - `crowding_friction`：funding/OI 的拥挤信号（若 episode 含此字段）
  - `vol_friction`：ATR/vol_regime=high
- 阻力越大，越倾向建议提高 λ 或提高 edge_min_bps，或建议在黑窗/高摩擦阶段观望。

### 3. 反思校准（推理→统计→修正）
- 将 `scores.total` 与后续结果（PnL/是否触发止损/edge_bps）做分桶对比，给出 E[R] 映射调整建议。
- 若高波动阶段持续亏损：建议 `lambda_risk=up` 与更严格的 `max_worst_slippage_bps`。

## Timeframe 默认平滑窗口

| Timeframe | MA短窗 | MA中窗 | MA长窗 | EMA快线 | EMA慢线 | 适用场景 |
|:---|:---:|:---:|:---:|:---:|:---:|:---|
| **15m** | 4 | 16 | 48 | 8 | 21 | 短线剥头皮 |
| **1h** | 5 | 20 | 60 | 8 | 21 | 日内交易 |
| **4h** | 6 | 24 | 72 | 12 | 26 | 波段操作 |
| **1d** | 5 | 20 | 60 | 12 | 26 | 中长线持仓 |
| **mixed** | 5 | 20 | 60 | 8 | 21 | 多周期综合 |

## 阻力权重配置

默认权重向量 (`balanced`):
```yaml
cost_friction: 0.30
liquidity_friction: 0.35
crowding_friction: 0.20
vol_friction: 0.15
```

可用预设: `conservative`, `balanced`, `aggressive`, `liquidity_first`, `cost_first`

## 归因时滞策略

| 策略 | 触发条件 | 等待轮数 | 证据阈值 |
|:---|:---|:---:|:---:|
| event_driven | 单次亏损>5% | 0 | 1 |
| standard | 同向证据积累 | 5-20 | 3 |
| conservative | 保守校准 | 10-30 | 5 |

## 图谱清单（用于归因）

### 维度子图（subplots，逐项对照 episode 字段）
- `price(close) + MA/EMA`
- `trend_strength / macro_fund_tailwind / memory_safety`（含平滑）
- `edge_bps`（含平滑）与 `gatekeeper.decision` 标注
- `costs_bps / worst_case_slippage_bps / spread_bps / depth_1pct_usdt`（执行摩擦）
- `regime` 标签轨（trend/range, high/low vol, risk_on/off）
- `odaily_research` 的链上/ETF/预测市场维度（仅解释层）

### 综合评估图（overview_plots）
- `radar_snapshot(latest)`（三维评分+阻力分解）
- `trend_vs_resistance`（速度/加速度 vs 阻力分解）
- `calibration_dashboard`（E[R]映射建议、λ建议、阈值建议）

## 可视化渲染器 (renderer.py)

### 使用方法
```python
from renderer import render_all_charts, render_trend_chart, render_radar_snapshot

# 生成所有图表
paths = render_all_charts(episode_series, analysis_result, output_dir="./charts")

# 或单独生成
html = render_trend_chart(episode_series, ma_windows={"ma_short": 5, "ma_medium": 20, "ma_long": 60})
html = render_radar_snapshot(scores, resistance)
html = render_calibration_dashboard(analysis_result)
html = render_trend_vs_resistance(trend_data, resistance_data)
html = render_interactive_trend(episode_series)  # Plotly 交互式
```

### 输出图表类型
| 函数 | 图表类型 | 技术栈 |
|:---|:---|:---|
| `render_trend_chart` | 趋势分析图 | Chart.js |
| `render_radar_snapshot` | 雷达图快照 | Chart.js |
| `render_calibration_dashboard` | 校准仪表盘 | HTML/CSS |
| `render_trend_vs_resistance` | 趋势 vs 阻力 | Chart.js |
| `render_interactive_trend` | 交互式趋势图 | Plotly |

## Contract v0.1（最小审计契约）
- 输入建议包含：`trace_id`、`ts`、`inst_id`
- 输出必须包含：`reason_codes`、`evidence_refs`

## Integration

### 上游
- `learning-episode-writer` 的 episode_series（或可回放字段）

### 下游
- `dream-posttrade-mrm-audit`（归因依据）
- `learning-lesson-distiller`（可选）
- `learning-proposal-generator`（可选）

### Boss Secretary 集成
```yaml
# 路由关键词
keywords:
  - "数据分析"
  - "趋势图"
  - "阻力分析"
  - "校准建议"
  - "雷达图"
  - "图表展示"
  - "可视化"
  - "Dashboard"
  - "MA/EMA"
  - "阻力分解"
  - "episode分析"
```

### 约定
- 不直接改变门禁与下单
- 只提供可校准的统计证据与图谱清单

## ⭐ 宪法地位（v1.1新增）

> **数据分析部门 = 系统的眼睛，是"没有调查就没有发言权"的具象化执行者**

### 宪法要求
根据系统最高指导宪法第一章，数据分析部门必须：

1. **维护趋势连续性**（对应发展论）
   - 日线MA/EMA是本质判断工具
   - 4H MA/EMA是时机选择工具
   - 必须标注"当前在趋势的哪个阶段"

2. **提供阻力分解**（对应矛盾论）
   - 识别阻力最小方向
   - 分解各项阻力来源
   - 判断趋势是否顺畅

3. **支撑复盘验证**（对应真理观）
   - 每个顾问建议的"假设验证"
   - 提供统计证据
   - 追踪假设是否成立

### 决策链位置
```
交易决策流程（必须）：
Step0 → Step1/2 → ⭐数据分析审核（日线趋势）→ Step3评分 → Step4执行 → Step6 Gate → Step7固化

数据分析审核要点：
- 日线趋势方向
- 阻力最小方向
- 当前在趋势的哪个阶段
- 决策方向是否与趋势一致
```

## Fail-Closed
- 若 episode_series 不足以计算（例如少于 5 个点）：
  - 输出 `reason_codes` 并降级为仅列清单与建议
  - 不生成趋势/阻力数值
  - 图表渲染时显示"数据不足"提示

## ⚠️ 审计记录 (2026-04-19)

### 问题: Dashboard数据100%为假（已修复）
- **旧文件**: `dream_data_dashboard_final.html` 使用 `Math.random()` 生成所有数据
- BTC基准价硬编码$65,000（实际$75,389，偏差-13.8%）
- 所有评分/宏观/记忆维度均为随机数
- **新文件**: `dream_data_dashboard_v4_live.html` 直接调用 OKX Public API 获取实时数据
- 技术指标(MA/EMA/RSI/ATR)基于真实K线计算
- 每个数据点标注来源（OKX/计算/Episode）

### 回测+压力测试报告 (2026-04-19 14:44)
#### 第一轮 (22/22 PASS, 等级A)
- JS vs Python技术指标一致性: MA/RSI/ATR偏差=0%, EMA20偏差<0.01%, EMA60偏差~0.2%
- 多周期×多币种回测: 5组全部PASS (BTC/ETH/SOL × 1H/4H/1D)
- 边界条件: 4组全PASS (20/60/100/200根K线)
- API基础压力: 连续10次0错误(平均207ms), 6路并发0错误(344ms总)
- Episode数据验证: 最近5个Episode全部在合理范围内

#### 第二轮 (7/8 PASS, 等级B)
- 连续30次刷新: 0错误, 平均199ms, P99=406ms, 价格漂移0.004%, EMA20标准差0%
- 并发压力(5路×3轮+重试): 27请求, 首次失败0, 重试后失败0 (23.7req/s)
- 速率限制(无间隔20次): 0触发 (OKX公网API对ticker接口较宽松)
- 数据完整性: 时间单调✅ OHLC逻辑✅ 成交量非负✅ 无极端跳变✅
- 历史范围: 15m/1H/4H/1D 全部精确
- 唯一WARN: 请求一致性在并发场景下偶现false negative (非数据源问题)

### 数据管道断裂问题（部分修复）
- `renderer.py` 设计正确但从未被自动化脚本调用
- `dream_kline_analysis.py` 真实但孤立，未与Dashboard集成
- 5个HTML图表(trend_chart.html等)是4月18日用模拟数据生成的一次性产物
- **已修复**: Dashboard v4_live加入API重试机制(指数退避)
- **待修复**: 脚本Step2.5应实际调用renderer.py刷新图表

### 宪法合规
- §2.3: 只检查文件存在性不验证数据真实性 → 需加强数据验证
- §2.4: 复盘引用的趋势报告可能是假数据 → 已替换为真实API版本

## 后续计划
- [ ] analyzer.py: 核心分析逻辑
- [ ] templates/: HTML 模板目录
- [ ] 支持静态图片导出 (Chart Image Skill)
- [ ] 支持 PDF 报告生成
- [x] **P0**: Dashboard连接真实OKX API (v4_live.html, 2026-04-19)
- [ ] **P1**: 脚本Step2.5调用renderer.py刷新图表
- [ ] **P2**: Episode JSON包含完整价格序列供趋势分析
- [ ] **P3**: 数据真实性验证（签名/校验）


---

## 邮件投递规范（宪法§12强制）

> **⚠️ 宪法§12规定：本部门完成工作后，必须将工作总结写入指定邮箱目录。没有投递 = 工作未完成。**

### 投递配置

| 项目 | 值 |
|:---|:---|
| **部门名称** | 数据分析部 |
| **目标邮箱** | 秘书汇总邮箱 (secretary) |
| **邮箱路径** | `~/.workbuddy/skills/boss-secretary/reports/` |
| **投递方式** | 直接复制/写入Markdown文件到指定目录 |
| **投递命令** | 直接写入文件到 `~/.workbuddy/skills/boss-secretary/reports/<文件名>.md` |

### 投递工作流

```
1. 本部门完成工作（自动化任务/手动触发）
2. 整理工作总结（Markdown格式）
3. 确定优先级: P0(紧急)/P1(重要)/P2(观察)/P3(正常)
4. 执行投递命令
5. 确认邮件ID返回 → 投递完成
```

### 代码入口

- **投递方式**: 直接写入Markdown文件到指定邮箱目录
- **查看邮箱**: `ls ~/.workbuddy/skills/boss-secretary/reports/`
