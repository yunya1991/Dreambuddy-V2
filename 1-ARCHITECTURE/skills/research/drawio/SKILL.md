---
name: drawio
description: Generate draw.io diagrams (architecture, flow, data flow) as editable .drawio files with optional PNG/SVG/PDF export
version: 1.0.0
created: 2026-10-05
updated: 2026-10-05
license: Apache-2.0
status: active
category: tooling
domain: 1-ARCHITECTURE
triggers:
  - drawio
  - 架构图
  - 流程图
  - 数据流图
  - diagram
  - architecture diagram
  - flow chart
depends_on: []
provides:
  - diagram-generation
  - architecture-visualization
cognitive_links: []
---

# drawio Skill — draw.io 图表生成

> 基于 jgraph/drawio-mcp 官方 Assistant Plugin 适配。生成可编辑的 `.drawio` 文件，支持可选 PNG/SVG/PDF 导出或浏览器 URL 打开。

## 何时调用

满足以下任一条件：
1. 需要生成系统架构图、流程图、数据流图、UML 图等可视化图表
2. 需要将架构设计/流程描述转化为可编辑的图表文件
3. 需要 publication-grade 的技术图表用于文档或报告

## 核心能力

### 1. 生成 .drawio 文件
- 输出原生 draw.io XML 格式的 `.drawio` 文件
- 文件可在 draw.io Desktop 或 app.diagrams.net 中直接编辑
- 支持所有 draw.io 形状库（AWS/Azure/GCP/UML/BPMN/网络等）

### 2. 可选导出格式
- **PNG/SVG/PDF**：通过 draw.io Desktop CLI 导出（`which drawio` 检测）
  - 使用 `--embed-diagram` 参数确保导出文件仍可在 draw.io 中编辑
- **浏览器 URL**：压缩 XML 后打开 `app.diagrams.net`（无需 draw.io Desktop）

### 3. 自动布局
- **ELK 自动布局**：分层布局，自动路由边
- **libavoid 路由**：保持节点位置，正交路由连接线

## 使用方式

### 生成架构图示例
```
请用 drawio 生成一个系统架构图，包含以下组件：
- DreamOS 内核（intent_engine, graph_planner, graph_executor, graph_store）
- 交易能力层（经典指标系统, 四大子交易系统）
- 基础能力层（知识库, 认知系统, 索引, 数据库）
- 用箭头表示调用关系
```

### 生成流程图示例
```
请用 drawio 生成一个策略开发流程图：
策略选题 → 文献调研 → 假设提出 → 回测验证 → 统计审查 → 同行评审 → 上线
```

## 输出规范

1. **文件路径**：`.drawio` 文件保存到用户指定目录或当前工作目录
2. **XML 格式**：合法的 draw.io mxGraphModel XML
3. **形状使用**：优先使用标准 UML/架构形状库
4. **布局**：使用 ELK 或 libavoid 自动布局，避免重叠
5. **导出**：如用户要求 PNG/SVG/PDF，检测 draw.io Desktop 是否可用

## 约束

- 不向云端发送图表数据（所有处理本地完成）
- 不调用 `convert.diagrams.net` 等云服务
- draw.io Desktop 不可用时，仅保留 `.drawio` 文件，不强制导出
- 图表 XML 必须是合法的 mxGraphModel 格式

## 与 dreambuddy-v2 集成

- 服务于策略架构文档、系统设计文档、回测流程可视化
- 与 `dream-science-framework-research` 协同：框架研究产出用 drawio 可视化
- 与 `dream-science-literature-review` 协同：综述流程图用 drawio 生成

## 许可证

Apache License 2.0（源自 jgraph/drawio-mcp）
