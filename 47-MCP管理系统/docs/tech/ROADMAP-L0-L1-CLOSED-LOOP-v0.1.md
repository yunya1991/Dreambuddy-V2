# 演进路线排期总览 v0.1

> 日期：2026-11-03
> 用途：三端对齐审查 / 每日站会参考 / 阻塞项跟踪
> 前置：四 SPEC 补入三问评估完成（COMM-SHADOW §5.6 + TRAIN-BASE TB3 第七维 + DOMAIN-AGENTS Dream-RSI alpha + DOMAIN-DISCOVERY §4.5 沙箱）

---

## §0 三端当前状态

| 端 | HEAD SHA | 四联门禁 | NeuralSDE v1 | NeuralSDE dim64/path_sig | GPU | 关键服务 |
|---|---|---|---|---|---|---|
| **本地 macOS M3** | 43fea1c793（TB3 七维升级提交后顺延） | ✅ | ✅ 有 | ✅ 有（`neural_sde_v1.pt` = dim64，sha `a023719e`） | ❌ 无（但 M1/M2 Mac Metal 可用） | — |
| **GitHub main** | 43fea1c793 | — | — | — | — | — |
| **云端 43.160.201.117 (Ubuntu 24.04, 4C16G)** | 43fea1c793 | ✅ | ✅ 有 v1.pt | ✅ **已一致**（sha `a023719e`）+ path_sig/v2 已补 | ❌ **缺口** | continual-training.timer (每30min) + frontend + REA/L0 |

---

## §1 演进路线全览（四阶段 + 12 个里程碑 + 阻塞项）

```
  当前 → ──────────────────────────────────────────────────────────────────
      
  阶段① MCP 壳层（主线，已在推）
  ┌────────────────────────────────────────────────────────────────────────┐
  │ ✅ M1① 注册表 v1 + validate_mcp_registry.py                           │
  │ ✅ M1② 能力集 v1 + validate_capability_set.py                         │
  │ ✅ M1③ 信封映射层 + cognitive/39 壳 envelope 返回                       │
  │ ✅ M1④ 基线脚本 (measure_baseline.py) — latency_baseline.md 已生成（11-02）│
  │    ↓                                                                  │
  │  M2⑥ 数据壳只读 + M2⑦ 评测壳薄包 + M3⑧ REA 壳 + M3⑨ 认知壳双模       │
  │  阻塞：bcrm2 切流需要用户窗口；M4⑪ 库管壳                            │
  └────────────────────────────────────────────────────────────────────────┘
         │ 壳层落地后
         ▼
  阶段② 通信层（COMM-SHADOW + 三问评估的 4 类 payload）
  ┌────────────────────────────────────────────────────────────────────────┐
  │ P0 静态 domain_transmission.json（零依赖，现在就能做）                 │
  │ P1 AgentMailShadow.observe() 旁路消费 + 真实轨迹采集                   │
  │ P2 generate_report() 加 P3 叠加印证假设建议章节                        │
  │ P3 候选策略 π 入池消费（替代硬编码 JSON）                               │
  │ 阻塞：Phase 0 基线稳定（V-S1~V-S6 至少 2 项）                          │
  └────────────────────────────────────────────────────────────────────────┘
         │ 壳层落地并行（零阻塞）
         ▼
  阶段③ L1 训练推理闭环（TRAIN-BASE + DOMAIN-DISCOVERY 沙箱）
  ┌────────────────────────────────────────────────────────────────────────┐
  │ Phase 0 静态架构（现在就能做）                                          │
  │   → 静态 domain_transmission.json + observe() 消费 + BTCRegimeDetector │
  │                                                                       │
  │ Phase A 标注数据管线（壳层落地并行）                                    │
  │   → TB1-TB5 旁路采集 → domain_discovery_training.jsonl 自动生成       │
  │   → 前 100 条样本人工 review                                          │
  │                                                                       │
  │ Phase B L1 增量训练 MVP（**需要 GPU**，Mac Metal 免费起步）             │
  │   → DomainCouplingHead 轻量 output head（< 1MB，冻结主体）             │
  │   → EWC + rolling 2y window + walk-forward OOS                        │
  │   → 验收：coupling MAE < 静态 baseline × 0.8                          │
  │   阻塞：**云端缺 GPU**（dim64/path_sig 已于 11-03 同步）             │
  │                                                                       │
  │ Phase C 闭环验证（COMM-SHADOW Phase 1 观察期）                         │
  │   → observe() 读真实 coupling + generate_report() 建议章节            │
  │   → 沙箱跑 P3 叠加印证假设 → P4 验证回执                                │
  │   → TB3/TB5/做梦器 吃 P4 回执 → pnl_delta_score v_adjusted V_new      │
  │   → 验收：COMM-SHADOW V 函数 hypervolume ≥ baseline × 1.1             │
  └────────────────────────────────────────────────────────────────────────┘
         │
         ▼
  阶段④ 壳后 agent 化（DOMAIN-AGENTS H1-H9 + 影子→激活）
  ┌────────────────────────────────────────────────────────────────────────┐
  │ Phase A 认知 agent 参数化（Shell 级参数透传已具备）                    │
  │ Phase B REA agent AI Audit + Dream-RSI V_new(π,T) α 分量              │
  │ Phase C 评测 agent OOD + VaR + verify 闭环                            │
  │ Phase D 语义 agent Mandate 写门控                                     │
  │ Phase E 数据 agent read-only 自治                                     │
  └────────────────────────────────────────────────────────────────────────┘
```

---

## §2 里程碑清单（按优先级排序）

| # | 里程碑 | 阶段 | 前置条件 | 产出 | 本地/云端 | 阻塞状态 | 时间预估 |
|---|---|---|---|---|---|---|---|
| **1** | M1④ 基线脚本云端跑 | ① MCP | 无（代码已 commit） | latency_baseline.md | 云端 | ✅ **已完成**（11-02 生成；recall 18.4ms / record 53.6ms / verify 197.35ms P50） | 已收口 |
| **2** | 静态 domain_transmission.json | ③ Phase 0 | 无（现在就能做；本地缺 `sector_transmission.json` 字段来源） | 从 sector_transmission 改字段，静态 v0.0 | 本地 → push | ✅ 无 | 1 天 |
| **3** | observe() 消费静态版本 | ② P0 | #2 | COMM-SHADOW observe() 加 l1_transmission_path 参数 | 本地 | ✅ 无 | 1 天 |
| **4** | BTCRegimeDetector k=3 + NeuralSDE dim64 regime 输入 | ③ Phase 0 | NeuralSDE dim64 在本地有 | 重写 regime 检测为 BTC-only k=3 + drift_net in_dim 18→21 | 本地 | ✅ **已完成**（k=3 + regime/transition 接线，4 个测试文件 27 passed） | 已收口 |
| **5** | TRAIN-BASE Phase 0 TB1-TB5 落地 | ① MCP→②③ 并行 | M1③ 信封稳定 | 5 个训练基座模块 + **43/43 TDD**（TB1 12 + TB2 8 + TB3 9 + TB4 4 + TB5 5 + Phase A 5） | 本地 → push → 云端 | ✅ **已完成** | 已收口 |
| **6** | NeuralSDE dim64 + path_sig 同步云端 | ③ Phase B 前置 | 本地有 | scp 或 git-lfs 推 | 本地 → 云端 | ✅ **已完成**（主模型 sha 一致 `a023719e`；path_sig/v2 已 scp + sha 校验） | 已收口 |
| **7** | 标注数据管线 MVP | ③ Phase A | #5 TB1-TB5 落地 | collect_domain_discovery_data.py 20 行 + JSONL schema | 本地 | ✅ 无 | 1 天 |
| **8** | **GPU 就绪**（Mac Metal 或腾讯云 T4） | ③ Phase B | 无 | Mac 本地用 Metal 免费；云端按需开 T4 | 本地 / 云端 | **🔴 Phase B 硬阻塞** | 1 天（腾讯云 T4 开 ¥2.4/小时） |
| **9** | DomainCouplingHead MVP + 增量训练 | ③ Phase B | #6 模型在云端 + #8 GPU | 训练脚本 + domain_transmission.json v0.1 推理 | 本地 Mac Metal | ✅ 无（有 GPU 后） | 3 天 |
| **10** | COMM-SHADOW Phase 0 基线稳定 | ② P0 | #3 + #4 + #5 | observe() 跑起来 ≥ 10 天，V-S1~V-S6 至少 2 项满足 | 云端运行 | ⏳ 依赖壳层 + 时间 | 2 周运行期 |
| **11** | 跨域组合验证沙箱 MVP | ③ Phase C | CounterfactualEvaluator 在产 + #5 + #9 | domain_hypothesis_sandbox.py + S1-S6 资产复用 | 本地开发 | ✅ 无 | 3 天 |
| **12** | COMM-SHADOW Phase 1 + 闭环验证 | ② P1-P3 + ③ Phase C | #10 + #11 | V 函数 hypervolume ≥ baseline × 1.1 | 云端运行 | ⏳ 依赖影子观察期 | 2 周观察 + 1 周验证 |

---

## §3 阻塞项清单

| # | 阻塞 | 影响 | 解法 | 紧急度 |
|---|---|---|---|---|
| **B1** | ~~腾讯云 QR 扫码~~：M1④ 基线脚本无法自动跑 | — | ✅ **已消解**：11-02 已生成 latency_baseline.md；云端可直连 | 已解 |
| **B2** | ~~云端缺 NeuralSDE dim64.pt + path_sig.pt~~ | — | ✅ **已消解**：主模型 sha 与本地一致（`a023719e`，即 dim64）；path_sig/v2 已 scp + sha 校验 | 已解 |
| **B3** | **云端无 GPU** | Phase B 增量训练无算力 | 选项 A：Mac Metal 本地训练（推荐，数据不出本地）；选项 B：腾讯云 T4 按需开 ¥2.4/小时 | 🔴 Phase B 硬阻塞 |
| **B4** | **bcrm2 切流窗口未定** | M2-M3 壳落地需要用户确认重启窗口 | 等用户给窗口 | 🟡 中 |

---

## §4 本地 vs 云端分工

| 环节 | 本地 | 云端 | 原因 |
|---|---|---|---|
| SPEC 写 + 静态 JSON + Python 原型 | ✅ | — | 本地开发效率高 |
| TRAIN-BASE TB1-TB5 编码 + TDD | ✅ | — | 本地 四联门禁 |
| NeuralSDE 增量训练（Mac Metal） | ✅ | — | 数据不出本地最安全；Mac Metal 免费 |
| NeuralSDE 增量训练（腾讯云 T4 备选） | — | ✅ | 云端 GPU 按需开 |
| COMM-SHADOW observe() 运行 | — | ✅ | 需要消费实时 envelope 数据流 |
| domain_transmission.json 推理写入 | — | ✅ | 每小时 1 次 cron，消费云端数据 |
| 跨域组合验证沙箱 | ✅ 开发 | ✅ 运行 | CounterfactualEvaluator 依赖云端 K-line |
| 四联门禁 | ✅ 每次 commit 前 | ✅ 每次 pull 后 | 三端一致 |

---

## §5 GPU 方案对比（Phase B 关键决策）

| 方案 | 月成本 | 可用性 | 优点 | 缺点 | 推荐 |
|---|---|---|---|---|---|
| **A. Mac Mini M1/M2 Metal** | ¥0 | ✅ 随时 | 免费 + 数据不出本地 + 最安全 + 训练时间 ~2h/次 | 比 T4 慢 ~2x | **⭐⭐⭐⭐⭐ MVP 起步首选** |
| B. 腾讯云 T4 GPU | ¥2.4/小时 × 8h/月 ≈ ¥19 | ⚠️ 按需开机 | 训练最快（~40min/次） | 需要 SSH 开关机自动化 | MVP 通过后切 |
| C. Colab Pro | ¥100/月 | ✅ 随时 | 免费 GPU 升级 | 数据需要上传/下载 + 24h 闲置断连 | 备选 |

---

## §6 依赖链（拓扑排序）

```
# 零阻塞，现在就能做
P0-1 静态 domain_transmission.json (⭐ 1天)
P0-2 observe() 消费静态版本 (⭐ 1天)
P0-3 BTCRegimeDetector k=3 重写 (⭐ 3天)

# 并行
├─ TRAIN-BASE Phase 0 (TB1-TB5 7天)
│     ├─→ 标注数据管线 MVP (1天)
│     └─→ NeuralSDE dim64 同步云端 (10分钟)  ← B2 阻塞
│
└─ GPU 就绪 (B3 阻塞，1天 Mac Metal 零成本)
      └─→ DomainCouplingHead MVP + 增量训练 (3天)

# 壳层落地后
├─ COMM-SHADOW Phase 0 基线稳定 (2周运行期)
├─ 跨域组合验证沙箱 MVP (3天)
└─ COMM-SHADOW Phase 1 + 闭环验证 (3周)
```

---

## §7 本周行动清单（无阻塞）

| 天 | 任务 | 产出 | 状态 |
|---|---|---|---|
| **Day 1** | 静态 domain_transmission.json + observe() 消费 | 2 文件，链路跑通 | ⏳（schema 来源待确认） |
| **Day 2-4** | BTCRegimeDetector k=3 + NeuralSDE dim64 regime 输入 | 2 模块 + 测试 | ✅ 已完成（27 passed） |
| **Day 5** | TRAIN-BASE Phase 0 启动 | TB1 drift_detector 开始写 | ✅ 已完成（12 passed） |
| **Day 6-7** | 持续 TRAIN-BASE + NeuralSDE dim64 scp 云端 | 训练基座 ≥ TB3 | ✅ 已完成（TB1-TB5 + Phase A = 43/43） |

**B1 处理**：✅ 已消解（latency_baseline.md 11-02 已生成，云端可直连）。
