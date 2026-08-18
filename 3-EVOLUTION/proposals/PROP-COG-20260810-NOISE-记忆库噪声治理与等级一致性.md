# PROP-COG-20260810-NOISE — 认知记忆库噪声治理与等级一致性提案

- 状态: **PENDING**（governance 审批，等人，不自动执行）
- 提出: cognitive-daily-monitor cron（2026-08-10 10:00 巡检）
- 范围: `4-MEMORY/9-工具与接口/` 的 record/distill 路径（认知逻辑变更，不涉交易策略/参数）

## 一、问题实证（2026-08-10 巡检发现）

### P1 timeout 解决路径噪声（占库容 54%→清理后仍 36%）
- 63 条记忆中 34 条为 `[解决路径] ... 结果: timeout` 模式，其中 15 条为**跨会话完全相同内容**的重复（本次已去重）。
- 根因：会话结束钩子对 timeout 结束且无实质产出的会话仍记录解决路径；"任务涉及 1 个文件 | 修改了 1 次文件 | timeout" 类条目零信息量。
- 危害：污染 recall top_k（CLAUDE.md 已警告 98% C 级噪声问题），稀释高价值条目命中率。

### P2 去重失效
- 相同内容（内容哈希后缀相同，如 `-188821b3`×12、`-1eb5692d`×5）在不同会话重复入库，说明 record 路径的去重仅覆盖短窗口/单会话，未做历史内容查重。

### P3 等级-置信度不一致（record 路径系统性缺陷）
- `cognitive_mcp_server.py::_handle_record` 硬编码 `confidence=0.3` 且原样接受任意显式 `quality_level` → 产生 S@0.3、A@0.3、B@0.3 等违反 CLAUDE.md 质量区间（S≥0.95/A≥0.70/B≥0.40）的条目。本次巡检发现并校正 8 条。
- 后果：recall 的 min_quality 过滤按等级排序时，未验证的 A@0.3 会压过真实验证的 B@0.6。

## 二、修复方案（待审批）

### F1 噪声过滤（改 cognitive_session.py / cognitive_hook.py 的会话结束记录逻辑）
```
if outcome == "timeout" and 无实质文件产出 and 无验证结论:
    skip 解决路径记录（或降级为计数器累计，不入 memories 表）
```

### F2 历史内容去重（改 record 入口）
```
record 前对 content 做哈希，命中 memories 表已有哈希 → 不新增，
改为对已有条目 verify(success=true) 计数 +1（重复出现=重复佐证）
```

### F3 等级一致性（改 cognitive_mcp_server.py::_handle_record）
```
level = _calculate_quality_level(confidence=0.3, verify_count=0)  # 引擎双门槛
# 或：按请求等级赋初始置信度带中值（S→0.95/A→0.7/B→0.4），再让 verify 爬梯
```
以 bayesian_memory_updater 的 `_calculate_quality_level` 为唯一事实源，禁止等级与置信度脱钩入库。

### F4（次要）tags 参数容错
`_handle_record` 对 `tags` 接受 list 或 comma-string 两种形态（当前 list 输入抛 AttributeError）。

## 三、验证计划（批准后）
1. 单元测试：stress_test_cognitive_noise_filter.py 扩展 F1/F2/F3 用例。
2. 回归：test_cognitive_session.py / test_rigorous_bayesian.py 全绿。
3. A8 校验：跑一周后统计 timeout 噪声占比 <10%、等级-置信度不一致条目 = 0。

## 四、红线自查
- 不涉及交易策略/参数 → 无需回测基线对比（v15-six-trading-20260601 不触发）。
- 不绕过 cognitive_backtest.py：若审批方认为 F1 属机制变更，可先跑 A/B 重放 path_advantage≥+0.2 门禁。
- 稳定优先：本提案仅降噪与一致性，不改变贝叶斯更新/蒸馏/反刍的核心数学。
