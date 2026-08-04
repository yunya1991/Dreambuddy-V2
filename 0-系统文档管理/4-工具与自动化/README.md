# 4-工具与自动化

> **版本**: v1.0 | **更新日期**: 2026-08-02
> **定位**: L0 元文档层 — 文档体系自动化校验与报告工具集
> **状态**: ✅ 已建设 | **依赖**: 仅 Python 3.8+ 标准库（无第三方依赖）

本目录存放 DreamBuddy-V2 文档体系的自动化工具，覆盖命名/格式检查、覆盖率统计、目录树生成、跨文档链接校验四个维度。所有脚本可独立运行，遵循统一约定：UTF-8 编码、`argparse` CLI、友好中文输出、规范退出码。

## 工具清单

| 工具 | 功能 | 退出码 | 状态 |
|------|------|--------|------|
| [`doc_lint.py`](./doc_lint.py) | 文档命名/格式/规范检查 | 0 通过 / 1 违规 / 2 错误 | ✅ |
| [`doc_coverage.py`](./doc_coverage.py) | 文档覆盖率统计与报告 | 0 完成 / 2 错误 | ✅ |
| [`index_generator.py`](./index_generator.py) | 自动生成目录树索引 | 0 成功 / 2 错误 | ✅ |
| [`link_checker.py`](./link_checker.py) | 跨文档引用链接校验 | 0 无断链 / 1 断链 / 2 错误 | ✅ |

---

## 1. doc_lint.py — 文档命名/格式/规范检查

依据 `1-规范体系/DOC_STANDARD.md` 与 `DOC_CLASSIFICATION.md` 检查：

- `docs/` 下 `.md` 文件名是否符合「大写+下划线」规范
- 禁止命名检测（`技术文档*.md`、`新技术文档.md`、`最终版文档.md`、`doc1.md`、`temp.md`、含主观形容词）
- L0/L2 文档头部是否包含 `**版本**` 与 `**更新日期**` 版本头
- 同一目录下 `README.md` 与 `INDEX.md` 并存检测（L2 用 README，L1 用 INDEX）

**用法：**

```bash
# 默认扫描 0-系统文档管理 + 各 NN-子系统
python 0-系统文档管理/4-工具与自动化/doc_lint.py

# 扫描指定目录
python 0-系统文档管理/4-工具与自动化/doc_lint.py 0-系统文档管理

# 多目录 + 只输出违规数
python 0-系统文档管理/4-工具与自动化/doc_lint.py 10-经典指标系统 16-调控系统 --quiet
```

**输出示例：**

```
共发现 1 项违规：

[WARN] README_INDEX_CONFLICT  0-系统文档管理/README.md — 同目录并存 README.md 与 INDEX.md（L2 用 README，L1 用 INDEX）

违规统计：1 项
```

违规类型：`NAMING_FORBIDDEN`（禁止命名）、`NAMING_CASE`（docs/ 命名大小写）、`VERSION_HEADER_MISSING`（缺少版本头）、`README_INDEX_CONFLICT`（README/INDEX 并存）。

---

## 2. doc_coverage.py — 文档覆盖率统计与报告

扫描项目根下所有 `NN-*/` 子系统（L2，编号 ≥ 10）及 L3 辅助模块，检查 5 文档标准：`README.md`、`docs/ENGINEERING_INDEX.md`、`docs/TECHNICAL_DESIGN.md`、`docs/API_SPEC.md`、`docs/CHANGELOG.md`。

**用法：**

```bash
# 自动识别项目根（向上查找 0-系统文档管理）
python 0-系统文档管理/4-工具与自动化/doc_coverage.py

# 指定项目根 + 输出 JSON
python 0-系统文档管理/4-工具与自动化/doc_coverage.py --root . --json coverage.json
```

**输出示例（汇总表对齐 INDEX.md 末尾格式）：**

```
| 层级 | 模块数 | 文档齐全 | 部分完整 | 缺失 | 覆盖率 |
|------|--------|---------|---------|------|--------|
| L2 子系统 | 7 | 6 | 1 | 0 | 97% |
| L3 辅助模块 | 6 | 0 | 5 | 1 | 30% |
| **合计** | **13** | **6** | **6** | **1** | **66%** |

> 覆盖率 = 现存文档数 / 应建文档数 × 100%
```

L3 辅助模块范围：`3-EVOLUTION`、`6-图结构上下文压缩`、`7-产物中台`、`15-监控告警系统`、`experiments`、`1-ARCHITECTURE/dreamos`。

---

## 3. index_generator.py — 自动生成目录树索引

递归生成指定目录的目录树（markdown 代码块格式），用于辅助维护 `INDEX.md` 的目录结构段。自动忽略 `.git/`、`node_modules/`、`__pycache__/`、`.venv/`、`*.pyc`、`dist/`、`build/` 等噪音目录。

**用法：**

```bash
# 限制深度 2 层，输出到 stdout
python 0-系统文档管理/4-工具与自动化/index_generator.py 0-系统文档管理 --max-depth 2

# 仅目录，写入文件
python 0-系统文档管理/4-工具与自动化/index_generator.py 14-V15经典马丁策略 --dirs-only -o tree.txt
```

**输出示例：**

```
```
0-系统文档管理/
├── 1-规范体系/
│   ├── TEMPLATES/
│   ├── DOC_CLASSIFICATION.md
│   └── DOC_STANDARD.md
├── 2-文档地图/
│   └── ...
└── INDEX.md
```
```

参数：`--max-depth N`（最大深度，1=仅直接子项）、`--dirs-only`（只显示目录）、`--include-files`（默认开启）、`--output/-o FILE`（写入文件）。

---

## 4. link_checker.py — 跨文档链接校验

扫描指定目录下所有 `.md` 文件的 markdown 链接 `[text](path)`，校验相对路径目标是否存在。跳过外部 URL（http/https/mailto/ftp）与纯锚点（`#xxx`）；链接中的锚点（`path#section`）只校验 path 是否存在。

**用法：**

```bash
# 校验 0-系统文档管理 下所有链接
python 0-系统文档管理/4-工具与自动化/link_checker.py 0-系统文档管理

# 只输出统计
python 0-系统文档管理/4-工具与自动化/link_checker.py 0-系统文档管理 --summary
```

**输出示例：**

```
共发现 4 个断链：

0-系统文档管理/INDEX.md:72  [10-经典指标系统/README.md]  →  ../10-经典指标系统/README.md
0-系统文档管理/3-文档治理/DOC_DEBT_INDEX.md:4  [DEBT_INDEX.md]  →  ../../../DEBT_INDEX.md

断链统计：4 / 334
```

> 说明：`1-规范体系/TEMPLATES/` 为脚手架模板目录，其中的占位链接不参与校验。

---

## 集成到 CI

在 `.github/workflows/` 中调用以上脚本，可在 PR 阶段自动拦截文档规范问题。示例 workflow：

```yaml
# .github/workflows/doc-check.yml
name: 文档规范检查
on:
  pull_request:
    paths:
      - '**/*.md'
      - '0-系统文档管理/4-工具与自动化/**'
jobs:
  doc-lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: 命名/格式/规范检查
        run: |
          python 0-系统文档管理/4-工具与自动化/doc_lint.py 0-系统文档管理
          python 0-系统文档管理/4-工具与自动化/doc_lint.py 10-经典指标系统 11-易经推理系统 12-三屏趋势系统 13-通用风控模块 14-V15经典马丁策略 16-调控系统 17-v4-wave-strategy

  doc-coverage:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: 文档覆盖率统计
        run: |
          python 0-系统文档管理/4-工具与自动化/doc_coverage.py --json coverage.json
          cat coverage.json
      - uses: actions/upload-artifact@v4
        with:
          name: doc-coverage-report
          path: coverage.json

  link-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: 跨文档链接校验
        run: |
          python 0-系统文档管理/4-工具与自动化/link_checker.py 0-系统文档管理 --summary
          # 全量校验（断链则失败）
          python 0-系统文档管理/4-工具与自动化/link_checker.py 0-系统文档管理
```

> 提示：CI 中建议将 `doc_lint.py` 与 `link_checker.py` 设为阻断型（退出码 1 即失败），`doc_coverage.py` 设为报告型（仅上传产物，不阻断）。

---

## 退出码约定

| 退出码 | 含义 |
|--------|------|
| 0 | 成功 / 通过 / 无断链 |
| 1 | 存在违规 / 存在断链（仅 doc_lint、link_checker） |
| 2 | 目录不存在 / 参数错误 / 项目根未识别 |

---

**维护说明**: 工具遵循 `1-规范体系/DOC_STANDARD.md` 规范定义；新增校验规则时优先更新规范文档，再在脚本中实现对应检查项。
