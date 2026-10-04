'use client';

import { GraphCompressionVisualizer, VisualizationData } from '@/components/features/graph-compression/GraphCompressionVisualizer';

// 构造真实感 mock 数据：dev 模式下无后端提供真实压缩数据
// B 层 Blueprint 架构 / A 层 Architecture DAG / C 层 Chronicle 执行
function buildMockData(): VisualizationData {
  const now = Date.now();
  const ts = (minAgo: number) => now - minAgo * 60 * 1000;

  const beforeB = [
    { id: 'B-001', name: '交易意图蓝图', layer: 'B' as const, score: 0.92, status: 'active' },
    { id: 'B-002', name: '风控约束图', layer: 'B' as const, score: 0.88, status: 'active' },
    { id: 'B-003', name: '部门编排策略', layer: 'B' as const, score: 0.45, status: 'stale' },
    { id: 'B-004', name: '遗留兼容层', layer: 'B' as const, score: 0.21, status: 'deprecated' },
    { id: 'B-005', name: '资产配置蓝图', layer: 'B' as const, score: 0.85, status: 'active' },
  ];
  const afterB = [
    { id: 'B-001', name: '交易意图蓝图', layer: 'B' as const, score: 0.92, compressed: false, status: 'active' },
    { id: 'B-002', name: '风控约束图', layer: 'B' as const, score: 0.88, compressed: false, status: 'active' },
    { id: 'B-005', name: '资产配置蓝图', layer: 'B' as const, score: 0.85, compressed: false, status: 'active' },
    { id: 'B-003', name: '部门编排策略', layer: 'B' as const, score: 0.45, compressed: true, status: 'stale' },
    { id: 'B-004', name: '遗留兼容层', layer: 'B' as const, score: 0.21, compressed: true, status: 'deprecated' },
  ];

  const beforeA = [
    { id: 'A-101', name: 'C-Drive 决策节点', layer: 'A' as const, score: 0.91, status: 'active' },
    { id: 'A-102', name: '信号聚合 DAG', layer: 'A' as const, score: 0.84, status: 'active' },
    { id: 'A-103', name: 'Reflector 校验', layer: 'A' as const, score: 0.79, status: 'active' },
    { id: 'A-104', name: '历史冗余分支', layer: 'A' as const, score: 0.18, status: 'stale' },
    { id: 'A-105', name: 'SUPPLEMENT 路由', layer: 'A' as const, score: 0.67, status: 'active' },
    { id: 'A-106', name: '废弃实验节点', layer: 'A' as const, score: 0.12, status: 'deprecated' },
    { id: 'A-107', name: 'BAC 压缩器', layer: 'A' as const, score: 0.73, status: 'active' },
    { id: 'A-108', name: '执行派发器', layer: 'A' as const, score: 0.86, status: 'active' },
  ];
  const afterA = [
    { id: 'A-101', name: 'C-Drive 决策节点', layer: 'A' as const, score: 0.91, compressed: false, status: 'active' },
    { id: 'A-102', name: '信号聚合 DAG', layer: 'A' as const, score: 0.84, compressed: false, status: 'active' },
    { id: 'A-103', name: 'Reflector 校验', layer: 'A' as const, score: 0.79, compressed: false, status: 'active' },
    { id: 'A-108', name: '执行派发器', layer: 'A' as const, score: 0.86, compressed: false, status: 'active' },
    { id: 'A-105', name: 'SUPPLEMENT 路由', layer: 'A' as const, score: 0.67, compressed: false, status: 'active' },
    { id: 'A-107', name: 'BAC 压缩器', layer: 'A' as const, score: 0.73, compressed: false, status: 'active' },
    { id: 'A-104', name: '历史冗余分支', layer: 'A' as const, score: 0.18, compressed: true, status: 'stale' },
    { id: 'A-106', name: '废弃实验节点', layer: 'A' as const, score: 0.12, compressed: true, status: 'deprecated' },
  ];

  const beforeC = [
    { id: 'C-201', name: '订单提交 #1024', layer: 'C' as const, score: 0.95, status: 'completed' },
    { id: 'C-202', name: '止损更新 #1025', layer: 'C' as const, score: 0.89, status: 'completed' },
    { id: 'C-203', name: '心跳日志 #1026', layer: 'C' as const, score: 0.15, status: 'noise' },
    { id: 'C-204', name: '仓位再平衡 #1027', layer: 'C' as const, score: 0.82, status: 'completed' },
    { id: 'C-205', name: '重复心跳 #1028', layer: 'C' as const, score: 0.10, status: 'noise' },
    { id: 'C-206', name: '信号快照 #1029', layer: 'C' as const, score: 0.77, status: 'completed' },
    { id: 'C-207', name: '调试事件 #1030', layer: 'C' as const, score: 0.08, status: 'noise' },
    { id: 'C-208', name: '风控审计 #1031', layer: 'C' as const, score: 0.91, status: 'completed' },
    { id: 'C-209', name: '冗余回放 #1032', layer: 'C' as const, score: 0.13, status: 'noise' },
    { id: 'C-210', name: '执行确认 #1033', layer: 'C' as const, score: 0.88, status: 'completed' },
    { id: 'C-211', name: '状态轮询 #1034', layer: 'C' as const, score: 0.19, status: 'noise' },
    { id: 'C-212', name: 'PnL 快照 #1035', layer: 'C' as const, score: 0.80, status: 'completed' },
  ];
  const afterC = [
    { id: 'C-201', name: '订单提交 #1024', layer: 'C' as const, score: 0.95, compressed: false, status: 'completed' },
    { id: 'C-202', name: '止损更新 #1025', layer: 'C' as const, score: 0.89, compressed: false, status: 'completed' },
    { id: 'C-204', name: '仓位再平衡 #1027', layer: 'C' as const, score: 0.82, compressed: false, status: 'completed' },
    { id: 'C-206', name: '信号快照 #1029', layer: 'C' as const, score: 0.77, compressed: false, status: 'completed' },
    { id: 'C-208', name: '风控审计 #1031', layer: 'C' as const, score: 0.91, compressed: false, status: 'completed' },
    { id: 'C-210', name: '执行确认 #1033', layer: 'C' as const, score: 0.88, compressed: false, status: 'completed' },
    { id: 'C-212', name: 'PnL 快照 #1035', layer: 'C' as const, score: 0.80, compressed: false, status: 'completed' },
    { id: 'C-203', name: '心跳日志 #1026', layer: 'C' as const, score: 0.15, compressed: true, status: 'noise' },
    { id: 'C-205', name: '重复心跳 #1028', layer: 'C' as const, score: 0.10, compressed: true, status: 'noise' },
    { id: 'C-207', name: '调试事件 #1030', layer: 'C' as const, score: 0.08, compressed: true, status: 'noise' },
    { id: 'C-209', name: '冗余回放 #1032', layer: 'C' as const, score: 0.13, compressed: true, status: 'noise' },
    { id: 'C-211', name: '状态轮询 #1034', layer: 'C' as const, score: 0.19, compressed: true, status: 'noise' },
  ];

  const retained = [
    'B-001', 'B-002', 'B-005',
    'A-101', 'A-102', 'A-103', 'A-105', 'A-107', 'A-108',
    'C-201', 'C-202', 'C-204', 'C-206', 'C-208', 'C-210', 'C-212',
  ];
  const compressed = [
    'B-003', 'B-004',
    'A-104', 'A-106',
    'C-203', 'C-205', 'C-207', 'C-209', 'C-211',
  ];
  const totalBefore = retained.length + compressed.length; // 25
  const totalAfter = retained.length; // 16

  return {
    before: {
      B: { nodes: beforeB },
      A: { nodes: beforeA },
      C: { nodes: beforeC },
    },
    after: {
      B: { nodes: afterB },
      A: { nodes: afterA },
      C: { nodes: afterC },
    },
    diff: {
      retained,
      compressed,
      compressionRatio: totalAfter / totalBefore,
      avgRetainedScore: 0.85,
      avgCompressedScore: 0.15,
    },
    stats: {
      totalNodesBefore: totalBefore,
      totalNodesAfter: totalAfter,
      nodesByLayerBefore: { B: beforeB.length, A: beforeA.length, C: beforeC.length },
      nodesByLayerAfter: {
        B: afterB.filter((n) => !n.compressed).length,
        A: afterA.filter((n) => !n.compressed).length,
        C: afterC.filter((n) => !n.compressed).length,
      },
      retainedContext: 0.92,
      compressionRatio: totalAfter / totalBefore,
    },
    timeline: [
      { id: 'C-201', name: '订单提交 #1024', kept: true, score: 0.95, status: 'completed', timestamp: ts(120) },
      { id: 'A-101', name: 'C-Drive 决策', kept: true, score: 0.91, status: 'active', timestamp: ts(118) },
      { id: 'C-208', name: '风控审计 #1031', kept: true, score: 0.91, status: 'completed', timestamp: ts(115) },
      { id: 'B-001', name: '交易意图蓝图', kept: true, score: 0.92, status: 'active', timestamp: ts(110) },
      { id: 'C-203', name: '心跳日志 #1026', kept: false, score: 0.15, status: 'noise', timestamp: ts(108) },
      { id: 'C-202', name: '止损更新 #1025', kept: true, score: 0.89, status: 'completed', timestamp: ts(105) },
      { id: 'A-104', name: '历史冗余分支', kept: false, score: 0.18, status: 'stale', timestamp: ts(102) },
      { id: 'C-204', name: '仓位再平衡 #1027', kept: true, score: 0.82, status: 'completed', timestamp: ts(98) },
      { id: 'C-205', name: '重复心跳 #1028', kept: false, score: 0.10, status: 'noise', timestamp: ts(95) },
      { id: 'B-003', name: '部门编排策略', kept: false, score: 0.45, status: 'stale', timestamp: ts(90) },
      { id: 'C-206', name: '信号快照 #1029', kept: true, score: 0.77, status: 'completed', timestamp: ts(85) },
      { id: 'A-106', name: '废弃实验节点', kept: false, score: 0.12, status: 'deprecated', timestamp: ts(80) },
    ],
    discarded: [
      { nodeId: 'C-203', reason: '心跳噪声，score < 阈值 0.30' },
      { nodeId: 'C-205', reason: '与 C-203 重复，去重压缩' },
      { nodeId: 'C-207', reason: '调试事件，无决策价值' },
      { nodeId: 'C-209', reason: '冗余回放，与历史快照重叠' },
      { nodeId: 'C-211', reason: '状态轮询噪声，score=0.19' },
      { nodeId: 'B-003', reason: '编排策略陈旧，已由 B-001 覆盖' },
      { nodeId: 'B-004', reason: '遗留兼容层已废弃，score=0.21' },
      { nodeId: 'A-104', reason: '历史冗余分支，无活跃引用' },
      { nodeId: 'A-106', reason: '废弃实验节点，score=0.12' },
    ],
  };
}

export default function GraphCompressionPage() {
  const mockData = buildMockData();

  return (
    <div className="px-6 py-4">
      <h1 className="text-xl font-bold text-white mb-1">图压缩</h1>
      <p className="text-xs text-slate-400 mb-4">
        B/A/C 三层图结构压缩可视化（开发模式：展示 mock 数据）
      </p>
      <GraphCompressionVisualizer data={mockData} />
    </div>
  );
}
