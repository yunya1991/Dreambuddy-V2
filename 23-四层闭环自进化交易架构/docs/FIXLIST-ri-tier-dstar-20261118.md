# 修复清单：ri 恒 0.5 / tier 恒 probe / d_star 恒 WAIT

> 诊断日期：2026-11-18 · 诊断结论见 [TRADING_FRAMEWORK_AND_SIGNAL_FLOW.md §6.5](./TRADING_FRAMEWORK_AND_SIGNAL_FLOW.md)
> 状态图例：`[ ]` 待修 · `[~]` 进行中 · `[x]` 已完成 · `[-]` 关闭（非缺陷/无需修） · `[!]` blocked（待决策）

## 清单

| # | 问题 | 根因 | 修复动作 | 验收标准 | 状态 |
|---|---|---|---|---|---|
| F1 | `ess_top_direction` 恒为空 → `ripple_ri` 硬编码 0.50 | ESS top1 为纯离场组合（`direction=both`），Provider 只取 top1 | `ESSDirectionProvider` 按 ESS 降序遍历，取第一个含 `long/short` 动作的组合 | 单测：top1 无方向、top2 有 long → 返回 long；云端 N9 `ess_top_direction` 非空 | `[x]` |
| F2 | `detect_ripple_source` 放量门槛固定 `2.0`，1H 实际触发率仅 0.12% | 阈值未随波动率适配 | 改为 20 日已实现波动率自适应：`clamp(1.20+25σ_d, 1.30, 2.50)`；env 可覆盖 | 模拟触发率 0.12%→3.38%（σ_1h=0.003）；云端 N9 `vol_threshold` 随波动率变化 | `[x]` |
| F3 | `R_flow=0.0` | Wyckoff effort/result：effort=0 且 pct_move 满档 → 低阻力 0 | 无需修复 | — | `[-]` |
| F4 | `d_star` 恒 WAIT（`wait=R_smooth×R_reflexivity`） | 量纲失配：两维 [0,1] 乘积系统性低于单维 R_up/R_down；实测 R_smooth p90=0.164 → wait≈0.07，方向代价最低 0.31，WAIT 结构性恒胜 | 新增 calibrated 口径 `wait=(1-R_smooth)×R_refl` + 中性区 `margin=0.30`；开关 `EVOLUTION_DSTAR_WAIT_MODE` 默认 `legacy`（行为不变），N4 事件影子对比 | 单测 8 项；云端 walk-forward：legacy=100% WAIT、flip=MDD 33%/60%、flip+30%=MDD 3.91%(4h)/10.37%(24h) | `[x]` |
| F5 | `reflection_ri=0.50` | 冷启动，`get_coin_stats.eligible=False` | 无需修复，样本积累后自然变化 | — | `[-]` |
| F6 | 定位信息不足 | N0 未记录 `ess_top_direction` / `vol_ratio` / `is_source` | N9 事件补充 `ri/tier/ess_top_direction/vol_ratio/ripple_is_source/ripple_ri/reflection_ri/reflection_eligible` | 云端 N9 可直接看出卡在哪一条件 | `[x]` |
| F7 | `PROBE_THRESHOLD` 口径不一致 | 记忆记录 0.55，23 handler 现值 0.50 | 已核对：23 handler 为 `0.50`；`0.55` 来自 `ripple_engine.get_ri_action`（cbr_boost 档）与 `tight_coupling_orchestrator`（RI≥0.55 形成推断），属不同阈值，非缺陷 | 结论记录 | `[-]` |
| F8 | `reflection_ri` 始终 0.5，样本看似不积累 | ① 已知源相对 `project_root` 解析（相对路径无法向上），23 子目录启动 → 22 账本读不到；② 自动发现把 `gene_data/shadow_validation/*_samples.jsonl`、`data/ess_reflection.jsonl` 当真实交易（pnl=-100 占位、exit_reason='运行时检测OKX持仓消失'）；③ 仓库级索引混入 11-易经等外部子系统成交；④ `get_coin_stats` 用完整合约代码查不到 `BTC` 键 → 恒回退 0.5 | ① `_repo_root()` resolve 后向上定位仓库根；② fills 排除 `source LIKE '%reconcil%'`；③ `is_synthetic`/`pnl_valid` + `record_source` 归属过滤（只认 `23-evolution`/`22-ledger`）；④ `get_coin_stats` 归一化 `BTC-USDT-SWAP→BTC` | 单测 7 项；云端 BTC n=2/win=0.5/ri=0.5/eligible=False（**真实战绩**，未达 0.55 阈值）；SOL n=3/33% | `[x]` |

## 执行记录

| 时间 | 项 | 动作 | 结果 |
|---|---|---|---|
| 2026-11-18 | F1 | `ess_provider` 按 ESS 降序取首个有方向组合；新增 2 个单测 | `[x]` 7 passed |
| 2026-11-18 | F2 | 新增 `calibrate_vol_threshold`（20 日 σ 自适应），`detect_ripple_source(vol_ratio_threshold=)` 支持传入；新增 4 单测 | `[x]` 49 passed |
| 2026-11-18 | F6 | N9 增加 ri/tier/ess_top_direction/vol_ratio/ripple_is_source/ripple_ri/reflection_ri/reflection_eligible | `[x]` handler 45 passed |
| 2026-11-18 | F3/F5/F7 | 判定为非缺陷 / 口径混淆 | 关闭 |
| 2026-11-18 | 全量 | 提交 `fca428e43e` + `3abf828a79` 推送；云端快进 + 重启 `dreambuddy-entry23`（12:27:30 CST） | `[x]` |
| 2026-11-18 | F1/F2 云端生效验证 | 重启后 N9：`ess_top_direction=long`（非空）、`vol_threshold=1.9303/2.1578`（随波动率变化） | `[x]` 生效 |
| 2026-11-18 | ri 仍 0.5 判定 | `vol_ratio=0.4226/0.2406` ≪ 阈值 → 确无放量，`ripple_is_source=False` 属**正确行为**；`reflection_ri=0.5` 冷启动 | `[-]` 非缺陷 |
| 2026-11-18 | F4 模拟回测 | 合成 100 seeds：A 累计 -118.38%/MDD 74.96%/WAIT 0%；B +0.61%/MDD 21.84%/WAIT 63.3% | 记录 |
| 2026-11-18 | F4 实际事件（n=339 N2） | 按 wait 口径重算动作：A=100% WAIT、B=100% long、flip_rate=100% → 简单翻符号会变成单边死多，不可直接采纳 | 记录 |
| 2026-11-18 | F4 真实 K 线 walk-forward（云端，BTC/ETH/SOL × 300×1H，含 5bps/边） | h=4h：legacy 100% WAIT / flip MDD 32.97% / flip+20% 88.9% short MDD 32.49% / **flip+30% WAIT 87.8%、short 12.2%、累计 +21.07%、MDD 3.91%**；h=24h：flip 累计 +170.52%/MDD 59.77%、flip+30% 累计 -2.72%/MDD 10.37% | 记录 |
| 2026-11-18 | F4 裁决 | legacy 恒 WAIT 是量纲问题（缺陷）；直接翻符号回撤过大（33%~60%）；采用「翻符号 + 30% 中性区」，默认开关关闭、影子对比后再启用 | `[x]` |
| 2026-11-18 | F4 落地 | `level0_path_cost.compute_d_star` 增加 `wait_mode/wait_margin` 与 `d_star_calibrated`，N4 事件记录 `d_star_shadow`；新增 `tests/test_level0_wait_calibration.py` 8 项 | `[x]` 54 passed |
| 2026-11-18 | 回测脚本 | `scripts/backtest_ri_gate.py` 新增 `--klines`（真实 K 线 walk-forward + margin 网格） | `[x]` |
| 2026-11-18 | 口径切换 | 云端 drop-in `/etc/systemd/system/dreambuddy-entry23.service.d/10-dstar.conf` 设 `EVOLUTION_DSTAR_WAIT_MODE=calibrated` + `MARGIN=0.30`，重启（13:00:27 CST）；N4 实测 `wait_mode=calibrated`、ETH/SOL `d_star=long`、BTC `d_star_calibrated=WAIT`（bc 0.4577 > wait 0.577×0.7） | `[x]` 已生效 |
| 2026-11-18 | 监控接入 | 15 新增 `signal_calibration_metrics` 11 指标 + 5 条告警 + `23_REFLECTION_STARVED` 日报项（15 TD §13.9.4） | `[x]` |
| 2026-11-18 | F8 样本排查 | 云端 `ReflectionScanner.scan()`：64 笔 trade 分布 64 个币（每币 1 笔）；`fills` 平仓 43 笔中 25 笔 `realized_pnl=0`、1 笔 NULL → win_rate 恒 0 → reflection_ri 恒 0.5 | `[!]` 待 22 侧回写 PnL |
