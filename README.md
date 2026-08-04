# DreamBuddy-V2

> AI 驱动的加密货币交易决策系统（多智能体架构）

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Version](https://img.shields.io/badge/version-2.0-blue.svg)](./VERSION)

---

## 📚 文档入口

**所有文档的统一入口** → [0-系统文档管理/](./0-系统文档管理/)

| 我想... | 去哪 |
|--------|------|
| 找任意文档 | [2-文档地图/](./0-系统文档管理/2-文档地图/) |
| 写新文档 | [1-规范体系/](./0-系统文档管理/1-规范体系/) |
| 管理文档债 | [3-文档治理/](./0-系统文档管理/3-文档治理/) |
| 查技术债 | [DEBT_INDEX.md](./DEBT_INDEX.md) |
| 查文档规范 | [DOC_STANDARD.md](./0-系统文档管理/1-规范体系/DOC_STANDARD.md) |

---

## 🚀 快速开始

### 环境要求

- Node.js >= 18 · Python >= 3.10 · PostgreSQL >= 14 · pnpm >= 8

### 启动前端

```bash
cd 3-FRONTEND/dream-universal-gateway
pnpm install
cp .env.example .env  # 编辑 .env 填写配置
pnpm db:push
pnpm dev               # http://localhost:3456
```

### 启动交易服务

```bash
# 详见各子系统 docs/ 中的 ENGINEERING_INDEX.md
make help              # 查看可用命令
```

---

## 🏛️ 核心系统

| 系统 | 目录 | 一句话 |
|------|------|--------|
| 文档元层 | `0-系统文档管理/` | 文档的文档 — 在哪找、怎么写、怎么管 |
| 架构设计 | `1-ARCHITECTURE/` | 架构 SSoT v3.0（[SYSTEM_ARCHITECTURE_OVERVIEW.md](./1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md)） |
| 交易研究 | `6-TRADING/` | A0-A9 九步决策流水线 |
| 经典指标 | `10-经典指标系统/` | 核心交易决策引擎 |
| 易经推理 | `11-易经推理系统/` | BCRM + 易经推理 |
| 三屏趋势 | `12-三屏趋势系统/` | V4+波浪趋势策略 |
| 通用风控 | `13-通用风控模块/` | 三层风控体系 |
| V15 马丁 | `14-V15经典马丁策略/` | 马丁格尔策略（文档标杆） |
| 调控系统 | `16-调控系统/` | 宏观离场调控 |
| V4 波浪 | `17-v4-wave-strategy/` | V4 减半周期 + 艾略特波浪互斥融合 |

> 各子系统的工程索引、技术设计、API 规格、变更日志详见各自 `docs/` 目录，或通过 [SYSTEM_MAP.md](./0-系统文档管理/2-文档地图/SYSTEM_MAP.md) 导航。

---

## 🤝 贡献

请阅读 [CONTRIBUTING.md](./CONTRIBUTING.md) 了解贡献流程。

- 使用 Conventional Commits 提交规范
- 文档与代码在同一个 PR 中变更
- 新增文档必须从 [TEMPLATES/](./0-系统文档管理/1-规范体系/TEMPLATES/) 模板开始

---

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](./LICENSE) 文件了解详情。
