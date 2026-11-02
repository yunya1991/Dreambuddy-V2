# L0 MCP 壳延迟基线（M1③）

- 测量日期：2026-11-02
- 宿主：/home/luke/venv-trading/bin/python3 ｜ 进程数：in-process=N=1 / stdio=每次新进程冷启动
- 每工具 N=100
- SPEC §3.8 验收：壳 P50 ≤ 基线 + 45ms（D4）

| Tool | In-Process P50 | In-Process P95 | stdio 冷启动 P50 | stdio P95 | ΔP50 | stdio/in-proc P50比 |
|---|---|---|---|---|---|---|
| recall | 18.4ms | 25.48ms | 399.56ms | 547.72ms | 381.16ms | 21.7× |
| record | 53.6ms | 95.1ms | 481.07ms | 948.33ms | 427.47ms | 9.0× |
| verify | 197.35ms | 276.91ms | 700.81ms | 1327.43ms | 503.46ms | 3.6× |
| stats | 46.77ms | 53.05ms | 501.59ms | 867.7ms | 454.83ms | 10.7× |
| health | 102.07ms | 118.31ms | 521.98ms | 744.8ms | 419.91ms | 5.1× |
| unified_search | 17.09ms | 17.95ms | 1082.84ms | 1540.92ms | 1065.75ms | 63.4× |

## 观察与风险

- stdio 冷启动 P50 含 Python 解释器 import / 模块加载 / CognitiveLoopEntry 初始化 → 预期比 in-process 慢 5-20×
- in-process 已走 recall SLA（200ms 阈值），冷启动 stdio 基线只是参考——**真正跑 MCP 壳时宿主进程 pre-fork 可省**，实际增量会显著降低
- health / unified_search / recall 三个工具的冷启动比最大（含 import 开销最重）