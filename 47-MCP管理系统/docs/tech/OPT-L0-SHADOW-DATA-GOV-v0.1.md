# OPT-L0-SHADOW-DATA-GOV v0.1 — 影子层轨迹数据治理优化

- 状态：已落地（优化项一、二）/ 暂缓（优化项三）
- 日期：2026-11-05
- 上游依据：SPEC-L0-AGENT-COMM-SHADOW-v0.1（S0-S3）、SPEC-L0-AGENT-TRAIN-BASE-v0.1（§6.5 校准协议）

## 0. 背景与现状（2026-11-05 实测）

- 轨迹存储：`.workbuddy/agent_mail/trajectories.jsonl`，单文件 6.2MB / 19404 条，持续追加，无保留策略
- 质量分布：ok 19153（98.7%），degraded 251（1.3%），shadow 前缀 1644 条
- 训练消费：`4-MEMORY/9-工具与接口/collect_domain_discovery_data.py` 两处加载（窗口流 / Phase A 流），样本构建未过滤 degraded
- 写入端：`mcp_shells/_shared/agent_mail_shadow.py`（S3 零干扰，落盘失败静默降级）

## 1. 优化项一：轨迹滚动切分 + 冷热分层保留（已落地）

### 1.1 设计约束

- **H1（agent 迭代期间壳 diff=0）**：禁止修改 `agent_mail_shadow.py` 写入端，采用**外置轮转脚本**方案
- **§6.5 校准协议**：保留窗口不得短于影子期 ≥2 周 ≥200 条样本的取数需求
- **S3 零干扰**：轮转失败不得影响主链路，脚本独立运行

### 1.2 方案

新增轮转脚本 `mcp_shells/_shared/rotate_trajectories.py`：

1. **按天滚动**：将 `trajectories.jsonl` 中早于当日的内容移入同目录 `archive/trajectories-YYYYMMDD.jsonl`，主文件仅保留当日热数据
2. **冷热分层**：归档文件保留 14 天原文（热，供校准取数）；超过 14 天压缩为 `.zst`；超过 90 天删除（对齐 C9 job_runs 保留语义）
3. **幂等安全**：按行迁移 + 临时文件原子替换；中断重跑不丢数据、不重复迁移

调度：systemd timer 每日一次（`dreambuddy-shadow-rotate.timer`）。

### 1.3 读取端兼容

训练侧读取（`_load_shadow_trajectories`）扩展为：主文件 + `archive/` 下未过期归档文件合并读取，对上层流程透明。

## 2. 优化项二：训练侧 degraded 过滤门（已落地）

### 2.1 设计约束

- **PSI/置信度校准逻辑必须保留 degraded 消费**：`compute_real_psi_map` / `compute_real_confidence_map` 以 degraded 字段实测各域稳定态偏离度，过滤门不得作用于这两个函数的输入
- **FAIL-OPEN**：无 degraded 字段的合成轨迹不受影响

### 2.2 方案

在 `collect_domain_discovery_data.py` 新增过滤函数：

1. `filter_degraded(entries)` → 返回非 degraded 且 error_code 为空的条目，仅用于**样本构建**环节（窗口流的 `group_trajectories_by_window` 输入、Phase A 流的样本循环输入）
2. PSI/置信度计算仍用全量轨迹（含 degraded），保证校准语义不变
3. degraded 条目单独归集至 `.workbuddy/l1_training/degraded_anomaly_store.jsonl`（异常样本库，供故障定位），由过滤函数顺带产出

## 3. 优化项三：信封 schema 版本化（暂缓）

- 现状：6/6 壳信封已对齐，耦合风险低
- 方案（下次 schema 变更时顺带落地）：信封带 `schema_version`，解析侧按版本分支，未知字段忽略（FAIL-OPEN）

## 4. 硬约束兼容性对照

| 约束 | 本方案处理 |
|---|---|
| H1 壳 diff=0 | 不改壳代码，轮转为外置脚本 |
| H2 冻结权重 | 不涉及 |
| H4 阈值硬编码 | 保留窗口 14/90 天为脚本常量，禁 env override |
| S3 零干扰 | 轮转独立运行，失败不影响主链路 |
| §6.5 校准协议 | 热保留 14 天 ≥ 影子期 2 周取数需求 |
| FAIL-OPEN | 过滤门/轮转失败均静默降级 |

## 5. 测试与验收

- 轮转脚本：TDD 测试覆盖按天切分、14 天压缩、90 天删除、幂等重跑
- 过滤门：TDD 测试覆盖 degraded 剔除、PSI 计算保留全量、异常样本库归集
- 全量回归：现有测试套件不破坏
