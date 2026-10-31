# SPEC-33-外部真实源接入（真实源清单与拉取规范）

| 项 | 值 |
|---|---|
| 版本 | v1.1 |
| 日期 | 2026-10-31 |
| 状态 | 待云端评估选择 |
| 归属 | 33-REA逆向解析工程 / 反思层 P3（外部最优路径） |
| 关联 | [SPEC-33-反思层.md](./SPEC-33-反思层.md) §5；[external_sources.json](./reflection_data/external_sources.json) v2.1 |
| 交付物 | 本 SPEC + `reflection_data/external_sources.json`（97 条源） |

## 0. 决策摘要

**可以做，且建议按 SPEC 流程做。** 理由：E1–E4 注入机制已用 `local_path` 冒烟验证通过；源清单已按 10 类系统映射到内部模块；风险点（网络不可达、候选集不含外部动作、E2 未做决策还原）已在 §9 明列。

云端只需回答三件事：
1. 每类 wave1 的 P0 源能否 `git clone --depth 1` 拉通（网络与体积）；
2. 许可证是否允许"只读解析 + 不执行代码"的用法；
3. 是否同意先按 wave1（11 源）做最小闭环验收，再进 wave2。

## 1. 背景与目标

### 1.1 现状

- 回放池内部树 6650 棵，抽样 3000 棵中 2999 棵为同一序列 `acceptance_gate → code_commit → doc_sync → cognitive_record`，序列多样性 ≈ 1。
- 外部池 0 棵；`harvest`/`optimal_path` 节点无真实输入，E5 收敛对比实验无法成立。
- 做梦器候选策略只重排"当前序列"，外部动作若不进入候选集，外部树对目标函数 V 贡献为 0。

### 1.2 目标

| 编号 | 目标 | 可度量结果 |
|---|---|---|
| G1 | 每个类别至少 1 个真实源完成 E1→E4 | `external/` 树 > 0 且 provenance=external |
| G2 | 源可追溯、可回放 | 每棵树记录 repo/commit/license/采集时间 |
| G3 | 外部路径对做梦评估生效 | 注入后 V 不劣化；E5 对比有数据 |
| G4 | 不污染内部结论 | 外部树仅按权重参与 V，不覆盖内部树 |

### 1.3 非目标

- 不执行目标仓库代码、不安装其依赖、不修改目标仓库。
- 不做外部源的"持续增量同步"（本期只做一次性快照 + commit 固定）。
- 不把 GPL/LGPL 代码并入产品。

## 2. 术语

| 术语 | 定义 |
|---|---|
| 源（Source） | 一个可被采集的成熟项目（GitHub 仓库或本地目录） |
| 内部树 internal | 由 DreamBuddy 自身分析产生的发现树 |
| 外部树 external | 由外部源解析产生的发现树，`provenance=external`，带来源元数据 |
| E1 采集 | 拉取源代码到只读临时目录，记录 commit 与校验和 |
| E2 解析 | 用 33-REA 分析器把源码转为发现树节点 |
| E3 验证 | 网络/内容/交叉三重验证，决定是否可注入 |
| E4 注入 | 写入外部回放池，赋予外部初始权重 |

## 3. 数据契约（SourceEnvelope）

`external_sources.json` 单条源的结构（`harvest` 只强制读 `source_type/location/label/patterns`，其余用于云端评估与审计）：

```json
{
  "id": "backtrader",
  "category": "finance_models",
  "priority": "P0",
  "wave": 1,
  "source_type": "github_repo",
  "location": "https://github.com/mementum/backtrader",
  "label": "backtrader",
  "language": "Python",
  "license": "GPL-3.0",
  "patterns": ["backtrader", "samples", "docs"],
  "expected_analyzers": ["architecture_pattern_detector", "python_analyzer"],
  "extract_target": "strategy/indicator/broker/feed 四层事件驱动骨架",
  "size_cap_mb": 30,
  "commit": null,
  "verified": false,
  "collected_at": null
}
```

注入后每棵外部树的必填元数据：`provenance=external`、`source_id`、`repo_url`、`commit`、`license`、`collected_at`、`weight`。

## 4. 接入流程（E1–E4）

### E1 采集

```bash
# 1) 网络可达性（云端执行）
git ls-remote --heads https://github.com/<org>/<repo>.git HEAD

# 2) 只读浅克隆
git clone --depth 1 https://github.com/<org>/<repo>.git /tmp/ext/<id>

# 3) 固定版本与体积
git -C /tmp/ext/<id> rev-parse HEAD
du -sm /tmp/ext/<id>          # 超过 size_cap_mb 则转 §4.1 裁剪
```

约束：串行/限并发；单仓超时；只读挂载；采集结束记录 `commit` 与目录大小。

### E2 解析（当前实现有缺口，需云端补齐）

顺序必须是：

1. `architecture_pattern_detector.detect_architecture_patterns(root, patterns)` → 模块/模式节点；
2. `s33_rea_recover_decisions` → 设计决策节点（ADR 级）；
3. `s33_rea_narrative` → 演化叙事节点。

当前 `harvest.py` 只做第 1 步 + fallback 文件扫描，缺 2/3，导致注入的是"文件清单树"而非"决策路径树"。**这是本 SPEC 要求云端修复的第一项。**

### E3 验证

| 维度 | 通过条件 | 当前问题 |
|---|---|---|
| 网络 | `git ls-remote` 成功 / 本地目录存在 | 本机 TLS 失败，需云端验证 |
| 内容 | 节点数 ≥ 阈值、存在 ≥1 决策节点、不空树 | 依赖 E2 补齐 |
| 交叉 | 与内部树动作集有交集 | 内部动作与外部 analyzer 无交集 → 恒失败；需改为"允许 external-external 交集" |

通过率 ≥ 0.6 才注入；< 0.6 记入 rejected 并保留证据。

### E4 注入

- `provenance=external`，初始 `weight=0.5`；
- 权重区间 0.1–1.0，按后续验证通过率动态调整；
- 只参与 V 的加权评估，不写入内部结论；
- 回滚：按 `source_id` 批量删除外部树即可，不影响内部池。

### 4.1 大仓裁剪（先裁剪再解析）

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/<org>/<repo>.git /tmp/ext/<id>
git -C /tmp/ext/<id> sparse-checkout set <子目录...>
# 或者只取单目录
git clone --depth 1 https://github.com/<org>/<repo>.git /tmp/ext/<id> \
  && find /tmp/ext/<id> -mindepth 1 -maxdepth 1 ! -name '<保留目录>' -exec rm -rf {} +
```

适用于：vscode、airflow、next.js、vllm、transformers、OpenHands、duckdb、langchain。

## 5. 源准入标准

| 项 | 标准 |
|---|---|
| 语言 | Python / TypeScript / JavaScript（有对应语义分析器） |
| 排除 | Go/Java/C/C++/Rust 主仓（仅 fallback 扫描，价值低） |
| 许可证 | MIT / Apache-2.0 / BSD 优先；GPL/LGPL 仅只读；`unknown` 必须先核对 |
| 体积 | ≤ 50MB（大仓裁剪后计入） |
| 可解析性 | 一级目录或指定 patterns 能被模式检测器命中 |
| 相关性 | 必须对应到 §6 的某一内部模块，且 `extract_target` 可执行 |
| 稳定性 | 优先成熟项目；commit 固定，不追 main 头 |

## 6. 类别映射与波次

| 类别 | 内部模块 | 源数 | wave1 P0 |
|---|---|---|---|
| 数据采集系统 | 18/19/20/21 | 6 | dlt |
| 数据库系统 | 38/19/7 | 4 | sqlite-utils |
| 搜索引擎系统 | 41/24/39 | 6 | whoosh |
| 广义认知系统（五类四层） | 35/4-MEMORY/2-KNOWLEDGE/0-文档 | 5 | letta |
| 逆向解析工程 | 33-REA/五层证明链/PoE | 6 | code2flow |
| 金融交易模型 | 12/13/14/17/22/23/25/26/28/29 | 23 | backtrader |
| 前端产品应用 | 3.1-FRONTEND/34/7/L0-L2 | 5 | zustand |
| AI 大模型训练 | 40/12-ml/39/31 | 20 | peft |
| DreamOS（SACG 四层） | dreamos/S·A·C·G/BAC/16 | 12 | langgraph |
| DSH（Harness） | dream-harness-bridge/36/30 | 10 | mcp-python-sdk、pluggy |

波次规模：wave1 = 11 源，wave2 = 33，wave3 = 43，wave4 = 10（合计 97）。

## 7. 验收标准

| 编号 | 验收项 | 判定 |
|---|---|---|
| A1 | 每类至少 1 源完整跑通 E1→E4 | external 树数 ≥ 10（每类 ≥1） |
| A2 | 元数据完整 | 每棵树含 repo/commit/license/collected_at |
| A3 | 注入后做梦 V 不劣化 | `V_after ≥ V_before`（同一候选集） |
| A4 | E5 对比可执行 | 有"仅内部 vs 内部+外部"两组收敛数据 |
| A5 | 回滚有效 | 按 source_id 删除后 external=0，内部池不变 |
| A6 | 无副作用 | 目标仓未被修改、未执行其代码 |

## 8. 风险与回滚

| 风险 | 影响 | 处置 |
|---|---|---|
| 网络不可达 | E1 全失败 | 云端放行 github.com 或镜像源；失败则该源标 `unreachable` |
| 仓库过大/超时 | E1 失败 | 裁剪/子目录；仍失败则降级为 P2 |
| 许可证不明 | 合规风险 | 保持 `unknown` 不入库，人工核对后翻转 |
| 外部先验污染 | 误导反思 | 初始权重 0.5、通过率动态调整、只读不覆盖 |
| 动作集不兼容 | V 无提升 | §9 的候选生成扩展必须先做 |

回滚命令（示意）：

```bash
python3 -c "
import os
from core.reflection.replay_simulator import ReplayPool
p = ReplayPool('reflection_data/replay_pool')
for t in p.list_trees('external'):
    if t.source_label in {'backtrader','code2flow','autogen'}:
        os.remove(os.path.join(p.external_dir, f'{t.tree_id}.json'))
"
```

> 当前 `DiscoveryTree` 只有 `source_label`，尚未有 `source_id/repo/commit/license/collected_at` 字段；§3 的元数据契约需随本 SPEC 一并扩展。

## 9. 已知前置修复（云端需评估）

1. **候选生成**：`generate_candidates` 需从池中挖掘 internal+external 序列，否则外部动作进不了候选集，V 贡献 0。
2. **交叉验证**：允许 external-external 动作交集，否则 E3 交叉门禁恒失败。
3. **E2 决策还原**：`harvest` 需调用 `recover_decisions` + `narrative`。
4. **网络**：本机访问 GitHub 失败（`SSL_ERROR_SYSCALL`），全部源 `verified=false`。
5. **树元数据扩展**：`DiscoveryTree` 需新增 `source_id/repo_url/commit/license/collected_at`，否则 A2 验收无法通过。

## 10. 云端评估勾选表

对每个类别请给出：可拉取 Y/N、可解析 Y/N、许可证 OK Y/N、体积 OK Y/N、备注。

| 类别 | 源（wave1） | 可拉取 | 可解析 | 许可 | 体积 | 备注 |
|---|---|---|---|---|---|---|
| 数据采集 | dlt |  |  |  |  |  |
| 数据库 | sqlite-utils |  |  |  |  |  |
| 搜索引擎 | whoosh |  |  |  |  |  |
| 广义认知 | letta |  |  |  |  |  |
| 逆向解析 | code2flow |  |  |  |  |  |
| 金融交易 | backtrader |  |  |  |  |  |
| 前端产品 | zustand |  |  |  |  |  |
| AI 训练 | peft |  |  |  |  |  |
| DreamOS | langgraph |  |  |  |  |  |
| DSH | mcp-python-sdk / pluggy |  |  |  |  |  |

## 11. 离线源快照分发（预下载 → 压缩包 → 云端按需解压）

### 11.1 结论

**可行，推荐作为默认分发方式。** 但有两条前置条件，缺一不可：

1. **构建主机必须能访问 GitHub**：本机 `git ls-remote`/`curl` 均 TLS 失败，无法在本机预下载；需用代理/VPN、云端构建机或可信镜像（镜像必须校验 commit SHA）。
2. **上传通道必须比云端直连 GitHub 更快**：若把压缩包传到 GitHub Release，而云端下载 Release 仍走同一条慢链路，**没有收益**。应使用对象存储/CDN、内部制品库或飞书云盘等云端可达的更优通道。

### 11.2 方案

| 环节 | 做法 |
|---|---|
| 快照粒度 | 每源一个 `tar.gz`（**不含 `.git`**），文件名 `<id>-<commit12>.tar.gz` |
| 下载方式 | `https://codeload.github.com/<org>/<repo>/tar.gz/<commit>`：单次 HTTP GET，比 `git clone` 快且无需历史 |
| 版本固定 | `commit` 写入 `sources.json` 与 bundle manifest；禁止跟 main 头 |
| 校验 | `sha256` + `commit` + `license`；云端解压前必须校验 |
| 分发 | 对象存储/CDN 或内部制品库；**不要复用 GitHub 慢链路** |
| 云端使用 | 首次下载 bundle → 校验 → 按 wave 解压到缓存 `/var/cache/dsh-sources/<id>` → `harvest` 以 `local_path` 注入；未使用的源不解压 |
| 磁盘 | wave1 预计几十 MB；全量压缩约 0.5–1.5GB、解压约 3–8GB（以构建机实测为准）；按 `--only waveN` 与 LRU 清理 |

### 11.3 与现有代码的兼容性

- `harvest.fetch_source` 已支持 `local_path`（返回目录即可），**无需改核心代码**；云端解压后把 `source_type` 改为 `local_path` 即可。
- 已核查 `core/design_decision_recovery.py` **不读取 git 历史**，因此不含 `.git` 的快照足够支撑当前 E2。
- 若未来 E2 接入"按 commit 还原决策"且需要历史，对相关源改用 `mode=full`（`git bundle` 分发），并在 manifest 标记。

### 11.4 合规

仅内部使用；快照保留原仓库 `LICENSE`；GPL/LGPL 源不得公开分发或并入产品。

### 11.5 新增验收

| 编号 | 验收项 | 判定 |
|---|---|---|
| A7 | 快照完整性 | 云端 `sha256` 与 manifest 一致，commit 一致 |
| A8 | 离线可跑 | 关闭外网后 harvest 仍能从缓存完成 E1→E4 |
| A9 | 按需解压 | 只解压选中的 wave，未选源不占解压空间 |

## 附录 A：真实仓库与拉取地址（97 条）

> 验证状态：全部待云端 `git ls-remote` 验证（本机无外网）。拉取统一用 `git clone --depth 1 <clone 地址> <目录>`。许可证标 `unknown` 的（reflexion / TradingAgents / FinRobot / finclaw / skill-compose 等）注入前必须核对。

| 类别 | id | P | 仓库 | clone 地址 | 语言 | 许可 | 上限MB | 提取目标 |
|---|---|---|---|---|---|---|---|---|
| 数据采集系统 | dlt | P0 | https://github.com/dlt-hub/dlt | git clone --depth 1 https://github.com/dlt-hub/dlt.git /tmp/ext/dlt | Python | Apache-2.0 | 50 | schema 演化/增量加载/源-管道-目的地三层抽象，对照 18→19→20 链路 |
| 数据采集系统 | airbyte | P1 | https://github.com/airbytehq/airbyte | git clone --depth 1 https://github.com/airbytehq/airbyte.git /tmp/ext/airbyte | Python/TS | MIT | 50 | Connector CDK 契约/增量同步状态机，对照 18 采集器插件化 |
| 数据采集系统 | OpenBB | P1 | https://github.com/OpenBB-finance/OpenBB | git clone --depth 1 https://github.com/OpenBB-finance/OpenBB.git /tmp/ext/OpenBB | Python | Apache-2.0 | 50 | 多数据源统一 Provider 接口 + 标准化模型层，对照 19 DAL 的多源适配 |
| 数据采集系统 | scrapy | P2 | https://github.com/scrapy/scrapy | git clone --depth 1 https://github.com/scrapy/scrapy.git /tmp/ext/scrapy | Python | BSD-3-Clause | 30 | Spider/Middleware/Pipeline 责任链，对照 20 清洗流水线 |
| 数据采集系统 | akshare | P2 | https://github.com/akfamily/akshare | git clone --depth 1 https://github.com/akfamily/akshare.git /tmp/ext/akshare | Python | MIT | 50 | 数据源函数编排与字段标准化（对照 18 的 A 股取数覆盖） |
| 数据库系统 | sqlite-utils | P0 | https://github.com/simonw/sqlite-utils | git clone --depth 1 https://github.com/simonw/sqlite-utils.git /tmp/ext/sqlite-utils | Python | Apache-2.0 | 20 | 轻量 DAL：表/索引/迁移/事务封装，对照 19-DAL 与 38-数据库管理 |
| 数据库系统 | sqlalchemy | P1 | https://github.com/sqlalchemy/sqlalchemy | git clone --depth 1 https://github.com/sqlalchemy/sqlalchemy.git /tmp/ext/sqlalchemy | Python | MIT | 50 | Engine/Pool/Session/UnitOfWork 分层，对照 DAL 连接池与事务边界 |
| 数据库系统 | chroma | P1 | https://github.com/chroma-core/chroma | git clone --depth 1 https://github.com/chroma-core/chroma.git /tmp/ext/chroma | Python/TS | Apache-2.0 | 50 | 集合/分段/元数据过滤的向量库 API 分层，对照 4-MEMORY 向量检索 |
| 数据库系统 | duckdb | P2 | https://github.com/duckdb/duckdb | git clone --depth 1 https://github.com/duckdb/duckdb.git /tmp/ext/duckdb | C++/Python | MIT | 80 | 列式执行/向量化算子（只看 Python 包边界，C++ 不入语义分析） |
| 搜索引擎系统 | whoosh | P0 | https://github.com/mchaput/whoosh | git clone --depth 1 https://github.com/mchaput/whoosh.git /tmp/ext/whoosh | Python | BSD-2-Clause | 20 | 倒排索引/分词/评分/查询 DSL 的纯 Python 实现，对照 41-文件索引 |
| 搜索引擎系统 | bm25s | P1 | https://github.com/xhluca/bm25s | git clone --depth 1 https://github.com/xhluca/bm25s.git /tmp/ext/bm25s | Python | MIT | 20 | 稀疏检索打分与 top-k 管线，对照知识库 BM25 通道 |
| 搜索引擎系统 | llama_index | P1 | https://github.com/run-llama/llama_index | git clone --depth 1 https://github.com/run-llama/llama_index.git /tmp/ext/llama_index | Python | MIT | 50 | Index/Retriever/NodePostprocessor 组合式检索，对照混合检索与重排 |
| 搜索引擎系统 | graphrag | P2 | https://github.com/microsoft/graphrag | git clone --depth 1 https://github.com/microsoft/graphrag.git /tmp/ext/graphrag | Python | MIT | 50 | 社区摘要+图检索管线，对照 24-图结构上下文压缩 |
| 搜索引擎系统 | txtai | P2 | https://github.com/neuml/txtai | git clone --depth 1 https://github.com/neuml/txtai.git /tmp/ext/txtai | Python | Apache-2.0 | 50 | 嵌入索引/管道式检索（可对照 39-金融语义蒸馏检索面） |
| 搜索引擎系统 | langchain | P3 | https://github.com/langchain-ai/langchain | git clone --depth 1 https://github.com/langchain-ai/langchain.git /tmp/ext/langchain | Python | MIT | 50 | BaseRetriever/EnsembleRetriever 契约（已有调研结论，做外部对照） |
| 广义认知系统（五类四层） | letta | P0 | https://github.com/letta-ai/letta | git clone --depth 1 https://github.com/letta-ai/letta.git /tmp/ext/letta | Python | Apache-2.0 | 50 | 分层记忆（core/recall/archival）+ 记忆自编辑，对照 4-MEMORY 三层记忆与 C2 |
| 广义认知系统（五类四层） | mem0 | P1 | https://github.com/mem0ai/mem0 | git clone --depth 1 https://github.com/mem0ai/mem0.git /tmp/ext/mem0 | Python/TS | Apache-2.0 | 50 | 抽取-去重-更新-检索四段记忆流水线，对照 C2 记忆层写路径 |
| 广义认知系统（五类四层） | dspy | P1 | https://github.com/stanfordnlp/dspy | git clone --depth 1 https://github.com/stanfordnlp/dspy.git /tmp/ext/dspy | Python | MIT | 40 | 程序化提示优化/自动编译，对照反思层的策略寻优与 C4 元认知 |
| 广义认知系统（五类四层） | reflexion | P2 | https://github.com/noahshinn/reflexion | git clone --depth 1 https://github.com/noahshinn/reflexion.git /tmp/ext/reflexion | Python | unknown | 30 | 自我反思+情景记忆+重试循环（反思层 P4/P5 的学术原型） |
| 逆向解析工程 | code2flow | P0 | https://github.com/scottrogowski/code2flow | git clone --depth 1 https://github.com/scottrogowski/code2flow.git /tmp/ext/code2flow | Python | MIT | 20 | 调用图构建与入口发现，对照 call_chain_tracer |
| 逆向解析工程 | pydeps | P1 | https://github.com/thebjorn/pydeps | git clone --depth 1 https://github.com/thebjorn/pydeps.git /tmp/ext/pydeps | Python | BSD-2-Clause | 20 | 模块依赖图与循环依赖检测，对照 dependency_graph |
| 逆向解析工程 | pycg | P1 | https://github.com/vitsalis/PyCG | git clone --depth 1 https://github.com/vitsalis/PyCG.git /tmp/ext/pycg | Python | MIT | 30 | 静态调用图算法与基准集，作为调用链解析质量标尺 |
| 逆向解析工程 | ast-grep | P1 | https://github.com/ast-grep/ast-grep | git clone --depth 1 https://github.com/ast-grep/ast-grep.git /tmp/ext/ast-grep | Rust/TS/Python | MIT | 50 | tree-sitter 结构查询与规则引擎（只解析绑定层与规则组织） |
| 逆向解析工程 | pyright | P2 | https://github.com/microsoft/pyright | git clone --depth 1 https://github.com/microsoft/pyright.git /tmp/ext/pyright | TypeScript/Python | MIT | 50 | 符号表/类型推断/引用解析，对照 python_analyzer 的语义深度 |
| 逆向解析工程 | semgrep | P2 | https://github.com/semgrep/semgrep | git clone --depth 1 https://github.com/semgrep/semgrep.git /tmp/ext/semgrep | OCaml/Python | LGPL-2.1 | 50 | 规则-匹配-污点分析的分层，作为 35-SPEC 所述 CodeQL 升级参照 |
| 金融交易模型 | backtrader | P0 | https://github.com/mementum/backtrader | git clone --depth 1 https://github.com/mementum/backtrader.git /tmp/ext/backtrader | Python | GPL-3.0 | 30 | strategy/indicator/broker/feed 四层事件驱动骨架，对照 22-执行引擎 |
| 金融交易模型 | jesse | P1 | https://github.com/jesse-ai/jesse | git clone --depth 1 https://github.com/jesse-ai/jesse.git /tmp/ext/jesse | Python | MIT | 50 | candle-time 原子化 + numpy 预缓存 + 向量化指标，对照 12-三屏指标计算 |
| 金融交易模型 | freqtrade | P1 | https://github.com/freqtrade/freqtrade | git clone --depth 1 https://github.com/freqtrade/freqtrade.git /tmp/ext/freqtrade | Python | GPL-3.0 | 50 | FreqAI 特征工程/time-split/LightGBM 管线，对照 Screen1 七维权重训练 |
| 金融交易模型 | vnpy | P2 | https://github.com/vnpy/vnpy | git clone --depth 1 https://github.com/vnpy/vnpy.git /tmp/ext/vnpy | Python | MIT | 50 | EventEngine + Gateway + App 分层，对照 29-事件驱动与 CTP 接入 |
| 金融交易模型 | qlib | P2 | https://github.com/microsoft/qlib | git clone --depth 1 https://github.com/microsoft/qlib.git /tmp/ext/qlib | Python | MIT | 50 | Data/Model/Backtest 三层标准分层，对照 23-四层闭环 |
| 金融交易模型 | FinRL | P1 | https://github.com/AI4Finance-Foundation/FinRL | git clone --depth 1 https://github.com/AI4Finance-Foundation/FinRL.git /tmp/ext/FinRL | Python | MIT | 50 | env-agent-trainer 三段式 RL 交易管线，对照 40-周期神经网络决策面 |
| 金融交易模型 | TradingAgents | P2 | https://github.com/TauricResearch/TradingAgents | git clone --depth 1 https://github.com/TauricResearch/TradingAgents.git /tmp/ext/TradingAgents | Python | unknown | 40 | 多角色研究/辩论/裁决流程，对照 32-对抗性辩论 Bot |
| 金融交易模型 | FinRobot | P2 | https://github.com/AI4Finance-Foundation/FinRobot | git clone --depth 1 https://github.com/AI4Finance-Foundation/FinRobot.git /tmp/ext/FinRobot | Python | unknown | 50 | 金融分析 Agent 的感知-推理-执行分层，对照 S 链 |
| 前端产品应用 | zustand | P0 | https://github.com/pmndrs/zustand | git clone --depth 1 https://github.com/pmndrs/zustand.git /tmp/ext/zustand | TypeScript | MIT | 20 | 极简 store/middleware 分层，对照 3.1 前端状态管理 |
| 前端产品应用 | shadcn-ui | P1 | https://github.com/shadcn-ui/ui | git clone --depth 1 https://github.com/shadcn-ui/ui.git /tmp/ext/shadcn-ui | TypeScript | MIT | 50 | 组件复制式架构与 registry 契约，对照前端组件库组织 |
| 前端产品应用 | vite | P1 | https://github.com/vitejs/vite | git clone --depth 1 https://github.com/vitejs/vite.git /tmp/ext/vite | TypeScript | MIT | 50 | 插件容器/钩子流水线（同时是 DSH 插件架构的对照源） |
| 前端产品应用 | TanStack-query | P1 | https://github.com/TanStack/query | git clone --depth 1 https://github.com/TanStack/query.git /tmp/ext/TanStack-query | TypeScript | MIT | 50 | 缓存/失效/重试状态机，对照前端数据层与后端 API 契约 |
| 前端产品应用 | nextjs | P2 | https://github.com/vercel/next.js | git clone --depth 1 https://github.com/vercel/next.js.git /tmp/ext/nextjs | TypeScript | MIT | 80 | 渲染模式/路由/中间件分层（大仓需裁剪） |
| AI 大模型训练 | peft | P0 | https://github.com/huggingface/peft | git clone --depth 1 https://github.com/huggingface/peft.git /tmp/ext/peft | Python | Apache-2.0 | 50 | LoRA/Adapter 注入点与配置分层，对照 12-ml 辅训模型改造 |
| AI 大模型训练 | unsloth | P1 | https://github.com/unslothai/unsloth | git clone --depth 1 https://github.com/unslothai/unsloth.git /tmp/ext/unsloth | Python | Apache-2.0 | 50 | 显存优化/训练加速的算子替换层，对照 31-分布式训练资源面 |
| AI 大模型训练 | axolotl | P1 | https://github.com/axolotl-ai-cloud/axolotl | git clone --depth 1 https://github.com/axolotl-ai-cloud/axolotl.git /tmp/ext/axolotl | Python | Apache-2.0 | 50 | YAML 配置驱动的训练管线与数据集编排，对照 walk-forward 训练配置化 |
| AI 大模型训练 | pytorch-lightning | P2 | https://github.com/Lightning-AI/pytorch-lightning | git clone --depth 1 https://github.com/Lightning-AI/pytorch-lightning.git /tmp/ext/pytorch-lightning | Python | Apache-2.0 | 50 | Trainer/Module/Callback 生命周期，对照 40-周期神经网络训练循环 |
| AI 大模型训练 | vllm | P3 | https://github.com/vllm-project/vllm | git clone --depth 1 https://github.com/vllm-project/vllm.git /tmp/ext/vllm | Python/C++ | Apache-2.0 | 80 | 推理调度/批处理/缓存，作为云端模型服务对照（大仓裁剪） |
| AI 大模型训练 | transformers | P3 | https://github.com/huggingface/transformers | git clone --depth 1 https://github.com/huggingface/transformers.git /tmp/ext/transformers | Python | Apache-2.0 | 80 | Model/Tokenizer/Pipeline 三层抽象（只取 src/transformers 子目录） |
| DreamOS 操作系统（SACG 四层） | langgraph | P0 | https://github.com/langchain-ai/langgraph | git clone --depth 1 https://github.com/langchain-ai/langgraph.git /tmp/ext/langgraph | Python | MIT | 40 | 状态图/检查点/中断恢复，对照 SACG-A层执行图与 C层调度 |
| DreamOS 操作系统（SACG 四层） | temporal-sdk-python | P1 | https://github.com/temporalio/sdk-python | git clone --depth 1 https://github.com/temporalio/sdk-python.git /tmp/ext/temporal-sdk-python | Python | Apache-2.0 | 40 | 持久化工作流/活动重试/补偿，对照 SACG-C层任务时间线与恢复 |
| DreamOS 操作系统（SACG 四层） | autogen | P1 | https://github.com/microsoft/autogen | git clone --depth 1 https://github.com/microsoft/autogen.git /tmp/ext/autogen | Python | MIT | 50 | AgentRuntime/群聊/工具调用分层，对照 DSH 子 agent 与 C 层执行 |
| DreamOS 操作系统（SACG 四层） | dagster | P1 | https://github.com/dagster-io/dagster | git clone --depth 1 https://github.com/dagster-io/dagster.git /tmp/ext/dagster | Python | Apache-2.0 | 50 | Asset/DAG/分区调度与 lineage，对照 A 层执行图与 G 层沉淀 |
| DreamOS 操作系统（SACG 四层） | airflow | P2 | https://github.com/apache/airflow | git clone --depth 1 https://github.com/apache/airflow.git /tmp/ext/airflow | Python | Apache-2.0 | 80 | DAG/Operator/Executor 调度分层，对照 SACG-A/C 两层（大仓裁剪） |
| DreamOS 操作系统（SACG 四层） | prefect | P2 | https://github.com/PrefectHQ/prefect | git clone --depth 1 https://github.com/PrefectHQ/prefect.git /tmp/ext/prefect | Python | Apache-2.0 | 50 | Flow/Task/状态机/重试，对照节点注册表与执行状态 |
| DreamOS 操作系统（SACG 四层） | crewAI | P2 | https://github.com/crewAIInc/crewAI | git clone --depth 1 https://github.com/crewAIInc/crewAI.git /tmp/ext/crewAI | Python | MIT | 40 | Sequential/Hierarchical/Flow 三模式编排，对照节点编排与角色分工 |
| DreamOS 操作系统（SACG 四层） | OpenHands | P2 | https://github.com/All-Hands-AI/OpenHands | git clone --depth 1 https://github.com/All-Hands-AI/OpenHands.git /tmp/ext/OpenHands | Python/TS | MIT | 80 | Agent runtime + 沙箱执行 + 事件流，对照 30-真实环境交互 |
| DreamOS 操作系统（SACG 四层） | MetaGPT | P3 | https://github.com/FoundationAgents/MetaGPT | git clone --depth 1 https://github.com/FoundationAgents/MetaGPT.git /tmp/ext/MetaGPT | Python | MIT | 50 | SOP 化多角色协作（调研评为低-中价值，作负样本对照） |
| DSH 架构（Harness） | mcp-python-sdk | P0 | https://github.com/modelcontextprotocol/python-sdk | git clone --depth 1 https://github.com/modelcontextprotocol/python-sdk.git /tmp/ext/mcp-python-sdk | Python | MIT | 20 | Server/Client/Transport/工具注册协议，对照 DSH 的 MCP 工具层 |
| DSH 架构（Harness） | pluggy | P0 | https://github.com/pytest-dev/pluggy | git clone --depth 1 https://github.com/pytest-dev/pluggy.git /tmp/ext/pluggy | Python | MIT | 20 | hookspec/hookimpl 插件钩子协议，对照 DSH Harness 扩展点 |
| DSH 架构（Harness） | stevedore | P1 | https://github.com/openstack/stevedore | git clone --depth 1 https://github.com/openstack/stevedore.git /tmp/ext/stevedore | Python | Apache-2.0 | 20 | entrypoint 插件发现与加载，对照 SKILL/节点动态注册 |
| DSH 架构（Harness） | semantic-kernel | P1 | https://github.com/microsoft/semantic-kernel | git clone --depth 1 https://github.com/microsoft/semantic-kernel.git /tmp/ext/semantic-kernel | Python/TS | MIT | 50 | Kernel/Plugin/Function 三层能力注册，对照 SKILL 调度与能力层 |
| DSH 架构（Harness） | mcp-servers | P2 | https://github.com/modelcontextprotocol/servers | git clone --depth 1 https://github.com/modelcontextprotocol/servers.git /tmp/ext/mcp-servers | TS/Python | MIT | 30 | 参考 server 的工具/资源抽象，对照 DSH 内置工具集 |
| DSH 架构（Harness） | aider | P2 | https://github.com/Aider-AI/aider | git clone --depth 1 https://github.com/Aider-AI/aider.git /tmp/ext/aider | Python | Apache-2.0 | 30 | repo map + 代码检索增强 + 编辑循环，对照 24-图结构上下文压缩 |
| 数据采集系统 | tavily-python | P2 | https://github.com/tavily-ai/tavily-python | git clone --depth 1 https://github.com/tavily-ai/tavily-python.git /tmp/ext/tavily-python | Python | MIT | 10 | 搜索 API 客户端 + 结果标准化，对照 18-数据获取中心的外部搜索接入 |
| 广义认知系统（五类四层） | rasa | P2 | https://github.com/RasaHQ/rasa | git clone --depth 1 https://github.com/RasaHQ/rasa.git /tmp/ext/rasa | Python | Apache-2.0 | 50 | 意图识别 (NLU) + 对话管理 (Core) 双系统 + 策略路由，对照 SACG-S 层意图路由 |
| 金融交易模型 | ElegantRL | P1 | https://github.com/AI4Finance-Foundation/ElegantRL | git clone --depth 1 https://github.com/AI4Finance-Foundation/ElegantRL.git /tmp/ext/ElegantRL | Python | MIT | 50 | 云原生轻量并行 RL 训练（Actor-Learner 分离），对照 40-周期神经网络与 Shadow-RL Phase3 |
| 金融交易模型 | FinBERT | P2 | https://github.com/yya518/FinBERT | git clone --depth 1 https://github.com/yya518/FinBERT.git /tmp/ext/FinBERT | Python | Apache-2.0 | 20 | 金融 NLP 预训练（情感/基本面分类），对照 39-金融语义蒸馏的基本面文本编码 |
| 金融交易模型 | FinGPT | P2 | https://github.com/AI4Finance-Foundation/FinGPT | git clone --depth 1 https://github.com/AI4Finance-Foundation/FinGPT.git /tmp/ext/FinGPT | Python | MIT | 50 | 金融大模型数据-训练-推理管线，对照 39-金融语义蒸馏系统的金融语料面 |
| 金融交易模型 | MFRA-BTC | P3 | https://github.com/RD20KHIZA/MFRA-BTC-regime-study | git clone --depth 1 https://github.com/RD20KHIZA/MFRA-BTC-regime-study.git /tmp/ext/MFRA-BTC | Python | unknown | 20 | 多因子 regime 归因分解，对照 23-四层闭环的因子归因层 |
| 金融交易模型 | Quant-Regime-Engine | P3 | https://github.com/alinakhay/Quant-Regime-Engine | git clone --depth 1 https://github.com/alinakhay/Quant-Regime-Engine.git /tmp/ext/Quant-Regime-Engine | Python | unknown | 20 | 三因子 regime 引擎（趋势/波动/流动性），对照 12-三屏的多维权重 |
| 金融交易模型 | Regime-Aware-BTC | P2 | https://github.com/matteodrakulic/Regime-Aware-BTC-Trading-System | git clone --depth 1 https://github.com/matteodrakulic/Regime-Aware-BTC-Trading-System.git /tmp/ext/Regime-Aware-BTC | Python | unknown | 20 | Gaussian HMM 3 状态 regime 检测 + regime 条件策略，对照 BDSM regime 切换 |
| 金融交易模型 | XuanYuan | P2 | https://github.com/Duxiaoman-DI/XuanYuan | git clone --depth 1 https://github.com/Duxiaoman-DI/XuanYuan.git /tmp/ext/XuanYuan | Python | unknown | 50 | 中文金融对话大模型训练与微调，对照 39-金融语义蒸馏的中文金融语料 |
| 金融交易模型 | ai-hedge-fund | P1 | https://github.com/virattt/ai-hedge-fund | git clone --depth 1 https://github.com/virattt/ai-hedge-fund.git /tmp/ext/ai-hedge-fund | Python | MIT | 50 | Risk 纯算法 + Portfolio LLM + compute_allowed_actions 动作空间约束，对照 13-风控与 22-执行引擎 |
| 金融交易模型 | equity-vs-commodity | P2 | https://github.com/kpnguyen21/equity-vs-commodity | git clone --depth 1 https://github.com/kpnguyen21/equity-vs-commodity.git /tmp/ext/equity-vs-commodity | Python | unknown | 20 | Granger 因果筛选跨资产特征，对照 23-四层闭环的因果归因特征工程 |
| 金融交易模型 | evolutionary-trading-strategies | P2 | https://github.com/b3hzadsh/Evolutionary-Trading-Strategies | git clone --depth 1 https://github.com/b3hzadsh/Evolutionary-Trading-Strategies.git /tmp/ext/evolutionary-trading-strategies | Python | unknown | 30 | DEAP 进化策略 + Walk-forward 验证 + ESS 多样性奖励，对照 23-四层闭环的进化循环与走前验证 |
| 金融交易模型 | finclaw | P2 | https://github.com/NeuZhou/finclaw | git clone --depth 1 https://github.com/NeuZhou/finclaw.git /tmp/ext/finclaw | Python | unknown | 30 | GA 进化策略 + 前向验证 + 蒙特卡洛，对照 23-四层闭环的策略进化循环 |
| 金融交易模型 | granger-causality-trading | P2 | https://github.com/suenot/117-granger-causality-trading | git clone --depth 1 https://github.com/suenot/117-granger-causality-trading.git /tmp/ext/granger-causality-trading | Python | unknown | 20 | 多变量 VAR + F 统计量因果链交易（VIX/DXY→BTC），对照 23-四层闭环的跨市场因果传导 |
| 金融交易模型 | nautilus_trader | P2 | https://github.com/nautechsystems/nautilus_trader | git clone --depth 1 https://github.com/nautechsystems/nautilus_trader.git /tmp/ext/nautilus_trader | Rust/Python | MIT | 80 | 回测/实盘统一执行引擎（仅解析 Python API 绑定层，Rust 核心不入语义分析），对照 22-执行引擎 |
| 金融交易模型 | regimes | P2 | https://github.com/knightianuncertainty/regimes | git clone --depth 1 https://github.com/knightianuncertainty/regimes.git /tmp/ext/regimes | Python | unknown | 20 | Bai-Perron + CUSUM + Chow Test + Markov Switching 结构断点全流程，对照 12-三屏的 regime 检测 |
| 金融交易模型 | skfolio | P2 | https://github.com/skfolio/skfolio | git clone --depth 1 https://github.com/skfolio/skfolio.git /tmp/ext/skfolio | Python | BSD-3-Clause | 50 | scikit-learn 兼容的投资组合优化/因子模型/风险度量统一接口，对照 13-风控与组合配置 |
| AI 大模型训练 | Calibration-Neural-SDEs | P3 | https://github.com/evaflonner/Calibration-of-Neural-SDEs-using-Bayesian-Methods | git clone --depth 1 https://github.com/evaflonner/Calibration-of-Neural-SDEs-using-Bayesian-Methods.git /tmp/ext/Calibration-Neural-SDEs | Python | unknown | 20 | 贝叶斯方法校准金融神经 SDE，对照 40-周期神经网络的不确定性校准 |
| AI 大模型训练 | Sig-SPT | P3 | https://github.com/janka-moeller/Sig-SPT | git clone --depth 1 https://github.com/janka-moeller/Sig-SPT.git /tmp/ext/Sig-SPT | Python | unknown | 10 | 随机投资组合理论中的签名方法，对照 13-风控的路径依赖组合度量 |
| AI 大模型训练 | Stable-Neural-SDEs | P2 | https://github.com/yongkyung-oh/Stable-Neural-SDEs | git clone --depth 1 https://github.com/yongkyung-oh/Stable-Neural-SDEs.git /tmp/ext/Stable-Neural-SDEs | Python | unknown | 20 | ICLR 2024 稳定神经 SDE（连续时间动态+不确定性），对照 40-周期神经网络的市场动态建模 |
| AI 大模型训练 | Time-MoE | P2 | https://github.com/Time-MoE/Time-MoE | git clone --depth 1 https://github.com/Time-MoE/Time-MoE.git /tmp/ext/Time-MoE | Python | unknown | 50 | 百亿参数时序 MoE（ICLR 2025），对照 40-周期神经网络的多专家路由 |
| AI 大模型训练 | causalml | P1 | https://github.com/uber/causalml | git clone --depth 1 https://github.com/uber/causalml.git /tmp/ext/causalml | Python | Apache-2.0 | 50 | Uber 因果推断（DML / Causal Forest / X-learner），对照 23-四层闭环的因果归因替代相关归因 |
| AI 大模型训练 | cflue | P2 | https://github.com/aliyun/cflue | git clone --depth 1 https://github.com/aliyun/cflue.git /tmp/ext/cflue | Python | unknown | 30 | 中文金融语言理解评估基准，对照 39-金融语义蒸馏的评测面 |
| AI 大模型训练 | decision-transformer | P2 | https://github.com/kzl/decision-transformer | git clone --depth 1 https://github.com/kzl/decision-transformer.git /tmp/ext/decision-transformer | Python | MIT | 30 | RL as Sequence Modeling 官方实现，对照 40-周期神经网络的序列决策面 |
| AI 大模型训练 | ds4 | P2 | https://github.com/antirez/ds4 | git clone --depth 1 https://github.com/antirez/ds4.git /tmp/ext/ds4 | Python | BSD-3-Clause | 30 | antirez DeepSeek V4 推理引擎（SSD streaming / distributed / performance），对照 31-分布式计算部署 |
| AI 大模型训练 | iisignature | P3 | https://github.com/iisignature/iisignature | git clone --depth 1 https://github.com/iisignature/iisignature.git /tmp/ext/iisignature | Python | unknown | 10 | Python CPU 版签名计算（signatory 的轻量替代），对照 23-四层闭环的路径抽象（fallback） |
| AI 大模型训练 | moment | P2 | https://github.com/moment-timeseries-foundation-model/moment | git clone --depth 1 https://github.com/moment-timeseries-foundation-model/moment.git /tmp/ext/moment | Python | MIT | 50 | 开放时序基础模型（ICML 2024），可微调/线性探测，对照 12-ml 辅训改造 |
| AI 大模型训练 | nixtla | P2 | https://github.com/Nixtla/nixtla | git clone --depth 1 https://github.com/Nixtla/nixtla.git /tmp/ext/nixtla | Python | Apache-2.0 | 50 | 100B 数据点预训练 Transformer 时序生成模型，对照 40-周期神经网络的生成式预测 |
| AI 大模型训练 | signatory | P2 | https://github.com/patrick-kidger/signatory | git clone --depth 1 https://github.com/patrick-kidger/signatory.git /tmp/ext/signatory | Python/C++ | Apache-2.0 | 20 | PyTorch 可微分签名计算（ICLR 2021），路径→张量坐标，对照 23-四层闭环的路径抽象 |
| AI 大模型训练 | signature-method-in-ML | P3 | https://github.com/kormilitzin/the-signature-method-in-machine-learning | git clone --depth 1 https://github.com/kormilitzin/the-signature-method-in-machine-learning.git /tmp/ext/signature-method-in-ML | Python | unknown | 30 | 签名方法 ML 基础与应用示例，对照 23-四层闭环路径抽象的入门参考 |
| AI 大模型训练 | timesfm | P1 | https://github.com/google-research/timesfm | git clone --depth 1 https://github.com/google-research/timesfm.git /tmp/ext/timesfm | Python | Apache-2.0 | 50 | Google 时间序列基础模型（纯 Transformer 预训练），对照 40-周期神经网络的时序预测面 |
| DreamOS 操作系统（SACG 四层） | openai-swarm | P1 | https://github.com/openai/swarm | git clone --depth 1 https://github.com/openai/swarm.git /tmp/ext/openai-swarm | Python | MIT | 20 | handoff 模式（agent 间移交）+ 工具调用路由，对照节点间 handoff 与 S 层路由 |
| DreamOS 操作系统（SACG 四层） | swe-agent | P2 | https://github.com/SWE-agent/SWE-agent | git clone --depth 1 https://github.com/SWE-agent/SWE-agent.git /tmp/ext/swe-agent | Python | MIT | 50 | ACI (Agent-Computer Interface) 动作空间抽象 + 轨迹记录，对照 30-真实环境交互系统 |
| DreamOS 操作系统（SACG 四层） | ufo | P1 | https://github.com/microsoft/UFO | git clone --depth 1 https://github.com/microsoft/UFO.git /tmp/ext/ufo | TypeScript/Python | MIT | 50 | HostAgent(调度)+AppAgent(执行)双层Agent OS + 统一动作层，对照 SACG-S层意图路由与C层执行 |
| DSH 架构（Harness） | anthropic-financial-services | P1 | https://github.com/anthropics/financial-services | git clone --depth 1 https://github.com/anthropics/financial-services.git /tmp/ext/anthropic-financial-services | TypeScript/Python | MIT | 50 | 10 个金融 agent 模板：agent = skills + connectors + subagents，对照 DSH 9 个 subagent 与金融能力层 |
| DSH 架构（Harness） | deepseek-harness | P1 | https://github.com/deepseek-ai/deepseek-harness | git clone --depth 1 https://github.com/deepseek-ai/deepseek-harness.git /tmp/ext/deepseek-harness | TypeScript/Node.js | MIT | 50 | Cordis 微内核 + Harness 扩展点设计，对照 dream-harness-bridge 的 Harness 内核架构 |
| DSH 架构（Harness） | skill-compose | P2 | https://github.com/MooseGoose0701/skill-compose | git clone --depth 1 https://github.com/MooseGoose0701/skill-compose.git /tmp/ext/skill-compose | Python/TypeScript | unknown | 50 | 技能注册表 + 一句话组装 Agent + 技能进化，对照 SKILL 注册表与动态编排 |
| DSH 架构（Harness） | superpowers | P1 | https://github.com/obra/superpowers | git clone --depth 1 https://github.com/obra/superpowers.git /tmp/ext/superpowers | TypeScript/Markdown | MIT | 30 | SKILL.md 格式规范 + 7 阶段软件开发工作流方法论，对照 SKILL 调度与元数据契约 |

## 附录 B：批量校验脚本

```bash
#!/usr/bin/env bash
set -u
python3 - <<'PY' > /tmp/sources.tsv
import json
d = json.load(open('reflection_data/external_sources.json'))
for s in d['sources']:
    print(f"{s['id']}\t{s['location']}")
PY
while IFS=$'\t' read -r id url; do
  if git ls-remote --heads "$url.git" HEAD >/dev/null 2>&1; then
    echo "OK   $id $url"
  else
    echo "FAIL $id $url"
  fi
done < /tmp/sources.tsv
```

## 附录 C：大仓裁剪示例

```bash
# next.js 只取核心
git clone --depth 1 --filter=blob:none --sparse https://github.com/vercel/next.js.git /tmp/ext/nextjs
git -C /tmp/ext/nextjs sparse-checkout set packages/next

# transformers 只取库代码
git clone --depth 1 --filter=blob:none --sparse https://github.com/huggingface/transformers.git /tmp/ext/transformers
git -C /tmp/ext/transformers sparse-checkout set src/transformers

# airflow 只取核心包
git clone --depth 1 --filter=blob:none --sparse https://github.com/apache/airflow.git /tmp/ext/airflow
git -C /tmp/ext/airflow sparse-checkout set airflow
```

## 附录 D：注入调用

```bash
# 设计器：源清单在 reflection_data/external_sources.json
python3 - <<'PY'
import json, os
from core.reflection.replay_simulator import ReplayPool
from core.reflection.harvest import ExternalHarvester, HarvestSource

d = json.load(open('reflection_data/external_sources.json'))
srcs = []
for s in d['sources']:
    if s['wave'] != 1:
        continue
    srcs.append(HarvestSource(source_type=s['source_type'], location=s['location'],
                              label=s['id'], patterns=s['patterns']))
pool = ReplayPool('reflection_data/replay_pool')
out = ExternalHarvester(pool).harvest(srcs)
print(out.injected_trees, out.rejected, out.errors)
PY
```

> 若目标仓不能联网，先按附录 C 拉取/裁剪到 `/tmp/ext/<id>`，再把该条 `source_type` 改为 `local_path`、`location` 改为本地目录。

## 附录 E：离线快照构建与按需解压

### E.1 构建（必须在可访问 GitHub 的主机执行）

```bash
mkdir -p bundle
python3 - <<'PY' > sources.tsv
import json
d = json.load(open('reflection_data/external_sources.json'))
for s in d['sources']:
    if s['wave'] == 1:                      # 先只构建 wave1
        repo = s['location'].replace('https://github.com/', '')
        print(f"{s['id']}\t{repo}\t{s['wave']}")
PY
while IFS=$'\t' read -r id repo wave; do
  sha=$(git ls-remote "https://github.com/${repo}.git" HEAD | awk '{print $1}')
  out="bundle/${id}-${sha:0:12}.tar.gz"
  curl -fL "https://codeload.github.com/${repo}/tar.gz/${sha}" -o "$out"
  if command -v sha256sum >/dev/null 2>&1; then
    h=$(sha256sum "$out" | awk '{print $1}')
  else
    h=$(shasum -a 256 "$out" | awk '{print $1}')
  fi
  printf '{"id":"%s","repo":"https://github.com/%s","wave":%s,"commit":"%s","archive":"%s","sha256":"%s","bytes":%s}\n' \
    "$id" "$repo" "$wave" "$sha" "$out" "$h" "$(wc -c < "$out" | tr -d ' ')" >> bundle/manifest.jsonl
done < sources.tsv
```

> `codeload` 快照会遵循仓库 `.gitattributes` 的 export-ignore，个别文件可能缺失。解压后需校验 `patterns` 目录是否存在；缺失则该源回退到 `git clone --depth 1`。

### E.2 上传（选一条比 GitHub 更快的通道）

```bash
# 示例：对象存储 / 内部制品库 / 云盘
aws s3 cp bundle/ s3://<bucket>/dsh-sources/v1/ --recursive
# 或 rclone copy bundle/ remote:dsh-sources/v1/
```

### E.3 云端按需解压

```bash
id=backtrader
line=$(grep "\"id\":\"${id}\"" bundle/manifest.jsonl)
sha=$(printf '%s' "$line" | sed -E 's/.*"commit":"([^"]+)".*/\1/')
sum=$(printf '%s' "$line" | sed -E 's/.*"sha256":"([^"]+)".*/\1/')
file="bundle/${id}-${sha:0:12}.tar.gz"

echo "${sum}  ${file}" | sha256sum -c -          # macOS 用 shasum -a 256 -c
mkdir -p /var/cache/dsh-sources/${id}
tar -xzf "$file" -C /var/cache/dsh-sources/${id} --strip-components=1
```

解压后把该源改为：

```json
{"source_type": "local_path", "location": "/var/cache/dsh-sources/backtrader"}
```

再执行附录 D 的注入调用。未选中的 wave 不解压，不占空间。
