# Gap1：FD7 新闻 72h × 200 条 SQLite 真实通路 — 设计文档

- **日期**: 2026-08-29
- **状态**: 设计确认 → TDD 开工
- **所属大 Spec**: `2026-08-29-fundamental-7engines-daotian-boost-spec.md` §6 Gap-1 数据空壳补全
- **关联文件**:
  - 代码落点：`11-易经推理系统/scripts/memory_l4/five_domain_feature_computer.py` L574 `_fetch_news_72h_limit200()`
  - 路径依赖：`11-易经推理系统/scripts/memory_l4/five_domain_sqlite_reader.py` `DEFAULT_DB_PATH`
  - 下游消费：`_fd_S_dao_boost / _fd_S_tian_boost / _fd7_shadow_compute`（3 处调用方）

---

## §1 背景 & 动机（为什么做）

### 现状空壳
[five_domain_feature_computer.py L574-582](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-%E6%98%93%E7%BB%8F%E6%8E%A8%E7%90%86%E7%B3%BB%E7%BB%9F/scripts/memory_l4/five_domain_feature_computer.py#L574-L582) 当前实现：
```python
def _fetch_news_72h_limit200(self) -> List[Dict[str, Any]]:
    try:
        # TODO 阶段2: 打开SQLite data_center.db，SELECT
        #   SELECT raw, metrics FROM records WHERE category='news'
        #   AND timestamp_ms >= (now_ms - 72*3600*1000) ORDER BY timestamp_ms DESC LIMIT 200;
        #   把 raw JSON 拼成 engines 用的 news_list[dict]。
        return []
    except Exception:
        return []
```

### 直接后果
- 7 引擎 S 级（Sentiment / EventLedger / NewsContract / EventMapping / Narrative）共 10 个 delta（dao 侧 5 + tian 侧 5）全部短路为 `0.0`；
- Shadow JSONL `fundamental_7engines_records.jsonl` `reason_code=FD7_NO_NEWS` 恒真，无法判断真实引擎是否有数据驱动的信号输出；
- 7 门槛样本累积（7日历天 1500+条）期间 boost 都是 0，相当于"假阳性"审计——不能用这些样本来判定引擎是否值得生产注入（样本有效但 boost 恒 0，exit=0 是因为 PASS 条件缺字段中性，不是因为引擎真的合格）。

### 目标收益
- ✅ Shadow 审计真实：`fd_S_dao_mean / fd_S_tian_mean` 出现非 0 值（±0.0x 级别），7 门槛评估能真实反映 S 级 5 引擎是否达到 G1/G2/G5/G6 四项指标；
- ✅ 最小改动不重启生产：只改一个函数体，`compute()` 下一轮自然调用（300s 轮询）自动生效，无需 kill 当前 PID 95538；
- ✅ 零风险：最外层 try/except + SQL 层 try/except + 逐条解析 try/except **三层 FAIL-OPEN 隔离**，任何异常都退化为 return []，等价于"保持现状"——不会改变 dao/tian 任何生产分数（字节等价生产注入红线仍是 False）。

---

## §2 目标 & 非目标

### ✅ 目标（本 TDD 范围）
1. **向后兼容的签名扩展**：`_fetch_news_72h_limit200(self, db_path: Optional[str] = None) -> List[Dict[str, Any]]`
   - 新增可选参数 `db_path=None`（默认 None，不传时生产走 DEFAULT_DB_PATH，对 3 调用方**零影响**）；
   - TC 直接传临时 DB 路径，无需 monkeypatch 模块变量（更稳无全局副作用）。
2. **从 SQLite records 表读真实数据**：WHERE category='news' + Python 端 72h 窗口过滤 + 截断最新 200 条
3. **字段安全映射**：每条新闻 dict 返回 8 字段集合（6 必填+2 可选）对齐 9 基本面引擎最小消费
4. **9 TC 全 GREEN**（清单见 §6），覆盖：主路径 / 边界 / 异常 / 集成打通验收
5. **生产验证**：下一轮 300s 轮询后 Shadow JSONL `reason_code ∈ {FD7_OK, FD7_NO_R3D, FD7_IMPORT_ERROR}`（不再是 `FD7_NO_NEWS`），`fd_S_dao_mean 或 fd_S_tian_mean` 至少一个非 0

### ❌ 非目标（本次 TDD 不做）
- ❌ 不打通 A 级引擎（least_resistance / SignalEngine）的真实数据源（A 级需要 raw_score/历史数据 + strategy 系统参数传递，独立作为 Gap3 后续开工）
- ❌ 不拆工具函数放 five_domain_sqlite_reader.py（过度抽象 YAGNI，当前唯一调用方就是本函数）
- ❌ 不做缓存 / 去重（300s 内重复查询 SQLite 成本可忽略；下次有性能瓶颈再优化）
- ❌ 不处理 Gap2 yijing_monitor env 注入（用户本次只批准 Gap1）

---

## §3 方案决策

**最终采纳**：方案 A（内联 SQL 直读）→ 用户已批准
- **原因**：最小改动（仅 1 文件 1 函数，≈30 行）、失败边界清晰（与现有 try/except return [] 形成双层外套 + 内层细粒度）、TDD 复杂度低、路径与生产对齐。

| 备选 | 结论 |
|------|------|
| 方案 B（抽工具函数到 reader.py） | 作为未来有第二处调用时的重构备选，本次 YAGNI |

### SQLite 查询策略（用户已确认）
```
SQL: WHERE category='news'（软分类，兼容未来新源 → sources.yaml news 大类下的任何源自动纳入）
ORDER BY id DESC LIMIT 400（3天容量≈安全上限，避免回表太多）
→ Python 端：解析 timestamp → 72h 窗口过滤 → 按 timestamp_ms DESC 排序 → [0:200]
异常粒度：单条解析失败只跳过本条（细粒度 Fail-Open）
```

---

## §4 接口签名 + news_list[dict] 字段规范

### 函数签名（扩展但向后兼容）
```python
def _fetch_news_72h_limit200(self, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
```
- 参数 `db_path` 优先使用；若 `None` 则回退 `five_domain_sqlite_reader.DEFAULT_DB_PATH`（生产默认）。

### news_list[dict] 每字段（6 必填 + 2 可选）

| # | 字段 | 类型 | 必填 | 取值优先级（从左到右） | 引擎消费 |
|---|------|------|:---:|-----------------------|---------|
| 1 | `source` | str | ✅ | records.source | 元数据审计 |
| 2 | `sub_category` | str | ✅ | records.sub_category | S2/S4 分类辅助 |
| 3 | `title` | str | ✅ | metrics.title → raw.title → `""` | S1 Sentiment / S4 EventMapping / S5 Narrative（主字段） |
| 4 | `content` | str | ✅ | metrics.content → raw.body / description / text → `""` | S1 / S4 / S5 主字段 |
| 5 | `timestamp_ms` | int | ✅ | raw.publishTimestamp(int) → records.timestamp(unix int × 1000) → records.timestamp(ISO 解析 × 1000) → `0` | 72h 过滤排序 / 引擎叙事时序 |
| 6 | `category` | str | ✅ | records.category（恒='news'，由 WHERE 保证） | S3 合约校验辅助 |
| 7 | `topic` | str\|None | 否 | metrics.topic → None | S4 map_event_type(topic=) 参数 |
| 8 | `url` | str\|None | 否 | metrics.url → raw.link → None | 审计追踪 |
| 9 | `event_type` | str\|None | 否 | metrics.event_type → None | S4 事件类型辅助 |

### 解析辅助规则
- **title/content 非字符串**：自动 str(x) 转字符串；不返回 None 避免引擎 KeyError（S1 将空字符串视为中立文本 sent=0.0，这是 fail-open 正确行为）
- **timestamp_ms = 0（时间完全不可知）**：**保留**（更保守不丢；引擎要的是文本，时间不明不影响 72h 语义；引擎自身会按顺序处理）
- **metrics/raw 不是合法 JSON**：跳过本条（continue），不影响其他

---

## §5 SQL 处理链 + 3 层 FAIL-OPEN 隔离

```
外层 1（函数级 try/except，已存在）：
  └─ 任何未预期 Exception → return []
      │
      ├─ 步骤 1：DB 路径解析
      │    · 若 db_path 参数传了（非 None 且非 ""）→ DB_PATH = db_path（TC 专用路径）
      │    · 否则 → import DEFAULT_DB_PATH from five_domain_sqlite_reader → DB_PATH = DEFAULT_DB_PATH
      │    → ImportError 或 os.path.exists(DB_PATH)=False → return []
      │    （隔离层 2：SQL 前 Fail-Open）
      │
      ├─ 步骤 2：sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
      │          SELECT source, category, sub_category, metrics, raw, timestamp, id
      │          FROM records WHERE category='news' ORDER BY id DESC LIMIT 400
      │    → sqlite3.Error / ProgrammingError / OperationalError → return []
      │    （隔离层 2：SQL 层 Fail-Open）
      │
      ├─ 步骤 3：逐条解析（for r in rows）
      │    for 内部单条 try/except:
      │      → metrics/raw 非合法 json.JSONDecodeError → continue（跳过本条）
      │      → timestamp 解析失败（非 int 非 ISO）→ timestamp_ms=0（保留）
      │      → 字段取值非 str → str(x) 兜底
      │    （隔离层 3：逐记录细粒度 Fail-Open — 最内层）
      │
      ├─ 步骤 4：72h 过滤
      │    cutoff_ms = int(time.time() * 1000) - (72 * 3600 * 1000)
      │    items = [n for n in parsed if n["timestamp_ms"] == 0 or n["timestamp_ms"] >= cutoff_ms]
      │    （timestamp_ms=0 保留 = 时间不明不丢，更保守）
      │
      └─ 步骤 5：排序 + 截断
           items.sort(key=lambda n: n["timestamp_ms"], reverse=True)
           return items[:200]
```

---

## §6 TDD TC 清单（9 条验收标准）

**测试夹具模式**：每个 TC 先写临时 SQLite 文件（或 `:memory:`），按 records 表 10 字段 schema（source / category / sub_category / timestamp / metrics / events / timeseries / raw / schema_version）插入 seed 数据。通过**显式传参数** `computer._fetch_news_72h_limit200(db_path=tmp_db_path)` 注入（TC-1 传不存在路径触发 DB 不存在断言，TC-2~8 传临时 DB 路径，均不需要 monkeypatch 全局变量）。

| TC # | 名称 | Seed 构造 | 核心断言 |
|------|------|----------|---------|
| TC-1 | DB 不存在 → 返回空 | DB_PATH = `/tmp/not_exist_xxx.db` | 返回 `len == 0` |
| TC-2 | category 过滤生效 | 3 条 `category='chain'` + 0 条 news | 返回 `len == 0` |
| TC-3 | 主路径：72h 内 1 条有效新闻 | `category='news'` source=odaily_newsflash / timestamp=now-1h / metrics & raw 合法 / raw.publishTimestamp 精确 | len=1；`title/content/source/sub_category/timestamp_ms/category` 6 字段非空；timestamp_ms 与 publishTimestamp 差 < 1000ms；topic/url 正确从 metrics 取到 |
| TC-4 | 72h 超期过滤 | 2 条：now-1h（72h内） / now-80h（超期） | len=1；唯一一条是 now-1h 的 |
| TC-5 | timestamp 解析失败 → 保留（=0） | raw.publishTimestamp 缺失 + timestamp="@@不是ISO_@@坏字符串" | len=1；唯一一条 `timestamp_ms == 0`；title/content 仍正常（非空）|
| TC-6 | 超 200 条 → 截断到最新 200 + 排序 DESC | 插 250 条（id 递增，timestamp 同步递增，都在 72h 内，都 category=news）| len=200；第 0 条 timestamp_ms > 第 199 条；第 0 条是 id=250（最新那条，ORDER BY id DESC 保证 LIMIT 400 一定能把它带回来）|
| TC-7 | 400 条里 200 条 72h 内 + 200 条超期 → 正好 200 | 200 条 now-1h + 200 条 now-100h（都 category=news） | len=200；每条 timestamp_ms ≥ now-72h_ms |
| TC-8 | 单条坏 JSON → 跳过本条 | 2 条：now-1h 正常 + now-2h metrics="}{bad{{json"（完全不合法）| len=1；唯一一条是 now-1h 正常的 |
| **TC-9（集成打通验收）** | _fd_S_dao_boost 返回非 0 → 通路真实有效 | monkeypatch `_fetch_news_72h_limit200` 返回 5 条 news_list：3 条「美联储 官宣降息 25bp」正面文本 + 2 条「SEC 起诉 Binance」负面文本（sentiment 聚合后 sent_mean 显著偏 0 一侧） | `v = computer._fd_S_dao_boost(cls_coin={}); assert v != 0.0`（只要非0证明 S级 Sentiment 聚合生效）；同时断言总 clamp：`abs(v) <= 0.10`（5 delta 总上限 ±0.10）|

---

## §7 对 7 引擎 Shadow 的影响（生产链路）

| 项目 | 当前状态（空壳） | 本设计落地后（预期） |
|------|-----------------|----------------------|
| `import_fail_count` | **0**（健康检查通过，与数据无关） | **不变 = 0**（引擎 import + 最小功能空调用在步骤 1，早于 news_list 是否有数据） |
| `shadow_reason_code` | **FD7_NO_NEWS**（恒真） | **三选一**：<br>• `FD7_OK`（有新闻 + A级 r3d/signal 也命中→最优）<br>• `FD7_NO_R3D`（有新闻、S级已跑通，但 A 级系统还没传 r3d/signal → 预期内，A 级是后续 Gap3）<br>• `FD7_IMPORT_ERROR`（引擎某个导入失败=健康检查有坏模块=需紧急修复） |
| `fd_S_dao_mean` / `fd_S_tian_mean` | **0.0**（恒真，news_list=[] 短路） | 真实值（±0.0x 级别，按 72h 新闻内容聚合出的情绪 / 事件 / 叙事信号）|
| `fd_A_dao_mean` / `fd_A_tian_mean` | **0.0** | **大概率仍 0.0**（预期内：A 级需 system_state 传入 r3d + signal_engine 自适应权重，链路未接通，是后续 Gap3 范围） |

### 7 门槛评估影响
落地后样本进入"真实累积期"：
- G1 `_hit ≥ 60%`：dao/tian boost 值与未来 PnL 是否同向 → 开始真实统计
- G5 `_s_acc ≥ 75%`：S 级 5 delta 5 个分项累计通过概率 → 开始真实统计
- G6 `_a_cons ≥ 60%`：A 级仍 0 可能判中性（中性 PASS 逻辑）→ 不影响整体通过判定
- G7 `_sch_pass ≥ 95%`：news_contract.schema.json 合规通过率 → 开始真实统计
- G2/G3/G4：与新闻通路无关（分别是 PnL 解冻准确率 / Sharpe / import_fail），保持原行为

---

## §8 生产生效步骤（无需重启进程）

本改动是 Python 纯代码，**但当前进程 PID 95538 已加载 five_domain_feature_computer 模块**（Python import 缓存）。生效方式：

| Option | 说明 | 风险 | 推荐 |
|--------|------|------|:---:|
| Option 1：**触发进程自恢复**（推荐） | 手动 kill PID 95538 → yijing_monitor.py 下次调度周期（或 launchd 触发）检测到 polling_trader 不存活 → run_polling_trader() 重新 Popen 启动 → **⚠️ 新进程将不带 OD/FD7 Shadow env（这是 Gap2 未解决问题！见 §10）** | ❌ Shadow 停更风险（Gap2） | NO |
| Option 2：**等 300s 轮询周期内模块热重载不可行**（Python importlib.reload 机制复杂，FiveDomainFeatureComputer 类实例已创建，reload 不影响已存在实例的方法绑定） | 实际等于不生效 | ❌ 无效 | NO |
| **Option 3（本次实际采用）**：按之前「进程启动蓝图」重新 Popen 一次正版 yijing_monitor 模式进程（带 Shadow env），kill 旧 PID 95538 | ✅ 10s 内完成；✅ Shadow env 继续携带；✅ 新代码从磁盘重新 import；✅ 下一轮 300s 轮询自动生效 | 与之前 10s 重启流程相同，风险低 | ✅ YES |

### 验证（生效后 ~330s 检查）
```bash
# fd7engines_hitrate_eval.py 不需要，只需要 JSONL head：
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统
# 检查最新 2 条
tail -n 2 scripts/runtime/fundamental_7engines_records.jsonl | python3 -c "
import sys, json
for l in sys.stdin:
    r = json.loads(l)
    print(f\"ts={r['ts_ms']} rc={r['shadow_reason_code']} ifc={r['import_fail_count']} Sdao={r['fd_S_dao_mean']} Stian={r['fd_S_tian_mean']} Adao={r['fd_A_dao_mean']}\")"
```
期望输出：
```
ts=... rc=FD7_OK           ifc=0 Sdao=+0.0083 Stian=-0.0125 Adao=0.0
ts=... rc=FD7_NO_R3D       ifc=0 Sdao=+0.0041 Stian=+0.0072 Adao=0.0
```
（rc 具体值取决于真实新闻聚合结果；**核心判断：不是 FD7_NO_NEWS、S_dao 或 S_tian 至少一个非 0** → 通路打通验收通过）

---

## §9 风险 & 回滚

### 风险矩阵
| # | 风险 | 概率 | 影响 | 缓解措施 |
|---|------|------|------|----------|
| R1 | SQLite 死锁（SELECT 用 mode=ro 只读） | 低-极低 | SELECT 失败 return [] → 等价现状 | 只读 URI 打开 + 外层 try/except 兜底 |
| R2 | 时间戳解析异常导致 OOM/内存爆 | 极低 | 单条解析 try/except 跳过；SQL LIMIT 400 硬上限 | LIMIT 400 + 逐条隔离 + 外层 return [] |
| R3 | 字段 key 错拼导致引擎 KeyError | 低 | 引擎 SentimentEngine 调用处已有 try/except（fd_S_dao_boost L629） → 跳过本条 return 0 | 上下 6 层 FAIL-OPEN 互锁 |
| R4 | 坏新闻数据（极端非 UTF-8）导致 decode 错 | 低 | sqlite3 自动返回 str；外层 + 内层双 try 隔离 | 所有 dict 取值 cast + 解析失败跳过 |

### 回滚方案（秒级回滚）
**1 行代码即回滚**：把 `_fetch_news_72h_limit200` 函数体恢复成 `return []`（当前空壳）即可，不需要任何配套修改。
- 影响：Shadow JSONL 重新回到 FD7_NO_NEWS、boost 恒 0 → 等价现在状态
- dao/tian 生产分数：**不受任何影响**（生产注入红线 enable_fundamental_7engines_production_injection=False 永不改）

---

## §10 后续 & 依赖 Gap

### Gap2：yijing_monitor Popen 双 Shadow env 注入（P1）
**为什么重要**：当前 Option 3（重新 Popen）需要手动，每次进程恢复都需要人手工补 env；若 yijing_monitor 自动接管（ProcessGuardian 检测异常重启），新进程会丢失 Shadow env → JSONL 停更。
**影响**：不影响本 TDD（9 TC GREEN 不需要重启进程），但影响 **7 日历天观察期的连续性**（进程自动恢复时 Shadow 断更 = 样本空档）。
**建议**：Gap1 TDD 完成后（9/9 GREEN + 生产验证通过）立刻开工 Gap2 TDD（轻量 3 TC）。

### Gap3：A 级引擎（least_resistance / SignalEngine）真实数据通路（P2）
当前 A 级 delta 需要 system_state.r3d / coin_data.least_resistance_3d + signal_engine 自适应权重生效。未打通时 `fd_A_dao_mean/fd_A_tian_mean` 恒 0，7门槛 G6_A_cons≥60% 只能判「缺字段中性PASS」，无法判断 A 级引擎真实贡献。
**建议**：7门槛样本期间（前 3 天）启动 Gap3 TDD，保证样本结束时 A 级也有足够数据通过 G6 门槛。

---

## 验收 & 决策门
```
TDD 9 TC → 8/8 纯单元 GREEN + TC-9 集成打通 GREEN（9/9）
  ↓
Option 3 重启进程（10s，与之前蓝图相同）
  ↓
等待 ~330s → 检查 fundamental_7engines_records.jsonl 新记录：
  [PASS] reason_code ∈ {FD7_OK, FD7_NO_R3D} AND S_dao_mean≠0 或 S_tian_mean≠0
  [FAIL] 仍 FD7_NO_NEWS 或 S_* 恒 0 → 调试 DB category='news' 实际数据
```

---

_本文档为 Gap1 TDD 唯一权威设计来源；若有更新，在文件顶部追加修订记录，不删除原章节。_
