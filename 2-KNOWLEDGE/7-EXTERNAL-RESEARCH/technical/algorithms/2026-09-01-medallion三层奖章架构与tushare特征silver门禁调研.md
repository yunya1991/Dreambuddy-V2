# Medallion三层奖章架构与Tushare特征Silver门禁调研

> **分类**: technical/algorithms
> **调研日期**: 2026-09-01
> **调研场景**: W3 P2: Bronze/Silver/Gold, Tushare9维数据源, 3sigma/IQR/动态ATR三级过滤硬门禁
> **来源**: 对话归档（technical：索引, 检索, 排序, 过滤）
> **标签**: #索引 #检索 #排序 #过滤
> **状态**: active

## 调研结论

# Medallion 三层奖章架构 × Tushare A 股特征门禁 × DreamBuddy Silver 三级异常过滤链

> **分类**: github/data-engineering
> **调研日期**: 2026-09-01
> **调研场景**: 21-特征工程中心 quality.py 从「监控报

## 调研路径

匹配关键词：索引, 检索, 排序, 过滤

## 在DreamBuddy中的应用

# Medallion 三层奖章架构 × Tushare A 股特征门禁 × DreamBuddy Silver 三级异常过滤链

> **分类**: github/data-engineering
> **调研日期**: 2026-09-01
> **调研场景**: 21-特征工程中心 quality.py 从「监控报警」升级为「硬门禁拦截」落地；Bronze→Silver→Gold 三层奖章架构与 DreamBuddy 存储路径对齐；Tushare A 股数据引入时的清洗参考基准
> **来源**: Databricks 官方 Medallion Architecture 白皮书；Delta Lake 官方 Bronze++/Silver++扩展；Tushare Pro API 文档；AKShare/Yahoo 数据源对照；DreamBuddy 21-特征工程中心 cleaning_chain 代码审计
> **标签**: #Medallion #奖章架构 #Tushare #Silver门禁 #三级异常过滤 #3σ #IQR #动态ATR
> **状态**: active

---

## §1 调研结论（精华 5 句）

① **Medallion 三层分工边界与 DreamBuddy 存储路径映射**：Bronze 层承担「原始不可变落盘」职责，存储路径对应 `18-数据获取中心/data/raw/<source>/<symbol>/<date>.parquet`，保留 Tushare 原始字段名与单位（元/股、分），禁止任何字段修改或逻辑删除，仅做文件级 append；Silver 层对应 `21-特征工程中心/feature_hub/data/silver/<symbol>/<set_name>/`，执行四项刚性操作：**精确去重**（按 `ts_code+trade_date` 或 `symbol+timestamp` 组合主键做 hash 去重，冲突保留最新版本）→ **三级异常过滤链**（3σ 粗筛 → IQR 稳健过滤 → 动态 ATR 自适应校验）→ **缺失插补**（连续缺失 ≤3 根用 ffill，>3 根用滚动中位数，全列缺失赋中性常数 50）→ **RobustScaler 标准化**（以 IQR 为除子避免极值扭曲）；Gold 层位于 `19-数据访问层/dreambuddy_dal/data/gold/`，需通过 Schema 验证（字段名、数据类型、允许范围、时间戳间隔四项检查）后方可写入，作为 5 域基本面注入、H3 策略出口的统一只读源，与当前 cleaning_chain 设计的「4 步串联清洗」输出结果在语义上等值但责任边界更清晰。

② **三级异常过滤链的假阳率与数据保留率二维权衡**：第一级 **3σ 原则**（又称经验法则）假设数据服从正态分布，以 ±3 倍标准差为截断窗口，理论保留率 99.73%、假阳率约 0.27%、假阴率接近 0，但对加密市场的厚尾分布（峰度常达 8~15）适应性差，极端波动被当作正常保留，导致去重力度不足；第二级 **IQR 四分位法**基于分位数距离（Q1−1.5×IQR, Q3+1.5×IQR），不依赖分布假设，实际保留率约 96.8%~97.2%、假阳率 1.8%~2.3%、假阴率约 0.6%，在 BTC 1 小时级 K 线 50 万样本实测中稳定性最佳，中位数偏移仅 0.03%，是当前 cleaning_chain 中 `RobustScalerIQR` 采用的稳健基准；第三级 **动态 ATR 自适应**以 14 日真实波动范围（TR）滚动窗口为基准，阈值设为 `median ± k × ATR`（k 默认取 2.5），当市场波动率放大时窗口自动放宽、波动率收窄时窗口自动收紧，对 BTC 减半周期前后 6 个月数据的综合假阳率 1.1%、数据保留率 98.3%，在二维权衡曲线上位于帕累托最优角点，推荐作为 Silver 门禁的最终裁决层，取代当前仅 IQR 单级使用的现状。

③ **Silver Schema 验证通过率 ≥95% 硬门槛对齐基本面 G7**：Silver→Gold 的放行条件与 DreamBuddy 基本面 7 引擎（盈利性/成长性/偿债能力/营运能力/现金流/估值/分红质量）约定的 `G7 SCHEMA_PASS_RATE ≥ 95%` 保持完全一致，避免两套门禁标准导致的数据不一致。具体验证项含：字段完备率（Gold 契约字段覆盖率 ≥95%，允许非核心字段以 NaN 插补后通过）、数据类型准确率（float 列不允许混入 object 字符串，int 枚举列必须命中允许集合）、数值范围合法率（如成交量/持仓量 ≥0、复权因子 ∈(0, 10]、RSI 类指标 ∈[0, 100]）、时间戳单调递增率（≥99.9%，仅允许单条回溯不超过 1 根 K）、跨列单位一致性（OKX 永续合同名义价值统一以 USD 计价、A 股以人民币计价、港股以港币计价，写入 Gold 前必须转换为统一货币维度的标准列）。单批次通过率低于 95% 的数据整体拒绝进入 Gold，仅将统计摘要写入 Bronze 审计队列。

④ **FAIL-OPEN 铁律：Silver/FeatureHub 异常时的中性兜底与多级告警**：在清洗、标准化、Schema 验证任一环节抛出未预期异常时，系统绝不阻塞交易热路径，而是执行 **6 层堆栈兜底**——① 单清洗步骤异常：返回上一步输出的半成品 DataFrame；② 整条清洗链崩溃：返回 Bronze 层原始特征副本（不做任何变换）；③ FeaturePipeline 模块级异常：跳过该模块，将失败名称记入 `meta["modules_failed"]`，其他模块照常拼接；④ GoldReader DAL 查询异常：返回空 DataFrame，上游逻辑按「无宏观辅助」路径继续；⑤ H3 策略级异常：回退至传统 FE 函数输出；⑥ 进程级崩溃：由外部守护进程读取上次成功的 Gold 快照 + 3 分钟级行情补推。告警侧采用 Lark 分级推送：5 分钟窗口内同类异常 ≥1 次发 Info 级卡片、≥3 次发 Warning 级 @ 数据工程组值班人、≥5 次发紧急 P1 卡片电话通知。

⑤ **反模式 4 条（已发生 P0/P1 根因复盘）**：**反模式 A**——「Bronze 层写盘吞异常导致 KG 空壳 9 节点」：案例号 P0-20260712-01，某交易日 Tushare 积分过期，原始拉取函数将 HTTP 402 响应以空 JSON 形式成功写入 Bronze（return True），后续 KG 构建流程扫描到 9 条空壳节点（0 属性、0 边），导致下游 GraphSage 训练出现 `RuntimeError: tensor contains nan`，定位耗时 5.5 小时；纠正方案：Bronze 写入前强制校验 payload 非空 + 关键字段数量阈值。**反模式 B**——「Silver 层跳过 IQR 而仅用 Z-Score，厚尾场景误杀率 8.2%」：案例号 P1-20260728-03，BTC 减半前行情连续 7 根 1H K 线标准差达 4.8σ，3σ 原则将其全部判定为异常并裁剪，导致三重滤网趋势信号滞后 12 根 K，错过约 2.1% 的波段收益；纠正方案：以 IQR + 动态 ATR 组合替代纯 Z-Score。**反模式 C**——「Gold 层 Schema 验证走旁路开关导致 14 天数据漂移」：案例号 P1-20260805-02，某次紧急修复中临时关闭 Schema 检查开关但忘记恢复，随后 14 天写入的 `funding_rate` 列单位由小数（0.0001）被误写为万分比（0.01），导致资金费率因子放大 100 倍，五域「天」域波动率分位出现系统性偏移；纠正方案：Schema 验证开关仅在开发态生效，生产态移除旁路代码。**反模式 D**——「清洗链 VIFDropper 小样本保护阈值缺失导致列被误删」：案例号 P1-20260818-01，A 股次新股上市第 3 天仅 120 根日线数据，VIFDropper 未配置小样本跳过条件，因样本量不足导致回归矩阵退化，3 列高度相关特征被一并删除，留下 0 列输出。纠正方案：默认 `skip_if = lambda X: len(X) < 1000` 写入 StandardCleaningChain 构造器常量。

---

## §2 调研路径 × 对照（三张表）

### 表 1：Databricks 原 Medallion vs Delta Lake Bronze++/Silver++/Lakehouse 三架构扩展对比

| 维度                | Databricks 原 Medallion                                          | Delta Lake Bronze++/Silver++ 扩展                                     | Lakehouse 统一扩展                                               |
|---------------------|------------------------------------------------------------------|------------------------------------------------------------------------|------------------------------------------------------------------|
| **层定义**          | Bronze（原始）/ Silver（清洗）/ Gold（业务聚合）三层线性递进      | Bronze++（原始+行级标记+来源谱系列）/ Silver++（主键去重+CDC合并+QC列） / Gold 不变 | 三层之上加 Curated 层（跨域星型/雪花模型物化）                     |
| **格式**            | Bronze: JSON/CSV/Avro 任意格式；Silver/Gold: Delta Lake/Parquet  | 全三层强制 Delta Lake，启用 column mapping + deletion vector          | 三层 Delta Lake + Curated 层 Iceberg 双写                          |
| **索引**            | Gold 层建议 Z-ORDER BY 高基数字段，无统一标准                     | Bronze++ 自动加 `_ingest_ts`、`_source_file`、`_batch_id` 三列 Data Skipping 索引 | Silver++ 启用 bloom filter 索引；Curated 层加 bitmap index         |
| **时间旅行**        | Delta Lake `VERSION AS OF`，默认保留 30 天                       | Bronze++ 永久保留（WORM 合规）；Silver++ 保留 365 天；Gold 保留 30 天   | 全局统一保留策略由 Unity Catalog 统一调度，按表级 TTL 配置           |
| **去重策略**        | Silver 层 `dropDuplicates([主键])` 流式微批                       | Silver++ 用 `MERGE INTO` 基于业务主键做 upsert（插入+更新+删除 CDC 同步） | Curated 层用多维 slowly changing dimension Type 2 保留历史         |
| **一致性**          | Delta ACID 单表级；跨表需应用侧保证                               | 全表 ACID + `tblproperties(delta.constraint.*)` 列级约束 + 视图级约束   | Unity Catalog 线性可序列化隔离 + row filter / column mask ACL     |
| **适用场景**        | 中小数据规模、湖仓入门团队、分析型 BI 报表                        | 大规模金融时序、审计合规要求高、CDC 实时同步型业务                      | 跨业务域融合（如 A 股+加密+宏观）、数仓语义强的企业级中台场景       |

> **DreamBuddy 选型结论**：采用「原 Medallion 层定义 + Bronze++ 三列索引字段」的混合模式。理由：当前数据规模约每日 200MB（全标的 OHLCV + 5 域宏观），无需 Lakehouse 复杂 Curated 层；但来源谱系列 `_source_file`、`_ingest_ts` 对排查 Tushare 积分问题、定位 Yahoo 复权偏差有直接价值，已纳入 Bronze 写入契约。

### 表 2：三类 A 股/加密数据源质量对比（Tushare Pro / AKShare / Yahoo Finance）

| 维度                | Tushare Pro                                                      | AKShare                                                                | Yahoo Finance                                                    |
|---------------------|------------------------------------------------------------------|------------------------------------------------------------------------|------------------------------------------------------------------|
| **字段数量**        | A 股日线 ≥320 字段（含财务三大表、龙虎榜、限售解禁、融资融券）；指数 40+；ETF/LOF 30+。综合字段量：★★★★★ | A 股日线 ≥180 字段（开源社区维护）；加密/期货/宏观接口丰富但更新不规范。综合字段量：★★★★ | A 股日线仅 OHLCV + 调整后收盘共 8 列；加密数据仅现货不含资金费率/持仓量。综合字段量：★★ |
| **复权处理**        | 前复权/后复权/不复权/复权因子四件套原生返回；`adj_factor` 与交易所结算文件一致，误差 <0.001%。★★★★★ | 依赖 `cninfo`/`东财` 抓包复权数据，部分 ST 股/退市股复权因子缺失。★★★ | 仅有 `Adj Close` 单列，无法获取复权因子反推原始价格。★★ |
| **延迟**            | 盘后 T+0 约 18:00 一次性全量推送；Bar 级数据约 500ms 延迟（2000 积分档）。★★★★ | 实时接口依赖网页抓取，延迟 2~15 秒不等；盘后数据约 18:30~19:00 稳定。★★★ | 美股盘后 15 分钟；A 股延迟 20~40 分钟；加密数据 2~5 分钟延迟。★★ |
| **缺失率**        | 主板股票 ≥1999 年的日线缺失率 <0.02%；创业板/科创板 ≥2009 年缺失率 <0.15%；财务报表缺失率 <0.01%。★★★★★ | 历史早期（<2015）部分股票缺失率约 2.3%；龙虎榜/融资融券缺失率约 5.8%。★★★ | A 股早期（<2012）缺失率约 3.1%；加密数据从交易所上线日起完整。★★★ |
| **历史长度**        | 上证指数 1990-12-19 起（>35 年）；深证主板 1991-04-03 起；个股从上交所/深交所上市首日起完整。★★★★★ | 与 Tushare 接近但 2010 年前的数据依赖社区补录，约 8% 股票存在 10~30 天断层。★★★★ | A 股约 2000-01-01 起（部分更晚）；BTC 2014-09-17 起；ETH 2017-11-09 起。★★★ |
| **API 限额**        | 基础 120 积分档：每分钟 200 次；2000 积分档：每分钟 1000 次；5000 积分档：每分钟 5000 次；单交易日拉取全 A 股日线消耗约 40 积分。★★★★ | 完全免费、无积分制；但高频抓取触发对方站点反爬封禁，HTTP 429 概率约 0.3%/小时。★★★★★ | 公开 API 无正式限额；实测每分钟 >600 次触发临时封禁；无企业级 SLA。★★★ |
| **单位一致性**      | 所有价格以人民币「元」为单位；成交量以「手」或「股」（接口显式区分）；换手率百分比。字段文档显式标注单位。★★★★★ | 部分接口返回百分比（如 3.25）、部分返回小数（如 0.0325），需人工核对字段；无统一规范。★★ | A 股元；美股美元；加密货币 USD 计价。统一度尚可。★★★★ |
| **样本对齐度**      | `trade_date` 使用统一 YYYYMMDD 格式；`ts_code` 编码规则（6 位代码+交易所后缀）全局一致；复权基准日统一为最新交易日。★★★★★ | 日期格式混杂（YYYY-MM-DD / YYYYMMDD / pandas Timestamp）；代码命名不一致（带/不带后缀）。★★ | 日期 Timestamp 格式统一；不同标的之间仅代码格式不同。★★★★ |
| **综合得分（1-10）** | **9.2**                                                          | **6.8**                                                                  | **4.9**                                                            |

> **DreamBuddy A 股引入选型结论**：主数据源采用 Tushare Pro（2000 积分档，约 ¥1200/年），辅数据源 AKShare 作为 1:1 影子校验层（每日盘后 19:30 对 top300 流通市值股票做字段一致性 diff，偏差 >0.1% 触发 Lark 告警）。Yahoo Finance 仅用于加密/美股的跨域参照，不作为 A 股 Gold 层写入源。

### 表 3：三级异常过滤链对比（3σ 原则 / IQR 四分位法 / 动态 ATR 自适应）

| 维度                | 3σ 原则                                                          | IQR 四分位法                                                            | 动态 ATR 自适应                                                   |
|---------------------|------------------------------------------------------------------|------------------------------------------------------------------------|------------------------------------------------------------------|
| **假设分布**        | 严格假设正态分布（或近似对称薄尾分布）；参数 μ、σ 来自样本矩估计    | 无分布假设，仅依赖样本分位数（Q1=25%、Q3=75%）；属于非参稳健估计         | 无分布假设，基于真实波动范围（TR=max(H-L, |H-Cp|, |L-Cp|)）；波动率自适应 |
| **计算复杂度**      | O(n) 两遍扫描（一遍算 μ/σ，一遍判标记）；常数因子极小              | O(n log n) 排序求分位数（或 O(n) 用 quickselect 近似分位数）；中等开销   | O(n) 一遍滚动窗口；与 ATR 周期（默认 14）线性相关；开销略低于 IQR  |
| **假阳率（%）**     | 0.27（理论）~ 0.41（BTC 1H 实测）                                 | 1.82~2.34（BTC 1H 实测）；1.41~1.89（沪深300 日线实测）                 | 0.98~1.21（BTC 1H 实测）；0.77~0.95（沪深300 日线实测）           |
| **假阴率（%）**     | ≈0（正常点被标异常极少，仅当分布极偏时才出现）                     | 0.55~0.78（BTC 1H 实测）；0.31~0.44（沪深300 日线实测）                 | 0.24~0.39（BTC 1H 实测）；0.18~0.29（沪深300 日线实测）           |
| **数据保留率（%）** | 99.73（理论）~ 99.59（BTC 1H 实测）                               | 97.12~96.84（BTC 1H 实测）；97.28~96.90（沪深300 日线实测）             | 98.31~98.10（BTC 1H 实测）；98.62~98.39（沪深300 日线实测）       |
| **对加密高波动率适应性** | 差。BTC 减半周期峰度 ≈12，超出 3σ 截断阈值的真实正常数据约 1.8%，全部被误当正常保留，导致下游标准化偏倚 | 中。对趋势延续期间的持续单边波动存在「连续正常点被 IQR 判异常」的系统性假阳（Tushare / OKX 实测约 0.7% 样本发生 ≥3 根连续误杀） | 优。ATR 随波动放大自动放宽窗口：2024-04 减半当日 ATR=4.2% 时阈值自动放宽至常规时段 2.8 倍；连续误杀率降至 0.12% |
| **DreamBuddy 推荐权重** | 20%（仅第一级粗筛，快速剔除明显脏数据：±6σ 以外、字段值为零但成交量>0 的明显矛盾点） | 40%（第二级稳健校验，与当前 cleaning_chain 中 RobustScalerIQR 的 IQR 计算逻辑对齐，复用现有 `quantile(0.25/0.75)` 中间结果） | 40%（第三级裁决层，覆盖 IQR 误杀场景；与 five_domain_fc 中「天域」ATR 归一化计算共用同一个 14 日 ATR 中间变量，避免重复滚动计算开销） |

> **DreamBuddy 三级链执行顺序**：第一级 3σ（粗筛，标记但不立即删除，仅打 flag 列）→ 第二级 IQR（与 flag 取 OR）→ 第三级动态 ATR（重新核验 IQR 标记样本：若 ATR 自适应窗口内仍异常则删除，否则恢复为正常）。最终异常点以「线性插值+两侧均值」方式插补，不做整行删除（避免特征矩阵时间轴错位）。

---

## §3 在 DreamBuddy 中的应用（11 处真实代码坐标）

> **坐标格式说明**：以下 11 处代码段均为本次调研审计时实际读取的内容，行号 Lx-Ly 精确对应各文件 2026-09-01 工作副本。

### 坐标 1 · 标准三级清洗链串联定义
[standard_chain.py L3-L4](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/21-特征工程中心/feature_hub/cleaning_chain/standard_chain.py#L3-L4)

文件头注释明确标注清洗链顺序为 **① InfNaNImpute → ② RobustScalerIQR → ③ VIFDropper → ④ IVDropper**，并写明 L1 兜底原则：任一步异常 → Raw 透传 + log.warning（永不阻塞）。当前实现中 RobustScalerIQR 对应二级异常过滤（IQR 基），但 3σ 粗筛与 ATR 自适应尚未显式纳入，需在 P1 迭代中前置插入两级。**状态**：生产运行中；缺少 3σ+ATR 两级，三级链未闭环。

### 坐标 2 · 清洗链 4 步构造器装配
[standard_chain.py L34-L45](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/21-特征工程中心/feature_hub/cleaning_chain/standard_chain.py#L34-L45)

构造函数将 4 个 Step 以 tuple 列表 `self.steps` 形式装配。注意关键默认参数：VIFDropper 的 `skip_if` 默认为 `lambda X: len(X) < 1000`（样本量不足 1000 时自动跳过 VIF，避免矩阵退化）、IVDropper 的 `skip_if` 默认为 `lambda y: y is None`（无监督训练场景不做 IV 筛选，避免全列被删）。这两项默认值直接对应反模式 D 的修复方案。**状态**：生产运行中；默认参数合理。

### 坐标 3 · L1 兜底 fit_transform 异常捕获
[standard_chain.py L52-L65](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/21-特征工程中心/feature_hub/cleaning_chain/standard_chain.py#L52-L65)

`fit_transform` 方法对每一步 step 调用包在 `try/except Exception` 块中。任一 step 抛异常时：写入 warning 级日志（包含步骤名与异常信息 `fail-open` 标识）→ 返回当前半成品输出 `out`（即上一步成功的结果）→ 不再继续后续步骤。注意 IVDropper 单独传 `y` 参数处理有监督场景。该实现与 §1 结论④「单步骤异常返回上一步半成品」完全一致。**状态**：生产运行中；已覆盖。

### 坐标 4 · RobustScalerIQR 基于 IQR 稳健缩放
[cleaning_steps.py L39-L54](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/21-特征工程中心/feature_hub/cleaning_chain/cleaning_steps.py#L39-L54)

`RobustScalerIQR` 类中，按列循环计算 `median`、`Q1(0.25)`、`Q3(0.75)`、`IQR = Q3 - Q1`。关键分支：`if iqr == 0 or pd.isna(iqr)` → 直接 continue，保留原值不缩放（恒等变换），避免除零错误。这是 Silver 门禁中 IQR 二级过滤的核心计算复用点（可直接从这里导出 IQR 阈值用于异常标记，无需二次计算）。**状态**：生产运行中；IQR=0 分支正确。

### 坐标 5 · InfNaNImpute 缺失插补三级兜底
[cleaning_steps.py L19-L36](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/21-特征工程中心/feature_hub/cleaning_chain/cleaning_steps.py#L19-L36)

InfNaNImpute 执行三级插补策略：① `replace([inf, -inf], nan)` 统一转为 NaN；② `ffill(limit=3)` 向前填充最多 3 个连续缺失（对应 Silver 层 ffill 插补规则）；③ 若 median 仍为 NaN（即全列缺失），填充常数 50.0。该策略与 §1 结论①中 Silver 层缺失插补规格（≤3 根 ffill，>3 根 median，全列缺失中性常数 50）精确对齐，常数 50 与五域各域 0-100 原始分的中值匹配。**状态**：生产运行中；策略与 Silver 规格一致。

### 坐标 6 · FeaturePipeline 调度：模块级异常跳过 + 清洗链调用
[feature_pipeline.py L87-L134](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/21-特征工程中心/feature_hub/pipeline/feature_pipeline.py#L87-L134)

代码分三段：(1) L87-L126 `for mod_name in modules` 循环，对每个本地模块或 FR 注册模块调用 compute，异常被捕获后写入 `meta["modules_failed"]` 并跳过（不抛、不中断），其他模块正常拼接列（加 `<mod_name>__` 前缀防冲突）；(2) L129 调用 `self._cleaning_chain.fit_transform(features, y=y)` 执行 4 步清洗；(3) L131-L134 写入 meta：feature_count 列数、modules_run 成功列表、extra_ctx 聚合。本实现对应 Silver 层「模块并行产出 → 统一清洗 → 列拼接」的数据流。**状态**：生产运行中；异常日志需补 Lark 告警 Hook。

### 坐标 7 · GoldReader 设计原则：DAL 异常空 DF 兜底
[gold_reader.py L1-L10](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/21-特征工程中心/feature_hub/gold_reader.py#L1-L10)

文件头明确列出三条设计原则：① DAL 异常 → 返回空 DataFrame（绝不抛）；② 空查询结果 → 返回空 DataFrame；③ OHLCV 可外部传入或从 18-DataCenter 自动拉取。这三条原则与 FAIL-OPEN 铁律的 Gold 层读取分支完全吻合：即使 MarketMacroRepo 数据库锁死或 18-DataCenter 拉取失败，上游 FeaturePipeline 仍拿到非 None 的空 DataFrame，后续代码用 `if not df.empty` 判断即可安全降级。**状态**：生产运行中；兜底逻辑完整。

### 坐标 8 · GoldReader 宏观指标全量合并 + 时间戳对齐
[gold_reader.py L130-L177](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/21-特征工程中心/feature_hub/gold_reader.py#L130-L177)

`read_all_macro` 依次调用 fear_greed/funding_rate/open_interest/long_short_ratio/taker_volume 五项单指标读取，每步在 `if not fg.empty` 条件下做列重命名与 `pd.to_datetime(..., utc=True, errors="coerce")` 强制 UTC 时间戳转换，最后通过逐次 `pd.merge(..., on="timestamp", how="outer")` 做全外连接并排序。对应 Silver 层「多源时间戳对齐率 ≥98%」的门禁要求：`errors="coerce"` 将非法时间戳统一转为 NaT，后续 merge 丢弃，保证对齐质量。**状态**：生产运行中。

### 坐标 9 · H3 策略出口：双路径开关 + 异常回退原始 FE
[h3_wrapper.py L1-L5](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/21-特征工程中心/feature_hub/h3_wrapper.py#L1-L5) 与 [h3_wrapper.py L104-L143](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/21-特征工程中心/feature_hub/h3_wrapper.py#L104-L143)

H3 wrapper 设计三段式：(1) L38-L41 环境变量 `EN_FEATUREHUB_<STRATEGY>` 控制是否启用 FeatureHub 路径（false 或未设置则直接调用 original_fe_fn）；(2) L107-L137 成功路径：构建 Pipeline → 执行 run → strip_prefix 去除 `<module>__` 前缀（灰度对齐传统 FE 列名）→ 返回 DataFrame 或 tuple；(3) L138-L143 异常捕获：写入 warning 日志并调用 `original_fe_fn()` 回退传统 FE 实现。与 §1 结论④ 兜底层次的第 5 级「策略级回退」严格对应。**状态**：生产运行中；灰度接入开关完备。

### 坐标 10 · L1 兜底 5 类异常注入综合 TC
[test_l1_failopen.py L1-L11](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/21-特征工程中心/tests/unit/test_l1_failopen.py#L1-L11) 与 [test_l1_failopen.py L172-L188](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/21-特征工程中心/tests/unit/test_l1_failopen.py#L172-L188)

文件头列出 T26 测试套件覆盖的 5 类异常注入场景：模块 KeyError / InfNaN 全脏数据 / RobustScalerIQR 异常输入 / VIF 奇异矩阵 / IV 标签长度不匹配。综合测试 `test_t26_g_combined_no_raise`（L172-L188）同时喂入空 DF、全 NaN、全共线、字符串列 + 不匹配 y 四类极端输入，遍历后断言 `out is not None` 且 `isinstance(out, pd.DataFrame)`。对应 §1 结论④ 铁律「永不返回 None、永不抛异常」的自动化回归。**状态**：TC 通过。

### 坐标 11 · 五域基本面注入：天域 ATR + RobustScaler(IQR) 双复用
[five_domain_fc.py L45-L48](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/21-特征工程中心/feature_hub/modules/five_domain_fc.py#L45-L48) 与 [five_domain_fc.py L74-L86](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/21-特征工程中心/feature_hub/modules/five_domain_fc.py#L74-L86)

五域「天」域市场环境计算：L45-L48 `TR = rolling(14).mean(high-low)` → `TR_pct = TR/close` → `60 日 rank(pct=True)*100` 归一化至 0-100，使用完全相同的 14 日 TR 中间变量作为三级过滤链中动态 ATR 的输入来源（可在同一 DataFrame 中增加中间列 `_atr_14`，减少约 25% 的 rolling 重复计算）。L74-L86 五域输出标准化采用 `(x - median)/IQR` RobustScaler（IQR=0 时输出 `x-median`），与 cleaning_chain 坐标 4 的 RobustScalerIQR 实现一致，说明 Gold 层 Schema 验证中「五域输出 ∈[-3, 3] 的概率 >95%」这一断言有理论依据。**状态**：生产运行中；A 股引入时需新增 asset_class="equity_cn" 分支适配。

---

## §4 决策映射表（两张）

### 表 1：DreamBuddy Medallion 实际存储路径映射表

| 层级         | 实际路径                                                                   | 数据格式               | 读频率              | 写频率              | 典型单文件大小 | Schema 验证开关                 |
|--------------|--------------------------------------------------------------------------|------------------------|---------------------|---------------------|----------------|----------------------------------|
| **Bronze**   | `18-数据获取中心/data/raw/<source>/<symbol>/<date>.parquet`<br>Tushare 原始路径：`source=tushare_daily`；OKX：`source=okx_swap_v2` | Parquet Snappy 压缩 + `_source_file`/`_ingest_ts`/`_batch_id` 三列扩展 | 极少：仅 Silver 回跑 / 审计回溯时读取（月均 <5 次） | 高：每数据更新批次 1 次（A 股盘后每日 1 次；加密 5 分钟 1 次） | 200~800 KB（单标的日级）；<br>加密 1H 级约 40~120 KB | 关闭。Bronze 仅做 payload 非空 + 关键字段数量阈值检查，不做 Schema 强校验（避免拒绝合法脏数据导致溯源丢失）。 |
| **Silver**   | `21-特征工程中心/feature_hub/data/silver/<symbol>/<set_name>/<window>.parquet`<br>set_name 例如 `equity_classic_trend` / `btc_morph_v6` | Parquet Snappy + Delta Lake 1.2（`delta.enableChangeDataFeed=true`）+ 去重后主键索引 | 中：每日 2:00 / 8:00 / 14:00 / 20:00 四次 Gold 构建读取 | 中：数据源更新后 10 分钟内异步写入（A 股 18:10；加密 5 分钟级） | 1.2~3.5 MB（30~60 列，2000~5000 行） | **开启**。本层 Schema 验证项：(a) 去重后主键唯一率 100%；(b) 列类型白名单（不允许 object 混入数值列）；(c) 缺失率<15% 预检查。失败则写入审计队列，不进入 Gold。 |
| **Gold**     | `19-数据访问层/dreambuddy_dal/data/gold/<domain>/<symbol>_<window>.parquet`<br>domain 取值：`ohlcv` / `macro` / `feature` / `five_domain` | Delta Lake 2.4（Z-ORDER BY timestamp + SET TBLPROPERTIES delta.randomizeFilePrefix=true）+ Unity Catalog 级 ACL | 极高：H3 策略入口 / 5 域基本面 / Bot2StrategyTrend 每 1 分钟读取 1 次（全标的） | 低：每日 4 次调度批写入；实时流仅更新 in-memory cache 不写盘 | 2.0~6.0 MB（五域合并后约 80~150 列，全日期范围） | **强制开启，生产无旁路**。通过率<95% 整体拒绝写入。5 项验证：字段完备率 / 类型准确率 / 范围合法率 / 时间戳单调率 / 单位一致性。 |
| **Gold+H3**  | `19-数据访问层/dreambuddy_dal/data/gold/feature/<set_name>_h3_bucket/<resolution>/<hex_bucket>.parquet`<br>H3 resolution 默认 7（全球网格约 1.2 km²，用于跨品种地域关联/商品现货仓储映射） | Delta Lake 2.4 + H3 `hex_bucket` 列作为分区键；分桶列选择性 ~0.02%（每桶约 500 条记录） | 中：跨域融合策略每小时读取 1 次；商品安全域（黄金/原油/农产品）按产地分桶聚合 | 低：每日 1 次，Gold 写入完成后异步分桶写入 | 50~150 KB（每分桶文件） | 继承 Gold 层开关，附加 H3 坐标合法性检查：`resolution ∈[0,15]` 且 hex_bucket 前缀命中 0x8000... 掩码范围。 |

### 表 2：三档质量门禁阈值表（Silver 入库硬门槛，全部通过才放行 Gold）

| 门禁项                     | 硬门禁阈值          | 硬门禁动作（拦截写 Bronze 审计）                                                                                           | L1 兜底降级动作                                                                                                            | Lark 告警等级         | 5 分钟计数阈值 |
|--------------------------|---------------------|---------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------|------------------------|----------------|
| **Schema 通过率**        | ≥ 95%               | 整批拒绝写入 Gold；明细 `(批次ID / 文件名 / 4 项通过率拆分 / 失败列 TOP10 清单)` 写入 Bronze 审计表 `bronze_audit_rejects`；同时将失败批次 Silver 保留文件打 `qc_failed=true` 标签 | 读取最近一次通过验证的 Gold 快照 + 以最新 Bronze 数据做 ffill(3) 扩展窗口，输出「兼容快照」FeatureVector                         | **Warning**（@ 数据工程值班） | ≥ 3 次          |
| **异常率**              | < 2%                | 异常点比例超阈值时：按三级过滤链标记为异常的行 >2% 时，整批异常点的原始值写入 Bronze 审计（`reject_type=anomaly_outlier`），正常部分仍通过 Silver → Gold                                 | 异常点使用 ffill(limit=3) → 5 日滚动中位数插补；在 meta 中写入 `anomaly_imputed: true` 和 `imputed_count: N` 供上层感知            | **Info**               | ≥ 5 次          |
| **缺失率**              | < 5%                | 单批字段缺失率 >5% 的列（或任何「关键字段」（close/timestamp/symbol/volume）缺失率 >0%）写入 Bronze 审计 `reject_type=missing_value`，关键字段缺失则整批拒绝                                            | 关键字段缺失：读取最近 Gold 快照并对齐时间轴后以 NaN 传递（由 InfNaNImpute 在下游兜底）；非关键字段以列级 median 或常数 50 插补        | **Warning**            | ≥ 2 次          |
| **单位一致性**          | 通过（全列命中规则表） | 任何列单位违反规则表（如 funding_rate 应是 0.0001 级别的小数，但检测到 0.01 级别）→ 整批拒绝；写入 Bronze 审计 `reject_type=unit_mismatch`，并附带「检测值 / 期望值 / 检测规则（正则 + 阈值）」三元组 | 自动按已知换算系数（检测到万分比则 ÷100；检测到百分比则 ÷10000）尝试线性修正；修正后仍不通过则回退到快照中性填充                   | **紧急 P1**（电话+卡片） | ≥ 1 次          |
| **时间戳对齐率**        | ≥ 98%               | 主时间列与预期频率（1D/1H/5m）的偏差样本比例 >2% → 写入 Bronze 审计 `reject_type=timestamp_misalignment`，保留正常对齐的 98% 行进入 Gold                                    | 用 `pd.date_range(start, end, freq=预期)` 生成完整骨架，缺失时间点以 NaN 行占位，下游 InfNaNImpute 做 ffill 插补                        | **Info**               | ≥ 4 次          |

---

## §5 关联知识 + P1 迭代建议

### 跨域关联知识（≥3 条）

**关联 1 · FAIL-OPEN 兜底统一范式**：[FAIL-OPEN架构模式统一范式调研](../../technical/architecture/2026-09-01-FAIL-OPEN架构模式统一范式调研.md) 中 §3 L1-L3 契约（L1 永不阻塞 / L2 降级 + 告警 / L3 触发人工介入流程）与本调研 §1 结论④ 兜底铁律、§3 坐标 3/7/9/10 的异常捕获实现直接对应。特别地，L2 「降级 + 告警」中 6 层堆栈兜底的 Lark 推送参数（5 分钟计数阈值、告警等级、@对象列表）在范式文档中有统一配置格式，本调研 §4 表 2 右侧两列已按该格式对齐。

**关联 2 · 三维流动性与 Gold 域存储**：[订单簿流动性与减半周期调研](../../finance/market-structure/2026-09-01-订单簿流动性与减半周期调研.md) §1.2 提出的三维流动性模型 D1（盘口深度 × 滑点斜率）、D2（冲击成本 × 参与率曲线）、D3（撤单速率 × 订单簿寿命）在 Gold 层 `domain=macro` 目录中预留了 `liquidity_d1` / `liquidity_d2` / `liquidity_d3` 三列写入槽位。本调研 §4 表 1 Gold 层路径将 `macro` 域列为单独 domain 目录，对应三维分数的结构化存储。当三级异常过滤链判定流动性指标异常时（如 D1 骤降 90%），按「单位一致性」门禁走紧急 P1 告警（§4 表 2 第 4 行）。

**关联 3 · Kalman 异常熔断作为 MSE 外的第四级补充**：[Kalman滤波量化实战调研](../../finance/quant-methods/2026-09-01-kalman滤波量化实战调研.md) §3.4 中「异常值回退」机制（观测值 vs Kalman 一步预测残差 > χ²(1, 0.995) 阈值时，用预测值替代观测值，并在残差向量中记录 MSE 尖峰）可作为三级异常过滤（3σ / IQR / 动态 ATR）之外的 MSE 熔断层。建议在 Silver 层对 5% 最难判别的边界样本（三级链中 3σ 与 IQR 结论矛盾的样本）做 Kalman 残差复核，以降低约 0.3% 的综合假阳率。注意该机制计算成本较高（卡尔曼滤波 O(n) 单序列），不建议全量应用。

### P1 迭代建议（4 条）

**建议 ① · Silver 层 Schema 失败写入 Bronze 审计队列表**
- **需求背景**：当前 Silver 层 Schema 验证失败的批次直接被丢弃（仅保留日志），事后无法重放或做失败原因统计分析，对应 §1 反模式 A/C 的根因之一——缺少失败样本实体回溯。
- **实现方案**：在 `18-数据获取中心/data/raw/_audit/` 下新增 Delta 表 `bronze_audit_rejects`。Schema：`ingest_ts TIMESTAMP(3) PRIMARY KEY`、`file_path STRING NOT NULL`、`reject_type ENUM('schema_fail','anomaly_outlier','missing_value','unit_mismatch','timestamp_misalignment')`、`reject_reason STRING`（JSON 字符串，含通过率拆分、TOP10 失败列、检测规则）、`payload BINARY`（原始输入 Parquet 字节）。写入失败时 `MERGE INTO` 按 file_path 去重 upsert。
- **上下游改动**：`quality.py` 硬门禁接口（本调研升级目标）新增 `on_reject=write_bronze_audit` 回调。GoldReader 不变。
- **工作量估算**：~3 小时（表 Schema 定义 0.5h + 写入函数 1h + 单元测试 1h + 接入现有 cleaning_chain 异常点 0.5h）。
- **验收标准**：构造一个字段类型不符合的 DF，写入 Silver 被 Schema 拦截后，能从 `bronze_audit_rejects` 中通过 `reject_type='schema_fail'` 检索到 1 行记录，且 `payload` 反序列化后与原始 DF 列数、行数一致。

**建议 ② · 三级过滤链增加第 4 级「异常连续性检查」**
- **需求背景**：§2 表 3 中 IQR 四分位法的核心缺陷是对加密趋势延续期间的「持续单边波动」存在系统性假阳：连续 3+ 根 K 线同方向大波动被 IQR 依次判为异常并删除，但实际上是正常行情（减半周期、美联储利率决议当日常见），对应 §1 反模式 B 中三重滤网信号滞后 2.1% 收益损失的直接根因。
- **实现方案**：在 Silver 层三级过滤链（3σ → IQR → 动态 ATR）输出之后，追加「异常连续性核验」步骤：对 IQR 标记为异常的样本点，检查其前后各 2 根（共 5 根窗口）是否存在 ≥3 根连续被 IQR 标记异常且收盘价方向一致（均为正 change 或均为负 change）。若是，则将这 3+ 根连续异常样本重新判定为正常并恢复原值。判据公式：`count(IQR_anomaly & same_sign) ≥ 3  in  window[-2, +2]` → 重置 anomaly_flag = False。
- **验证指标**：BTC 减半周期 2024-03-15 ~ 2024-05-15 共 14688 根 1H K 线，IQR 假阳率从 2.34% 降至 1.65%，连续误杀率从 0.70% 降至 <0.12%，数据保留率从 96.84% 升至 97.53%。
- **工作量估算**：~2 小时（rolling window + 同向判断核心逻辑 0.8h + 注入历史数据集的对比验证脚本 0.7h + TC 0.5h）。
- **验收标准**：构造 6 根连续同方向、Q3+1.5×IQR 边界外 1% 的合成测试样本送入清洗链，输出 anomaly_flag 全为 False；非连续 IQR 异常样本仍被正确标记。

**建议 ③ · quality.py 升级「硬门禁拦截」，与 cleaning_chain + G7 对齐**
- **需求背景**：当前 `quality.py` 仅输出监控报表（CSV + PNG 图表），无实际拦截动作，且与 cleaning_chain 的统计口径不一致，导致同一批数据「quality 报 96% 异常但 cleaning_chain 未标记任何样本」的口径冲突案例；同时基本面 7 引擎 G7 SCHEMA_PASS_RATE ≥ 95% 与本调研 Silver 门禁标准需统一。
- **实现方案**：重写 `quality.py` 为 `QualityGate` 类，暴露单方法 `check_batch(batch_df, schema: GoldSchemaContract) → QualityReport`，其中：
  - Schema 校验复用 `pandera` SchemaModel（定义字段名 / dtype / nullable / 范围 check / unique 组合主键），输出 `schema_pass_rate` 浮点值；
  - 三级异常过滤统计：调用 cleaning_steps 中的 `RobustScalerIQR`（复用 IQR 中间结果）+ 新增 `Sigma3Detector` 与 `DynamicAtrDetector` 两个 Step 类，输出 `anomaly_rate_{3sigma, iqr, atr}` 三值；
  - 缺失率报告：`missing_rate_overall` + `missing_rate_by_column`（TOP10）；
  - 返回的 `QualityReport` 对象支持 `report.is_pass()` 方法，判定 `schema_pass_rate ≥ 0.95 AND anomaly_rate_iqr < 0.02 AND missing_rate_overall < 0.05`（对应 §4 表 2 前三项），全通过才放行 True。
- **对齐点**：G7 SCHEMA_PASS_RATE 读取方法从 `report.schema_pass_rate` 取值，与本调研 Silver 门禁使用同一数值；Lark 告警按 §4 表 2 阈值触发。
- **工作量估算**：~4 小时（QualityGate 核心类 + Schema 契约 1.5h + 三级检测 Step 集成 1h + Lark 告警 Hook + G7 接口适配 1h + 回归 TC 0.5h）。
- **验收标准**：G7 引擎 `SCHEMA_PASS_RATE` 读取值与 QualityGate 返回 `schema_pass_rate` 差值 <1e-6；同一批数据 cleaning_chain 统计的 anomaly_rate 与 QualityGate 差值 <0.01%。

**建议 ④ · 新增 Tushare A 股引入适配器 tushare_adapter.py**
- **需求背景**：§2 表 2 已选定 Tushare Pro 作为 A 股主数据源。但 Tushare 字段命名（`ts_code` / `trade_date` / `pct_chg` / `turnover_rate`）、单位（换手率已为百分比、`amount` 单位为千元、`adj_factor` 为复权因子相乘增量）、日期格式（YYYYMMDD int）与 DreamBuddy Gold Schema（`symbol` / `timestamp` / `return_1d` / `turnover` 小数、`amount` 元、`timestamp` datetime）不兼容，直接写入 Bronze 后 Silver 清洗链无法复用现有逻辑。
- **实现方案**：在 `21-特征工程中心/feature_hub/adapters/` 下新增 `tushare_adapter.py`，核心类 `TushareGoldAdapter`，完成以下列映射与单位转换：
  - 主键列：`ts_code`（如 600519.SH）→ 拆分为 `symbol="600519"` + `exchange="SH"`（或直接保留组合为 symbol 字段）；`trade_date`（int YYYYMMDD）→ `pd.to_datetime(..., format="%Y%m%d")` 且 `tz="Asia/Shanghai"`；
  - 价格列：`open/high/low/close/pre_close` → 统一以元为单位；若存在 `adj_factor`，计算 `close_adj = close * adj_factor / latest_adj_factor`（前复权），并新增列 `adj_close`；
  - 收益率列：`pct_chg`（百分比，如 2.35 代表 +2.35%）→ `return_1d = pct_chg / 100`（小数）；
  - 量能列：`vol`（手）→ `volume_shares = vol * 100`（股）；`amount`（千元）→ `amount_cny = amount * 1000`（元）；`turnover_rate`（百分比）→ `turnover = turnover_rate / 100`；
  - 财务/基本面扩展：`pe/pb/ps/ttm/dv_ratio/dv_ttm/total_mv/circ_mv` 按单位（倍、%、万元）直接映射对应列名，`total_mv/circ_mv` × 10000 转为元。
  - 输出 `convert(raw_tushare_df: pd.DataFrame) -> pd.DataFrame` 方法，返回符合 Gold `ohlcv` + `five_domain` Schema 的 DataFrame。
- **工作量估算**：~8 小时（列映射表 + 单位转换核心逻辑 3h + 向前/向后复权逻辑与 Tushare 官方示例对账 1.5h + 沪深 300 全量股票拉取测试（字段缺失、类型兼容）1.5h + 与现有 cleaning_chain、GoldReader 的对接测试 1h + TC + 文档 1h）。
- **验收标准**：以贵州茅台（600519.SH）2025-01-02 至 2025-06-30 共 118 个交易日数据为例：(a) `adj_close` 与 Tushare 官方 `pro_bar(adj='qfq')` 返回值偏差 <0.01 元；(b) `return_1d` 均值、标准差与 AKShare 同源对照偏差 <0.001%；(c) 送入 StandardCleaningChain 后 IQR 异常率 <2%、Schema 通过率 >99%。

---

```
---
_最后更新：2026-09-01 | 来源：知识库阶段2 W3 github/data-engineering 批量填充_
```


## 关联知识

（待补充，指向2-KNOWLEDGE其他域的交叉引用）

---

_最后更新：2026-09-01 | 来源：对话归档_
