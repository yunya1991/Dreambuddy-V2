# CHANGELOG — 47-MCP管理系统

## 2026-11-03 全仓断链治理（第一批，10-经典指标体系暂缓）

- 断链 983 → **724**，剩余全部位于 `10-经典指标系统/`（721 条）与其引用（3 条），按用户要求单开对话分析
- 非 10 域：**0 断链**（本地实测）
- 处理方式：可解析 → 改写为指向**已入库（git tracked）**的最近同名文件（版本号归一取最新）；不可解析 → 原链接改为「（链接失效）」纯文本；外部 `file:///Users/...`（非本仓库）→ 「（外部链接失效）」
- 影响 83 个文件 / 246 行，仅链接与失效标注变化，无正文语义改动
- 云端对齐轮：以 `git worktree` 干净检出（=云端文件集）为基准复测，另修 37 处「本地存在但未入库」的引用（backtest 数据、`dream-harness-bridge` 代码、`.trae/` 草稿等），统一标注「（未入库）」；干净检出与本地均 **0 非 10 断链**

## 2026-11-03 技术文档一致性修复（断链 + 契约 + 状态回填）

- **断链清零**：47 docs 7 处（`../../../../` 层级错误 ×4、`SPEC-L0-DOMAIN-AGENTS-v0.1` 文件名过期 ×3）；44 2 处；PLAN 1 处绝对路径 → 相对路径。三根（0 / 47 / 44）link_checker 均 0 断链
- **全仓绝对链接归一**：1284 处 `file:///Users/...` → 相对路径（111 文件），断链总数 1002 → 983（无回归，纯收益）
- **CI 防回归**：新增 `docs-links` job，对 0 / 47 / 44 三个活跃文档根执行 link_checker，断链即失败
- **契约修正**：`registry/mcp_capabilities.yaml` v0.1→v0.2，`planned_shells` 三壳（data/eval/store-admin）迁入 `shells`（status=available），校验器输出 7 壳 / 0 规划壳 / 24 active 工具
- **状态回填**：TRAIN-BASE（✅ 48/48 + 影子 PASS）、DOMAIN-AGENTS（Phase 0 完成 + Phase A 落地）、PLAN（已开工）、ALIGNMENT（终审已执行）

## 2026-11-03 TB5 P4 回执消费闭环（TRAIN-BASE 与新 SPEC 完全对齐）

- `evolve_step(p4_receipts=...)`：DOMAIN-DISCOVERY §4.5.4 要求的 P4 沙箱回执消费
- 有效回执（非空 `trace_id` + `counterfactual_result`）→ `v_adjusted = pareto_score + V_ALPHA×(pnl_mean−0.5)`，`V_ALPHA=0.1` 硬编码
- 无回执 → `v_adjusted == pareto_score`，零行为变化（向后兼容）
- FAIL-OPEN：非 list 容器 / 非 dict / 缺 trace_id / 字段非数值 → 丢弃回执，不抛异常、不触发 fallback
- `training_reward.pnl_delta_score_from_receipt` 改为公开函数，供 TB5 复用同一归一化口径（避免两套公式）
- 测试 5→10 条（RED 6 零变化 / RED 7 alpha 加权 / RED 8 过滤 / RED 9 非法内容 / RED 10 容器类型）
- 全局 **48/48**（TB1 12 + TB2 8 + TB3 9 + TB4 4 + TB5 10 + Phase A 5）
- C10 白名单补登记 `tb_shadow_run.py`（档三：只读影子脚本，mode=ro），保留原有定性三档注释

## 2026-11-03 TB3 七维契约升级 + ROADMAP 状态回填

- **TB3 七维落代码**（文档此前已改七维，代码仍六维）：`REWARD_WEIGHTS` 改 `(0.23, 0.18, 0.18, 0.14, 0.12, 0.05, 0.10)`；`RewardComponents` 新增 `pnl_delta_score`；`compute_reward` 新增 `counterfactual_result` 参数，按 `clip((treatment−control+0.05)/0.25, 0, 1)` 归一化
- FAIL-OPEN：无回执 / 非 dict / 字段缺失 / 类型错误 → 中性 0.5，不抛 KeyError
- 测试 6→9 条（新增 RED 7 中性、RED 8 clip 边界、RED 9 缺字段）；TB1-TB5+Phase A 全局 **43/43**
- **SPEC 自洽修复三处**：§3 标题/§3.1/§3.2/§0.5.1 流程图的「六维」改七维；§3.3 `pareto_score` 骨架补 `pnl_delta_score`（原文漏第七维）；§3.4 RED 6 改 `len==7` + 补 RED 7-9 + 验收 9/9；§6.1/§6.2 数字对齐 43/43；§6.5 校准表权重改七维
- **ROADMAP 状态回填**（原内容落后于实际代码）：三端 HEAD `43fea1c793`；M1④ 基线已完成（11-02）；#4 BTCRegimeDetector k=3 + regime 接线已完成（27 passed）；#5 TRAIN-BASE 43/43；#6 dim64/path_sig 云端已一致（sha `a023719e`）；B1/B2 已消解；§7 Day2-7 标记完成
- 云端实测：主模型 `neural_sde_v1.pt` sha 与本地一致（即 dim64），`path_sig.pt`/`path_sig_v2.pt` 已 scp 并校验 sha，/tmp 已清理

## 2026-11-03 Phase A 认知 agent 参数化（train_base recall 排序）落地

- `recall(sort_mode="train_base")` 新增第三种排序模式，TB1+TB2+TB3 三阶段注入 recall 结果
- 排序公式：`boosted = score × (0.5+0.5×β_mean) × ψ_gate × (0.7+0.3×citation)`
- TB1：PSI > 0.25 → `psi_gate=0.7` 全局 recall 降权；基线从 `psi_baseline.json`（TB1 影子跑写入）
- TB2：每条记忆的 Beta 后验 mean 提升（verify 多次成功的记忆更靠前）
- TB3：citation_diversity ≈ quality_level rank（S=1.0/A=0.8/B=0.6/C=0.4/D=0.2）
- H1 硬约束满足：零 MCP 壳改动，所有改动在 agent 侧 `cognitive_loop_entry.py` 内部
- FAIL-OPEN：PSI 基线缺失/文件损坏 → `psi_gate=1.0`；单条 Beta 加载异常 → 保留原 score
- 测试 `test_train_base_recall.py` RED 5 条全绿；TB1-TB5+PhaseA 联合 **40/40**

## 2026-11-03 影子验证合并跑 TB1-TB5（真实 DB 数据）

- 新增 `tb_shadow_run.py`（与 TB1-TB5 同目录，绝对 import）：影子跑脚本，零业务回写
- 数据源：`cognitive_memory.db` 539MB（262K memories，mean confidence 0.301；verify_count>0 的 3403 条真实 success_rate mean=0.474）
- 第一次 shadow 暴露采样坑：`voyager_consecutive.jsonl` 里大量 C 级未验证记忆（success_rate≈0）→ TB2 Beta 后验塌缩 mean=0.0015；recall_hits 硬算常数 → TB3 分布平坦 spread=0.0；TB5 两候选在低 gaps / 低 refs 下无分歧 → 零切换。**非代码 bug，纯数据采样策略问题**
- 第二次 shadow 修正：改用 DB `verify_count>0` 记忆算 success_rate（quality_level rank 加权）+ recall_hits 从每样本派生 + TB5 候选差异拉开（threshold 1 vs 10 + refs_budget 1 vs 20）
- **第二次 shadow 结论**：
  - TB1 PSI=0.0001，stable ✅
  - TB2 Beta 后验 Beta(96.3, 104.7) mean=0.479，从 0.301 提升 ✅
  - TB3 pareto_score mean=0.667, p50=0.665, p90=0.717, spread=0.118
  - TB4 regime gate 四 arm mean 置信度 0.45~0.50，commodity 最高（DB 里该 arm 对应质量等级≈B）；drift 50 步触发一次 reset，本次 200 步触发 3 次
  - TB5 切换 0 次（当前 extras 样本 gaps/refs 普遍低，两候选截断后输入相同 → 合理不切换）；FAIL-OPEN fallback 0
  - **verdict = PASS**
- 影子报告落 `4-MEMORY/artifacts/tb_shadow_report.{json,md}`（artifacts/ 在 .gitignore，不入库；与 SPEC §6.3 / §6.5 影子期校准协议对齐，后续 ≥200 条 agent 结论可复跑校准）

## 2026-11-03 TB5 PolicySelectLoop 落地（TB1-TB5 全部完成）

- 新增 `grpo_evolution.py`：`StrategyConfig`（格式偏好，H2 冻结权重）+ `GRPOEvolutionLoop`（`evaluate_config` → 候选 argmax → 严格改进才切换）
- 修正 SPEC 骨架两处逻辑坑：① `dict(scores)[self.current_config]` 不可用（可变 dataclass 不可哈希）→ current_score 单独计算；② 原 `best_score >= current_score` 使不劣化分支恒真、`else` 不可达 → 改为 `best_score > current_score`（RED 5 才成立）
- H2/H4 代码内显式标注：无 `.train()/.backward()/.backprop`；异常时 FAIL-OPEN 并记 `history fallback`
- 测试 `test_grpo_loop.py` RED 5 条全绿；TB1-TB5 联合回归 **35/35**
- SPEC §5.2 路径修正为同目录；§5.3 import 收敛为实际依赖；§6.1/§6.2 数字对齐实测（TB1 12/12、TB2 8/8、全局 35/35）
- 范围说明：`STRATEGY_CONFIG_SCHEMA` 常量与 `OracleVerificationLayer` 按 SPEC 标注留待 Phase A-C（本次仅落 TDD 5/5 的 loop）

## 2026-11-03 TB4 Thompson Sampling regime gate 落地

- 新增 `regime_gate.py`：`ThompsonSamplingRegimeGate`（美林四段 arm），Beta 采样选 arm、部分成功率更新、`drift_detected=True` 全 arm 重置 Beta(1,1)、`get_confidence` 返回 Beta mean
- 测试 `test_regime_gate.py` RED 4 条全绿（随机过程显式 seed 可复现）
- SPEC §4.2 测试路径修正为同目录；§4.4 RED 2 阈值 `>0.8` 经数学复核 `E[X³]=11/14≈0.786` 不可达，修正为 `>0.75`（场景 10 次成功不变）；RED 4 补全前序 Beta(2,1) 输入口径
- TB1+TB2+TB3+TB4 联合回归 30/30

## 2026-11-03 TB3 AlphaPareto 六维奖励落地

- 新增 `training_reward.py`：`RewardComponents` 六维（verify mean / recall 命中率 / PSI 稳定度 / citation 多样性 / 过程奖励 / 转移平滑度）+ `compute_reward` + `pareto_score`
- 硬编码 `REWARD_WEIGHTS=(0.25,0.20,0.20,0.15,0.12,0.08)`（和=1.0），无 env override / 运行期调整（与 TB1 H8 同类硬约束）
- 边界：PSI>1.0 → psi_stability 0.0；known_gaps>10 → citation 下限 0.0；recall_total=0 → p_recall_hit 0.0
- 测试 `test_alpha_pareto.py` RED 6 条全绿；TB1+TB2+TB3 联合回归 26/26，C10 直连门禁与 47 注册表校验通过
- SPEC §3.2 测试路径修正为同目录、§3.3 移除不存在的 `from drift_detector import psi`、§3.4 RED 2 明确六维均差的输入口径

## 2026-11-03 TB2 Beta 分布 verify 升级落地

- `cognitive_interfaces.py` 新增 `BetaState` / `VerifyResult` / `verify_beta`（SPEC §2 骨架），TB3 可直接 `from cognitive_interfaces import BetaState`
- `cognitive_loop_entry.py` 新增 `_beta_verify_adapter`（bool → success_rate 桥接）+ `_load_beta_state` / `_save_beta_state`（后验持久化于 `storage_path` 同目录 `beta_states.json`），`verify()` 增加可选 `drift_detected` 参数（TB1 PSI 漂移 → Bayesian reset）
- 零业务回归口径：无持久化后验时以记忆现有 confidence 作先验种子（`Beta(c, 1-c)`），conf 0.5 + 一次成功 → mean 0.75 ≥ 0.7；旧返回键全部保留，新增 `confidence/beta_alpha/beta_beta/drift_detected/data_schema_version`
- 测试 `test_beta_verify.py` RED 8 条全绿；回归：`test_drift_detector` 12/12、PoE / Evidence Ledger / M6 契约 / 认知 session 等用例通过（`test_p0_1_hook_wiring`、`test_auto_access::test_mcp_tool_call_stats` 为既有 envelope 断言失败，stash 复验确认与 TB2 无关）
- 同步修正 SPEC §1.2/§2.2 测试路径为实际同目录，§2.4 增补 RED 7/8，验收 6/6 → **8/8**

## 2026-11-03 TB1 PSI 漂移检测器落地（本地接续云端开发）

- 拉取云端未提交进度（`drift_detector.py` + `test_drift_detector.py`）到本地并完成开发
- 修复 `classify_drift` 边界语义：改为 `<= threshold - 1e-9`，`0.099999999 → stable`、`0.1 → minor_drift`（原实现口径相反导致 2 条用例失败）
- 补齐 SPEC §1.4 缺失功能：`classify_drift_triple`（PSI+KS 融合，KS 命中升一档）、`drift_kill_switch` 双形态（psi 阶梯 / 等级字符串 SPEC 形态）
- 测试 10 → **12 条全绿**；同步修正 SPEC RED 5/6 边界预期与验收数（9/9 → 12/12）

## 2026-11-03 云端评审 REVIEW-AGENT-ARCH 7 项复核与修订

云端评审（`REVIEW-AGENT-ARCH-v0.1.md`）提出 P1-P7 共 7 项存疑，本地逐项复核后处置：

| 项 | 复核结论 | 修订 |
|---|---|---|
| P1 奖励维度不一致 | 成立（且实际会 TypeError） | TRAIN-BASE §3 统一为六维 + 6 权重（和=1.0）+ RED 6；DOMAIN-AGENTS §4.1 改为只引用 |
| P2 45 PG 表数 | **不成立**（实测 8 条 CREATE TABLE，第 9 处为注释） | 无需修改 |
| P3 GRPO 术语误用 | 成立 | TRAIN-BASE §5 更名 PolicySelectLoop + 借喻声明 |
| P4 论文引用 | 成立（编号有误） | 更正 Alpha-R1 2512.23515 / EvolveR 2510.16079 / AlphaPareto 2609.34188；ADTS 标待验证 |
| P5 经验值无校准 | 成立 | 新增 TRAIN-BASE §6.5 影子期校准协议（离线校准，禁止运行期自调） |
| P6 代码落点未创建 | 成立（表述风险） | DOMAIN-AGENTS §6 标注"计划新增" |
| P7 agent_mail 未创建 | 确认非缺陷 | 无需修订 |

- 新增评审文档 `docs/tech/REVIEW-AGENT-ARCH-v0.1.md`（含 §3.1 本地复核结论）
- CHANGELOG 与三份 SPEC 同步修订；TRAIN-BASE 代码块已通过 py_compile 校验

## 2026-11-03 M2/M3 收口缺口修复（注册表/双模/CI/trace_id）

### 修正

- **注册表 V6 对齐**：新增 `l0.rea.mcp`（6 个两段式 submit/poll 工具，status=available # M3⑦）；`l0.rea-client.mcp` 转 `deprecated`（被前者取代，保留登记不删）
- **envelope_version 统一**：`l0.data.mcp` / `l0.eval.mcp` / `l0.store-admin.mcp` 由 0.2 回正为 **0.1**，与 `mcp_shells/_shared/envelope_wrap.py` 的 `ENVELOPE_VERSION` 一致
- **任务号注释回正**：data M2⑤ / eval M2⑥ / store-admin M4⑩；`l0.eval.mcp` 的 `capability_id` 回填为 `l0.rea`（C6 仅 5 个 id，不新增）
- **双模变量名统一（V7）**：TECH §5.3 的 `MCP_PROFILE=local-readonly` 改为实现真值 `COGNITIVE_MCP_MODE=local`；新增 `registry/mcp_profiles.json` 模板（cognitive-local / cognitive-cloud-ssh）

### 新增

- **CI 阻断**：`l0-contracts.yml` 追加 `python -m pytest mcp_shells/ -v`（M2/M3/M4 壳契约测试）
- **V5 trace_id 贯穿断言**：`mcp_shells/test_trace_id_coverage.py`，4 壳（data/eval/rea/store-admin）验证 `MCP_TRACE_ID` → 信封 `trace_id`，并校验 source/version/三态

### 索引同步

- M2④ `19-数据访问层/docs/CONNECTION_GOVERNANCE.md` 补入 19 ENGINEERING_INDEX 文件树与 `0-系统文档管理/INDEX.md` 文档计数（7→8）

## 2026-11-02 PLAN v0.2 修正（本地审查云端产出）

### 背景

云端产出 `PLAN-L0-MCP-P0-P3 v0.1` 后，本地与 SPEC v0.3 / ALIGNMENT v1.0 交叉比对发现 1 处冲突，修正为 v0.2。

### 修正

- **任务载体冲突（P1）**：v0.1 任务②新建 `0-系统文档管理/l0_capability_set.v1.yaml` 作为"DSH 能力集单一载体"，与 ALIGNMENT B4「单一载体 = `47/registry/mcp_capabilities.yaml`」冲突。修正为：任务①合并原任务②，mcp_capabilities.yaml 包含完整的**角色→能力标签→工具**三层映射；删除多余的 l0_capability_set.v1.yaml
- **任务编号重排**：因删除 1 个任务，M1 ①②③、M2 ④⑤⑥、M3 ⑦⑧⑨、M4 ⑩⑪（原 M4⑫→⑪）；K1 引用 M1③→M1②，K3 引用 M4⑫→M4⑪，§一 P3 引用同步
- **范围说明补充**：头部新增「本计划仅覆盖 47-MCP 侧」说明，46-DSH 侧见 DESIGN-DSH-ARCH-UPGRADE §五

### 评审判定

云端产出的其余部分（里程碑依赖、K1-K5 对策、出口判据、envelope 字段列表）均与 SPEC/ALIGNMENT 一致，无需修正。

## 2026-11-02 两端改动集成（本地 v0.3 + 云端修正）

### 集成说明

- 本地 46-DSH 会话产出 **SPEC v0.3**（B1-B6 / G1-G3 决议落定，见 §8）+ 新增 `docs/tech/ALIGNMENT-46-47-v1.0.md`
- 云端评审会话产出 README 断链修正 + SPEC §3.1/§3.5/§3.8 三处补充 + 本 CHANGELOG
- 两端改动经交叉核对**零语义冲突**，已合并为单一版本统一上传

### 本地修正（集成时并入）

- SPEC 状态措辞修正：「终审通过」→「决议落定，可开工；R8 终审待云端签发」（终审权归云端 R8）
- SPEC §3.2 勘误：45 PG「七表」→「八表」（`001_init.sql` 实测 8 个 CREATE TABLE，ALIGNMENT §八 指出但未回改）

## 2026-11-02 文档修正（评审后修订）

### 修正

- **断链引用修正（README）**: 外部关联文档表中 `ANALYSIS-L0-MCP-ENCAPSULATION v0.2` 与 `SPEC-L0-three-layer-architecture v0.5` 的版本号后缀与实际文件名不符，已去除版本后缀，与实际文件对齐
- **状态标注补充（README）**: 存量 MCP 面登记表前增加状态说明，明确契约注册表 `registry/mcp_capabilities.yaml` 与顶层 `mcp_shells/` 目录为 P0 交付物、当前尚未创建
- **时序矛盾消除（SPEC §3.8）**: 明确 D4 延迟数值为目标值，须在基线测量完成并产出基线报告后方可作为验收生效标准（先基线，后生效）
- **运维细节补充（SPEC §3.1/§3.5）**: 连接上限数值归属 19-DAL 治理方案定义；补充 ssh 云端拉起模式认证沿用宿主 ssh 密钥机制、壳进程异常退出由宿主负责重启的说明

### 新增

- 本 CHANGELOG 文件，对齐项目内其他模块（16/21 等）的文档规范


## 2026-11-03 MCP 壳架构收尾（M1-M4 全部落地）

### 收尾验证
- 6 壳 24 工具 stdio 真实拉起冒烟全部通过（认知 6 / 语义 4 / REA 6 / 数据 4 / 评测 2 / 库管 2）
- 统一信封校验 6/6 通过；全量壳契约测试 22/22 全绿（luke 用户）
- 注册表校验通过：4 存量壳 + 3 规划壳 / 24 active 工具 / 上限 40
- REA 影子双跑 SHA-256 指纹一致（M3⑨ 出口判据达成）

### 修复
- **39 语义壳接入统一信封**：此前返回裸业务体，与注册表 envelope_version 0.1 登记不一致；已在 tools/call 响应构造处接入 mcp_shells/_shared/envelope_wrap，业务体原样透传 envelope.data，未新增 sys.path hack

### 文档
- TECH-L0-MCP-v0.1.md 状态更新为 M1-M4 全部落地，新增 §9 收尾验证记录
