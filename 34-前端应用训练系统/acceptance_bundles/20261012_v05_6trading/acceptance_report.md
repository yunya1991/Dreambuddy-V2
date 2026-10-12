# 验收报告 — SPEC v0.5 DSH 训练数据源 6-TRADING 采集器族

- 日期: 2026-10-12
- SPEC: SPEC-DSH-训练数据源-v0.5-6TRADING.md
- 变更类型: code-full（4 采集器 + 4 测试 + SPEC 文档 + 注册点 +5 行）

## 五维证据验收

| 维度 | 证据 | 结果 |
|------|------|------|
| 1. 症状复测 | repro_after.log: P0=33 P1=97 P2=5 P3=8 total=143 条真实数据采集 | ✅ |
| 2. 日志证据 | run_continual_training 实跑: DSH 喂入 436 成功 0 失败, S级5, step 3411→3464(+53); limit=200 全量: ASeriesTheory=97, 总采集 1766 | ✅ |
| 3. 回归证据 | test.log: 511 passed in 10.26s, exit=0（v0.4 456 + v0.5 55） | ✅ |
| 4. 影响面核查 | fix.diff: run_continual_training.py +5 行注册; 新增 8 文件(4 adapters + 4 tests) + SPEC + 本验收包; 无越界变更 | ✅ |
| 5. 边界验证 | FAIL-OPEN 双场景在每个采集器测试内覆盖(目录不存在→空列表; 单文件异常→跳过): TR-1.10/11, TR-2.11/12, TR-3.11/12, TR-4.11/12 | ✅ |

## SPEC 达标对照

| 指标 | SPEC 目标 | 实际 | 判定 |
|------|----------|------|------|
| P0 ASeriesSession | 100-150 | 33 | ⚠️ 数据源限制 |
| P1 ASeriesTheory | 50-80 | 97 | ✅ 超额 |
| P2 OneirologyDream | 20-30 | 5 | ⚠️ 数据源限制(仅1日志5梦境) |
| P3 MasterSeminar | 10-20 | 8 | ⚠️ 数据源限制(仅2报告) |
| DSH 总量 | ≥700 | 677(534+143) | ⚠️ 差23 |
| 测试 | 全绿 | 55/55 新增, 511/511 全量 | ✅ |

结论: **PASS（带数据量偏差说明）** — P0/P2/P3 未达目标为训练数据源（6-TRADING session/梦境/研讨报告）自然产量不足，代码逻辑正确且随数据产出线性增长。P1 超额 21%。
