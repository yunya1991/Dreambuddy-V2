# 9基本面 7 引擎 S/A 级 dao/tian Shadow Boost 实施方案 Tasks

> **关联 Spec**: [2026-08-29-fundamental-7engines-daotian-boost-spec.md](./2026-08-29-fundamental-7engines-daotian-boost-spec.md) v1.0 📝 Draft（待 Review → Approved）
> **总任务数**: 约 40 个可执行任务（P0-4 阶段1 TDD 15T → 阶段2 TDD 10T → 阶段3 运维观察 8T → 收尾 7T）
> **开发方法论**: **严格 TDD**（红 → 绿 → 重构 3 步）。每阶段开始前必须调用 `test-driven-development` Skill
> **风险级变更控制**: 所有代码变更通过 **PR + Code Review**（非紧急，Spec H9），不得直推 main
> **前置依赖**: P0-3 Odaily 阶段2 必须已完工（17 TC GREEN + polling_trader shadow 已激活）

---

## 任务依赖 DAG

```
阶段1 测试骨架 + 4 代理模块 RED（T01-T04）
  ├── T05  TC-1 None→0.0（红）→ T13 _fd_S_dao_boost 骨架（绿）
  ├── T06  TC-2 红线关字节一致（红）→ T14 2 行乘法守卫（绿）
  ├── T07  TC-3 S_dao 正命中（红）→ T15 D1~D5 算法实现（绿）
  ├── T08  TC-4 S_dao 负命中 + TC-5/6 S_tian 正负（红）→ T15 继续（绿）
  ├── T09  TC-7 S 级 clamp 边界（红）→ T16 clamp 外边界（绿）
  ├── T10  TC-8~12 A 级 5 项（红）→ T17 _fd_A_dao / _fd_A_tian 方法（绿）
  ├── T11  TC-13 乘法联合顶 clamp 80→100（红）→ T14 继续 + dao/tian 各守卫（绿）
  ├── T12  TC-14 单引擎 FAIL-OPEN（红）→ T18 各自独立 try/except（绿）
  └── T13  TC-15 fx_r3_sample 双点命中（红）→ 算法调参（绿）
          ↓ 15 TC ALL GREEN
         T19 阶段1 验收 & 代码风格 CR
          ↓
阶段2 测试骨架 + Shadow fixtures（T20）
  ├── T21  TC-1 红线默认 False（红）→ T27 类属性 + env __init__（绿）
  ├── T22  TC-2 JSONL 9+字段齐全（红）→ T28 _fd_7engines_shadow_compute（绿）
  ├── T23  TC-3 FD_NO_NEWS_BATCH（红）→ 同上 shadow 分支（绿）
  ├── T24  TC-4 FD_IMPORT_ERROR（红）→ T29 7 引擎 import try + import_fail_count（绿）
  ├── T25  TC-5 FD_PERMISSION（红）→ T30 JSONL append PermissionError 吞（绿）
  ├── T26  TC-6 FD_GENERIC_ERR / TC-7 Shadow 只读 / TC-8 engine_detail 齐全
  └── T26  TC-9 脚本 exit=2 样本不足 / TC-10 脚本 G4 FAIL exit=1（红）→ T31 fd7engines_hitrate_eval.py
          ↓ 10 TC ALL GREEN
         T32 阶段2 验收 & 7 门槛脚本 mock 样本验证
          ↓
阶段3 运维 & 7 日历天观察（T33-T40）
  ├── T33 创建空占位 JSONL runtime 目录
  ├── T34 start_trading.sh / polling_trader_live_300s.sh 注入 export FUND_7ENGINES_BOOST=1
  ├── T35 清 five_domain_state.json 缓存 + 重启 polling_trader（H10：战略层代码改后必重启）
  ├── T36 Day 1：shadow JSONL 开始写入；第一行 FD_OK；engine_detail S3_pass_rate ≥ 0.90
  ├── T37 Day 3：`wc -l` ≥ 400（预期 3d × 288 = 864，46% = 400 合格）；IMPORT_FAIL_total = 0
  ├── T38 Day 5：`wc -l` ≥ 1000；fd7engines_hitrate_eval.py 预跑观察 7 门槛实际值
  ├── T39 Day 7：`wc -l` ≥ 1500；正式跑 eval 脚本 → exit=0/1/2
  └── T40 门槛结果判定：
          - exit=0 → 进入 T41
          - exit=1 → 发 issue 列 FAIL 项清单 + 延 7 天，循环 T36-T39
          - exit=2 → 延 2 天累积样本
          ↓（exit=0 才进入）
收尾 T41-T47
  ├── T41 发起 PR1：代码无修改，仅附 7 门槛评估报告 + JSONL 产出摘要（用于 CR 讨论）
  ├── T42 Code Review 通过后，发起 PR2：改类属性 enable_fundamental_7engines_boost: bool = True
  ├── T43 PR2 合并 main → 清 five_domain_state.json → 重启 polling_trader（再次 H10）
  ├── T44 Day 1 生产验证：新代码 S/A boost 乘法守卫真启用；war_state cap 回升（若非仍 FREEZE）
  ├── T45 文档更新 5 文档：CHANGELOG(11/18) + ENGINEERING_INDEX(11/18) + DOC_DEBT_INDEX销项 + Spec/Taks/CheckList 状态改为 ✅ Approved / 🏗️ 已完成
  ├── T46 Day14 观测：thaw_count=3，war_state 从 FREEZE → COOLDOWN → ALLOW 转换；cap 从 20% → 50%
  └── T47 阶段复盘：P0-4 对庙算总分实际贡献率报告（7引擎 vs 仅Oday 3 delta 对比 A/B）
```

---

## 任务清单（约 40 主任务，按顺序执行）

### 🧪 P0-4 阶段1：4 代理模块 + S/A 4 boost 方法 + 2 乘法守卫（T01 ~ T19，TDD 循环，约 1.5 人天）
> **⚠️ TDD Skill 前置**：T01 开始前必须调用 `test-driven-development` Skill（新一轮 TDD）

| ID | 任务名 | 类型 | 文件路径 | 具体操作 | RED→GREEN 验证 |
|---|---|---|---|---|---|
| **T01** | 阶段1 测试脚手架 + 10 fixture | 新建测试 | `tests/test_fd7engines_stage1.py` | (a) 路径 import（与 test_odaily_booster_stage1.py 同 setup：THIS_DIR/_REPO/_COMPUTER_ROOT）；(b) fx_news_list_positive（30 条 BTC ETF 获批类正面假新闻 dict 列表）；(c) fx_news_list_negative（30 条 SEC 起诉/禁止类负面）；(d) fx_system_state_dao_up（含 dao_history_14=[42..62] 线性升 20 点）；(e) fx_system_state_dao_down（dao_history_14=[62..42] 线性降）；(f) fx_signal_engine_accurate（mock _adaptive_weight 返回 1.8 → w_ratio=1.8）；(g) fx_signal_engine_inaccurate（mock _adaptive_weight 返回 0.4 → w_ratio=0.4）；(h) fx_r3_sample（news_positive + state_dao_up + signal_accurate 三合一 fixture）；(i) fx_news_empty（[]，用于 TC-1）；(j) mocker 辅助函数 `mock_sqlite_news(n)` 构造假 DB 返回 N 条 | import 成功；10 fixture 定义加载（尚未写 TC） |
| **T02** | **RED 证据 1**：4 代理模块不存在 | 断言（测试写） | `tests/test_fd7engines_stage1.py`（顶部 conftest 级断言） | 在文件最顶部以 `# === T02 RED 证据：4 代理模块 NOT EXISTS ===` 区块写 4 行 pytest 启动前断言：`assert not Path("9-基本面分析/engines/event_ledger_engine.py").exists()`（4 条）→ 启动阶段必然 FAIL，证明 TDD 真的「测试先于代码」 | 运行 pytest → 4 个 NOT EXISTS 断言 FAIL（✅ RED 正确证据） |
| **T03** | 新建 4 代理模块（薄封装）+ 本地验证 7 引擎 import 实际成功 | 新建 4 个文件 | `9-基本面分析/engines/event_ledger_engine.py / event_mapping_engine.py / narrative_engine.py / news_contract_validator.py` | 每个代理模块模板：<br>```<br>import sys, os<br>_NANOCLAW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ops", "nanoclaw", "core_task1")<br>if _NANOCLAW not in sys.path: sys.path.insert(0, _NANOCLAW)<br>from scripts.event_ledger_generator import EventLedgerGenerator  # 对应路径<br>_INST = EventLedgerGenerator()<br>def generate_ledger(news_list):<br>    try:<br>        return _INST.generate_ledger(news_list)<br>    except Exception:<br>        return []<br>```<br>4 个代理各对应正确路径 + 正确对外函数签名（generate_ledger / map_event_type / build_narratives / validate_batch→pass_rate） | 手工 `python -c "from engines.event_ledger_engine import generate_ledger; print(generate_ledger([]))"` 4 件都 exit 0 无 ImportError → T02 RED 断言 4 NOT EXISTS 现在自然 PASS（✅ GREEN 了 RED） |
| **T04** | 再次 pytest：4 代理 NOT EXISTS 现在 ALL PASS；fixture 10 件加载 OK | 测试 | 同 T01 | `pytest tests/test_fd7engines_stage1.py -v` → 0 TC FAILED（因为还没写 TC）；fixture 无 SyntaxError | 0 failed |
| **T05** | TC-1 `fx_None / 空 news_list → S=0`（红）→ S 方法骨架（绿）| 红 → 绿 | 测试 + `five_domain_feature_computer.py` | **写 TC-1**：`_fd_S_dao_boost(None, {}) == 0.0`；`_fd_S_tian_boost({}, {empty_db_state}) == 0.0` → 运行 → FAILED（方法不存在）<br>**GREEN 实现**：新增 4 方法签名 `def _fd_S_dao_boost(self, cd, ss) -> float: try: return 0.0 except Exception: return 0.0`（4 方法均空壳 return 0.0，含外层 try/except）+ 新增 `_fetch_news_72h_limit200` 壳 return [] | FAILED → PASSED |
| **T06** | TC-2 红线关字节一致（红）→ 2 行乘法守卫（绿）| 红 → 绿 | 测试 + five_domain_feature_computer.py（dao L244 & tian L349 附近）| **写 TC-2**：构造 enable=False + coin_data fx_r3_sample → `compute() 结果 == baseline（预先保存未改代码版本 compute 结果 pickle 或固定值）` 字节完全 == → FAILED<br>**GREEN 实现**：_compute_dao 乘法行 `dao_raw = dao_raw * (1+pn) * (1+od)` 后加守卫 `if self.enable_fundamental_7engines_boost: dao_raw *= (1+self._fd_S_dao_boost(cd)) * (1+self._fd_A_dao_boost(cd,ss))`；tian 同理。注意**必须守卫**：enable=False 时乘 1 → 字节一致 | FAILED → PASSED（TC-2 字节 == 现在成立）|
| **T07** | TC-3 S_dao 正命中（红）→ D1~D5 算法实现（绿）| 红 → 绿 | 同上 | **写 TC-3**：mock `_fetch_news_72h_limit200` 返回 fx_news_list_positive（30 条正）；mock 5 S 引擎返回正向值（s_mean=+0.7 / r_diff=+0.6 / pass_rate=0.97 / crypto_reg_ratio=0.05 / monetary_ratio=0.3 + s_mean=+0.7→sign(+1) / t_mean=+0.6, n_cnt=4）；断言 `0.03 <= _fd_S_dao_boost(fx, {}) <= 0.10` → FAILED<br>**GREEN 实现**：按 Spec §4.2 表 D1~D5 逐项实现 + isinstance 守卫 + 各引擎独立 try/except；deltas=[D1..D5] sum；clamp [-0.1,0.1] round 6 | FAILED → PASSED |
| **T08** | TC-4 S_dao 负 / TC-5 S_tian 政策正 / TC-6 S_tian 紧急负（红）→ S_tian 方法继续实现（绿）| 红 → 绿 | 同上 | 写 3 个 TC：<br>TC-4（负新闻 30 条 + s_mean=-0.8, crypto_reg_ratio=0.5, t_mean=-0.7, n_cnt=5）→ S_dao ∈ [-0.10, -0.02]<br>TC-5（仅政策类新闻，p_cnt=7, s_policy_mean=+0.7, reg_traj=+0.6, evidence_score=0.9）→ S_tian ∈ [0.03, 0.10]<br>TC-6（urgent_ratio=0.5, avoid_ratio=0.4）→ S_tian ∈ [-0.08, -0.01]<br>统一 RED 后，按 Spec §4.3 T1~T5 逐项实现 S_tian；再跑三 TC → 全 GREEN | FAILED×3 → PASSED×3 |
| **T09** | TC-7 S 级 clamp 边界精确（红）→ 补 clamp 逻辑验证（绿）| 红 → 绿 | 同上 | **写 TC-7**：构造 5 引擎极端返回（s_mean=+1.0, r_diff=+1.0, pass_rate=1.0, crypto_ratio=0, monetary=1.0, s_mean_sign=+1, t_mean=+1.0, n_cnt=999→min(1.)）→ `_fd_S_dao_boost() == pytest.approx(0.10, abs=1e-6)`；相反极端 → `== -0.10`；S_tian 同理 2 个方向 clamp 精确 → 共 4 断言<br>若算法自然未到 ±0.10，用 monkeypatch 强制各 Dx=+0.05 共 5 项 sum=0.25 → 必须截到 0.10（验证 clamp 生效） | FAILED → PASSED |
| **T10** | TC-8~12 A 级 5 个（红）→ _fd_A_dao/_fd_A_tian 两方法（绿）| 红 → 绿 | 同上 | 写 5 TC：<br>TC-8（dao_hist_up）→ A_dao ∈ [0.005, 0.04]<br>TC-9（dao_hist_down）→ A_dao ∈ [-0.04, -0.005]<br>TC-10（全 50，neutral）→ A_dao ≈ 0.0 abs≤0.001<br>TC-11（SignalEngine w=1.8）→ A_tian ∈ [0.015, 0.02]<br>TC-12（w=0.4）→ A_tian ∈ [-0.02, -0.01]<br>RED 后，按 Spec §4.4/4.5 实现 A 两方法 | FAILED×5 → PASSED×5 |
| **T11** | TC-13 乘法联合顶 80→100 精确（红）→ 验证两行守卫 clamp（绿）| 红 → 绿 | 同上 | **写 TC-13**：构造 coin_data/system_state 让 _pn=+0.20（fx_pn_max）+ _od=+0.10（fx_od_max）+ _fd_S=+0.10（T09 已验证 clamp 输出 0.10）+ _fd_A=+0.05（A 极值）；enable=True；dao_raw 基线=80 → `dao_final = clamp(80×1.5246, 0,100) = 100 精确`；tian 同理基线=70 → `70×1.5246=106.722→100` 精确；另 dao_raw=30 取全下界 0.6156 → 18.47 合理（仍≥0 不报警） | FAILED → PASSED |
| **T12** | TC-14 单引擎 FAIL-OPEN 隔离（红）→ 7 引擎各自独立 try（绿）| 红 → 绿 | 同上 | **写 TC-14**：用 monkeypatch.setattr 分别单独把 S3 schema_validator 挡抛 ImportError / S5 NarrativeAnalyzer 挡抛 ValueError / A6 compute_resistance_3d 抛 RuntimeError（3 场景，各 1 TC 合并函数）→ 每次对应 delta=0，但**方法整体仍返回 float ∈ [-0.1, +0.1] 不抛**；S_dao/S_tian/A_dao 结果合法区间 | FAILED → PASSED（证明单引擎隔离成立）|
| **T13** | TC-15 fx_r3_sample 四点命中（红）→ 算法微调整参（绿）| 红 → 绿 | 同上 | **写 TC-15**：喂 fx_r3_sample 三合一 fixture；断言 4 点区间：<br>S_dao ∈ [0.04, 0.10] / A_dao ∈ [0.01, 0.04] / S_tian ∈ [0.04, 0.10] / A_tian ∈ [0.01, 0.02]<br>再加乘法精确差断言：`multiplier = (1+pn)×(1+od)×(1+S)×(1+A)` 与手工计算（保存 4 个实际 boost 值，算 (1+S)(1+A)）差 ≤ 1e-6<br>若初始断言 FAIL（差 0.001 区间），微调 §4 系数：例如 D1×0.06→0.065 或 T1×0.08→0.075（必须 Spec v1.0.1 补丁，不得无文档改系数）→ 最终 GREEN | 可能需 2-3 轮 → 最终 PASSED |
| **T14** | S/A 算法与 Odaily 代码风格 CR 检查 | CR | five_domain_feature_computer.py | 对齐 _od_dao_boost 写法：(a) 签名参数；(b) 顶层 isinstance(cd,dict) 判断；(c) 每个 Dx 前 isinstance(x,(int,float)) 守卫 if 分支，else 0.0；(d) deltas=[D1..D5] list + sum；(e) `return max(-0.1, min(0.1, round(total, 6)))` clamp + round 6 位；(f) 最外层 except Exception: return 0.0<br>差异点仅 S ∈[-0.1,0.1] / A ∈[-0.05,0.05] 范围不同（A 方法 clamp 独立 ±0.04/±0.02 后，再加 ±0.05 双保险） | CR 无风格红警 |
| **T15** | FAIL-OPEN 6 层全覆盖人工清单 + 覆盖率 check | 自检 + pytest-cov（若装了）| test_fd7engines_stage1.py | 核对 §6.1 L1~L6 各 1 TC：L6=TC-2 / L4=TC-1 / L3=mock news 返回空+TC-1 / L2=TC-14（import case）/ L1=TC-14（引擎内 value error 场景）/ L5 = 阶段2 TC-6（暂未写，阶段 1 结束仍 OK；阶段 2 补覆盖）<br>可选：`pytest --cov=five_domain_feature_computer tests/test_fd7engines_stage1.py` → 新增代码行覆盖率 ≥ 90% | 全覆盖证明文档化（附截图或 log） |
| **T16** | 阶段1 总跑 + 基线回归（无 Odaily TC 破坏） | 测试 | 11-易经推理系统/tests | 命令：`pytest tests/test_fd7engines_stage1.py tests/test_odaily_booster_stage1.py tests/test_odaily_engine_shadow_stage2.py -v` → 15+7+6 = **28 passed** | 28 passed, 0 failed；若回归失败，阶段 1 不能结束 |
| **T17** | 阶段1 验收 4 项（Spec §9 汇总 C 类）| 归档 | — | (a) 15 TC 全绿；(b) TC-15 r3_sample 4 点命中记录日志；(c) TC-2 字节一致 RED→GREEN 证据保留；(d) PR1（阶段1 代码）提交 GitHub，CR 无阻塞评论 → **Merge**（阶段 1 风险低，可先合并进 main 以不阻塞） | 归档 4 项验收证据 |
| **T18** | 阶段1 独立 Spec §7.1 7 个文件修改对照 Checklist 打勾 | 自检 | Spec §7.1 | 逐一核对：1. event_ledger ✔️ 2. event_mapping ✔️ 3. narrative ✔️ 4. news_contract_validator ✔️ 5. 4方法+2守卫✔️ 6. test 文件存在✔️ → 7/7 | 全部通过 |
| **T19** | TDD Skill 后处理：RED→GREEN 关键截图（至少 6 张）归档 | 归档 | runtime/spec_evidence/ | 保存：(1) T02 4 NOT EXISTS FAIL；(2) T05 TC-1 FAIL → green；(3) T07 TC-3 FAIL → green；(4) T10 TC-8~12 ×5 FAIL → green；(5) T12 TC-14 FAIL → green；(6) T16 28 passed 总截图 | 6 张 PNG 存目录 |

### 🧪 P0-4 阶段2：Shadow 红线审计 + JSONL + 7 门槛脚本（T20 ~ T32，约 1.0 人天 + 7 观察日，TDD 循环）
> **⚠️ TDD Skill 前置**：T20 开始前必须重新调用 `test-driven-development` Skill（新一轮 TDD）

| ID | 任务名 | 类型 | 文件 | 操作 | RED→GREEN 验证 |
|---|---|---|---|---|---|
| **T20** | 阶段2 脚手架 + 9 fixture | 新建测试 | `tests/test_fd7engines_shadow_stage2.py` | (a) 沿用 _mk_computer(tmp_path, shadow_enable, override_jsonl_path) 构造函数（复制 Odaily 版本，改 od → fd）；(b) fx_fd_r3_sample 标准正向 coin_data+system_state；(c) fx_news_5items（仅 5 条新闻，触发 FD_NO_NEWS_BATCH）；(d) monkeypatch_builtin_import 挡 4 代理（触发 FD_IMPORT_ERROR）；(e) monkeypatch_permission_error（open jsonl a 模式抛）；(f) monkeypatch_fetch_news_runtimeerror（DB 查抛 RuntimeError → FD_GENERIC_ERR）；(g) fx_fd_2000_ok（2000 条手造 FD_OK 最小 JSONL 样本，用于 eval）；(h) fx_fd_2000_fail_g4（2000 条中 1 条 import_fail_count=1）；(i) fx_fd_10items（10 条样本，exit=2 预期） | import OK；fixture 9 件定义加载 |
| **T21** | TC-1 红线默认 False（红）→ 类属性 + env 读取（绿）| 红 → 绿 | 测试 + five_domain_feature_computer.py | **写 TC-1**：`assert FiveDomainFeatureComputer.enable_fundamental_7engines_boost is False`（✅ 类属性红线必 False）；再构造 enable=False，喂 fx_r3_sample；compute() → JSONL 文件**未被创建**（`os.path.exists`=False）；结果字节等于 baseline | FAILED → GREEN（在 __init__ 里加 FUND_7ENGINES_BOOST env 读取 + 类属性 False 已写在阶段1？若阶段1 没写类属性，这里 RED → GREEN 写） |
| **T22** | TC-2 JSONL 9+字段齐全 + FD_OK（红）→ _fd_7engines_shadow_compute 主函数（绿）| 红 → 绿 | 测试 + five_domain_feature_computer.py | **写 TC-2**：enable=True + fx_fd_r3_sample → compute()；JSONL 文件存在 → 读取 line 1 → 9 字段齐全（ts_ms int/asset_class_cnt=3/coin_classes=3list/S_dao/S_tian/A_dao/A_tian 均 float/shadow_reason_code=str FD_OK/import_fail_count=0 int/engine_detail dict 存在且含 S1_sent_mean 等 ≥10 个子键）；**额外关键断言**：enable=True vs False 两次 compute → `result_true == result_false`（Shadow 只读不改结果！这是 TC-7 的合并，TC-7 单独再验证一遍严格字节）| FAILED → 实现 shadow_compute：sys.path 9基本面 insert + 读 coin_data 跨类 boost 均值 + engine_detail 构造 + JSONL append → 9+字段齐全 → PASSED |
| **T23** | TC-3 FD_NO_NEWS_BATCH（红）→ shadow news_len<10 分支（绿）| 红 → 绿 | 同 | 写 TC-3：monkeypatch._fetch_news_72h_limit200 返回 5 条 → JSONL line 1 reason=FD_NO_NEWS_BATCH；S/A mean=0.0；import_fail=0 | FAILED → 在 shadow_compute 先查 len(news_list)<10 → FD_NO_NEWS_BATCH 分支赋值 → GREEN |
| **T24** | TC-4 FD_IMPORT_ERROR（红）→ 7 引擎 import 计数（绿）| 红 → 绿 | 同 | 写 TC-4：用 monkeypatch 挡 4 代理 import（ImportError）→ shadow reason=FD_IMPORT_ERROR；import_fail_count ≥ 1 且 ≤ 7 | FAILED → shadow_compute 首步做 7 引擎 import 存在性检查，失败数累加 import_fail_count，原因码覆盖写 IMPORT_ERROR → GREEN |
| **T25** | TC-5 FD_PERMISSION（红）→ JSONL open 抛 PermissionError 吞（绿）| 红 → 绿 | 同 | 写 TC-5：mock open 抛 PermissionError → compute() 顶层不抛任何异常；result 字节 == baseline（TC-2 baseline） | FAILED → shadow_compute 末尾 JSONL append 加 try/except (OSError, PermissionError) → pass 吞；并在 record dict 内改 reason = FD_PERMISSION（即使写不下，record 变量内仍保留原因码供日志）→ GREEN |
| **T26** | TC-6 FD_GENERIC_ERR + TC-7 Shadow 只读 + TC-8 engine_detail 数值合法（红）→ 3 合并实现（绿）| 红 → 绿 | 同 | 写 3 个 TC：<br>TC-6（monkeypatch 内部函数抛 RuntimeError）→ 顶层不抛；JSONL line 1 原因码=FD_GENERIC_ERR；import_fail=0<br>TC-7（enable=True/False 分别跑 compute 2 次）→ `result_true == result_false` 字节全等 assert<br>TC-8（对 TC-2 的 FD_OK line 读 engine_detail）→ 断言 S3_pass_rate∈[0,1] / A6_direction_sign∈{-1,0,1} / A7_w_ratio ∈ [0.3, 2.0] / news_batch_size ≥ 10 | FAILED×3 → GREEN×3（通过补 shadow_compute 大 try 吞 + 不改 result + engine_detail 每值 isinstance 守卫 + clamp 合法范围） |
| **T27** | TC-9 脚本退出码=2（样本不足）+ TC-10 脚本 G4 FAIL exit=1（红）→ fd7engines_hitrate_eval.py（绿）| 红 → 绿 | 新建脚本 `scripts/memory_l4/fd7engines_hitrate_eval.py` + 测试 | **TC-9**：`subprocess.run([py, script_path, "--jsonl", tmp_10.jsonl])` → rc==2；stdout 含「样本」「⏳」字样<br>**TC-10**：写 fx_fd_2000_fail_g4（2000 条，1 条 import_fail_count=1）→ subprocess rc==1；stdout grep "G4_IMPORT_FAIL_total" 行含 "FAIL" 字样<br>RED 后，实现 fd7engines_hitrate_eval.py（结构对齐 odaily_shadow_hitrate_eval.py：读 JSONL → 7 门槛 7 项计算 → 表格打印 + 报告 JSON → 退出码 0/1/2）；7 门槛按 Spec §5.4 公式严格实现 | FAILED×2 → GREEN×2 |
| **T28** | fd7engines_hitrate_eval.py 退出码=0 全 PASS 验证（用手造完美样本 2000 条）| 断言 | 脚本目录 | 新建 fx_fd_2000_perfect（2000 FD_OK 行，7 门槛全部超阈值：hit=0.75/thaw=0.85/sharpe=1.3/IMP=0/S=0.88/A=0.78/SCHEMA=0.98）→ subprocess → rc=0；stdout 7 行 PASS；报告 JSON ALL_PASS=true | 48 退出码全通过 |
| **T29** | JSONL 空占位 runtime 目录创建 | 新建 | scripts/runtime/ | `mkdir -p scripts/runtime`（若不存在）；`touch scripts/runtime/fundamental_7engines_records.jsonl`；若 .gitignore 未含 runtime，加一行 `11-易经推理系统/scripts/runtime/*.jsonl`（保留 .gitkeep 或其他） | 0B 空文件存在，`wc -c = 0` |
| **T30** | 阶段2 总跑 + 三文件回归（阶段1+Odaily）| 测试 | tests 目录 | `pytest tests/test_fd7engines_stage1.py tests/test_fd7engines_shadow_stage2.py tests/test_odaily_booster_stage1.py tests/test_odaily_engine_shadow_stage2.py -v` → 15+10+7+6 = **38 passed** | 38 passed, 0 failed；任何回归失败，阶段 2 不结束 |
| **T31** | 7 门槛 mock 完美样本脚本运行日志保存归档 | 归档 | runtime/spec_evidence/ | 保存 T28 7 门槛完美 PASS 终端截图；T29 38 passed 总截图；TC-7 字节 == 证据 | 3 项证据归档 |
| **T32** | 阶段2 提交 PR2，CR 通过后 Merge main | CR → merge | GitHub | PR 标题：「P0-4 阶段2：7引擎 Shadow 审计 + 7门槛 + JSONL 10 TC GREEN」 | CR 通过 → Merge |

### 🧪 P0-4 阶段3：运维 & 7 日历天观察（T33-T40，约 7 天）

| ID | 任务名 | 操作 | 验证 |
|---|---|---|---|
| **T33** | 空占位 JSONL 路径存在确认 | `ls -la 11-易经推理系统/scripts/runtime/fundamental_7engines_records.jsonl` | size=0 |
| **T34** | start_trading.sh + polling_trader_live_300s.sh 注入 env FUND_7ENGINES_BOOST=1 | 编辑两个 sh 文件，在其他 export（如 ODAILY_ENGINE_BOOST=1）之后加一行：`export FUND_7ENGINES_BOOST=1` | `grep -n FUND_7ENGINES_BOOST start_trading.sh polling_trader_live_300s.sh` 输出两行 |
| **T35** | 战略层代码改后重启（H10 硬约束！）| (a) `rm scripts/runtime/five_domain_state.json`（清内存缓存）；(b) 查旧 PID `ps aux \| grep polling_trader \| grep -v grep → <OLD_PID>`；(c) kill <OLD_PID>；(d) 后台启动 `nohup ./polling_trader_live_300s.sh &`；(e) 30 秒后查新 PID：`ps aux \| grep polling_trader \| grep -v grep` → 新 PID 存在 | 新 PID 启动后 `echo $?`=0；无 Traceback；`wc -l scripts/runtime/fundamental_7engines_records.jsonl` 在 300s 后 ≥ 1 |
| **T36** | **Day 1** 生产 Shadow 首条 OK 验证 | 等 300s+ 后；`tail -1 scripts/runtime/fundamental_7engines_records.jsonl | python -m json.tool` → (a) shadow_reason_code = FD_OK；(b) import_fail_count=0；(c) engine_detail.S3_pass_rate ≥ 0.90；(d) S_dao_boost_mean 为小正数（或负数也可，只要 ≠0 非 NaN）；另：`wc -l scripts/runtime/odaily_engine_boost_records.jsonl` 仍继续增长（Oday 独立 shadow 并行 ✅） | 4 项 + odaily 并行 5 项全满足 |
| **T37** | **Day 3** 中期检查 | (a) `wc -l fundamental_7engines_records.jsonl` ≥ 400（3d×288×46%=400）；(b) `python -c "import json; [print(l['shadow_reason_code'], l.get('import_fail_count',0)) for l in [json.loads(line) for line in open('fundamental_7engines_records.jsonl')]]" \| sort \| uniq -c` → 分布 > 80% FD_OK，<1% IMPORT_ERROR；(c) IMPORT_FAIL_total 累加 = 0（G4 门禁） | 3 项通过 |
| **T38** | **Day 5** 7 门槛预跑观察（非最终）| `cd scripts/memory_l4 && python3 fd7engines_hitrate_eval.py --jsonl ../runtime/fundamental_7engines_records.jsonl` → 打印 7 门槛实际值（样本≈1440 → 可能仍 exit=2 或刚好 ≥1500 exit=1）。记录 G1~G7 每一项的实际值；若 G5 S_ACCURACY 或 G6 A_CONSISTENCY 仅 < 阈值 ≤ 3pp，说明算法可用但需要更大量样本，不做代码修改，仅延长观察 2 天 | 预跑报告保存 `runtime/spec_evidence/day5_7gate_report.json` |
| **T39** | **Day 7** 正式评估 | `wc -l JSONL` ≥ 1500（7d×288×75%=1500 标准）；再次跑 eval 脚本 → exit 三选一：<br>• **exit=0 全 PASS** → 恭喜！进入收尾 T41<br>• **exit=1 有 FAIL** → 打印 FAIL 的具体门槛项；发 issue 列根因分析 + 延 7 天（T36-T39 循环）<br>• **exit=2 样本不足** → 延 2 天重跑（可能 polling_trader 周末低频或重启导致丢条） | 正式报告 `runtime/spec_evidence/day7_7gate_final_report.json` 归档 |
| **T40** | 结果判定 + 后续动作（含延期分支）| 按 exit=0/1/2 分别处理；延长期每天运行 eval，直到 exit=0 连续 2 次或判定算法需修复；若连续 21 天 ≥ exit=1，发起 Spec v1.1 修订（降低 G5/G6 阈值，PR+CR 批准后重试） | 决策文档化；延期则 Tasks 追加 T40a/T40b/T40c 三天观察循环 |

### 🏁 收尾：PR+CR 开开关 + 文档 + 观测（T41-T47）

| ID | 任务名 | 操作 | 验证 |
|---|---|---|---|
| **T41** | PR1：评估报告提交（仅文档，不改代码）| GitHub PR，仅 Markdown，附 Day5 + Day7 两个 JSON 报告链接 + Shadow 样本统计（总条数/原因码分布/7门槛表格）；供讨论 7 门槛验证过程 | CR 通过（或 NIT 修改后通过） |
| **T42** | PR2：开开关 | 修改 five_domain_feature_computer.py 类属性 `enable_fundamental_7engines_boost: bool = True`；附带报告路径注释；发起 PR + CR | CR 通过 → Merge main |
| **T43** | 部署：清缓存 + 重启 polling_trader | `rm scripts/runtime/five_domain_state.json` → kill 旧 → 启动新 → 30s 后 PID 存在（H10 重做一遍，开关改类属性属于战略层核心代码，必重启）| PID 新；`grep enable_fundamental_7engines_boost scripts/memory_l4/five_domain_feature_computer.py | head -1` → 显示 True |
| **T44** | **Day 1** 生产真开启验证 | (a) `python -c "from five_domain_feature_computer import FiveDomainFeatureComputer as F; print(F.enable_fundamental_7engines_boost)"` → True；(b) compute() 实际 dao/tian 与开启前（手动设 enable=False）跑 baseline 对比 → 数值差在 1-5 分（S/A 注入生效，不是 0）；(c) war_state cap 若仍 FREEZE（预期仍可能几日），但 dao/tian 子项分已上升 2-3 分（SQL 或日志里能查到） | 3 项通过 |
| **T45** | 文档更新（T-DOC，5 文档 + Spec 三件套状态更新）| 1. 11/CHANGELOG.md 追加 v4.5.2：P0-4 7 引擎挂载 40T 完工 / 开启方式 / 验证结果；2. 11/ENGINEERING_INDEX.md 新增 4 方法 + shadow_compute + 4 代理模块职责；3. 9基本面/ENGINEERING_INDEX.md （若存在）新增 4 代理模块说明；4. DOC_DEBT_INDEX.md（若存在"9基本面引擎未挂载到五计层"项）销项；5. 本 Spec/Tasks/CheckList 头部状态改为 `✅ Approved → 🏗️ 已落地`，附最终 PR 号、日期 | 5+3=8 处文档更新提交 PR → Merge |
| **T46** | **Day 14** thaw_count=3 解冻观测 | `cat scripts/runtime/five_domain_state.json \| python3 -c "import json,sys;d=json.load(sys.stdin); print(d['_by_class']['crypto_usdt'].get('thaw_count','N/A'), d['_by_class']['crypto_usdt']['war_state'])"` → thaw_count ≥ 3 & war_state = ALLOW（或至少 COOLDOWN → ALLOW 转换中）；cap ≥ 0.50（50%~80%档）| 记录截图；若未跨 60（仍 FREEZE），延 3 天再观察并记录 |
| **T47** | 复盘报告：P0-4 7 引擎实际贡献 A/B 对比 | 生成 A/B 报告：(a) 仅启用 pn×od 基线的 14 天庙算均值 / 档位分布；(b) 叠加 pn×od×fd_S×fd_A 真开启的 14 天：dao/tian 子项差、总分提升、war_state 档位转换次数、Day14 thaw_count 是否≥3；(c) 7 引擎 4 boost 每日均值时间序列折线图；(d) 与 Spec §Executive Summary「Day 7 总分提升 2-3 分 / Day10-12 跨 60」预期对比 → 结论写入 11/CHANGELOG.md v4.5.2 附录 | 报告存 `docs/superpowers/performance_reports/2026-09-12-p0-4-7engines-ab-comparison.md`（或对应实际日期） |

---

## 任务完成度追踪表（动态更新，实施时每完成 1T 打 ✅）

| ID | 任务 | 阶段 | 预估耗时 | 状态 | 验证记录 |
|---|---|---|---|---|---|
| T01 | 阶段1 脚手架 10 fixture | 阶段1 | 20min | ⬜ | |
| T02 | RED 证据：4 代理模块 NOT EXISTS | 阶段1 | 5min | ⬜ | |
| T03 | 新建 4 代理模块薄封装 | 阶段1 | 40min | ⬜ | |
| T04 | T02 PASS 确认 + fixture 加载 | 阶段1 | 5min | ⬜ | |
| T05 | TC-1 None→0.0（红）→ 4 方法骨架（绿）| 阶段1 | 30min | ⬜ | |
| T06 | TC-2 红线关字节一致（红）→ 2 行乘法守卫（绿）| 阶段1 | 30min | ⬜ | |
| T07 | TC-3 S_dao 正命中（红）→ D1~D5 算法（绿）| 阶段1 | 50min | ⬜ | |
| T08 | TC-4/5/6 S_dao 负/S_tian 正/S_tian 负（红）→ S_tian 实现（绿）| 阶段1 | 60min | ⬜ | |
| T09 | TC-7 S 级 clamp 边界精确（红）→ GREEN | 阶段1 | 20min | ⬜ | |
| T10 | TC-8~12 A 级 5 项（红）→ A 两方法（绿）| 阶段1 | 50min | ⬜ | |
| T11 | TC-13 乘法联合顶 80→100 精确（红）→ GREEN | 阶段1 | 25min | ⬜ | |
| T12 | TC-14 单引擎 FAIL-OPEN 隔离（红）→ 独立 try（绿）| 阶段1 | 30min | ⬜ | |
| T13 | TC-15 fx_r3_sample 四点命中（红）→ 调参（绿）| 阶段1 | 40min | ⬜ | |
| T14 | 风格 CR 对齐 Odaily 写法 | 阶段1 | 20min | ⬜ | |
| T15 | FAIL-OPEN 6 层全覆盖检查 + 覆盖率 | 阶段1 | 15min | ⬜ | |
| T16 | 阶段1 + Odaily 28 TC 总回归 | 阶段1 | 5min（跑 pytest） | ⬜ | |
| T17 | 阶段1 验收 4 项归档 | 阶段1 | 10min | ⬜ | |
| T18 | Spec §7.1 7 文件修改对照打勾 | 阶段1 | 5min | ⬜ | |
| T19 | 6 张 RED→GREEN 证据截图归档 | 阶段1 | 10min | ⬜ | |
| T20 | 阶段2 脚手架 9 fixture | 阶段2 | 25min | ⬜ | |
| T21 | TC-1 红线默认 False（红）→ 类属性 + env（绿）| 阶段2 | 25min | ⬜ | |
| T22 | TC-2 JSONL 9+字段齐全（红）→ shadow_compute（绿）| 阶段2 | 60min | ⬜ | |
| T23 | TC-3 FD_NO_NEWS_BATCH（红）→ 分支（绿）| 阶段2 | 20min | ⬜ | |
| T24 | TC-4 FD_IMPORT_ERROR（红）→ import 计数（绿）| 阶段2 | 30min | ⬜ | |
| T25 | TC-5 FD_PERMISSION（红）→ 吞异常（绿）| 阶段2 | 20min | ⬜ | |
| T26 | TC-6/7/8 三TC（红）→ 三实现（绿）| 阶段2 | 40min | ⬜ | |
| T27 | TC-9/10 eval 脚本 exit=2/1（红）→ fd7engines_hitrate_eval.py（绿）| 阶段2 | 90min | ⬜ | |
| T28 | eval exit=0 完美样本验证 | 阶段2 | 20min | ⬜ | |
| T29 | JSONL 空占位 runtime 目录创建 | 阶段2 | 2min | ⬜ | |
| T30 | 阶段2 + 阶段1 + Odaily 38 TC 总回归 | 阶段2 | 6min（跑 pytest） | ⬜ | |
| T31 | 7 门槛全PASS日志 + 总回归截图归档 | 阶段2 | 10min | ⬜ | |
| T32 | 阶段2 PR CR + Merge main | 阶段2 | 1d CR | ⬜ | |
| T33 | JSONL 空占位路径确认 | 阶段3 | 1min | ⬜ | |
| T34 | sh 注入 export FUND_7ENGINES_BOOST=1 | 阶段3 | 5min | ⬜ | |
| T35 | 清 five_domain_state.json + 重启 polling_trader | 阶段3 | 5min 操作 + 5min 观察 | ⬜ | |
| T36 | Day 1 Shadow 首条 OK 验证 | 阶段3 | 300s 等待 + 10min 检查 | ⬜ | |
| T37 | Day 3 中期检查 | 阶段3 | 10min | ⬜ | |
| T38 | Day 5 7 门槛预跑观察 | 阶段3 | 15min | ⬜ | |
| T39 | Day 7 正式评估 exit=0/1/2 | 阶段3 | 15min | ⬜ | |
| T40 | 判定 + 延期或进入收尾 | 阶段3 | 5min 决策 + 延期循环 | ⬜ | |
| T41 | PR1：7 门槛评估报告提交（文档）| 收尾 | 20min 写 + CR | ⬜ | |
| T42 | PR2：开开关 enable=True | 收尾 | 改 1 行 + CR | ⬜ | |
| T43 | 部署：清缓存 + 重启 | 收尾 | 10min | ⬜ | |
| T44 | Day 1 生产开启真验证 | 收尾 | 15min | ⬜ | |
| T45 | 5 文档更新 + Spec 三件套状态更新 | 收尾 | 60min | ⬜ | |
| T46 | Day14 thaw_count=3 解冻观测 | 收尾 | 5min 查 JSON | ⬜ | |
| T47 | A/B 对比复盘报告 + CHANGELOG 附录 | 收尾 | 60min | ⬜ | |
