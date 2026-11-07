# ENGINEERING INDEX — 51-OKX CLI 系统

> 版本：v0.1.0
> 更新：2026-11-07
> 状态：🟢 P1 骨架已落地；P2 trade-exec MCP 接线待评审

---

## 1. 模块定位

| 项 | 内容 |
|---|---|
| 模块编号 | 51 |
| 模块名 | OKX CLI 系统（OKX Venue Adapter） |
| 层级 | 执行层 EXEC/L1.5（场所适配层） |
| 唯一职责 | 把 OKX CLI 命令面收束为受治理的 Port |
| 不是 | 交易系统 / 策略层 / 风控层 / 执行出口 / MCP 壳 |
| 上游 | 49 交易框架协议、47-MCP 管理系统 |
| 下游 | trade-exec MCP（paper）、11 域 okx_client 旁路（live） |
| 外部依赖 | `@okx_ai/okx-trade-cli`（pin 版本）、Python ≥3.10 标准库 |

---

## 2. 文件地图

| 路径 | 职责 | 状态 |
|---|---|---|
| `SPEC.md` | 设计规格：定位、决策、Port、边界、迁移、阶段 | ✅ |
| `README.md` | 使用说明、环境变量、目录结构 | ✅ |
| `docs/ENGINEERING_INDEX.md` | 本文件 | ✅ |
| `docs/TECHNICAL_DESIGN.md` | 技术设计：进程模型、错误映射、审计、P2 接线 | ✅ |
| `docs/API_SPEC.md` | Port API 契约与 CLI 命令映射 | ✅ |
| `docs/CHANGELOG.md` | 变更记录 | ✅ |
| `src/okx_venue/__init__.py` | 包导出 | ✅ |
| `src/okx_venue/config.py` | profile / mode / 环境变量 / 自洽校验 | ✅ |
| `src/okx_venue/catalog.py` | 命令白名单 | ✅ |
| `src/okx_venue/runner.py` | subprocess + JSON + 审计 + 错误分类 | ✅ |
| `src/okx_venue/adapter.py` | Market/Account/Order Port 实现 | ✅ |
| `src/okx_venue/errors.py` | 错误模型 | ✅ |
| `src/okx_venue/selector.py` | P2 OrderPort 选择器（paper / okx-cli-demo） | ✅ |
| `tests/test_config.py` | demo/live 隔离、profile 自洽 | ✅ 35 用例 |
| `tests/test_catalog.py` | 白名单、危险 flag、shell 元字符 | ✅ |
| `tests/test_runner.py` | 参数注入、审计、错误分类、超时 | ✅ |
| `tests/test_adapter.py` | 结果归一化、下单 argv、选择器 | ✅ |
| `runtime/audit/` | 运行时审计 JSONL（不提交内容） | 运行时生成 |

---

## 3. 依赖图

```text
adapter.py
  ├─ config.py ── errors.py
  ├─ runner.py ── catalog.py ── errors.py
  └─ errors.py

selector.py
  ├─ adapter.py
  ├─ config.py
  └─ errors.py

__init__.py
  └─ 导出上述公开符号
```

无第三方 Python 依赖；仅使用 `subprocess` / `json` / `dataclasses` / `pathlib` / `threading`。

---

## 4. 入口点

| 入口 | 用法 |
|---|---|
| Python API | `from okx_venue import OkxCliVenue, VenueConfig` |
| P2 选择器 | `build_order_adapter("okx-cli-demo")` |
| 测试 | `python -m pytest "51-OKX CLI 系统/tests" -q` |

---

## 5. 测试与验收

```bash
# 单元测试
python -m pytest "51-OKX CLI 系统/tests" -q

# 静态检查（项目根已有 ruff/black）
ruff check "51-OKX CLI 系统/src" "51-OKX CLI 系统/tests"
black --check "51-OKX CLI 系统/src" "51-OKX CLI 系统/tests"
```

**P1 验收标准：**

- [x] 35 用例全绿
- [x] live 写恒拒绝（无需环境变量）
- [x] live 读默认拒绝、显式开关放行
- [x] demo profile 与 mode 自洽校验
- [x] 调用方不能传 `--profile` / `--demo` / 凭证 flag
- [x] 每次调用写审计 JSONL，凭证 flag 脱敏
- [x] 6-TRADING legacy live 路径 fail-closed

---

## 6. 与其他模块的接口

| 模块 | 接口 | 状态 |
|---|---|---|
| trade-exec MCP | `OkxCliVenue` 作为 OrderPort 可选实现 | P2 |
| 6-TRADING | legacy 路径守卫 + 迁移说明 | ✅ P1 守卫 |
| 49 交易框架协议 | DEC-25 / R-L0-03 收口证据 | 🟡 迁移中 |
| 47-MCP 管理系统 | 不新增 shell；硬约束对照 | ✅ |
| 13 通用风控 | 51 在 RiskBridge 之后，不直接调用 | ✅ 设计 |
| 11 交易执行器 | live 唯一出口，不变 | ✅ |

---

## 7. 状态与后续

| 阶段 | 内容 | 状态 |
|---|---|---|
| P1 | 51 骨架 + Port + 测试 + legacy 守卫 | ✅ |
| P2 | trade-exec MCP 选择器接线 + 契约测试 | ⏳ 待评审 |
| P3 | 6-TRADING 封装完全迁移、文档收口 | ⏳ 待排期 |
| P4 | live 交给 51（需 ADR 修订硬约束） | ❌ 未批准 |