# 🎓 大师策略档案索引 (经验 — 实战数据)
> **来源**: dream-multiskill-v2/2-INTEL/master-seminar/config/masters.yaml + data/master_stats.json
> **类别**: 经验 — 已蒸馏大师的配置与统计数据

## 总览：10位大师

| 大师 | 阵营 | 核心风格 | 擅长Regime | 采纳率 |
|:---|:---:|:---|---:|:---:|
| **Soros** | 🟢多 | 反身性·宏观择时 | HIGH_VOL/BEAR/CRISIS_RECOVERY | 63.4% |
| **Druckenmiller** | 🟢多 | 趋势追踪·杠杆 | TREND_BULL/HIGH_VOL/BULL | 63.4% |
| **Buffett** | 🟢多 | 价值投资·长期 | NEUTRAL/BULL_REGIME/STABLE_BULL | 0% |
| **O'Neil** | 🟢多 | CANSLIM·成长股 | BULL_REGIME/TREND_BULL | 63.4% |
| **PTJ** | 🔴空 | 宏观择时·危机Alpha | HIGH_VOL/BEAR/CRISIS | 63.4% |
| **Dalio** | 🔴空 | 宏观对冲·风险平价 | CRISIS/DEFLATION/HIGH_VOL | 63.4% |
| **Livermore** | 🟡中 | 关键点交易·趋势 | TREND/RANGE/BREAKOUT | 63.4% |
| **Tharp** | 🟡中 | 交易系统·仓位管理 | ALL(通用) | 63.4% |
| **Talmans** | 🟡中 | 技术分析·趋势跟踪 | TREND/BREAKOUT | 0% |
| **Michele** | 🟡中 | 量化系统·统计套利 | RANGE/SIDEWAYS/MEAN_REVERSION | 0% |

## 权重规则
- 初始权重: 1.0(所有人)
- 采纳率>70% → 权重×1.1 | 采纳率<40% → 权重×0.9
- 阵营投票 = Σ(多方投票×权重) / Σ(空方投票×权重)
- 中立阵营占总票50~70%

## 场景最佳匹配
| 市场环境 | 高分大师 | 低分大师 |
|:---|---:|:---|
| 强势牛市 | Druckenmiller, O'Neil | Michele, Dalio |
| 高波动熊市 | Soros, PTJ, Dalio | Buffett, O'Neil |
| 震荡横盘 | Livermore, Michele | Druckenmiller |
| 危机暴跌 | PTJ, Dalio, Soros | Buffett |
| 稳定上涨 | Buffett, O'Neil | Soros, PTJ |

## 大师 YAML 档案
每个大师有一个独立 YAML 文件在同目录，含：
- 阵营/核心风格/擅长Regime/不擅长Regime
- 统计: total_seminars, total_adoptions, weight_history
- 核心哲学摘要 (core_philosophy)
- 适用场景指引 (application)

### 文件列表
- `soros.yaml` — 反身性理论
- `druckenmiller.yaml` — 趋势追踪
- `buffett.yaml` — 价值投资
- `oneil.yaml` — CANSLIM
- `ptj.yaml` — 危机Alpha
- `dalio.yaml` — 宏观对冲
- `livermore.yaml` — 关键点交易
- `tharp.yaml` — 系统交易
- `talmans.yaml` — 技术跟踪
- `michele.yaml` — 量化系统
