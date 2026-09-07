# 五计政策维度补全 + Odaily 采集器集成 实施方案 Tasks

> **关联 Spec**: [2026-08-29-odaily-policy-tian-integration-spec.md](./2026-08-29-odaily-policy-tian-integration-spec.md) v1.0 ✅ Approved
> **总任务数**: 20 个可执行任务（按 P0-1 → P0-2 TDD → P0-3 阶段1 TDD → P0-3 阶段2 TDD 顺序执行）
> **开发方法论**: TDD 循环（红 → 绿 → 重构 3 步），详见 Spec §4.7/§5.4 单测清单
> **风险级变更控制**: 所有代码变更通过 PR + Code Review（非紧急，memory H6 硬约束），P0-1 运维可直接操作

---

## 任务依赖图（DAG）

```
T01 ─┬─ T02 ─── T03 ─── T04 ─── T05 ─── T06 (P0-1 运维 6T, 0.1d, 串行)
     │
     └─ T07 (建 TDD 脚手架 + 5 fixture)
           ├── T08  TC-1 正常20条（红）→ T13 OdailyNewsflashCollector 类骨架 → T08 绿
           ├── T09  TC-2 增量去重（红）→ T14 checkHasNew + lastId 逻辑 → T09 绿
           ├── T10  TC-3 event_type 分布（红）→ T15 关键词正则(14+7类) → T10 绿
           ├── T11  TC-4 网络超时 fail-open（红）→ T16 requests.Session 封装 → T11 绿
           └── T12  TC-5 ImportError 中性（红）→ T17 sentiment lazy import 兜底 → T12 绿
                    ↓ (5 TC 全绿 → P0-2 collector 代码完成)
                   T18 Registry + Scheduler + sources.yaml 注册（4 处文件）
                    ↓
                   T19 FiveDomainSqliteReader §ODAILY 9 字段派生 + policy_sentiment_score 覆盖写
                    ↓
                   T20 P0-2 7 项验收（§4.8 1-7项，含 --once + 增量去重 + fail-open）
                    ↓
T07 TDD 脚手架（复用）+ 7 fixture 扩展
  ├── T21  TC-1 None 0.0（红）→ T26 _od_dao_boost 骨架 → T21 绿
  ├── T22  TC-2 正 delta（红）→ T27 D1/D2/D3 算法 → T22 绿
  ├── T23  TC-3 负 delta（红）→    同上               → T23 绿
  ├── T24  TC-4 tian 宽松（红）→ T28 _od_tian_boost D1/D2/D3 → T24 绿
  ├── T25  TC-5 地缘≥3（红）→          同上            → T25 绿
  ├── T26(已合并) ↓ + TC-6 乘法上限 + TC-7 异常 fail-open
                   T29 2 行乘法叠加（diff / dao L214 / tian L313）
                    ↓
                   T30 P0-3 阶段1 4 项验收（R3 sample + None 字节一致 + style CR）
                    ↓
T07 TDD 脚手架 + 6 fixture 扩展（P0-3 阶段2）
  ├── T31 TC-1 enable=False 红线（红）→ T37 shadow 代码块 if enable guard → T31 绿
  ├── T32 TC-2 ImportError 阻塞（红）→ T38 lazy import try + 24h blocked var → T32 绿
  ├── T33 TC-3 JSONL 8 键（红）→ T39 _od_engine_shadow_compute R4 4.2 7 步 → T33 绿
  ├── T34 TC-4 lifecycle growing（红）→   同上  Step 2.2 narrative → T34 绿
  ├── T35 TC-5 3D stress 0.8（红）→   同上 Step 2.3 three_dee → T35 绿
  └── T36 TC-6 PermissionError（红）→ T40 _shadow_jsonl_append try/except → T36 绿
           ↓ (6 TC 全绿)
          T41 JSONL 空占位 runtime 目录创建 + odaily_shadow_hitrate_eval.py 脚本
           ↓
          T42 P0-3 阶段2 8 项验收（红线 + 6 TC + 7 天门槛 + 文档更新）
```

---

## 任务清单（20 个主任务，按顺序执行）

### 🛠️ P0-1：launchd 调度器运维启动（T01-T06，0.1 人天，串行，无代码改）

| ID | 任务名 | 操作 | 验证通过标准 | 关联 Spec |
|---|---|---|---|---|
| **T01** | 环境预检 | ① `sw_vers -productVersion` 判断 launchctl 命令版本；② `/opt/anaconda3/bin/python3 -c "import data_center"` import OK；③ `mkdir -p 18-数据获取中心/logs`；④ touch DB + chmod 644 | 全 exit 0，无 error | Spec §3.2 Step ① |
| **T02** | 前台 --once 验证 | `cd 18-数据获取中心 && /opt/anaconda3/bin/python3 data_center_scheduler.py --once 2>&1 \| tee logs/once_verify_<epoch>.log` | 任务数≥8，全部 status=SUCCESS；panewslab≥60 条 + stablecoin≥2 条；quality.py 0 CONTRACT_INVALID/DUPLICATE | Spec §3.2 Step ② |
| **T03** | 拷贝 plist 到 LaunchAgents | `cp 18-数据获取中心/launchd/com.dreambuddy.data-center-scheduler.plist ~/Library/LaunchAgents/com.dreambuddy.dc-scheduler.plist` | `test -f ~/Library/LaunchAgents/com.dreambuddy.dc-scheduler.plist && ls -l` 确认存在 | Spec §3.2 Step ③ |
| **T04** | 加载 plist | macOS≥13 → `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.dreambuddy.dc-scheduler.plist`；<13→`launchctl load ...` | 命令 exit 0；无 Bootstrap failed | Spec §3.2 Step ③ |
| **T05** | 健康检查 3 次（每 5min） | ① `launchctl list \| grep dc-scheduler` → PID≠- Status=0；② `tail scheduler.log` WAKEUP 行存在；③ `wc -c err.log` <1KB | 3 次检查全部通过 | Spec §3.2 Step ④ |
| **T06** | 热路径安全验证 | （若 polling_trader 在运行）检查 polling_trader PID 不变，五维 shadow 验证无异常；否则 `python3 -c "from polling_trader import FiveDomain; FiveDomain().compute()"` 无 throw | 无 crash，无 error 日志 | Spec §3.3 第6项 |

### 🧪 P0-2：Odaily 采集器实装（T07-T20，1.5 人天，严格 TDD：红→绿→重构）
> **TDD skill 前置调用**：开始 T07 前必须调用 test-driven-development skill

| ID | 任务名 | 类型 | 文件路径 | 具体操作 | 验证（红→绿） |
|---|---|---|---|---|---|
| **T07** | TDD 脚手架 + 5 fixture | 新建测试 | `18-数据获取中心/tests/news/test_odaily_collector.py` | ① import 路径、conftest、fixture 准备；② fx_odaily_20_items_http_200：mock requests 返回 R3 验证 20 条 JSON；③ fx_last_id_max：mock checkHasNew lastId=513727 → data=0；④ fx_policy_items_batch：mock 4 条政策新闻（各含 1 类关键词）；⑤ requests.Session  monkeypatch helper | 5 fixture 定义加载成功，import OK（还没写 TC） |
| **T08** | TC-1 正常 20 条响应（红）→ Collector 骨架（绿） | 先写 TC（红） | 同 T07 | 写 test_fetch_20_items_ok → 运行 → **FAILED**（import 不存在）；然后新建 `data_center/collectors/news/odaily_newsflash.py` 空 `OdailyNewsflashCollector(BaseCollector)`，类属性 source/category；fetch 返回空列表→先能 import；再实现 fetch 读 HTTP→20 条→`DataRecord` 构造→再跑 TC→**5 passed**（20 条 / contract 全过 / metrics 正确） | FAILED → PASSED |
| **T09** | TC-2 增量去重（红）→ lastId 逻辑（绿） | 红 → 绿 | 同 T07 + T08 文件 | 写 test_incremental_no_new → FAILED；实现 fetch(params) 中先调 checkHasNew → data=0 直接 return []；再次跑 TC-2 | FAILED → PASSED |
| **T10** | TC-3 event_type 分布（红）→ 关键词正则（绿） | 红 → 绿 | 同 | 写 test_event_type_keyword_hit → FAILED；在 Collector 类内加 _POLICY_KEYWORDS(14)+EVENT_TYPE_MAP(7)+_DECAY_HRS(4) 三个常量；实现 _infer_event_type(text) 函数返回 7 类之一；TC-3 断言 4 类分布 Counter | FAILED → PASSED |
| **T11** | TC-4 网络超时 fail-open（红）→ Session 封装（绿） | 红 → 绿 | 同 | 写 test_network_timeout_fail_open（monkeypatch Session.get 抛 Timeout）→ FAILED；Collector._get_session() + try/except requests.exceptions → return []；TC-4 断言空列表无抛 | FAILED → PASSED |
| **T12** | TC-5 ImportError sentiment 中性（红）→ lazy import 兜底（绿） | 红 → 绿 | 同 | 写 test_import_error_sentiment_neutral（monkeypatch builtins.__import__ 挡 sentiment_engine）→ FAILED；Collector._lazy_sentiment_score(text) 内 lazy import，try/except→score=0.0；metrics 算 od_policy_sentiment_0_1 兜底 0.5；TC-5 断言全=0.5 | FAILED → PASSED |
| **T13** | Collector 代码重构与 lint | 重构（TDD 第三步） | 同 T08 文件 | ① 抽 _get / _check_has_new / _fetch_page / _infer_attention_type 4 个函数；② 所有常量大写并加 docstring；③ 10s timeout 常量；④ 与 GdeltCollector 代码风格对齐（行宽 88 / import 排序 / f-string） | `pytest test_odaily_collector.py -v` 仍 5 passed + `ruff lint` 0 warning |
| **T14** | Registry 注册 + import | 修改 | `data_center/core/dispatcher.py` `_register_defaults` | 加 1 行 `from data_center.collectors.news.odaily_newsflash import OdailyNewsflashCollector` + `reg.register("news", "odaily_newsflash", OdailyNewsflashCollector)`；位置在 gdelt/tavily/feedparser 之后 | `DataCenter().list_collectors()` → 含 `('news', 'odaily_newsflash')` |
| **T15** | sources.yaml 加启用 | 修改 | `config/sources.yaml` news 块末尾 | 加 2 行：`odaily_newsflash: enabled: true`；缩进与其他 news 源对齐（YAML 2 空格） | yaml.safe_load 解析成功，news.odaily_newsflash.enabled=True |
| **T16** | Scheduler 注册任务 | 修改 | `data_center/scheduler.py` `default_tasks()` 尾部 | 加 4 行：CollectionTask(name="odaily_newsflash_latest", category="news", source="odaily_newsflash", params={"route": "latest"}, interval_sec=14400)；interval 对齐 panewslab route=all（4hr） | `default_tasks()` 返回 list 里 odaily task interval=14400，params route=latest |
| **T17** | 前台 --once 采集验证 | 运维 | `cd 18-数据获取中心 && python3 data_center_scheduler.py --once 2>&1 \| tee logs/once_verify_odaily_<epoch>.log` | 任务 odaily_newsflash_latest status=SUCCESS；metrics.records_count ∈ [15, 20]（首屏 20 条减去 lastId 过滤后的合理范围） | Spec §4.8 第 2 项 |
| **T18** | FiveDomainSqliteReader：SELECT IN + §ODAILY 派生 9 字段 + policy_sentiment_score 覆盖写 | 修改 | `11-易经推理系统/scripts/memory_l4/five_domain_sqlite_reader.py` | ① L92-94 SELECT IN 加 'odaily_newsflash'（位置在 theblockbeats_dataview 后）；② §blockbeats 代码块之后新增 §ODAILY：最近 72h 衰减加权均值 + 8 COUNT（important_count / crypto_regulation / regulation_policy / security / geopolitics / batch_size / avg_decay_hrs / narrative_hot_word_hits）→ 共 9 字段写入 result dict；③ L200 policy_sentiment_score 新增优先级 odaily > blockbeats > panewslab → 且 odaily_policy_sentiment_3d ∈ [0.2, 0.8] 才信任（极值保护） | `read_macro_from_sqlite()` 返回 dict 含 9 odaily_* 字段；读首屏 17 条后 policy_sentiment_score ∈ [0.35, 0.65]（非恒 0.5） |
| **T19** | 增量去重验证（两次 --once + 插假记录） | 运维 | data_center.db records 表 SQL | ① 第一次 --once：COUNT odaily_newsflash=15；② 第二次 --once immediately：COUNT 增量=0（lastId 增量过滤）；③ `INSERT INTO records(source, sub_category, timestamp, metrics, raw) VALUES('odaily_newsflash', 'newsflash_99999999', unixepoch('now'), '{"od_source_id":99999999}', '{}');` ④ 第三次 --once：COUNT 增量≥1（假 id 比 max 大，增量去重第一道 checkHasNew 生效） | 3 步结果符合预期 |
| **T20** | FAIL-OPEN L3 验证（临时 mv sentiment_engine）+ 5 TC 全绿总测 | 运维 + 测试 | 18-数据获取中心目录 | ① 临时 `mv 9-基本面分析/engines/sentiment_engine.py /tmp/sentiment_engine_bak.py`；② `python3 data_center_scheduler.py --once` → odaily task 仍 SUCCESS，records_count≥15 / 所有 od_policy_sentiment_0_1 ≈0.5；③ mv 回来恢复；④ 总测 `pytest tests/news/test_odaily_collector.py -v` → **5 passed** | Spec §4.8 6-7 项 |

### 🧪 P0-3 阶段1：基础 boost（T21-T30，1.0 人天，TDD 循环）
> **TDD skill 前置调用**：开始 T21 前必须再次调用 test-driven-development skill（新一轮 TDD）

| ID | 任务名 | 类型 | 文件 | 操作 | 验证（红→绿） |
|---|---|---|---|---|---|
| **T21** | 阶段1 脚手架 + 7 fixture | 新建测试 | `11-易经推理系统/tests/test_odaily_booster_stage1.py` | ① 加载 FiveDomainFeatureComputer；② 7 个 coin_data fixture：R3 sample（17 条政策快讯聚合→9 odaily_* 字段）/ 暖 sentiment / 冷+严监管 / 货币宽松 / 地缘≥3 / 极值乘法 / 异常字段类型 | import 成功，fixture 加载；还没写 TC |
| **T22** | TC-1 None → 0.0（红）→ 方法骨架（绿） | 红 → 绿 | 同上测试 + 修改 `five_domain_feature_computer.py` | 写 TC-1（coin_data=None → _od_dao_boost=0.0，_od_tian_boost=0.0）→ FAILED；新增两个空方法签名（含 try/except Exception 兜底 0.0）+ 类属性 enable_odaily_engine_boost=False | FAILED → PASSED |
| **T23** | TC-2 dao 正 delta（红）→ D1/D2/D3 算法（绿） | 红 → 绿 | 同 | TC-2（sentiment=0.7 → dao_boost ∈ (0.02, 0.08]）→ FAILED；实现 _od_dao_boost D1=0.16*(s-0.5) + D2 reg_ratio ±0.06/0.02 + D3 imp_ratio×sign×0.08 → 均值 clamp | FAILED → PASSED |
| **T24** | TC-3 dao 负 delta（红）→ 算法验证（绿） | 红 → 绿 | 同 | TC-3（s=0.3 + crh/batch=0.4 → dao_boost ∈ [-0.1,-0.02)）→ FAILED；补算法细节边界 clamp | FAILED → PASSED |
| **T25** | TC-4 tian 货币宽松（红）→ D1/D2/D3（绿） + TC-5 地缘≥3（绿） | 红 → 绿 | 同 | TC-4 rp_ratio=0.2+s>0.6 → tian_boost=+0.03~+0.06 → FAILED；实现 _od_tian_boost D1 货币分支 + D2 geo 阈值 + D3 安全分支；TC-5 geo≥3 → tian 负 delta | FAILED → PASSED |
| **T26** | TC-6 乘法叠加上限（绿）+ TC-7 异常字段类型 → 0.0（绿） | 红 → 绿 | 同 + five_domain_feature_computer.py L214/L313 | 写 TC-6（pn=+0.2 + od=+0.1 → dao_raw=×1.32，_normalize_0_100 后仍∈[0,100]）→ FAILED；**实现两行乘法叠加改动**（见 Spec §5.2.4 diff）→ PASSED；TC-7（字段类型错，如 sentiment=字符串）→ FAILED；方法 try/except 全包裹后→PASSED | FAILED → PASSED |
| **T27** | R3 sample 值验证：dao=+0.028±0.005 / tian=+0.034±0.005 | 断言 | 同测试文件 | 喂入 R3 17 条快讯聚合后的 9 字段 fixture → 断言 dao_boost 和 tian_boost 范围；差值原因：sentiment 均值≈+0.12 / reg_ratio≈0.29 / imp_ratio≈0.40 | 断言 OK |
| **T28** | FAIL-OPEN None 字节一致性验证 | 断言 | 同测试文件 | 构造 coin_data 空 None + enable=False → compute() 返回 result；对比 P0-3 代码未改动版本的 baseline_result（提前 pickle 一份）→ `assert result == baseline_result` | 字节相等（dict 逐 key 比较 == True） |
| **T29** | 代码风格 CR 一致性检查 | Code Review | five_domain_feature_computer.py | 逐行对比 _pn_dao_boost/_od_dao_boost：签名一致 / Optional[Dict] 参数一致 / try/except Exception 一致 / clamp max-min 一致 / 注释风格一致。差异点 od range [-0.1,0.1] vs pn [-0.2,0.2] 符合设计（更保守） | CR 通过，无风格红警 |
| **T30** | 7 项单测全绿 + 4 项验收归档 | 总测试 | 同 | `pytest tests/test_odaily_booster_stage1.py -v` → **7 passed**；T27-T29 三项（R3 sample + None 字节 + CR）三项全部通过 | Spec §5.5 阶段 1 第 1-4 项 |

### 🧪 P0-3 阶段2：Shadow 引擎全链路（T31-T42，2.0 人天 + 7 观察日，TDD 循环）
> **TDD skill 前置调用**：开始 T31 前必须再次调用 test-driven-development skill（新一轮 TDD）

| ID | 任务名 | 类型 | 文件 | 操作 | 验证（红→绿） |
|---|---|---|---|---|---|
| **T31** | 阶段2 脚手架 + 6 fixture | 新建测试 | `tests/test_odaily_engine_shadow_stage2.py` | ① 加载 FeatureComputer + mock 9基本面 4 引擎 SentimentEngine/NarrativeAnalyzer/ThreeDResistance/SignalEngine；② fake runtime directory 临时 JSONL 路径；③ enable=True/False fixture；④ ImportError monkeypatch；⑤ PermissionError monkeypatch JSONL 写失败 | import 成功，fixture OK |
| **T32** | TC-1 enable=False 红线（红）→ guard 代码（绿） | 红 → 绿 | 测试 + five_domain_feature_computer.py | 写 TC-1（enable=False，进入 compute() → shadow 代码块 0 次；runtime/odaily_engine_boost_records.jsonl size=0B；result 与 baseline 字节一致）→ FAILED；在 compute() return 前加 `if self.enable_odaily_engine_boost and coin_data.get("odaily_batch_size_3d",0)>=3 and time.time()>self._shadow_import_blocked_until_ts:` → guard OK + 不调用 shadow；再跑 TC-1 | FAILED → PASSED |
| **T33** | TC-2 ImportError 24h 阻塞（红）→ lazy import + 24h 变量（绿） | 红 → 绿 | 同 | 写 TC-2（enable=True + mock ImportError → JSONL 有 IMPORT_FAIL 记录；_shadow_import_blocked_until_ts = now+86400；result 不变）→ FAILED；实现 _od_engine_shadow_compute 开头 sys.path insert + try 4 import + except 设置 blocked_ts + 写 JSONL IMPORT_FAIL 行 | FAILED → PASSED |
| **T34** | TC-3 JSONL 8 键全（红）→ R4 4.2 公式 7 步全实现（绿） | 红 → 绿 | 同 | 写 TC-3（enable=True + 4 引擎 mock 返回确定值 → JSONL 1 行；键 ts/asset_classes/war_state_pred/_shadow_version 齐全；asset_classes[cls] 8 子键（tian_old/.../od_tian_boost_stage1）全；实际 result 与 enable=False 字节一致）→ FAILED；实现 _od_engine_shadow_compute 7 步（Step 2.1 ts_20 反推 / 2.2 narrative + lifecycle_bonus / 2.3 three_dee + stress×0.5 / 2.4 w_policy _adaptive_weight / 2.5 subscore clamp 0-100 / 2.6 3 类 tian_new_predict / 2.7 JSONL 记录）+ 辅助方法 _shadow_infer_policy_ts_20 + _shadow_jsonl_append + _shadow_predict_total_score | FAILED → PASSED |
| **T35** | TC-4 lifecycle growing（+3）差值（红）→ Step 2.2 验证（绿）+ TC-5 3D stress=0.8 减半（绿） | 红 → 绿 | 同 | TC-4（lifecycle="growing" bonus+3 vs lifecycle="emerging" bonus+1 → policy_subscore 高 2~5 分）→ FAILED；验证算法 Step 2.2 narrative_boost = heat×10*(lifecycle_bonus/5)，heat=1.0 default，3-1=2 → 差值=2/5×10=4.0 分，正确；TC-5 stress=0.8 → (1 - 0.8×0.5)=0.6 → three_dee_boost 正好 0.6 倍 | FAILED → PASSED |
| **T36** | TC-6 PermissionError JSONL 失败（红）→ try/except 吞掉（绿） | 红 → 绿 | 同 | 写 TC-6（mock builtins.open → 抛 PermissionError）→ compute() 仍正常返回，不抛任何异常；_shadow_jsonl_append 加 try/except OSError → pass 吞掉 | FAILED → PASSED |
| **T37** | 6 TC 全绿 + Shadow 红线生产验证 | 总测试 + 运维 | 11-易经推理系统 + runtime 目录 | ① `pytest tests/test_odaily_engine_shadow_stage2.py -v` → **6 passed**；② 确认真实生产环境 enable=False 情况下：import 监控（grep "sentiment_engine" import 次数）=0；`wc -c scripts/runtime/odaily_engine_boost_records.jsonl`=0B；result 与基线字节一致（跑 3 次 compute） | Spec §5.5 阶段2 第 5-6 项 |
| **T38** | 新建空占位 JSONL + 目录 | 新建 | `scripts/runtime/` 目录 | ① `mkdir -p scripts/runtime`（若不存在）；② `touch scripts/runtime/odaily_engine_boost_records.jsonl`；③ 加 .gitignore 规则（若 runtime 已 ignore 则跳过） | 文件存在且 size=0B |
| **T39** | 新建 odaily_shadow_hitrate_eval.py 评估脚本 | 新建 | `scripts/memory_l4/odaily_shadow_hitrate_eval.py` | 实现：① 读 JSONL（每 line json.load）；② 计算 4 门槛：命中率≥60%（policy_subscore>55→后续7日收益>0）；解冻准确率≥70%（should_thaw=True→3日内 war_state 真跨 60）；夏普比≥1.05（tian_new_predict 替代 tian_old 重算仓位决策的夏普）；IMPORT_FAIL=0（shadow_stage=="IMPORT_FAIL" COUNT=0）；③ 输出表格 4 门槛实际值 + 阈值对比 + PASS/FAIL 总体结论；④ 支持 --json 输出机器可读 | 喂入 30 条 mock JSONL 样本脚本运行 exit 0，输出 PASS/FAIL 判定正确 |
| **T40** | 文档更新（Spec 附录 C 清单 5 项） | 修改 4 文档 + 销项（若有） | 见 Spec 附录 C | ① `11-易经推理系统/docs/CHANGELOG.md` 追加 [v4.5.1]：P0-3 变更说明 / 验证方式 / 回滚；② `11-易经推理系统/docs/ENGINEERING_INDEX.md` 文件清单加 _od_dao_boost / _od_tian_boost / _od_engine_shadow_compute 三个函数；③ `18-数据获取中心/docs/CHANGELOG.md` 追加 [v1.x]：P0-2 Odaily collector；④ `18-数据获取中心/docs/ENGINEERING_INDEX.md` 增加 OdailyNewsflashCollector 文件职责说明；⑤ DOC_DEBT_INDEX 若有相关项销项 | 5 项文档变更提交 PR（与代码 PR 合并 CR） |
| **T41** | 7 天 Shadow 产出 + 门槛评估 | 7 日历天运维 | `scripts/runtime/odaily_engine_boost_records.jsonl` + 评估脚本 | ① Day 5 检查 `wc -l JSONL` ≥1000 条（每 5min 1 条×7天≈2016，75%=1500 标准，Day 5 70% 是良好信号）；② Day 7 晚上跑 `odaily_shadow_hitrate_eval.py`；③ 记录输出报告；④ 若 4 门槛全 PASS → 下一步 T42；若任一门槛 FAIL → 发 issue 排查根因 + 延期 7 天 | Spec §5.5 阶段2 第 7-8 项 |
| **T42** | 开开关（4 门槛全 PASS 后才做） | PR 修改 + 上线 | five_domain_feature_computer.py enable_odaily_engine_boost | ① 改类属性 `enable_odaily_engine_boost: bool = True`；② 附带评估报告链接；③ PR + Code Review 通过；④ 合并 main；⑤ 部署：清理 `runtime/five_domain_state.json`（旧缓存）+ 重启 polling_trader.sh；⑥ 观察 24h 解冻计数器，预期 Day 12-14 连续 3 日≥60 → war_state 解冻 ALLOW | 观测 thaw_count 累加，war_state 从 FREEZE → ALLOW 转换 |

---

## 任务完成度追踪表（动态更新，实施时每完成 1T 打 ✅）

| ID | 任务 | 所属 P | 预估 | 状态 | 验证记录（链接/截图/日志路径） |
|---|---|---|---|---|---|
| T01 | 环境预检 | P0-1 | 2min | ⬜ 未开始 | |
| T02 | 前台 --once 验证 | P0-1 | 10min | ⬜ | |
| T03 | plist 拷贝 | P0-1 | 30s | ⬜ | |
| T04 | plist 加载 | P0-1 | 30s | ⬜ | |
| T05 | 健康检查 3 次 | P0-1 | 15min | ⬜ | |
| T06 | 热路径安全 | P0-1 | 2min | ⬜ | |
| T07 | P0-2 TDD 脚手架 5 fixture | P0-2 | 20min | ⬜ | |
| T08 | TC-1 正常 20 条（红）→ 骨架（绿） | P0-2 | 40min | ⬜ | |
| T09 | TC-2 增量去重（红）→ lastId（绿） | P0-2 | 30min | ⬜ | |
| T10 | TC-3 event_type（红）→ 关键词正则（绿） | P0-2 | 40min | ⬜ | |
| T11 | TC-4 网络超时 fail-open（红）→ Session 封装（绿） | P0-2 | 20min | ⬜ | |
| T12 | TC-5 ImportError 中性（红）→ lazy import 兜底（绿） | P0-2 | 30min | ⬜ | |
| T13 | Collector 重构 + lint | P0-2 | 20min | ⬜ | |
| T14 | Registry 注册 | P0-2 | 10min | ⬜ | |
| T15 | sources.yaml 启用 | P0-2 | 5min | ⬜ | |
| T16 | Scheduler 注册 | P0-2 | 10min | ⬜ | |
| T17 | --once 采集验证 | P0-2 | 5min | ⬜ | |
| T18 | Reader §ODAILY 派生 9 字段 + 覆盖写 | P0-2 | 60min | ⬜ | |
| T19 | 增量去重 3 次验证 | P0-2 | 15min | ⬜ | |
| T20 | FAIL-OPEN L3 验证 + 5 TC 全绿 | P0-2 | 15min | ⬜ | |
| T21 | 阶段1 TDD 脚手架 7 fixture | P0-3-1 | 20min | ⬜ | |
| T22 | TC-1 None→0.0（红）→ 方法骨架（绿） | P0-3-1 | 30min | ⬜ | |
| T23 | TC-2 dao 正 delta（红）→ D1/D2/D3 算法（绿） | P0-3-1 | 40min | ⬜ | |
| T24 | TC-3 dao 负 delta（红）→ 边界 clamp（绿） | P0-3-1 | 20min | ⬜ | |
| T25 | TC-4/TC-5 tian D1/D2/D3 两个场景（红→绿） | P0-3-1 | 50min | ⬜ | |
| T26 | TC-6 乘法上限 + TC-7 异常字段（红）→ 2 行乘法（绿） | P0-3-1 | 30min | ⬜ | |
| T27 | R3 sample boost 值验证 | P0-3-1 | 15min | ⬜ | |
| T28 | None 字节一致性验证 | P0-3-1 | 20min | ⬜ | |
| T29 | 代码风格一致性 CR | P0-3-1 | 10min | ⬜ | |
| T30 | 7 TC 全绿 + 4 项验收归档 | P0-3-1 | 10min | ⬜ | |
| T31 | 阶段2 TDD 脚手架 6 fixture | P0-3-2 | 20min | ⬜ | |
| T32 | TC-1 enable=False 红线（红）→ guard（绿） | P0-3-2 | 30min | ⬜ | |
| T33 | TC-2 ImportError 24h 阻塞（红）→ lazy import+blocked（绿） | P0-3-2 | 40min | ⬜ | |
| T34 | TC-3 JSONL 8 键（红）→ 7 步公式全实现（绿） | P0-3-2 | 90min | ⬜ | |
| T35 | TC-4 lifecycle growing + TC-5 3D stress 0.8（红→绿） | P0-3-2 | 40min | ⬜ | |
| T36 | TC-6 PermissionError JSONL 失败（红）→ try/except（绿） | P0-3-2 | 20min | ⬜ | |
| T37 | 6 TC 全绿 + 生产红线验证 | P0-3-2 | 30min | ⬜ | |
| T38 | 空占位 JSONL + 目录 | P0-3-2 | 5min | ⬜ | |
| T39 | odaily_shadow_hitrate_eval.py 评估脚本 | P0-3-2 | 60min | ⬜ | |
| T40 | 5 文档更新（Spec 附录 C） | P0-3-2 | 30min | ⬜ | |
| T41 | 7 天 Shadow 产出 + 门槛评估 | P0-3-2 | 7 日历天 | ⬜ | |
| T42 | 4 门槛 PASS 后开开关 + 部署验证 | P0-3-2 | 30min | ⬜ | |

**合计**: 42 个细分任务（主任务 20 个）；P0-1 纯运维；P0-2 到 T07 前必须调 TDD skill；P0-3 每阶段前必须调 TDD skill。
