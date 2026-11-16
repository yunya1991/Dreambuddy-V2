# G-IF2 冻结与真实数据前端联调验收报告

## 基本信息

- **验收对象**：G-IF2 `lights[]` 行/轴 Schema、四轴强度、行级合成与阈值消费口径冻结；D-E19 与 T2（D-E15、D-E10、D-E16）真实数据前端联调。
- **验收时间**：2026-11-16 02:53 CST。
- **验收人**：AI；真实只读快照、真实 Python 脚本、真实 Next API 与浏览器渲染联合验收。
- **代码基线**：`e52c5fdfdc fix(memory): P0 修复向量索引失联与记忆淘汰前提`；本轮变更尚未提交。
- **运行边界**：本地只读数据；隔离 Next dev 实例 `127.0.0.1:3011`；`L1_ARTIFACTS_ENABLED=0`。未写生产表，未进入 L-SIGNAL，未 commit/push/deploy。

## 验收目标与通过标准

1. 冻结公开契约，不允许前端另造轴强度、标定阈值或方向语义。
2. `/api/visual/overview` 使用真实数据返回非空 D-E19/T2 产物，Schema、hash 与行级公式校验通过。
3. 浏览器实际呈现 D-E19、阈值分色、缺轴降级和三条 T2 曲线，图种切换可用。
4. 后端全量回归、前端组件回归、TypeScript 检查和显式边界测试均以 exit code 0 结束。
5. 五维证据与四文件验收包完整，范围外问题如实披露。

## G-IF2 冻结结论

契约主文档为 TD v2.65 §7.5 B-1A/B-2A、§7.11，SPEC 同步至 v0.17。

- **行级 Schema**：`lights_row` 为封闭对象，11 个必填字段为 `symbol/class/as_of/axes/strength/summary/light_weights_hash/n/min_rows/status/flags`；不新增行级 `state/bucket`。
- **轴级 Schema**：`lights_axis` 5 个必填字段为 `state/strength/bucket/evidence/flags`；四轴固定为 `trend/inertia/cycle/foresight`，五态固定为 `lit/warm/dim/conflict/unavailable`。
- **四轴强度**：`trend/inertia/foresight` 分别由 `axes.trend/axes.inertia/axes.coherence` 按对应 `axis_weights` 归一并 `clamp01`；`cycle=clamp01(abs(I39 cycle[-1].value)/amplitude)`。`foresight` 是 `coherence` 的展示投影，`adx` 不进入 lights 四轴，`light_weights.cycle` 不是周期归一化除数。
- **行级合成**：`strength = Σ light_weights[k] × axis_strength[k] / Σ participating light_weights[k]`；缺失轴剔除后按剩余权重重新归一，不补零。
- **唯一标定口径**：统计对象为行级合成强度；45 个 `as_of` 快照、303 个有效行；`lit_pct=p70=0.764706`，`warm_pct=p40=0.572400`。禁止用四轴池化分位回写；`0.70/0.40` 仅为后端配置缺失或非法时的最终兜底。
- **消费边界**：标定取行级 `strength`；后端 `_classify` 逐轴分档；前端强度条按行级 `strength` 分档。两处消费同一组 `meta.thresholds`，不承诺各轴自然呈现相同 p70/p40 比例。前端不得写死阈值或自行重算；阈值缺失时强度条置灰。
- **方向边界**：`band/flags` 仍由 `direction_rule.decide()` 唯一生产；信号链保持 `rule_inputs.build_inputs(...) → direction_rule.decide → handoff`，`lights[]` 不直接作为方向规则入参。

## 五维证据矩阵

| 维度 | 状态 | 证据 | 判定说明 |
|---|---|---|---|
| 症状复测 | PASS | `repro_after.log:773-787`；`browser_lights.png`、`browser_d_e15.png`、`browser_d_e16.png` | 真实 API HTTP 200；D-E19 12 行实际渲染，阈值分色和 2 个不可用轴可见；D-E15/D-E10/D-E16 均完成真实图种切换与渲染。 |
| 日志证据 | PASS | TD v2.65 §7.11；SPEC v0.17；`repro_after.log:775-783` | SPEC→代码→真实脚本/API→非空 `acceptance_metrics` 链路完整；12 行、48 个轴、三条 T2 点数、阈值和 hash 均非空；Schema/强度校验最终 PASS。 |
| 回归测试 | PASS | `test.log:33,50-72` | 54-L1 后端全量 `backend_full_exit=0`；前端最终 2 suites / 6 tests 全绿；`tsc --noEmit` exit=0；显式后端边界 `backend_boundary_exit=0`。 |
| 影响面 | PASS | `fix.diff:1,45,87,135,148,245`；`git apply --stat` | 本轮归档 diff 仅 6 个声明内文件，102 insertions、19 deletions；未混入 `visual_overview.py`、记忆系统或其他工作流修改。 |
| 边界验证 | PASS | `test.log:55-60,71-72`；`repro_after.log:775-780,784` | 缺轴重归一、非法阈值后端兜底、`unavailable` 优先、行级标定默认口径、后端阈值缺失前端置灰、空态均有证据；真实缺轴和部分降级同时复测。 |

## 真实数据与浏览器联调结果

### 数据与 API

- 快照 `as_of=2026-11-11`，资产数 12，D-E19 返回 12 行；行状态为 `available=10`、`partial=2`。
- 48 个轴的状态为 `lit=20`、`warm=2`、`dim=24`、`unavailable=2`；整体质量为 `partial`，原因 `axes_unavailable`，未伪造缺失 cycle 轴。
- 后端阈值为 `lit_pct=0.764706`、`warm_pct=0.5724`，`thresholds_uncalibrated=false`。
- `light_weights_hash=1c0b5ce40edbf95e1869b8520a3878f12a6080cfb91e082969601df1f3154478`，所有行 hash 与 meta 一致。
- 12 行全部通过 `lights_row` Schema；三条 T2 在剥离 API 的 UI 包装字段 `id` 后全部通过纯 `visual` Schema。
- 逐行重算行级合成公式，最大绝对误差为 `4.713152945701182e-07`。
- 真实 `/api/visual/overview` 多次返回 HTTP 200，证据见 `repro_after.log:788-791`。

### 浏览器呈现

| 图种 | 实测结果 |
|---|---|
| D-E19 点亮投影 | 12 行；BTC 灰、ETH 琥珀、XAU 绿；NG 行级强度恰为 `0.764706`，按 `>= lit_pct` 显示绿色；XAG/NG 缺 cycle 轴显示不可用，页面显示部分降级。 |
| D-E15 价格与 EMA26 | 195 点，原始线与 EMA26 线共 2 条。 |
| D-E10 回撤路径 | 195 点，1 条回撤曲线。 |
| D-E16 加权聚合曲线 | 293 点，原始线与 EMA26 线共 2 条，另有 293 段逐点覆盖度带。 |

`/api/trading-ranking/today` 返回 503 时，页面仍保持默认资产池和真实图表，符合 FAIL-OPEN 设计；该 503 不计为 D-E19/T2 渲染失败。

## 回归与边界明细

- 后端全量：FactorAnalysis/statsmodels 有既有收敛警告，但测试最终 exit=0，无失败。
- 前端最终回归：
  - VisualWorkbench：首屏后端图表、图表服务失败降级，共 2 项通过。
  - LightsView：五态展示且无方向词、后端标定阈值分色、阈值缺失置灰、空态，共 4 项通过。
- 后端显式边界：缺轴重归一、非法阈值回退、`unavailable` 优先、标定 CLI 默认 `--aggregate row`，合计 6 项通过。
- 空态的计分证据仅来自组件测试；未把未生效的浏览器网络 mock 计为通过。

## 影响面清单

`fix.diff` 仅包含：

1. `3.1-FRONTEND/src/components/visual/LightsView.tsx`
2. `3.1-FRONTEND/src/components/visual/__tests__/LightsView.test.tsx`
3. `54-L1架构能力聚合层/SPEC-54-L1交易层.md`
4. `54-L1架构能力聚合层/contracts/capability_result.schema.json`
5. `54-L1架构能力聚合层/docs/TECHNICAL_DESIGN.md`
6. `54-L1架构能力聚合层/scripts/calibrate_light.py`

前端逻辑变化限于透传并消费后端 `meta.thresholds`；标定算法、公开 Schema 结构、`direction_rule`、handoff 和 L-SIGNAL 均未改。

## 红旗清单

本轮验收范围内无阻塞红旗。

## 非阻塞警示与范围外观察

1. **原 3001 Next dev 缓存故障**：验收时页面因 `.next` 缺少 `use-sync-external-store` vendor chunk 返回 500。为遵守未提交工作区与其他并发修改边界，未清理、未重启原 3001 服务，改用 `/tmp` 隔离源码快照在 3011 端口完成真实联调。
2. **浏览器空态 mock 未生效**：`network route --abort` 与精确 URL body mock 均未替代真实响应；已 `unroute` 并恢复 12 行真实数据。空态只按组件测试 PASS 记录，不宣称浏览器空态已验证。
3. **控制台环境警示**：Next HMR `handleStaticIndicator` 有 `components` TypeError，TokenMonitor 有 401；二者未阻断本轮真实图表渲染，但不据此宣称相关环境功能正常。
4. **首次 Schema 校验器失败已保留**：`repro_after.log:7,771` 记录 API 的 UI 包装字段 `id` 被送入纯 `visual` Schema 而失败。校验器修正为先剥离 `id`，业务数据与 API 未改；最终 `real_data_acceptance_exit=0`，见 `repro_after.log:772-783`。
5. **D-E18 范围外观察**：扩展校验曾发现既有 D-E18 `dataset.meta` 与纯 `visual` Schema 不兼容。本轮范围仅为 D-E19/T2，未修改该实现，也不将其误记为本轮失败或通过项。

## 验收结论

- [x] 五维证据全部通过。
- [x] G-IF2 公开契约已冻结，真实脚本、API、Schema、行级公式与浏览器渲染一致。
- [x] D-E19 与 T2 真实数据前端联调验收通过。
- [x] 四文件验收包完整，三张浏览器截图作为支持证据归档。
- [x] 本轮不自动进入 L-SIGNAL，不自动提交、推送或部署。

## 签字

- **AI 验收**：2026-11-16，PASS。
- **用户确认**：待确认（可选）。
