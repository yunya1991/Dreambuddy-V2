# 中台设计文档索引

> **版本**: v1.0
> **更新日期**: 2026-05-16

---

## 📚 文档列表

### 1. 产物中台 (Artifact Hub)

| 文档 | 描述 | 状态 |
|------|------|------|
| [PRODUCT_HUB.md](./PRODUCT_HUB.md) | 产物中台基础设计 | ✅ 基础 |
| [PRODUCT_HUB_FULL.md](./PRODUCT_HUB_FULL.md) | 产物中台完整设计 | ✅ 完整 |
| [COMPANY_CENTRAL_HUB.md](./COMPANY_CENTRAL_HUB.md) | 公司中枢设计（六部门 + 六人董事会 + 双中台 + 双交易工作流） | ✅ 新增 |

### 2. 网关中台 (Gateway Hub)

| 文档 | 描述 | 状态 |
|------|------|------|
| [GATEWAY_HUB.md](./GATEWAY_HUB.md) | 网关中台设计 | ✅ 完成 |

### 3. 百炼集成 (Bailian Integration)

| 文档 | 描述 | 状态 |
|------|------|------|
| 百炼集成中心 | API调用/知识库/RAG配置 | 🔄 进行中 |

---

## 🏗️ 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    中台 / 公司中枢总览                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐      │
│   │  多前台入口  │    │   公司中枢   │    │   网关中台   │      │
│   │ Feed/Chain  │───▶│ Artifact Hub │◀───│   API Hub   │      │
│   │ Ops/Market  │    │     V2      │    │             │      │
│   └─────────────┘    └─────────────┘    └─────────────┘      │
│         │                  │                  │              │
│         └──────────────────┼──────────────────┘              │
│                            ▼                                  │
│              ┌─────────────────────────┐                      │
│              │   治理与执行中枢层       │                      │
│              │  • Route / Trace        │                      │
│              │  • Task / Result        │                      │
│              │  • Audit / Approval     │                      │
│              └─────────────────────────┘                      │
│                            │                                  │
│                            ▼                                  │
│              ┌─────────────────────────┐                      │
│              │      共享底座与集成        │                      │
│              │  • dreambuddy data      │                      │
│              │  • 外部模型/交易/API     │                      │
│              │  • 市场/运营/审计输入     │                      │
│              └─────────────────────────┘                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 📊 模块说明

### 产物中台 (Artifact Hub)

**核心功能**:
- 统一管理所有AI执行产物
- 产物投递验证与归档
- 邮件路由系统
- 跨部门交付物流转
- 正在升级为公司中枢的共享治理底座

**核心文件**:
- `7-ARTIFACT_HUB/artifact-alignment-manager/`（遗留路径，待迁移）
- `dreambuddy/artifacts/` - 产物存储
- `./COMPANY_CENTRAL_HUB.md` - 公司中枢设计

### 网关中台 (Gateway Hub)

**核心功能**:
- 用户认证与授权
- API配置管理
- 交易参数设置
- 积分系统

**核心文件**:
- `/3-FRONTEND/dream-universal-gateway/` - Next.js项目
- `src/stores/` - 状态管理
- `src/lib/` - 核心库

### 百炼集成中心

**核心功能**:
- 统一API调用管理
- 知识库构建
- RAG配置
- Function Calling

**核心文件**:
- `~/.workbuddy/skills/dream-bailian-integration/`

---

## 🔗 相关文档

- [前端设计](../前端设计/README.md)
- [治理系统](../../2-GOVERNANCE/README.md)
- [SKILL索引](../工作索引/SKILL_INDEX.md)
- [部门矩阵](../工作索引/DEPARTMENT_MATRIX.md)
- [公司中枢设计](./COMPANY_CENTRAL_HUB.md)
- [治理中枢化设计](../../docs/superpowers/specs/2026-05-16-artifact-hub-v2-governance-central-design.md)

---

## 🚀 快速链接

- [产物中台详细设计](./PRODUCT_HUB_FULL.md)
- [公司中枢设计](./COMPANY_CENTRAL_HUB.md)
- [网关中台设计](./GATEWAY_HUB.md)
- [工作索引](../工作索引/README.md)
