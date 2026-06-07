# 工程索引

## 项目定位

- `7-产物中台` 是当前产物中台总容器。
- `系统研究索引体系` 是已经归位的现有实现工程。
- `ui-map`、`用户上下文索引系统`、`策略主线`、`系统研究链路`、`系统运营链路` 是后续按模块推进的目标目录。

## 当前文档主线

- 当前保留的设计文档：
- [ui-map-independent-hub-main-map-design.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2-mainline/7-%E4%BA%A7%E7%89%A9%E4%B8%AD%E5%8F%B0/docs/superpowers/specs/2026-05-22-ui-map-independent-hub-main-map-design.md)
- [ui-map-real-data-integration-contract.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2-mainline/7-%E4%BA%A7%E7%89%A9%E4%B8%AD%E5%8F%B0/docs/superpowers/specs/2026-06-07-ui-map-real-data-integration-contract.md)
- [product-hub-directory-migration-design.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2-mainline/7-%E4%BA%A7%E7%89%A9%E4%B8%AD%E5%8F%B0/docs/superpowers/specs/2026-05-22-product-hub-directory-migration-design.md)
- 当前保留的实施计划：
- [ui-map-independent-hub-main-map-implementation.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2-mainline/7-%E4%BA%A7%E7%89%A9%E4%B8%AD%E5%8F%B0/docs/superpowers/plans/2026-05-22-ui-map-independent-hub-main-map-implementation.md)
- [product-hub-directory-migration-implementation.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2-mainline/7-%E4%BA%A7%E7%89%A9%E4%B8%AD%E5%8F%B0/docs/superpowers/plans/2026-05-22-product-hub-directory-migration-implementation.md)

## 目录地图

- `docs/`
- 当前治理文档与正式 spec / plan 沉淀区。
- `系统研究索引体系/`
- 已归位的老中台实现工程，当前可运行并负责系统研究索引能力。
- `当前 ui-map 的真实实现入口位于：系统研究索引体系/app/ui-map/`
- `ui-map/`
- 独立中台首页模块预留目录；当前仍以规划占位为主，不是主实现目录。
- `用户上下文索引系统/`
- 用户配置、记忆、执行上下文承载模块预留目录。
- `策略主线/`
- 策略统一收口与主链承接模块预留目录。
- `系统研究链路/`
- 系统研究链路透视模块预留目录。
- `系统运营链路/`
- 系统运营链路透视模块预留目录。

## 协作者先看

- 先看 `docs/superpowers/specs/2026-05-22-ui-map-independent-hub-main-map-design.md`。
- 若要接真实中台数据，再看 `docs/superpowers/specs/2026-06-07-ui-map-real-data-integration-contract.md`。
- 再看 `docs/superpowers/specs/2026-05-22-product-hub-directory-migration-design.md`。
- 若要改 `ui-map` 页面实现，请优先进入 `系统研究索引体系/app/ui-map/`，不要误改 `ui-map/` 预留目录。
- 若要追溯旧文档，请查看 `docs/archive/README.md` 提示并通过 `git` 历史查询。
