# D-E05 多资产相关矩阵 TopK 验收报告

## 基本信息

- 验收时间：2026-11-15
- 验收对象：54-L1 `D-E05` 双序列补充 M03，以及多资产 M05/M06/M07 矩阵、TopK、平均相关度能力接线
- 规划依据：`docs/TECHNICAL_DESIGN.md` §0.2.2、§2.4、§6.3
- 执行入口：`capabilities.stats.correlation` / `run_capability("D-E05", series=..., dates=..., k=...)`
- 关联 commit：无（用户未要求提交）
- 数据边界：仅本地合成样本与测试；未访问或写入云端生产库

## 五维证据矩阵

| 维度 | 状态 | 证据 | 备注 |
|---|---|---|---|
| 症状复测 | PASS | `repro_after.log:1` 含 `observed=D-E05.matrix_topk ok=True n=120 pairs=6 top1=BTC-ETH:+1.000000 avg_abs_r=0.565005`，`:4` 为 `exit=0` | 原 `series` 入口 TypeError 已消失，真实 executor 返回非空矩阵榜单 |
| 日志/运行证据 | PASS | `repro_after.log:2` 含 `type=contemporaneous`、`lag=0`、`window=120`、`as_of=2024-04-29`、6 对 `pairs`、3 条 `topk`、`p_adj/q` 与 `avg_abs_r=0.565005` | SPEC→executor→实际运行→非空 metrics 链路完整 |
| 回归测试 | PASS | `test.log:12` 为 `exit=0`，`:14` 为 `collected=674` | 54-L1 全量回归；目标能力文件单独运行为 27 passed |
| 影响面 | PASS（有披露） | `fix.diff` 仅覆盖 `stats.py`、`test_capabilities.py`、`capability_manifest.yaml` | 未改 REGISTRY 数量、`research.py`、计数断言、审计计数或用户并行维护的技术文档 |
| 边界验证 | PASS | `test.log:25-28` 四项 PASSED，`:30` 为 `4 passed`，`:32` 为 `boundary_exit=0` | 覆盖单资产、完整对齐 59<60、并列/符号/乱序确定性、旧双序列短样本 |

## TDD 证据

- RED：首轮 `tests/test_capabilities.py` 有 6 项目标失败，分别为 manifest 缺 M03/M05–M07、双序列缺 Kendall、4 处多资产 `series` 入口 TypeError。
- GREEN：最小实现后同一文件 27 项全部通过；全量 674 项 exit=0。
- 排序契约：按 `|ρ|` 降序；资产名排序使绝对值并列时结果确定，负相关符号不取反。
- 对齐契约：共享位置轴逐行完整对齐，任何资产缺失/非有限值时整行剔除；不足 60 个完整对齐点返回 `status=empty`。

## 红旗与限制

- 三个实现/测试/配置文件在 git 中均为未跟踪文件，因此 `fix.diff` 是整文件新增 diff（1106 行），包含此前会话尚未跟踪的内容，不能视为仅本次 D-E05 的最小补丁。
- 多资产入口消费的是已共享位置轴的序列；不同资产各自独立时间戳轴的原始数据仍须先经对齐层处理。
- 本榜单仅为同期联动，不表达领先、因果、前瞻 IC 或样本外稳定推荐。

## 验收结论

**PASS（带未跟踪文件披露）**。五维证据齐全，无功能性红旗；未提交代码，未修改生产数据。
