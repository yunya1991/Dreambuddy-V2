# {系统名称}

> 一句话描述系统定位

---

## 概述

（2-3 段描述系统的目标、核心能力、在 DreamBuddy-V2 中的角色）

---

## 目录结构

```
NN-系统名称/
├── docs/                        # 技术文档
│   ├── ENGINEERING_INDEX.md     # 工程索引
│   ├── TECHNICAL_DESIGN.md      # 技术设计
│   ├── API_SPEC.md              # 接口规格
│   └── CHANGELOG.md             # 变更日志
├── core/                        # 核心代码
├── lib/                         # 工具层
├── config/                      # 配置文件
├── tests/                       # 测试套件
└── README.md                    # 本文件
```

---

## 快速开始

### 1. 环境要求

- Python 3.9+
- 依赖：`pip install -r requirements.txt`

### 2. 配置

```bash
cp .env.example .env
# 编辑 .env 填入必要配置
```

### 3. 运行

```bash
python main.py
```

---

## 核心功能

| 功能 | 说明 | 入口 |
|------|------|------|
| 功能1 | 描述 | `func1()` |
| 功能2 | 描述 | `func2()` |

---

## 配置说明

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `KEY` | `value` | 描述 |

---

## 测试

```bash
python -m pytest tests/ -v
```

---

## FAQ

**Q: 常见问题1？**
A: 答案1。

---

## 相关文档

- [工程索引](./docs/ENGINEERING_INDEX.md) — 文件级索引
- [技术设计](./docs/TECHNICAL_DESIGN.md) — 架构设计
- [接口规格](./docs/API_SPEC.md) — API 文档
- [变更日志](./docs/CHANGELOG.md) — 版本历史
- [项目文档索引](../0-系统文档管理/INDEX.md) — 全项目导航

---

**维护者**: DreamBuddy v2
