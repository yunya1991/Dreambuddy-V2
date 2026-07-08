# L2 Shortterm 入口映射

## 职责

- 承接短周期 episode 反馈，更新 bandit 状态与审计。
- 提供短期一致性与健康分巡检。

## 调用映射

- `run_l2_shortterm_feedback(...)` -> `MemoryEngine.update_bandit_from_episodes(...)`
- `run_l2_shortterm_health_check(...)` -> `MemoryEngine.check_consistency() + get_health_score()`
