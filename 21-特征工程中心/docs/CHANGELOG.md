# 21-特征工程中心 — 变更日志

> **版本**: v1.0 | **更新日期**: 2026-09-30
> **定位**: 记录每次变更的原因、内容、验证方式，对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) §3.5

---

## [v1.0] - 2026-09-30

### 新增
- **变更内容**: 补齐 5 文档标准——新增 `README.md`、`docs/ENGINEERING_INDEX.md`、`docs/TECHNICAL_DESIGN.md`、`docs/API_SPEC.md`、`docs/CHANGELOG.md`
- **影响范围**: `21-特征工程中心/`
- **验证方式**: `python3 0-系统文档管理/4-工具与自动化/doc_coverage.py` 确认 21 号覆盖率 0/5→5/5
- **回滚策略**: `git rm -rf 21-特征工程中心/docs/ 21-特征工程中心/README.md`

---

## 历史变更（从 FEATURE_HUB_SPEC.md 迁移）

### FeatureHub 统一特征管道建设

### 新增
- **变更内容**: `hub/feature_registry.py` — FeatureRegistry 统一注册表，回测/实盘共用 compute_all 入口
- **影响范围**: `hub/`
- **验证方式**: `tests/unit/test_feature_pipeline.py` + `tests/integration/test_consistency.py` GREEN
- **回滚策略**: `git revert`

### 新增
- **变更内容**: `pipeline/feature_pipeline.py` — FeaturePipeline 按 ENABLED_SETS 编排 + L1 fail-open
- **影响范围**: `pipeline/`
- **验证方式**: `tests/unit/test_feature_pipeline.py` GREEN
- **回滚策略**: `git revert`

### 新增
- **变更内容**: `modules/` 9 大特征模块（crypto_morphology/elder_ray/triple_screen_trend/classic_indicators/talib_aligned/five_domain_fc/martin_features/fundamental_ratios/yijing_cycle）
- **影响范围**: `modules/`
- **验证方式**: `tests/integration/test_cross_strategy_sets.py` GREEN
- **回滚策略**: `git revert`

### 新增
- **变更内容**: `cleaning_chain/standard_chain.py` — StandardCleaningChain 标准化清洗链
- **影响范围**: `cleaning_chain/`
- **验证方式**: `tests/unit/test_standard_cleaning_chain.py` GREEN
- **回滚策略**: `git revert`

### 新增
- **变更内容**: `hub/lineage.py` + `hub/versioning.py` — 血缘追踪 + 特征版本管理
- **影响范围**: `hub/`
- **验证方式**: `tests/unit/test_lineage_and_versioning.py` GREEN
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

**文档版本**: v1.0
**最后更新**: 2026-09-30
