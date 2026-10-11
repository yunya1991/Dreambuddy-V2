# 📁 独立脚本 (scripts/)
> **用途**: 独立工具脚本，非crontab调度
> **最后更新**: 2026-10-11 | 共 17 个文件

## 离场评估器（Phase 0-3）

| 文件 | 用途 |
|:---|:---|
| [phase0_exit_evaluator.py](./phase0_exit_evaluator.py) | Phase 0 离场评估器 |
| [phase2_exit_evaluator.py](./phase2_exit_evaluator.py) | Phase 2 离场评估器 |
| [phase3_exit_evaluator.py](./phase3_exit_evaluator.py) | Phase 3 离场评估器 |
| [auto_exit_system.py](./auto_exit_system.py) | 自动离场系统 |
| [trailing_stop_runner.py](./trailing_stop_runner.py) | 追踪止损运行器 |

## 调度与验证

| 文件 | 用途 |
|:---|:---|
| [step_controller.py](./step_controller.py) | Session 步骤控制器（GATE 1+2 实现脚本） |
| [evolution_cron_runner.py](./evolution_cron_runner.py) | 进化 cron 运行器 |
| [verify_phase2.py](./verify_phase2.py) | Phase 2 验证脚本 |

## 工具与同步

| 文件 | 用途 |
|:---|:---|
| [skill_importer.py](./skill_importer.py) | Skill 导入器 |
| [sync_artifact.py](./sync_artifact.py) | 产物同步 |
| [write_health_status.py](./write_health_status.py) | 健康状态写入 |
| [review_filter.py](./review_filter.py) | 复盘过滤器 |
| [notebook_hook.py](./notebook_hook.py) | Notebook 钩子 |

## 测试

| 文件 | 用途 |
|:---|:---|
| [test_e2e_exit_system.py](./test_e2e_exit_system.py) | E2E 离场系统测试 |
| [test_strategy_exit_adapter.py](./test_strategy_exit_adapter.py) | 策略离场适配器测试 |
| [stress_test_7scenarios.py](./stress_test_7scenarios.py) | 7 场景压力测试 |
| [notebook_stress_test.py](./notebook_stress_test.py) | Notebook 压力测试 |
