# 验收报告 — D3 Worker 拉起器 W4 收口

## 基本信息

- 验收对象：方案 B（`InProcessSessionExecutor`）+ 可观测（`metrics.json`）+ 运维 CLI + systemd unit
- 技术文档：`46-DSH架构/docs/tech/PROPOSAL-P0-D3-WORKER-LAUNCHER-v0.1.md` v0.5（§4.8/§4.9/§4.15/§4.16/§6/§7）
- 验收时间：2026-11-13 01:30-01:35（CST）
- 验收人：AI（证据驱动）
- 关联 commit：未提交（工作区改动）

## 一、SPEC → 代码 → 运行 → 输出 追溯链

| # | SPEC 功能定义 | 代码落点 | 运行方式 | 输出证据 |
|---|---|---|---|---|
| F1 | §4.15 单运行时多会话 `run_batch` | `core/inproc_session_executor.py:74` | 真实 `dsh`（stub LLM，额度受限） | `repro_after.log`：`host_pid=26786`，2 个不同 `session_id`，均 `done`，1662ms |
| F2 | §4.15 拉起器批路径 + 单任务兼容 | `core/worker_launcher.py`（`_execute_batch` / `run_batch` 探测） | `pytest` 批执行器用例 + CLI `once` | `test.log` exit 0；`cli_chain.log` `executed=1` |
| F3 | §4.16 指标：计数/P50/P95/成功率/在途峰值 | `core/worker_launcher_metrics.py` | CLI `once` ×2 → `status` | `cli_chain.log`：`passes=2`、`role_rejections=1`、`success_rate=0.5`、`latency_ms` 非空 |
| F4 | §4.16 运维 CLI 与退出码 | `core/worker_launcher_cli.py` | `preflight` / `once` / `status` / `run`（锁占用） | `cli_chain.log` exit=0/0/0；`boundary.log` `run_exit=3` |
| F5 | §4.16 systemd unit + env | `deploy/dreambuddy-worker-launcher.service`、`deploy/worker-launcher.env.example` | 静态校验（云端不可达） | `fix.diff` 新增文件；`ExecStartPre/ExecStart` 与 CLI 一致 |
| F6 | 文档与实现对齐 | PROPOSAL-P0-D3 | 逐条比对 | 修正 3 处：§4.9 启动前检查口径、附录目录、附录 systemd 命令 |

## 二、五维证据矩阵

| 维度 | 状态 | 证据 | 备注 |
|---|---|---|---|
| 症状/功能复测 | ✅ | `repro_after.log` 第 2 行 `observed=run_batch_returned`；末行 `observed=single_runtime pids=[26786] sessions=2 all_done=True` | 与 W4 结论一致（此前 pid 24062） |
| 日志/输出证据（强制） | ✅ | `cli_chain.log` 的 `metrics.json` 含非默认值；`status` 派生视图 | 功能验收口径：非空、非默认 metrics |
| 回归测试 | ✅ | `test.log`：`pytest_exit=0`（1132 collected）；`ruff_exit=0` | 全量 `tests/` |
| 影响面 | ✅ | `fix.diff`：12 个文件（5 改 7 增），均在 `34-前端应用训练系统/{core,tools,tests,deploy}` 与 PROPOSAL 文档 | 未触碰 `router_loop.py`（A6） |
| 边界验证 | ✅ | `boundary.log` 4 场景 | 见下表 |

## 三、边界场景

| 场景 | 期望 | 实测 |
|---|---|---|
| B1 `metrics.json` 损坏 | FAIL-OPEN，status 仍可用 | `passes=0`、exit=0，不抛错 |
| B2 损坏后继续 `once` | 重建文件 | 新 `passes=1`，计数归零重启 |
| B3 双开（flock） | 第二个实例拒绝 | `already_running`，`run_exit=3` |
| B4 坏 inbox 行 | 计入 `bad_lines`，继续消费后续行 | `bad_lines=1`，ACC-4 `done`，exit=0 |
| B5 角色越权 | `failed(manual, role_violation)`，executor 零调用 | `cli_chain.log` ACC-3 回执符合 |

## 四、文档对齐修复清单

1. §4.9「启动前检查」：原文「L0 目录可读、offset 文件可写」→ 改为实现口径「花名册非空且自检通过、状态/回执目录可写、offset 可解析」。
2. 附录「建议目录」：原 `worker_launcher/` 包结构（从未实现）→ 改为实际落地的 `core/` + `tools/` + `deploy/` + `tests/` 清单。
3. 附录 systemd：原 `-m worker_launcher.preflight` / `-m worker_launcher`（不存在的模块）→ 改为 `-m core.worker_launcher_cli preflight|run`，并声明 `deploy/` 为唯一真源。

## 五、红旗清单

| 项 | 等级 | 说明 |
|---|---|---|
| 真实额度未验证 | ⚠️ | stub LLM 只证明运行时链路；P95 时延/token 成本需额度恢复 |
| A5 实跑连接计数 | ⚠️ | 仍为静态口径；`in_flight_peak`/`passes` 已就位，待 8 Worker 实跑 |
| 云端 systemd 重启恢复 | ⚠️ | unit 未在云端安装/重启验证 |
| 影子运行一周 | ⚠️ | 未开始（需常驻部署） |

以上均为外部条件依赖，非本次代码缺陷。

## 六、结论

- [x] 五维证据全通过（代码 + 本地可运行链路）
- [x] 文档与实现对齐（3 处漂移已修）
- [ ] 生产就绪（受 4 项外部条件约束，不阻塞本轮收口）

AI 验收：2026-11-13
