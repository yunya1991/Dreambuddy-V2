# 三屏趋势系统 - 工程索引

## 1. 概述

三屏趋势系统（Three-Screen Trend System）是基于 Alexander Elder 三重屏幕交易系统理论构建的趋势分析引擎，用于识别跨时间框架的趋势一致性，为交易决策提供趋势过滤信号。

### 1.1 核心定位

| 属性 | 说明 |
|------|------|
| 系统名称 | 三屏趋势系统 |
| 目录位置 | `12-三屏趋势系统/` |
| 主入口 | `engine.py` |
| 核心模块 | `core/` |
| 依赖系统 | 经典指标系统（10）、通用风控模块（13） |

### 1.2 功能概览

- 多时间框架趋势分析（周线/日线/4小时线）
- 趋势一致性判断
- 动态权重调整
- 信号融合与过滤
- 与经典指标系统的桥接集成

## 2. 目录结构

```
12-三屏趋势系统/
├── core/                    # 核心业务逻辑
│   ├── __init__.py
│   ├── config.py            # 配置管理
│   ├── dynamic_weights.py   # 动态权重计算
│   ├── fusion.py            # 信号融合
│   ├── indicators.py        # 指标计算
│   └── trend_consistency.py # 趋势一致性判断
├── data/                    # 数据层
│   ├── __init__.py
│   ├── fundamental_data.py  # 基本面数据
│   └── market_data.py       # 市场数据
├── docs/                    # 文档
│   ├── ENGINEERING_INDEX.md # 工程索引（本文档）
│   └── TECHNICAL_DESIGN.md  # 技术设计文档
├── tests/                   # 测试
│   ├── __init__.py
│   └── test_core.py         # 核心模块测试
├── classic_bridge.py        # 与经典指标系统的桥接
├── engine.py                # 主引擎
├── exit_integration.py      # 退出系统集成
├── signals.py               # 信号生成
├── ENGINEERING_INDEX.md     # 旧版工程索引（保留兼容）
├── README.md
└── __init__.py
```

## 3. 关键文件说明

### 3.1 核心模块

| 文件 | 功能说明 |
|------|----------|
| `core/config.py` | 配置加载与验证 |
| `core/dynamic_weights.py` | 基于趋势强度的动态权重调整 |
| `core/fusion.py` | 多信号融合算法 |
| `core/indicators.py` | 技术指标计算（MA、EMA、MACD等） |
| `core/trend_consistency.py` | 三屏趋势一致性判断核心逻辑 |

### 3.2 数据层

| 文件 | 功能说明 |
|------|----------|
| `data/market_data.py` | 市场行情数据获取与缓存 |
| `data/fundamental_data.py` | 基本面数据集成 |

### 3.3 集成模块

| 文件 | 功能说明 |
|------|----------|
| `classic_bridge.py` | 与经典指标系统的桥接接口 |
| `exit_integration.py` | 退出系统集成点 |
| `signals.py` | 信号生成与输出 |

## 4. 依赖关系

### 4.1 外部依赖

| 依赖 | 版本要求 | 用途 |
|------|----------|------|
| pandas | >=1.5.0 | 数据处理 |
| numpy | >=1.21.0 | 数值计算 |
| talib | >=0.4.0 | 技术指标计算 |
| requests | >=2.28.0 | HTTP请求 |

### 4.2 内部依赖

| 系统 | 依赖方式 | 用途 |
|------|----------|------|
| 10-经典指标系统 | 桥接调用 | 获取候选币种列表、信号验证 |
| 13-通用风控模块 | 接口调用 | 风控评估、退出决策 |

## 5. 配置管理

### 5.1 配置文件

配置通过 `core/config.py` 加载，支持以下配置项：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| SCREEN1_WINDOW | 50 | 周线EMA窗口 |
| SCREEN2_WINDOW | 20 | 日线EMA窗口 |
| SCREEN3_WINDOW | 13 | 4小时线EMA窗口 |
| TREND_THRESHOLD | 0.3 | 趋势强度阈值 |
| CONSISTENCY_THRESHOLD | 0.7 | 趋势一致性阈值 |

### 5.2 环境变量

暂无环境变量配置，使用默认配置即可运行。

## 6. 部署与运行

### 6.1 启动方式

```bash
# 直接运行引擎
python engine.py

# 通过经典指标系统调用
python classic_bridge.py
```

### 6.2 运行模式

- **实时模式**：实时获取行情数据，输出趋势信号
- **回测模式**：基于历史数据进行趋势分析验证

## 7. 测试体系

### 7.1 测试文件

| 文件 | 测试内容 |
|------|----------|
| `tests/test_core.py` | 核心模块单元测试 |

### 7.2 测试命令

```bash
python -m pytest tests/ -v
```

## 8. 快速导航

| 目标 | 路径 |
|------|------|
| 技术设计文档 | `docs/TECHNICAL_DESIGN.md` |
| 主引擎入口 | `engine.py` |
| 趋势一致性核心 | `core/trend_consistency.py` |
| 信号融合 | `core/fusion.py` |
| 单元测试 | `tests/test_core.py` |

## 9. 技术债务

| 债务项 | 严重程度 | 说明 |
|--------|----------|------|
| 缺少 API 文档 | 中 | 需要补充接口规范文档 |
| 缺少性能测试 | 低 | 需要补充压力测试 |
| 配置分散 | 中 | 配置项分散在多个文件 |
| 与V15系统接口不一致 | 高 | 需要统一接口规范 |

---

**文档版本**: v1.0  
**最后更新**: 2026-07-13