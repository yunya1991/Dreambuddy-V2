# PROP-20260829 — DreamOS 架构文档对齐（OS≠交易系统 区分贯穿 + SSoT 修补）

> **状态**: ✅ 已实施（批准 2026-08-29，commit `3742ce2b`，验收 6/6 通过）
> **来源**: D系列调研《DreamOS操作系统架构设计审查》(D1→D2→D4)
> **类型**: 纯文档变更（6文件），零代码改动

## 背景与问题

D1 调研发现（事实）：
1. 「OS≠交易系统」区分仅在 `dreamos/docs/TECHNICAL_DESIGN.md §1.1.1` 明文成立；外围文档混用：
   - `four-loop/FOUR_LOOP_GUIDE.md` 正文用「DreamOS」直接指代交易流水线
   - `1-ARCHITECTURE/README.md` 把 `dreamos/`（OS内核）标为「DreamOS CLI」
   - `TRADING_MODULES_OVERVIEW.md` 把「Agent C (DreamOS)」并列为交易模块
2. SSoT (`SYSTEM_ARCHITECTURE_OVERVIEW.md`) 失真：
   - 零收录「四闭环」（8/15 物理验证导通的当前生产流水线）
   - 节点数声称 22 / 注册表声称 35+，实际 23 / 28
   - 目录树列出不存在的 `dreamos/README.md`；测试位置写反（实际 `dreamos/tests/` 13个，`dreamos-tests/` 空壳）
   - `file://` 链接指向已迁移的 macOS 环境
3. 版本号自相矛盾：TD 标题 v2.1 vs 头部 v2.5.0；EI 标题 v2.1 vs 头部 v2.4.0；TD 章节出现两个「## 4.」
4. 用户「四支柱」口径（认知系统+易经推理引擎+DreamOS+子系统交易系统/能力节点）在架构文档中无载点

## 变更清单（6 文件）

| # | 文件 | 改动 |
|---|---|---|
| 1 | `1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md` | §1.3 新增术语锚点（统一写法/两闭环对照/四支柱）；§2.6 修正计数与路径；新增四闭环小节；§4.3 补双重身份引用 |
| 2 | `1-ARCHITECTURE/four-loop/FOUR_LOOP_GUIDE.md` | 正文限定为「DreamOS 交易系统」 |
| 3 | `1-ARCHITECTURE/README.md` | dreamos/ 索引行改为「Dreambuddy OS 内核（代码+文档）」 |
| 4 | `1-ARCHITECTURE/TRADING_MODULES_OVERVIEW.md` | Agent C 行限定为「DreamOS 交易系统」 |
| 5 | `1-ARCHITECTURE/dreamos/docs/TECHNICAL_DESIGN.md` | 标题版本对齐 v2.5.0；修复重复「## 4.」章节编号 |
| 6 | `1-ARCHITECTURE/dreamos/docs/ENGINEERING_INDEX.md` | 标题版本对齐 v2.4.0 |

## 不做范围

不动代码；不动 A系列 cron；不建 doc-lint 门禁（方案B 另案）；不重写 SSoT；不退役 Agent A/B/C 旧称。

## 验收

- grep「四闭环」SSoT ≥1 且章节完整
- SSoT 节点数=23、注册表=28（与代码实测一致）
- 外围 3 处混用清零（grep 验证）
- TD/EI 标题版本=头部版本
- 单 commit 仅含上述文件

## 回滚

单 commit → `git revert` 一步还原。
