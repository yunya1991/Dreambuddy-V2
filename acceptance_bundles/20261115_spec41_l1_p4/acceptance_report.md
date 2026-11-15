# SPEC-41-L1 P4 验收报告

## 基本信息

- 验收对象：执行器文档按需 retrieve + 两项扩展可行性评估
- 验收时间：2026-11-15 05:54 CST
- 验收人：AI
- 关联 SPEC：41-文件索引系统/SPEC-41-L1语义意图检索增强-v1.0.md §2.3/§4.4/§6.5/§7

## 五维证据矩阵

| 维度 | 状态 | 证据 | 备注 |
|---|---|---|---|
| 症状复测 | 通过 | repro_after.log 第 1-23 行 | 21/21 注册意图 found=True、degraded=False，executor_doc 字符数均非零 |
| 日志证据 | 通过 | repro_after.log observed 标记 | SPEC §4.4 → IntentDocRetriever → 实际运行 → found/doc_chars/examples/negatives 非空指标 |
| 回归测试 | 部分通过 | test.log | 41 意图 35 项 exit=0；34 路由 39 项 exit=0；golden 374/378，4 个既有失败 exit=1 |
| 影响面 | 通过 | fix.diff | 改动限定在 41 SPEC/检索器/生成器/测试/预研及本验收包；L1 注册表和 l1_route_signal.py 未改 |
| 边界验证 | 通过 | test.log boundary exit=0 | 11 项覆盖缓存、非法 intent、目录/文档缺失、损坏 JSONL、非法 UTF-8 和 21 注册意图覆盖 |

## 边界明细

- 空字符串、路径穿越、非法分隔符 intent：返回 invalid_intent_id，不读取路径。
- 单元目录或 executor.md 缺失：显式 found=False、degraded=True。
- JSONL 单行损坏：保留有效行并报告文件与行号。
- executor.md 非法 UTF-8：安全降级，不向上抛异常。
- 同实例重复 retrieve：使用已加载缓存。

## 红旗清单

- golden set 仍有 4 个 asset_class_trend 标注被 leader_compare 正则优先命中：纳指和BTC谁强、黄金和原油表现对比、加密货币和黄金走势对比、美股/黄金/加密对比。这是 P2/P3 已记录的正则优先级/标签歧义，P4 未修改注册表或正则，失败数量未增加。

## 验收结论

- [x] P4 声明范围验收通过：按需 retrieve 链路可用，两份预研报告已交付，相关回归与边界测试通过。
- [ ] 全量 golden 全绿：保留上述 4 个既有失败，需另开正则/标注校准任务，不在 P4 擅自扩 scope。

## 签字

AI 验收：2026-11-15  
用户确认：待确认（可选）
