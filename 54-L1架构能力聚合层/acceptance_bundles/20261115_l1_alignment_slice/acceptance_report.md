# 54-L1 D-E12/R18 时空对齐切片验收报告

## 基本信息

- 验收时间：2026-11-15
- 验收对象：D-E12/R18 能力接线、FAIL-OPEN 降级、manifest 真实执行覆盖及 SPEC/TECHNICAL_DESIGN/METHOD_LIBRARY/RESEARCH 文档对齐
- 规划依据：`SPEC-54-L1架构能力聚合层.md` v1.9 §3.5/§11.4/§17；`docs/TECHNICAL_DESIGN.md` v2.12 §2.4/§6；`docs/METHOD_LIBRARY.md` v1.14 §14/S7
- 关联 commit：本地提交前验收；上一轮交付基线为 `b8228e8a11`
- 数据边界：仅本地合成样本与 pytest；未访问或写入云端生产库，未修改任何生产表

## 五维证据矩阵

| 维度 | 状态 | 证据 | 备注 |
|---|---|---|---|
| 症状复测 | PASS | `repro_after.log:2` 为 `observed=D-E12.good`，`:6` 为 `exit=0` | 真实 `run_capability("D-E12")` 返回 good、`sample_n=30`、窗口 `2024-01-11~2024-02-09`，BTC/ETH 末值分别为 139.0/128.0 |
| 日志/运行证据 | PASS | `repro_after.log:1-5` 形成 SPEC→executor→运行→非空 metrics 链 | 输出包含 `methods=["R18"]`、`daily_last+ffill`、UTC、stale 上限 3 天和两条非空资产窗口行，不是只检查调用是否报错 |
| 回归测试 | PASS | `test.log:13` 为 8 项目标/边界测试通过；`:440` 为 `698 passed`；`:14`、`:26`、`:29`、`:33`、`:35`、`:425`、`:427-428`、`:441` 各 exit 均为 0 | 全量 54-L1 回归、ruff、black、py_compile、全量 audit 与 diff check 均通过 |
| 影响面 | PASS | `fix.diff` 对应 8 个实现/测试/配置/文档/audit 文件；四文件验收包单独归档 | 未纳入 `11/`、`18/`、`23/`、`41/`、`43/runtime`、`48/`、`50/`、`54/reports` 等无关改动 |
| 边界验证 | PASS | `repro_after.log:3-5`；`test.log:8-14` | 覆盖历史不足、空窗口、跨源同日去重、隔日 ffill/stale、R18 确定性及空输入门禁；异常路径均安全返回 empty |

## 覆盖率与 audit

- `test.log:37`：`implemented=386 passed=386 failed=0`。
- 验证覆盖率：66.15%，`executed=1028`、`not_applicable=762`、`missing=526`。
- `passed` 仅表示已执行检查通过，不等同于完整验证覆盖；缺失覆盖继续如实披露。

## 红旗与限制

- 无功能性红旗。
- D-A14/F26 仅交付固定权重 `score/components/weights/n`；`level` 阈值未冻结，本轮未自行发明阈值，未宣称 D-A14 完整交付。
- 本地验收使用合成样本；MERS 全量真实数据验收与生产周期任务仍须在云端唯一生产写入口执行。
- S5 对外推荐保持关闭；本轮未修改方法层 R18 数值口径。
- `fix.diff` 不包含验收包自身，避免自引用；四文件验收包随本轮变更一并归档。

## 验收结论

**PASS**。五维证据齐全，D-E12 真实入口产生符合契约的非空指标，样本不足与空窗口显式降级，全量回归和静态检查通过，影响面受控。

AI 验收：2026-11-15
用户确认：可选
