# 18-数据获取中心 — 变更日志

> **版本**: v1.1 | **更新日期**: 2026-10-01
> **定位**: 记录每次变更的原因、内容、验证方式，对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) §3.5

---

## [v1.1] - 2026-10-01

### 修改

- **变更内容**: 散落文件治理（dream-scattered-file-cleanup 工作流推进）
  - `docs/ENGINEERING_INDEX.md` §2 目录地图补齐：`docs/README.md`(10/1新建)、`docs/archive/`(IMPLEMENTATION_PLAN 已归档)、`config/.env`+`.env.example`、`dataview_html_parser.py`(被 theblockbeats_dataview+five_domain_sqlite_reader 引用)、`pyproject.toml`、`requirements.txt`、`data_center.db`(514MB,.gitignore)、`logs/`(运行时,.gitignore)
  - `docs/ENGINEERING_INDEX.md` §2 launchd 目录补充 3 个 plist 说明（datacenter=datacenter.plist 实际运行服务、data-center-scheduler.plist 安装模板、archive/ 归档重复）

### 归档

- **变更内容**: launchd plist 重复治理
  - 归档 `launchd/com.dreambuddy.dc-scheduler.plist` → `launchd/archive/com.dreambuddy.dc-scheduler.plist.bak`（与 `com.dreambuddy.datacenter.plist` 仅 Label 不同，Duplication is Evil）
  - 保留 `launchd/com.dreambuddy.datacenter.plist`（实际运行服务源，PYTHONPATH 已修正含 20-数据清洗中心）
  - 保留 `launchd/com.dreambuddy.data-center-scheduler.plist`（安装模板，有完整注释）

### 修复

- **变更内容**: `launchd/com.dreambuddy.datacenter.plist` PYTHONPATH 修正
  - 之前修复任务（VM-1790862605750）只更新了 `~/Library/LaunchAgents/` 副本，源文件 PYTHONPATH 仍缺 20-数据清洗中心
  - 现源文件 PYTHONPATH = `18-数据获取中心:20-数据清洗中心`，与实际运行服务一致

- **影响范围**:
  - `18-数据获取中心/docs/ENGINEERING_INDEX.md`（目录地图+版本号）
  - `18-数据获取中心/docs/CHANGELOG.md`（本记录+版本号）
  - `18-数据获取中心/launchd/com.dreambuddy.datacenter.plist`（PYTHONPATH 修正）
  - `18-数据获取中心/launchd/archive/com.dreambuddy.dc-scheduler.plist.bak`（归档）

- **验证方式**:
  - 散落文件治理 5 步流程完整执行：双维度分类→状态机判断→索引登记→三态决策→认知闭环
  - `dataview_html_parser.py` 被 2 处 Active 引用（`data_center/collectors/news/theblockbeats_dataview.py` + `11-易经推理系统/scripts/memory_l4/five_domain_sqlite_reader.py`）→ Active 保留
  - `verify_e2e_pipeline_blockbeats.py` 在 `tests/` 下（非根层散落，已正确归位）
  - `docs/IMPLEMENTATION_PLAN.md` 已归档到 `docs/archive/`（M1-M5 已完成）
  - `docs/README.md` 10/1 补建（对齐 DOC_STANDARD L3 五件套）
  - `__pycache__/`、`.pytest_cache/` 已被 .gitignore（非治理重点）
  - launchd plist diff 确认 dc-scheduler 与 datacenter 仅 Label 不同（重复）

- **治理结论**:
  - 18-数据获取中心 子系统已治理良好，根层文件全部 Active（5 个 .py + 4 个配置/数据文件）
  - docs/ 五件套齐全（README+IDX+TD+API+CL）+ archive/ 历史归档
  - launchd/ 3→2 plist（归档 1 重复）+ archive/ 子目录
  - data_center/ 核心包 60+ Python 文件结构清晰（6 域 33 collector）
  - 唯一修正项：datacenter.plist 源文件 PYTHONPATH（之前修复遗漏）

- **回滚策略**:
  - `git checkout docs/ENGINEERING_INDEX.md docs/CHANGELOG.md launchd/com.dreambuddy.datacenter.plist`
  - `mv launchd/archive/com.dreambuddy.dc-scheduler.plist.bak launchd/com.dreambuddy.dc-scheduler.plist`

---

## [v1.0] - 2026-09-30

### 新增
- **变更内容**: 补齐 5 文档标准——新增 `docs/ENGINEERING_INDEX.md`、`docs/API_SPEC.md`、`docs/CHANGELOG.md`
- **影响范围**: `18-数据获取中心/docs/`
- **验证方式**: `python3 0-系统文档管理/4-工具与自动化/doc_coverage.py` 确认 18 号覆盖率 2/5→5/5
- **回滚策略**: `git rm 18-数据获取中心/docs/ENGINEERING_INDEX.md 18-数据获取中心/docs/API_SPEC.md 18-数据获取中心/docs/CHANGELOG.md`

### 修改
- **变更内容**: `docs/TECHNICAL_DESIGN.md` 头部关联文档链接补充 API_SPEC/CHANGELOG
- **影响范围**: `docs/TECHNICAL_DESIGN.md`
- **验证方式**: `link_checker.py 18-数据获取中心/docs/` 无新增断链
- **回滚策略**: `git checkout 18-数据获取中心/docs/TECHNICAL_DESIGN.md`

---

## 历史变更（从 README.md 迁移）

### 2026-08-29: Odaily 星球日报快讯采集器

### 新增
- **变更内容**: `collectors/news/odaily_newsflash.py` — OdailyNewsflashCollector(BaseCollector)
  - source=`odaily_newsflash`, category=`news`, 14 关键词 8 类 event_type, 5 类 attention_type
  - 三端点：`/newsflash/page` + `/newsflash/checkHasNew` + `/hotWord/list`
  - FAIL-OPEN: Session Timeout/Exception→[]，SentimentEngine ImportError→sentiment=0.5
- **影响范围**: `collectors/news/`, `core/dispatcher.py`, `config/sources.yaml`, `scheduler.py`
- **验证方式**: `tests/news/test_odaily_collector.py` 5 TC GREEN
- **回滚策略**: `git revert` 相关 commit

### 前期里程碑（M1 已完成）

- ✅ `DataRecord` 统一契约（`core/contract.py`）+ 校验
- ✅ 异常体系（`core/errors.py`）
- ✅ `BaseCollector` 抽象（`collectors/_base.py`）
- ✅ FRED macro collector（`collectors/macro/fred_collector.py`）
- ✅ Registry + Dispatcher（`core/registry.py`、`core/dispatcher.py`）
- ✅ 去重 + sqlite 落库（`storage/cache.py`、`storage/sink_sqlite.py`）
- ✅ CLI 壳（`cli/app.py`：`fetch`/`list`/`crawl`/`schedule`）
- ✅ `from data_center import DataCenter, DataRecord`
- ✅ `.env` 自动加载 + 端到端集成测试（39 项全绿）
- ✅ M5 监控三件套（metrics/quality/alerting）
- ✅ H1 Silver 中间件（QualityGate 硬门禁 + 20-DAL 写入）
- ✅ Phase G BDSM 原生采集器（Pump/Aave/Hype/Uniswap/Circle/Solana）

---

## 变更类型说明

| 类型 | 说明 |
|------|------|
| **新增** | 添加新功能、新文件、新接口 |
| **修改** | 修改已有功能、重构、优化 |
| **修复** | 修复 bug、缺陷、错误 |
| **删除** | 移除废弃功能、文件、接口 |

---

**文档版本**: v1.1
**最后更新**: 2026-10-01
