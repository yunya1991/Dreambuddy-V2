# 20-数据清洗中心 — 变更日志

> **版本**: v1.1 | **更新日期**: 2026-10-01
> **定位**: 记录每次变更的原因、内容、验证方式，对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) §3.5

---

## [v1.1] - 2026-10-01

### 新增

- **变更内容**: 补建 `docs/README.md` 文档索引（对齐 DOC_STANDARD L3 五件套标准）
  - 原 docs/ 四件套（ENGINEERING_INDEX+TECHNICAL_DESIGN+API_SPEC+CHANGELOG）缺 README 文档索引
  - 新建 docs/README.md 含五件套索引表 + archive/ 子目录说明

### 归档

- **变更内容**: `docs/DATA_CLEANING_SPEC.md` → `docs/archive/DATA_CLEANING_SPEC.md`
  - 原因：DATA_CLEANING_SPEC.md 是归档版设计规格（文档自标"归档版，设计冻结，与全局 specs 一致"），属于历史归档而非活跃文档
  - 归档后 docs/ 五件套为标准结构：README + ENGINEERING_INDEX + TECHNICAL_DESIGN + API_SPEC + CHANGELOG

### 修改

- **变更内容**: 散落文件治理（dream-scattered-file-cleanup 工作流推进）
  - `README.md` §目录结构修正：README.md 从 docs/ 下移到根层（原误列为 docs/README.md # 本文件，实际本文件在根层），DATA_CLEANING_SPEC.md 改为 archive/ 子目录
  - `docs/ENGINEERING_INDEX.md` §2 目录地图补齐：docs/README.md（文档索引）、docs/archive/（历史归档）、requirements.txt（空，依赖通过 18 号管理）
  - `docs/ENGINEERING_INDEX.md` §8 快速导航补充 docs/README.md + archive/ 链接
  - `docs/ENGINEERING_INDEX.md` 版本号 v1.0→v1.1

- **影响范围**:
  - `20-数据清洗中心/docs/README.md`（新建）
  - `20-数据清洗中心/docs/archive/DATA_CLEANING_SPEC.md`（归档移动）
  - `20-数据清洗中心/README.md`（目录结构修正）
  - `20-数据清洗中心/docs/ENGINEERING_INDEX.md`（目录地图+导航+版本号）
  - `20-数据清洗中心/docs/CHANGELOG.md`（本记录+版本号）

- **验证方式**:
  - 散落文件治理 5 步流程完整执行：双维度分类→状态机判断→索引登记→三态决策→认知闭环
  - `requirements.txt` 0B 空文件判定：依赖通过 18 号 requirements.txt 或全局环境管理，保留作占位符
  - `DATA_CLEANING_SPEC.md` 归档判定：文档自标"归档版（设计冻结）"，属于历史归档
  - 根层 README.md 目录结构修正：原 L22 误列 `docs/README.md # 本文件`（实际本文件在根层 L44），已修正
  - docs/ 五件套对齐 DOC_STANDARD L3：README+IDX+TD+API+CL

- **治理结论**:
  - 20-数据清洗中心 子系统已治理良好，根层文件全部 Active（README.md + requirements.txt 空占位符）
  - data_cleaning/ 核心包结构清晰（contract/pipeline/errors/adapters/dal_sink/cli + cleaners/4 + gate/）
  - tests/ 14+ 测试覆盖完整（cleaners/gate/adapters/pipeline/dal_sink/e2e）
  - docs/ 五件套补齐（新增 README.md 文档索引）+ archive/（DATA_CLEANING_SPEC 归档）
  - 无 launchd/ 目录（20 号是被 18 号调度器调用的被调模块，无独立 launchd 服务）

- **回滚策略**:
  - `rm docs/README.md && mv docs/archive/DATA_CLEANING_SPEC.md docs/ && git checkout README.md docs/ENGINEERING_INDEX.md docs/CHANGELOG.md`

---

## [v1.0] - 2026-09-30

### 新增
- **变更内容**: 补齐 5 文档标准——新增 `README.md`、`docs/ENGINEERING_INDEX.md`、`docs/TECHNICAL_DESIGN.md`、`docs/API_SPEC.md`、`docs/CHANGELOG.md`
- **影响范围**: `20-数据清洗中心/`
- **验证方式**: `python3 0-系统文档管理/4-工具与自动化/doc_coverage.py` 确认 20 号覆盖率 0/5→5/5
- **回滚策略**: `git rm -rf 20-数据清洗中心/docs/ 20-数据清洗中心/README.md`

---

## 历史变更（从 DATA_CLEANING_SPEC.md 迁移）

### Silver 层清洗链建设

### 新增
- **变更内容**: `data_cleaning/pipeline.py` — DataCleaningPipeline 7 步编排（去重→异常→缺失→单位→还原→门禁→产出）
- **影响范围**: `pipeline.py`, `cleaners/`, `gate/`, `adapters.py`
- **验证方式**: `tests/test_pipeline_t9_e2e.py` + `tests/test_e2e_silver_chain.py` GREEN
- **回滚策略**: `git revert`

### 新增
- **变更内容**: `cleaners/outlier_filter.py` — Outlier3LFilter 三层异常过滤（3σ + IQR + ATR）
- **影响范围**: `cleaners/`
- **验证方式**: `tests/test_cleaners_t3_outlier.py` GREEN
- **回滚策略**: `git revert`

### 新增
- **变更内容**: `gate/quality_gate.py` — QualityGate 复用 18 号 QualityChecker，4 类检查（EMPTY_RESULT/CONTRACT_INVALID/DUPLICATE_DETECTED/TIMESTAMP_FRESHNESS）
- **影响范围**: `gate/`
- **验证方式**: `tests/test_gate_dirty_injection.py` GREEN（脏数据注入测试）
- **回滚策略**: `git revert`

### 新增
- **变更内容**: `dal_sink.py` — DalSink.write_silver() 将 SilverRecord 写入 19-DAL（fail-open）
- **影响范围**: `dal_sink.py`
- **验证方式**: `tests/test_dal_sink.py` GREEN
- **回滚策略**: `git revert`

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
