# PROP-20260810-SCHEDULER-PATHS: DreamOS 调度器回测/优化子进程路径可移植化修复

- **提案ID**: PROP-20260810-SCHEDULER-PATHS
- **类型**: trading（涉及编排记忆管线 → A层节点选择 → 交易路径）
- **创建时间**: 2026-08-10 09:15 UTC
- **状态**: ✅ IMPLEMENTED_VERIFIED（2026-08-10；重启后 0 次路径错误 vs 旧进程 19 次）
- **提交方**: dreamos-daily-monitor cron（每日监控七步闭环 第2步 Bug修复）

---

## 背景与问题

`1-ARCHITECTURE/dreamos/cli/scheduler.py` 中 `backtest_evaluation`（每6h）与
`orchestration_optimize`（周一03:00）两个 job 的子进程调用硬编码了 macOS 路径：

- 解释器: `/opt/anaconda3/bin/python3`
- 工作目录: `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE`

本机为 Linux（`/home/ubuntu/Dreambuddy-V2-main`），两条路径均不存在。

**故障证据**（scheduler.log）：
- `回测评估失败: [Errno 2] No such file or directory: '/Users/zhangjiangtao/...'` × 13 次（2026-08-08 22:04 起，每6h一次全失败）
- `编排优化失败: [Errno 2] ...` × 5 次
- 且 job 包装层仍记录 `Job 'backtest_evaluation' completed successfully`（假成功信号）

**下游影响**：
- `orchestration_memory.json`（A层编排记忆表）自迁移以来从未生成（日志 `编排记忆表已保存` 出现 0 次）
- 所有场景编排恒定降级走 L3 默认 c_chain（今日 `编排记忆表不存在` 日志 744 次）
- A层"回测学习→编排优化"闭环在本机完全断路

## 修复内容（已实施，未激活）

`cli/scheduler.py`（3处，<20行，纯环境可移植化，不改 SACG 四层语义）：

1. 新增 `_ARCH_DIR = Path(__file__).resolve().parents[2]`（→ `.../1-ARCHITECTURE`）
2. `_backtest`: `/opt/anaconda3/bin/python3` → `sys.executable`；cwd → `str(_ARCH_DIR)`
3. `_optimize`: 同上

**验证**：
- `python3 -m py_compile scheduler.py` PASS
- 守护进程同款解释器（hermes venv）`python3 -m dreamos.cli.dreamos_backtester --help` 从推导 cwd 导入成功

## 为何需要审批（而非直接重启激活）

修复虽为纯环境适配，但激活后 `orchestration_optimize`（--optimize）将首次写入
`orchestration_memory.json`，使 `graph_planner` 的 L0/L1/L2 编排查询可能命中非默认链，
**影响 A层节点选择 → 交易路径**。按硬门禁「任何代码上线 → 走 trading 审批」提交。

## 激活方式（批准后）

空闲窗口（无运行中 job）重启守护进程即可；crontab pgrep 看门狗（每5min，venv）自动拉起。
避开 :05(scan_main)/:30(exit_check) cron 时点。重启后观察下一个整点 :00 的
backtest_evaluation（或手动触发）确认 `回测评估完成` 日志与退出码。

## 回退方式

`git diff` 仅涉及 scheduler.py 3 处；回退 = 恢复硬编码路径（或 git checkout）后重启。

## 附带观察（未在本提案修复）

1. job 函数返回 error dict 时调度器仍记 "completed successfully" —— 假成功观测性问题，建议后续提案处理。
2. `backtest_evaluation` job 配置 `symbols=[]` → 每次回退默认 BTC/ETH/SOL（WARNING），建议补全为与 scan_main 一致的币种集。


---

## 实施记录（2026-08-10 13:31）

实施记录: 修复代码已在磁盘（09:15写入），守护进程 PID 2749915（03:49启动，早于修复）→ SIGTERM 重启。验证: 重启后日志 macOS 硬编码路径/FileNotFoundError 计数 0，旧进程时段 19 次。
