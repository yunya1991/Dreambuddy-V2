# 28-策略信号触发模块

> **端口**：8096 | **类型**：Flask 服务
> **定位**：代币筛选 + Freqtrade webhook 接收与路由

## 核心能力

1. **代币筛选**
   - Beta 范围过滤
   - 相关性阈值过滤
   - 聚类分组

2. **Freqtrade webhook 接收**
   - entry / exit / cancel / fill / status 事件
   - 路由到下游系统

## 边界说明

- **不含** Quant 信号（独立子系统）
- **不含** 三屏信号（独立子系统）

## 依赖

- 26-策略管理模块 — 查询策略 source_zip（可选 HTTP 调用）

## 目录结构

```
28-策略信号触发模块/
├── app.py                  # Flask 入口
├── signal_trigger/         # 信号触发核心
│   ├── freqtrade/          # Freqtrade webhook
│   │   └── webhook.py      # webhook 处理
│   └── universe/           # 标的筛选
│       └── screen.py       # 聚类筛选
├── tests/                  # 测试
└── data/                   # 数据
```

## 启动

```bash
python app.py
```

服务监听 `0.0.0.0:8096`。
