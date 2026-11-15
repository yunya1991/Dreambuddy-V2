# L1 跨资产与同赛道比较路由歧义修复验收报告

## 基本信息

- 验收对象：4 条 `asset_class_trend` 被前置 `leader_compare` 正则误路由的问题。
- 验收时间：2026-11-15 10:04:27 CST。
- 验收人：AI。
- 关联 commit：未提交（用户未要求提交）。
- 根因：`leader_compare` 先于 `asset_class_trend` 匹配，并覆盖宏观资产词与比较词组合；排除条件还必须从字符串起始位置评估，避免搜索起点后移绕过。
- 修复：Python/TypeScript 双端在 `leader_compare` 上增加带起始锚点的跨资产让位条件；只排除后续 `asset_class_trend` 已能命中的组合，不产生空路由。

## 五维证据矩阵

| 维度 | 状态 | 证据 | 备注 |
|------|------|------|------|
| 症状复测 | PASS | `repro_after.log` 第 2-5 行，4 条原始消息均 `actual=asset_class_trend pass=True` | 与修复前同一 golden 测试路径复测，最终 378/378 |
| 日志证据 | PASS | `repro_after.log` 含 8 条可 grep 的 `observed` 行及 `summary total=8 passed=8` | 直接执行 `l1_route_signal.detect_intent`，非静态推断 |
| 回归测试 | PASS | `test.log`：golden 378/378、Python 路由 41 项、41 意图 35 项、TypeScript 18 项，所有命令 `exit=0` | 无 SKIP、ERROR 或 FAIL |
| 影响面 | PASS | `fix.diff`：4 个 tracked 代码/测试文件，15 行新增、1 行删除 | 另有本任务前已 untracked 的 SPEC 仅同步状态；无依赖、数据库、云端变更 |
| 边界验证 | PASS | `repro_after.log` 第 6-9 行：两条同赛道比较仍为 `leader_compare`，既有 ETH/BTC 强弱仍为 `asset_class_trend`，无关消息仍为 unknown | 4 条边界全部符合预期 |

## Calibration 证据

- 命令：`python3 scripts/calibrate_intents.py --skip-roc --json /tmp/spec41_l1_calibration_after.json`。
- 结果：15/15 个有向量意图通过 calibration。
- `asset_class_trend`：21 条正例，TPR=100.0%；80 条反例，FPR=0.0%。
- `path_insight`：TPR=95.7%，仍满足 ≥95% 门禁。
- 无向量且无正例的 `calendar_event`、`whale_flow` 仍按既有报表显示 FAIL，不计入 15 个有向量意图通过率。
- uplift 仍受 golden set 正则 100% 覆盖的结构性限制，不据此执行向量裁剪。

## 红旗清单

- 无。

## 验收结论

- [x] 五维全通过，验收通过。
- [ ] 有红旗，验收不通过。

## 签字

- AI 验收：2026-11-15。
- 用户确认：可选。
