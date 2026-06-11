# 工程索引

## 项目定位

- `7-产物中台` 是当前产物中台总容器。
- `系统研究索引体系` 是已经归位的现有实现工程。
- `ui-map` 独立中台首页已进入 Phase B 真实数据接入阶段，当前已接入：系统研究索引、研究链路、运营链路、策略主线（summary-only）、用户上下文索引（summary-only）五个模块。
- `ui-map/`、`用户上下文索引系统/`、`策略主线/`、`系统研究链路/`、`系统运营链路/` 仍作为模块预留目录存在，具体实现集中在 `系统研究索引体系/app/ui-map/`。

## 当前文档主线

- 当前保留的设计文档：
- [ui-map-independent-hub-main-map-design.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-%E4%BA%A7%E7%89%A9%E4%B8%AD%E5%8F%B0/docs/superpowers/specs/2026-05-22-ui-map-independent-hub-main-map-design.md)
- [ui-map-real-data-integration-contract.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-%E4%BA%A7%E7%89%A9%E4%B8%AD%E5%8F%B0/docs/superpowers/specs/2026-06-07-ui-map-real-data-integration-contract.md)
- [product-hub-directory-migration-design.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-%E4%BA%A7%E7%89%A9%E4%B8%AD%E5%8F%B0/docs/superpowers/specs/2026-05-22-product-hub-directory-migration-design.md)
- 当前保留的实施计划：
- [ui-map-independent-hub-main-map-implementation.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-%E4%BA%A7%E7%89%A9%E4%B8%AD%E5%8F%B0/docs/superpowers/plans/2026-05-22-ui-map-independent-hub-main-map-implementation.md)
- [product-hub-directory-migration-implementation.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/7-%E4%BA%A7%E7%89%A9%E4%B8%AD%E5%8F%B0/docs/superpowers/plans/2026-05-22-product-hub-directory-migration-implementation.md)

## 目录地图

- `docs/`
- 当前治理文档与正式 spec / plan 沉淀区。
- `系统研究索引体系/`
- 已归位的老中台实现工程，当前可运行并负责系统研究索引能力。
- `当前 ui-map 的真实实现入口位于：系统研究索引体系/app/ui-map/`
- 核心实现文件：
- `app/ui-map/page.tsx`：服务端装配入口，调用五个真实数据 adapter。
- `app/ui-map/UIMapShell.tsx`：纯渲染壳层，消费 view-model。
- `app/ui-map/ui-map-shell-view-model.ts`：view-model 生成，支持 fixture / real-data 双入口。
- `app/ui-map/ui-map-scenarios.ts`：场景 fixture，降级模式保留。
- `app/chain/page.tsx`：A 系列三环驾驶舱页，只通过 `app/chain/summary-only.ts` 接入 `content.server` 的规范索引。
- `app/chain/summary-only.ts`：summary-only 聚合层，严格禁止 fs / log / raw content 读取。
- `lib/ui-map-real-data.ts`：五个真实数据 adapter（系统研究索引、研究链路、运营链路、策略主线、用户上下文索引）。
- `lib/content.server.ts`：系统研究产物索引与关系数据源。
- `lib/realtime-hub.ts`：运营事件实时数据源。
- `ui-map/`
- 独立中台首页模块预留目录；当前仍以规划占位为主，不是主实现目录。
- `用户上下文索引系统/`
- 用户配置、记忆、执行上下文承载模块预留目录；summary-only 聚合已由 `buildUserContextUIMapOverride` 提供。
- `策略主线/`
- 策略统一收口与主链承接模块预留目录；summary-only 聚合已由 `buildStrategyUIMapOverride` 提供。
- `系统研究链路/`
- 系统研究链路透视模块预留目录；真实数据由 `lib/ui-map-real-data.ts` 中 `buildResearchChainUIMapOverride` 提供。
- `系统运营链路/`
- 系统运营链路透视模块预留目录；真实数据由 `lib/ui-map-real-data.ts` 中 `buildOperationsUIMapOverride` 提供。

## 协作者先看

- 先看 `docs/superpowers/specs/2026-05-22-ui-map-independent-hub-main-map-design.md`。
- 若要接真实中台数据，再看 `docs/superpowers/specs/2026-06-07-ui-map-real-data-integration-contract.md`。
- 再看 `docs/superpowers/specs/2026-05-22-product-hub-directory-migration-design.md`。
- 若要改 `ui-map` 页面实现，请优先进入 `系统研究索引体系/app/ui-map/`，不要误改 `ui-map/` 预留目录。
- 若要追溯旧文档，请查看 `docs/archive/README.md` 提示并通过 `git` 历史查询。

## ui-map 模块状态（2026-06-10）

- **Phase A（壳层）**：已稳定。路由 `/ui-map`、`UIMapShell`、场景切换、语义分层均已验证（`ui-map-shell-view-model.test.ts` 14 个测试通过）。
- **Phase B（真实数据接入）**：系统研究索引、研究链路、运营链路、策略主线、用户上下文索引五个模块已接入，每个模块均具备 fixture 降级模式。
  - 系统研究索引：`buildSystemResearchUIMapOverride` 基于 `content.server.ts` 产物索引生成。
  - 研究链路：`buildResearchChainUIMapOverride` 基于 `getChainPhaseArtifacts` 阶段分组生成。
  - 运营链路：`buildOperationsUIMapOverride` 基于 `realtime-hub.ts` 最近事件摘要生成。
  - 策略主线：`buildStrategyUIMapOverride` 基于 artifacts 索引的 `type=strategy` 统计生成（摘要级接入，明确标记 `summary-only`，敏感配置与执行状态未透出）。策略主线统计从全量 artifacts 精确化为仅 `type=strategy`（phase 分布、活跃/已沉淀状态均仅统计策略产物）；支持小写 phase 标签归一化（a9→A9）。
  - 用户上下文索引：`buildUserContextUIMapOverride` 基于 artifacts 索引全量统计生成（summary-only：未透出任何用户配置或敏感信息，仅沉淀产物数量与活跃状态摘要）。
- **未接入**：无（全部五个索引底座模块均以 summary-only 接入真实数据，用户配置等敏感信息继续不透出）。
- **测试覆盖**：`lib/ui-map-real-data.test.ts` 18 个测试覆盖真实数据注入与降级行为。
