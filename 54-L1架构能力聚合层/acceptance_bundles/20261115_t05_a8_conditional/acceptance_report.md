# T0.5/A8 条件前瞻分布五维验收报告

## 基本信息

- 验收对象：R02 PIT 全桶分布与 p10/p90、复用 I30 滚动波动率、A8 h=1 默认 4 桶及 4→2 降级、D-E13 profile/schema/text 扩展、D-E02 manifest+executor。
- 验收时间：2026-11-15 02:15:51 CST（Asia/Shanghai）。
- SPEC 依据：`SPEC-54-延续性统计分析模块.md` §8 T0.5 行；`docs/TECHNICAL_DESIGN.md` D-E02/T0.5 描述。
- 执行边界：仅本地验收与 `acceptance_bundles/20261115_t05_a8_conditional/` 产物；未修改生产代码、测试或文档 SSoT，未提交、未部署、未连接云端或生产 DB、未执行生产写入。

## 五维证据矩阵

| 维度 | 状态 | 证据 | 判定 |
|---|---|---|---|
| 症状复测 | ✅ | `repro_after.log:8-15`：以 tests 同风格 `random.Random(5)` 生成 1600 个价格与 ISO 日期，实际调用 `run_capability("D-E02")`，exit=0 | `gate=ok`、`requested_buckets=buckets=4`、`pit=true`、`h=1`、`as_of=2028-05-18`；当前桶 `effective_n=nonoverlap_n=329`，mean/median/p10/p90 均非空 |
| 日志证据 | ✅ | `repro_after.log:9-14`：D-E02 返回 `state_method=I30`、`method=R02`、quality=good、degraded_reason=null，并输出全 4 桶指标及 80% 历史区间文本 | SPEC→I30/R02→D-E02 executor→运行输出链完整；4 桶 nonoverlap_n 分别为 366/330/329/305，全部 ≥250；每桶 effective_n、mean/median/p10/p90 均非空且 p10≤median≤p90 |
| 回归测试 | ✅ | `test.log:4-35`：要求的原始命令 `python3 -m pytest tests -q` exit=0；同范围去除继承的重复 `-q` 后显示完整摘要 `671 passed in 4.88s`、exit=0。`test.log:50-55`：audit R02/I30 为 2/2、exit=0 | 全量 671 项通过，无 fail/error/skip；R02、I30 的 meta/gate/determinism/synthetic/null/reference 全通过 |
| 影响面 | ✅（有基线警告） | `fix.diff` 共 4197 行、9 个 `diff --git` 段，仅含指定的 9 个路径；未纳入其他并行改动 | 路径范围符合要求。9 个目标均为 untracked，因此采用逐文件 `git diff --no-index /dev/null <path>` 留存整文件新增差异，未暂存或清理用户改动 |
| 边界验证 | ✅ | `test.log:37-48`：指定 5 个测试独立复跑，`5 passed in 1.84s`、exit=0 | 4 桶、4→2、短样本、future_rows、release_ts 五类边界全部通过，详见下节 |

## 边界与扩展契约明细

1. **4 桶门禁**：`test_a8_conditional_distribution_uses_four_pit_buckets` 验证 D-E13 `build_profile` 的 A8 使用 I30/R02、h=1、默认 4 桶、PIT/as_of、当前与全桶 p10/median/p90，以及每桶 nonoverlap_n≥250。
2. **4→2 降级与文本披露**：`test_a8_conditional_distribution_degrades_four_to_two_buckets` 验证 `degraded_reason=bucket_nonoverlap_lt_250`、2 桶仍满足门禁、profile 文本披露“降为 2 桶”，且无“将会/预计/必然”。
3. **短样本独立门禁**：`test_a8_short_sample_has_independent_gate` 验证 A8 返回 `insufficient_samples`，且不 retroactively 改变 A1–A7 的 good 质量语义。
4. **PIT 未来行隔离**：`test_r02_pit_future_rows_do_not_change_as_of_result` 验证 as_of 之后的极端价格和指标不改变既有结果。
5. **release_ts 可见性**：`test_r02_pit_release_ts_controls_visibility` 验证指标只有在 release_ts 到达后才进入 PIT 可见样本。
6. **schema/manifest/executor**：全量 671 项包含 `test_profile_matches_schema`、D-E02 manifest 可执行性及 D-E02 输出 schema 测试；D-E13 扩展与 D-E02 出口均随全量回归通过。

## 红旗与证据限制

- **无功能性红旗**。
- ⚠️ **未跟踪基线**：验收时 9 个目标路径均显示 `??`，常规 `git diff -- <9 paths>` 为空。`fix.diff` 因而不是相对已提交基线的最小增量，而是 9 个整文件新增 diff；可核查路径边界，不能据此断言每行都属于本次 T0.5/A8 变更。
- ⚠️ **文档状态漂移**：指定 SPEC/TECHNICAL_DESIGN 的 T0.5 行仍保留 `⬜` 或“未接线”状态描述，与本次 manifest+executor 实测已接线存在状态差异；按任务约束未修改文档 SSoT。
- 全量套件中的本地真实库冒烟用例使用已存在的本地 `19-数据访问层/data/dreambuddy_core.db` fixture，`l1agg/align.py` 以 SQLite `mode=ro` 只读访问；未访问云端/生产 DB。D-E02 复测仅使用内存合成数据，A8 边界使用 pytest `tmp_path` 临时 SQLite。

## 验收结论

**PASS**：症状复测、日志证据、全量回归、限定影响面与五类边界均取得新鲜 exit=0 证据；全量 **671 passed**，目标边界 **5 passed**，方法审计 **2/2 passed**。上述两项警告不否定本次功能运行结论，但保留给后续提交基线与文档同步处理。
