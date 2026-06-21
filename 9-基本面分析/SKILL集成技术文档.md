# SKILL 集成技术文档（方案 B：Hub + 标准化，BTC 优先）

本文目标：将 OKX/Binance/Gate 的公开 SKILL 能力（优先开源可直接复用的 Skill）以“只读建议 + 可追溯证据链”的方式统一接入到本仓库的基本面分析子域（`/fundamental/*`），并为下游多 Agent 自动化交易系统提供稳定可消费的基本面数据与摘要结论。

## 1. 背景与目标

现状问题（概括）：

- 资金流、叙事与情绪数据覆盖不足，且口径存在分散风险。
- 我们已具备 Gate/Binance 多个 Skill 与既有基本面框架，但未形成“统一契约 + 统一门禁 + 统一落盘”的工程闭环。
- OKX Trade Kit 生态中包含交易所内行情、盘口深度、资金费率、OI、宏观联动、社交叙事等能力，可作为覆盖率补齐与证据增强的重要来源。

总体目标（BTC 初期只关注 BTC）：

- 以方案 B（Hub + 标准化）为骨架：Skills → Adapter → Source Snapshot(v1) → Feature Cube(v1) → 三柱输出（Flow/Narrative/Macro）→ Fundamental Hub 汇总 → `/fundamental` 页面与下游消费。
- 输出一套“可审计、可降级、可演进”的接入方案：白名单 Skill、字段命名与映射、质量/覆盖率门禁、落盘规范、与多 Agent 对接输出契约。

与现有框架对齐：

- 基本面总体模块与路由约定见 [基本面研究文档.md](file:///Users/zhangjiangtao/ft_userdata/%E5%9F%BA%E6%9C%AC%E9%9D%A2%E5%88%86%E6%9E%90_fundamental/%E5%9F%BA%E6%9C%AC%E9%9D%A2%E7%A0%94%E7%A9%B6%E6%96%87%E6%A1%A3.md#L242-L372)。
- 基本面工程独立化与页面/后端边界演进见 [基本面独立化架构与清理规划.md](file:///Users/zhangjiangtao/ft_userdata/%E5%9F%BA%E6%9C%AC%E9%9D%A2%E5%88%86%E6%9E%90_fundamental/%E5%9F%BA%E6%9C%AC%E9%9D%A2%E7%8B%AC%E7%AB%8B%E5%8C%96%E6%9E%B6%E6%9E%84%E4%B8%8E%E6%B8%85%E7%90%86%E8%A7%84%E5%88%92.md#L33-L59)。

## 2. 集成红线（强制）

- 只读建议语义：默认 `execution_gate=readonly_advisory`，Skill 数据仅进入研究与建议层，不可绕过既有执行/鉴权/审计链路。
- Fail-closed：当 `coverage/confidence` 不满足门槛，允许展示“数据与缺失”，但禁止输出风险放大建议（只允许 `hold/reduce/hedge/stop_loss` 中的保守动作）。
- 证据可追溯：所有关键结论必须能回溯到 `source_skill + asof + evidence_refs(包含 URL/endpoint + timestamp)`。
- 最小白名单：只接入明确为只读或可控只读的 Skill；任何“可下单/可写资产”的能力一律不纳入基本面链路。
- 不落密钥：不在代码/日志/产物中写入 API Key/Secret；如未来需要带鉴权调用，必须走 secrets 管理并默认仅在本地/沙盒启用。

## 3. Skill 生态与白名单（BTC 首期）

### 3.1 Gate（已接入/可复用）

已在本项目 `.trae/skills` 中可见的 Gate 系 Skill：

- `gate-info-research`
- `gate-info-coinanalysis`

这些 Skill 当前已通过标准化脚本做部分字段抽取与质量标注，可作为“资金流/微观结构/情绪”主力来源与兜底来源（见 [sync_web3_skill_snapshot.py](file:///Users/zhangjiangtao/ft_userdata/%E5%9F%BA%E6%9C%AC%E9%9D%A2%E5%88%86%E6%9E%90_fundamental/ops/nanoclaw/core_task1/flow/scripts/sync_web3_skill_snapshot.py#L168-L260) 的解析策略示例）。

### 3.2 Binance（开源在库可复用）

本仓库已内置 Binance Skills Hub 源码（用于开源 Skill 复用）：

- 入口说明：[binance-skills-hub-main/README.md](file:///Users/zhangjiangtao/ft_userdata/%E5%9F%BA%E6%9C%AC%E9%9D%A2%E5%88%86%E6%9E%90_fundamental/%E5%B8%81%E5%AE%89Skill/binance-skills-hub-main/README.md)
- BTC 首期建议白名单：
  - `crypto-market-rank`（榜单/社交热度/聪明钱流入/地址 PnL）：[SKILL.md](file:///Users/zhangjiangtao/ft_userdata/%E5%9F%BA%E6%9C%AC%E9%9D%A2%E5%88%86%E6%9E%90_fundamental/%E5%B8%81%E5%AE%89Skill/binance-skills-hub-main/skills/binance-web3/crypto-market-rank/SKILL.md)
  - `query-token-info`（标的画像、实时市场数据与 K 线）：[SKILL.md](file:///Users/zhangjiangtao/ft_userdata/%E5%9F%BA%E6%9C%AC%E9%9D%A2%E5%88%86%E6%9E%90_fundamental/%E5%B8%81%E5%AE%89Skill/binance-skills-hub-main/skills/binance-web3/query-token-info/SKILL.md)
  - `query-address-info`（地址持仓与仓位）：本项目 `.trae/skills/query-address-info/SKILL.md`
- 风险提示：
  - Binance Spot 相关 skill（含鉴权、交易写入）仅作为未来“执行层”能力候选，不纳入基本面链路（参考 [binance/spot/SKILL.md](file:///Users/zhangjiangtao/ft_userdata/%E5%9F%BA%E6%9C%AC%E9%9D%A2%E5%88%86%E6%9E%90_fundamental/%E5%B8%81%E5%AE%89Skill/binance-skills-hub-main/skills/binance/spot/SKILL.md) 的鉴权与主网确认规范）。

### 3.3 OKX（新增接入候选，BTC 首期）

以下 OKX Trade Kit Skill 具备明确的“覆盖率补齐”价值，且可先以只读研究方式接入：

- `market-intel`：聚合 Twitter/X 热门叙事，捕捉社交动量突变，支持每日简报/异动警报/关键词研究（补叙事与情绪）。
- `cmc-okx`：CMC（市值、供应、主导率、持仓分布、项目背景、宏观事件日历）+ OKX Trade Kit（实时价格、资金费率、持仓量、70+ 技术指标、盘口深度）（补市场快照与衍生品/微观结构）。
- `alpha-vantage`：跨资产宏观数据（标普 500、黄金、美元指数、利率、CPI、GDP 等）+ OKX 实时市场数据联动（补宏观压力与相关性/独立定价判断）。
- `hyperliquid-analyzer`：巨鲸成交/持仓监控推送、挂单墙扫描、链上持仓、HL×OKX 资金费情绪分析、链上链下价差扫描（补链上/巨鲸/资金费与价差）。
- `crypto-research`：七步尽调报告（技术面、衍生品、项目基本面、新闻情绪、红旗/绿旗清单与风险评级），建议作为 BTC 以外扩币的后期能力。

## 4. 方案 B：Hub + 标准化总体架构

### 4.1 角色分层

- Skill Adapter（采集/调用层）
  - 负责：调用 Skill 或其底层 API，落盘原始响应（raw），生成 `source_snapshot_v1`。
  - 不负责：合成结论、不负责策略建议、不负责执行写入。
- Normalizer（标准化层）
  - 负责：把不同来源映射到统一 `bindBase` 命名体系与单位体系，补齐质量字段与证据引用。
- Feature & Regime（研究合成层）
  - 负责：从 `source_snapshot_v1` 生成 `feature_cube_v1`，并合成 `FlowTrend/FlowImpulse/FlowStress`、`NarrativeStress`、`MacroPressure`。
  - 允许：多源交叉确认（confirmations）与分状态（regime）阈值。
- Fundamental Hub Orchestrator（总控编排层）
  - 负责：跨模块编排、schema 校验、coverage 门禁、fail-closed 降级、输出 `/fundamental/overview/latest` 等聚合接口。
  - 不直接“改写业务语义”：分项技能输出保持自治，Hub 只做聚合与门禁。

### 4.2 与本仓库现有资产的连接点

- 资金流：`ops/nanoclaw/core_task1/flow/`（脚本与回测/产物路径）
- 叙事：`ops/nanoclaw/core_task1/narrative/`
- Schema（已存在的 SSoT）：
  - [flow_brief_request.schema.json](file:///Users/zhangjiangtao/ft_userdata/%E5%9F%BA%E6%9C%AC%E9%9D%A2%E5%88%86%E6%9E%90_fundamental/ops/nanoclaw/core_task1/schema/flow_brief_request.schema.json)
  - [flow_brief_receipt.schema.json](file:///Users/zhangjiangtao/ft_userdata/%E5%9F%BA%E6%9C%AC%E9%9D%A2%E5%88%86%E6%9E%90_fundamental/ops/nanoclaw/core_task1/schema/flow_brief_receipt.schema.json)
  - [narrative_contract.schema.json](file:///Users/zhangjiangtao/ft_userdata/%E5%9F%BA%E6%9C%AC%E9%9D%A2%E5%88%86%E6%9E%90_fundamental/ops/nanoclaw/core_task1/schema/narrative_contract.schema.json)
  - [news_contract.schema.json](file:///Users/zhangjiangtao/ft_userdata/%E5%9F%BA%E6%9C%AC%E9%9D%A2%E5%88%86%E6%9E%90_fundamental/ops/nanoclaw/core_task1/schema/news_contract.schema.json)
- 多 Agent 桥接（下游消费）：[multi_agent_bridge.mjs](file:///Users/zhangjiangtao/ft_userdata/%E5%9F%BA%E6%9C%AC%E9%9D%A2%E5%88%86%E6%9E%90_fundamental/ops/nanoclaw/core_task1/scripts/multi_agent_bridge.mjs)

## 5. 数据契约（SSoT）与落盘规范

### 5.1 Source Snapshot(v1)：证据与可追溯统一载体

定位：把任何 Skill/API 的返回，统一整理成“可审计、可降级”的条目集合（items），并记录证据引用。

建议最小结构（文档口径）：

```json
{
  "schema": "source_snapshot_v1",
  "asset": "BTC",
  "asof_ts": "2026-04-08T00:00:00Z",
  "items": [
    {
      "bindBase": "funding_rate_bps__btc__okx__perp",
      "value": 12.3,
      "unit": "bps",
      "source": "okx:cmc-okx",
      "latency_sec": 30,
      "revision": { "provider_revision_ts": "2026-04-08T00:00:00Z" },
      "quality": { "status": "ok", "reasons": [], "error": "" },
      "generated_at": "2026-04-08T00:00:05Z",
      "evidence_refs": [
        { "type": "endpoint", "ref": "okx_trade_kit:funding_rate", "asof": "2026-04-08T00:00:00Z" }
      ]
    }
  ],
  "execution_gate": "readonly_advisory"
}
```

落盘位置（建议）：

- 原始响应：`ops/nanoclaw/core_task1/raw/<vendor>/<skill>/<YYYYMMDD>/<timestamp>.json`
- 标准化快照：`ops/nanoclaw/core_task1/outputs/source_snapshot_v1_<asset>_<timestamp>.json`

### 5.2 Feature Cube(v1)：研究合成输入

定位：把 `bindBase` 级别观测变为可合成的研究特征（z-score、分位数、窗口统计、regime 标签、贡献度）。

建议最小结构（文档口径）：

```json
{
  "schema": "feature_cube_v1",
  "asset": "BTC",
  "asof_ts": "2026-04-08T00:00:00Z",
  "features": [
    {
      "feature_key": "funding_rate_pctl_30d",
      "value": 0.82,
      "horizon": "4h",
      "regime_tag": "heated",
      "weight": 0.15,
      "contribution": -0.08,
      "quality": { "status": "ok" },
      "source_refs": ["funding_rate_bps__btc__okx__perp"]
    }
  ]
}
```

### 5.3 Hub 输出：面向页面与多 Agent 消费

定位：统一输出“偏置/过滤/风控动作建议 + 证据链 + 覆盖率”。

建议最小字段（文档口径）：

- `bias`：long_bias / short_bias / neutral（方向偏置）
- `filter`：allow / slowdown / block（用于执行前过滤）
- `risk_action_proposal`：hold / reduce / hedge / stop_loss（默认只输出保守动作）
- `coverage`：0~1
- `confidence`：0~1
- `critical_missing_sources[]`、`missing_data[]`
- `evidence_refs[]`
- `execution_gate=readonly_advisory`

## 6. 指标映射与模块归属（OKX/Binance/Gate → 三柱输出）

### 6.1 资金流与衍生品（Flow）

目标：产出 `FlowTrend/FlowImpulse/FlowStress`，并为“资金最小阻力研究”页提供可分层统计输入。

优先观测（BTC 首期）：

- 资金费率（Funding Rate）
- 持仓量（OI）
- 盘口深度与价差（Depth/Spread/Impact cost）
- 清算与极端波动（若 Skill 提供）
- 稳定币流入/交易所储备（若 Skill 提供）
- 链上/巨鲸成交与仓位变化（Hyperliquid analyzer / 地址类 skill）

来源与定位：

- Gate `coinanalysis/research`：作为当前主力快照（已有解析示例）。
- OKX `cmc-okx`：补齐 OKX 场内资金费率、OI、盘口深度与技术指标快照。
- OKX `hyperliquid-analyzer`：补齐巨鲸、链上链下价差、挂单墙与跨场情绪。
- Binance `crypto-market-rank`：可提供“聪明钱流入榜/地址 PnL”作为辅助确认（confirmations），不直接主导方向。

bindBase 命名建议：

- 统一遵循 [基本面研究文档.md 的字段命名模板](file:///Users/zhangjiangtao/ft_userdata/%E5%9F%BA%E6%9C%AC%E9%9D%A2%E5%88%86%E6%9E%90_fundamental/%E5%9F%BA%E6%9C%AC%E9%9D%A2%E7%A0%94%E7%A9%B6%E6%96%87%E6%A1%A3.md#L631-L718) 的“key__asset__venue__market”风格。
- 示例：
  - `funding_rate_bps__btc__okx__perp`
  - `oi_usd__btc__okx__perp`
  - `spread_bps__btc__okx__spot`
  - `orderbook_depth_pct__btc__okx__spot`
  - `whale_position_delta_usd__btc__hyperliquid__perp`

### 6.2 叙事与情绪（Narrative & Sentiment）

目标：把叙事与情绪定位为过滤器与 stress 预警，不作为单独方向主因子。

来源与定位：

- OKX `market-intel`：社交叙事聚合（热点叙事 × OKX 交易对 × 实时价格），适合作为 `CommunityEffective` 与 `NarrativeStress` 的上游证据。
- Binance `crypto-market-rank`：社交热度榜（可选）用于交叉验证与“多源一致性”。
- Gate `coinanalysis`：现有情绪字段可作为补充/兜底，并继续输出 `evidence_grade` 与 `missing_disclosure`。

强制约束（重申）：

- 缺失或冲突证据：只允许输出降风险动作建议，且必须写明 `missing_data[]/conflict_reasons[]`。
- 建议至少保留 `source_diversity/concentration_risk/bot_suspect_ratio/latency_sec` 维度，便于 `EvidenceScore` 可复算（对齐 [基本面研究文档.md 对叙事模块的扩展建议](file:///Users/zhangjiangtao/ft_userdata/%E5%9F%BA%E6%9C%AC%E9%9D%A2%E5%88%86%E6%9E%90_fundamental/%E5%9F%BA%E6%9C%AC%E9%9D%A2%E7%A0%94%E7%A9%B6%E6%96%87%E6%A1%A3.md#L258-L267)）。

覆盖率口径（叙事与情绪，B2：数据源 bucket 覆盖率）：

- bucket 定义：`okx_market_intel` / `news` / `macro` / `onchain` / `derivatives`。
- 可用状态：`ok|stale|backfilled` 计入覆盖；`suspect|missing|unknown` 不计入覆盖。
- 目标：`coverage >= 0.80`（至少 4/5 bucket 可用）。
- Onchain proxy 允许：当真链上源缺失时，允许用交易所储备、跨场巨鲸成交、链上链下价差等 proxy 回补，但必须记为 `backfilled` 并显式披露。

覆盖率诊断表（下一轮：不改代码，仅分析与输出）：

- 目标：把当前接口返回中可用字段按 bucket 自动归类，输出“覆盖率诊断表”，用于定位缺口与优先补齐项。
- 推荐输出字段：`bucket`、`covered`、`status`、`provider_hint`、`evidence_count`、`missing_reason`。
- 示例命令（stdout 输出，不写入仓库）：

```bash
python - <<'PY'
import json, urllib.request
from collections import OrderedDict

def get(u):
    with urllib.request.urlopen(u, timeout=8) as r:
        return json.loads(r.read().decode())

base = "http://localhost:3005"
nar = get(base + "/api/fundamental/narrative/registry/latest?_ts=1")
rec = (nar.get("record") or {}) if isinstance(nar, dict) else {}
contract = (rec.get("contract") or {}) if isinstance(rec.get("contract"), dict) else {}
quality = (contract.get("quality") or {}) if isinstance(contract.get("quality"), dict) else {}
buckets = (quality.get("source_bucket_coverage") or {}) if isinstance(quality.get("source_bucket_coverage"), dict) else {}
missing = set([x for x in (quality.get("missing_disclosure") or []) if isinstance(x, str) and x.startswith("bucket_")])

rows = []
for b in ["okx_market_intel","news","macro","onchain","derivatives"]:
    st = str(buckets.get(b) or "missing")
    covered = st in {"ok","stale","backfilled"}
    rows.append({"bucket": b, "covered": covered, "status": st, "missing_flag": ("bucket_"+b) in missing})

print(json.dumps({"coverage": quality.get("coverage"), "rows": rows}, ensure_ascii=False, indent=2))
PY
```

### 6.3 宏观与跨资产（Macro）

目标：通过跨资产宏观数据回答“BTC 今天是在跟风险资产走，还是在独立定价”，并形成 `MacroPressure`（仅用于 risk-off）。

来源与定位：

- OKX `alpha-vantage`：SPX/Gold/DXY/利率/CPI/GDP 等宏观数据。
- OKX Trade Kit 实时数据：与 BTC 价格/资金费率/OI 联动用于状态识别（risk-on / risk-off / decouple）。

输出约束：

- 宏观压力只能映射为风险动作（`hold/reduce/hedge`），禁止单独作为“加仓理由”。

## 7. 质量、覆盖率与门禁（Hub 统一执行）

统一质量枚举（与现有 flow/narrative/news 对齐）：

- `ok | stale | missing | backfilled | suspect | unknown`

覆盖率（coverage）口径建议：

- `coverage = Σ (w_i * I(quality_i in {ok,stale})) / Σ w_i`，并记录 `critical_missing_sources[]`。

P0.5（2026-04-08）补充口径：

- 页面层可在 `flow_regime` 基础上叠加 `source_snapshot_v1` 的回补证据，允许将 `missing/suspect` 回填为 `backfilled`。
- 对 BTC Flow 页面（`/fundamental/flows`）执行“恢复覆盖率”策略：当 `bindBase` 命中关键缺口映射表时，覆盖率按回补后口径重新计算。
- 目标：基础展示覆盖率 ≥ 0.80，且必须保留 `missing_data[]` 与 `critical_missing_sources[]` 的显式披露。

门禁规则（建议默认）：

- `coverage < 0.55`：结论降级为 `neutral + risk_action=reduce_or_hold`，且必须输出 `missing_data[]`。
- 存在 `suspect` 且命中关键维度（资金费率/OI/宏观关键指标）：禁止输出任何“加风险”倾向，仅允许 `hold/reduce/hedge/stop_loss`，并强制 `execution_gate=readonly_advisory`。

## 8. 与多 Agent 自动化交易系统对接

现有桥接脚本 [multi_agent_bridge.mjs](file:///Users/zhangjiangtao/ft_userdata/%E5%9F%BA%E6%9C%AC%E9%9D%A2%E5%88%86%E6%9E%90_fundamental/ops/nanoclaw/core_task1/scripts/multi_agent_bridge.mjs) 已包含：

- `buildSentimentFromNarrativeRegistry`：将叙事输出转为 sentiment-analyst 可消费字段
- `buildNarrativeFromRegistry`：将叙事 top narrative 转为 narrative-analyst 输出
- `buildFlowFromRegime`：将 flow regime 输出转为 flow-analyzer 输出

本方案的对接方式：

- Hub 统一落盘 `fundamental.overview.v1` 与分项模块产物（flows/narrative/macro）。
- multi_agent_bridge 只读取 Hub 聚合输出与必要的 source_snapshot 指针，保证下游 Agent 的输入稳定，不直接依赖某一家 Skill 的原始结构。

## 9. 分期落地（建议）

- P0（BTC 覆盖率补齐）
  - 接入 OKX：`market-intel`、`cmc-okx`、`alpha-vantage`、`hyperliquid-analyzer`（只读）
  - 复用 Gate/Binance：保持现有产物与页面可用
  - 输出：source_snapshot_v1 + feature_cube_v1 的最小落盘，Hub 在 `/fundamental/overview` 聚合展示 coverage/quality/missing
- P1（契约固化与门禁收敛）
  - 扩充 bindBase 映射表，形成“字段字典 + 单测”
  - 引入冲突与一致性检查（同一维度多源对照）
- P2（扩币与尽调）
  - 接入 `crypto-research`：将尽调输出作为“项目风险评级与红旗清单”子模块，服务 BTC 以外标的扩展

## 10. 验收与回归（DoD）

- 任一新增 Skill 进入白名单前必须满足：
  - 有明确 read_only 数据路径，或可被强制约束为只读采集
  - 能映射到 `bindBase`（至少覆盖 3 个关键维度）
  - 输出包含 `quality/coverage/evidence_refs`（缺失可降级但必须显式披露）
- 产物校验与回归建议复用既有测试框架（见 `tests/`），并新增：
  - “schema 校验 + 映射覆盖率”单测
  - “fail-closed 门禁”单测（coverage 低时不得输出加风险建议）

## 11. P0 实施拆解（文件边界 + 6 个任务 + 可执行步骤）

对应执行计划文件：

- [2026-04-08-btc-skill-p0-integration.md](file:///Users/zhangjiangtao/ft_userdata/%E5%9F%BA%E6%9C%AC%E9%9D%A2%E5%88%86%E6%9E%90_fundamental/docs/superpowers/plans/2026-04-08-btc-skill-p0-integration.md)

### 11.1 文件边界（新增/修改/测试）

新增文件（Create）：

- `ops/nanoclaw/core_task1/flow/scripts/okx_skill_collector.py`
- `ops/nanoclaw/core_task1/schema/source_snapshot_v1.schema.json`
- `ops/nanoclaw/core_task1/schema/feature_cube_v1.schema.json`
- `shared/okx_flow_schema_map.json`
- `tests/test_okx_skill_collector.py`
- `tests/test_sync_web3_skill_snapshot_okx.py`

修改文件（Modify）：

- `ops/nanoclaw/core_task1/flow/scripts/sync_web3_skill_snapshot.py`
- `backend/src/_embedded_ml_trade_service_source.py`
- `backend/src/ml_trade_service.py`（仅必要包装）
- `ops/nanoclaw/core_task1/scripts/multi_agent_bridge.mjs`
- `基本面研究文档.md`
- `SKILL集成技术文档.md`

测试与验证（Test）：

- `tests/test_okx_skill_collector.py`
- `tests/test_sync_web3_skill_snapshot_okx.py`
- `tests/test_web3_market_digest_automation.py`
- `tests/test_p2_lifecycle_integration.py`

### 11.2 六个任务分解（按执行顺序）

#### Task 1：契约层（Schema + 映射）

- Step 1：先写失败测试（schema required 字段、枚举、最小结构）
- Step 2：运行测试确认失败
- Step 3：最小实现 `source_snapshot_v1.schema.json`、`feature_cube_v1.schema.json` 与 `okx_flow_schema_map.json`
- Step 4：运行测试确认通过
- Step 5：提交（commit）

示例命令：

```bash
pytest tests/test_sync_web3_skill_snapshot_okx.py::test_source_snapshot_schema_has_required_fields -v
```

#### Task 2：采集层（OKX P0 四 Skill Raw Bundle）

- Step 1：先写失败测试（采集器输出必须包含四个 OKX 主源 skill）
- Step 2：运行测试确认失败
- Step 3：最小实现 `okx_skill_collector.py`（先 stub + raw 落盘）
- Step 4：运行测试确认通过
- Step 5：提交（commit）

示例命令：

```bash
pytest tests/test_okx_skill_collector.py::test_build_snapshot_stub_contains_p0_sources -v
```

#### Task 3：标准化层（Raw → Source Snapshot）

- Step 1：先写失败测试（`sync_web3_skill_snapshot.py` 新增 OKX 四 mode）
- Step 2：运行测试确认失败
- Step 3：最小实现 mode 与映射函数（`okx-market-intel`/`okx-cmc-okx`/`okx-alpha-vantage`/`okx-hyperliquid-analyzer`）
- Step 4：运行测试确认通过
- Step 5：提交（commit）

示例命令：

```bash
pytest tests/test_sync_web3_skill_snapshot_okx.py -v
```

#### Task 4：后端聚合层（/fundamental 读取与汇总）

- Step 1：先写失败测试（`/fundamental/overview/latest` 包含 OKX 主源与 Gate/Binance 兜底摘要）
- Step 2：运行测试确认失败
- Step 3：最小实现后端聚合逻辑（source_summary + quality/coverage/missing）
- Step 4：运行测试确认通过
- Step 5：提交（commit）

示例命令：

```bash
pytest tests/test_web3_market_digest_automation.py::test_fundamental_overview_contains_okx_p0_sources -v
```

#### Task 5：multi-agent 桥接层（稳定消费 + 门禁）

- Step 1：先写失败测试（桥接输出包含宏观压力、来源覆盖率字段）
- Step 2：运行测试确认失败
- Step 3：最小实现 `multi_agent_bridge.mjs` 字段映射与 `coverage<0.55` 的 fail-closed
- Step 4：运行测试确认通过
- Step 5：提交（commit）

示例命令：

```bash
pytest tests/test_p2_lifecycle_integration.py::test_bridge_outputs_macro_pressure_and_source_coverage -v
```

#### Task 6：回归验收与文档同步

- Step 1：补齐 `基本面研究文档.md` 与本文档的 P0 状态、门禁与字段口径
- Step 2：运行全量回归测试
- Step 3：运行后端语法校验与前端 lint
- Step 4：确认 `readonly_advisory`、`fail-closed`、`coverage gate` 在输出中可见
- Step 5：提交（commit）

示例命令：

```bash
pytest tests -q
python -m py_compile backend/src/_embedded_ml_trade_service_source.py backend/src/ml_trade_service.py
cd frontend && npm run lint
```

### 11.3 三项强制治理（贯穿 6 个任务）

- `readonly_advisory`：所有 P0 Skill 输出默认只读建议，不直接触发执行写入。
- `fail-closed`：当 coverage 不足、关键字段 missing/suspect、或多源冲突时，自动降级为保守动作建议。
- `coverage 门禁`：默认 `coverage < 0.55` 时禁止“风险放大”类建议，必须显式输出 `missing_data[]` 与 `critical_missing_sources[]`。

### 11.4 当前执行状态（P0 实施进度）

- Task 1（契约层）：已完成
  - 已新增：`source_snapshot_v1.schema.json`、`feature_cube_v1.schema.json`、`shared/okx_flow_schema_map.json`
- Task 2（采集层）：已完成
  - 已新增：`okx_skill_collector.py`（stub 版，已纳入测试）
- Task 3（标准化层）：已完成
  - 已扩展 `sync_web3_skill_snapshot.py` 支持四个 OKX mode：`okx-market-intel`、`okx-cmc-okx`、`okx-alpha-vantage`、`okx-hyperliquid-analyzer`
- Task 4（后端聚合层）：已完成
  - `/fundamental/overview/latest` 已新增 `source_summary`（OKX 主源 + Gate/Binance 交叉兜底）
- Task 5（multi-agent 桥接层）：已完成
  - `multi_agent_bridge.mjs` 已新增 `macroPressure`、`sourceCoverage` 字段映射与 `coverage<0.55` fail-closed
- Task 6（回归验收与文档同步）：执行中（当前章节即为同步产物）

### 11.5 P0.5 增强（Onchain/Leverage 零信号修复 + 覆盖率冲刺）

- 已完成：`regime_classifier.py` 增加基于 `web3_skill_snapshot_latest.json` 的代理补值
  - Leverage：补 `funding_rate`、`oi_usd`、`liq_pressure`
  - Onchain：补 `whale_activity`、`gate_address_tracker`、`exchange_flow`、`gas_price`
- 已完成：`assess_data_quality` 支持通过 `bindBase` 映射将关键缺失源回填为 `backfilled`，并将 `directional_guard` 仅绑定 `suspect`，避免 backfilled 直接冻结方向信号。
- 已完成：`_embedded_ml_trade_service_source.py` 将 Flow 快照读取路径切换到工程根目录（修复 `backend/src/ops/...` 误路径），并加入覆盖率恢复重算。
- 当前目标状态：页面聚合层支持覆盖率恢复到 ≥0.80；若真实上游 source 全部缺失，仍按 fail-closed 输出保守动作。

## 12. Task7 入口（发布前门禁与灰度）

稳定性排查结论（当前轮）：

- 对 `tests/test_*.py` 做按文件 20s 超时探测，发现 `test_web3_market_digest_automation.py` 存在超时风险，其余当前核心测试文件通过。
- 因此 Task7 将优先处理“全量 `pytest tests -q` 长跑挂起”，再执行灰度发布门禁。
- 已新增快测文件：`tests/test_web3_market_digest_automation_fast.py`
- 慢测开关：`RUN_SLOW_TESTS=1` 时才执行 `tests/test_web3_market_digest_automation.py`

Task7 执行计划：

- 计划文件：[2026-04-08-task7-pre-release-gate-gray.md](file:///Users/zhangjiangtao/ft_userdata/%E5%9F%BA%E6%9C%AC%E9%9D%A2%E5%88%86%E6%9E%90_fundamental/docs/superpowers/plans/2026-04-08-task7-pre-release-gate-gray.md)
- 目标：
  - 建立发布前门禁脚本（测试/编译/lint）
  - 将长跑测试拆分为 slow 组并引入确定性 fast 测试
  - 引入 `/fundamental/overview/latest` 新字段灰度开关（可回滚）

Task7 第二阶段（已落地）：

- 测试分组：
  - `pytest.ini` 注册 `slow` marker
  - 默认快测：`pytest tests -q -m "not slow"`
  - 夜间慢测：`RUN_SLOW_TESTS=1 pytest tests -q -m slow --maxfail=1`
- CI 分组策略：
  - `/.github/workflows/ci-not-slow.yml`：push/PR 默认执行 `not slow`
  - `/.github/workflows/ci-slow-nightly.yml`：`cron + workflow_dispatch` 执行 `slow`
- 门禁脚本升级：
  - `ops/nanoclaw/core_task1/scripts/pre_release_gate.sh` 切到 `not slow` 默认策略
