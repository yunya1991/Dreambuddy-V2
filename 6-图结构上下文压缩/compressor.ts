import {
  BlueprintGraph, ArchitectureGraph, ChronicleGraph,
  BNode, ANode, CNode, BEdge, AEdge, CEdge,
  NodeId, DataFlow, NodeMetadata, CompressionResult, ExpansionResult
} from './models';

function createDefaultMetadata(status: NodeMetadata['status'] = 'pending'): NodeMetadata {
  return {
    tokenCost: 0,
    latencyMs: 0,
    status,
    timestamp: Date.now(),
  };
}

function createDataFlow(type: string, description: string): DataFlow {
  return {
    type,
    schema: `${type}_v1`,
    description,
  };
}

export class ContextCompressor {
  private blueprints: Map<string, BlueprintGraph> = new Map();
  private architectures: Map<string, ArchitectureGraph> = new Map();
  private chronicles: Map<string, ChronicleGraph> = new Map();

  createBlueprint(name: string): BlueprintGraph {
    const id = `bp_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    
    const blueprint: BlueprintGraph = {
      id,
      name,
      version: '1.0.0',
      nodes: new Map(),
      edges: [],
      rootId: `bp_root`,
      createdAt: Date.now(),
    };

    const root: BNode = {
      id: blueprint.rootId,
      type: 'module',
      name: '量化分析系统',
      description: '完整的量化交易分析流程',
      metadata: createDefaultMetadata('completed'),
      children: [],
    };
    blueprint.nodes.set(root.id, root);

    const components: BNode[] = [
      {
        id: 'intent_engine',
        type: 'service',
        name: '意图识别引擎',
        description: '识别用户意图并分类',
        metadata: createDefaultMetadata('completed'),
      },
      {
        id: 'knowledge_base',
        type: 'service',
        name: '知识库检索',
        description: '检索相关知识和策略',
        metadata: createDefaultMetadata('completed'),
      },
      {
        id: 'market_data',
        type: 'service',
        name: '行情数据服务',
        description: '获取实时和历史行情数据',
        metadata: createDefaultMetadata('completed'),
      },
      {
        id: 'analysis_chain',
        type: 'module',
        name: '分析链',
        description: 'S1-S5 分析步骤',
        metadata: createDefaultMetadata('completed'),
        children: [],
      },
      {
        id: 'strategy_engine',
        type: 'service',
        name: '策略引擎',
        description: '策略生成和验证',
        metadata: createDefaultMetadata('completed'),
      },
      {
        id: 'report_generator',
        type: 'service',
        name: '报告生成器',
        description: '生成最终报告',
        metadata: createDefaultMetadata('completed'),
      },
    ];

    components.forEach(c => {
      blueprint.nodes.set(c.id, c);
      root.children!.push(c.id);
    });

    const edges: BEdge[] = [
      { source: root.id, target: 'intent_engine', dataFlow: createDataFlow('control', '触发意图识别') },
      { source: 'intent_engine', target: 'knowledge_base', dataFlow: createDataFlow('query', '意图驱动的知识检索') },
      { source: 'intent_engine', target: 'market_data', dataFlow: createDataFlow('query', '意图驱动的行情查询') },
      { source: 'intent_engine', target: 'analysis_chain', dataFlow: createDataFlow('control', '路由到分析链') },
      { source: 'knowledge_base', target: 'analysis_chain', dataFlow: createDataFlow('knowledge', '注入知识库数据') },
      { source: 'market_data', target: 'analysis_chain', dataFlow: createDataFlow('market', '注入行情数据') },
      { source: 'analysis_chain', target: 'strategy_engine', dataFlow: createDataFlow('analysis', '分析结果驱动策略') },
      { source: 'analysis_chain', target: 'report_generator', dataFlow: createDataFlow('result', '分析结果生成报告') },
      { source: 'strategy_engine', target: 'report_generator', dataFlow: createDataFlow('strategy', '策略建议生成报告') },
    ];

    blueprint.edges = edges;
    this.blueprints.set(id, blueprint);

    return blueprint;
  }

  expandToArchitecture(blueprintId: string): ArchitectureGraph {
    const blueprint = this.blueprints.get(blueprintId);
    if (!blueprint) throw new Error(`Blueprint not found: ${blueprintId}`);

    const id = `arch_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    
    const arch: ArchitectureGraph = {
      id,
      blueprintId,
      nodes: new Map(),
      edges: [],
      entryPoint: 'start',
      createdAt: Date.now(),
    };

    const entryNode: ANode = {
      id: 'start',
      type: 'step',
      name: '开始',
      parentNodeId: blueprint.rootId,
      metadata: createDefaultMetadata('completed'),
    };
    arch.nodes.set(entryNode.id, entryNode);

    const analysisChain = blueprint.nodes.get('analysis_chain');
    if (analysisChain) {
      const steps: ANode[] = [
        {
          id: 'S1_RESEARCH',
          type: 'step',
          name: 'S1 调研',
          parentNodeId: 'analysis_chain',
          metadata: createDefaultMetadata('pending'),
          requires: ['start'],
        },
        {
          id: 'S2_ANALYSIS',
          type: 'step',
          name: 'S2 分析',
          parentNodeId: 'analysis_chain',
          metadata: createDefaultMetadata('pending'),
          requires: ['S1_RESEARCH'],
        },
        {
          id: 'S3_DESIGN',
          type: 'step',
          name: 'S3 设计',
          parentNodeId: 'analysis_chain',
          metadata: createDefaultMetadata('pending'),
          requires: ['S2_ANALYSIS'],
        },
        {
          id: 'S4_VALIDATE',
          type: 'step',
          name: 'S4 验证',
          parentNodeId: 'analysis_chain',
          metadata: createDefaultMetadata('pending'),
          requires: ['S3_DESIGN'],
          branches: [
            { condition: '回测通过', target: 'S5_EXECUTE' },
            { condition: '回测失败', target: 'S3_DESIGN' },
          ],
        },
        {
          id: 'S5_EXECUTE',
          type: 'step',
          name: 'S5 执行',
          parentNodeId: 'analysis_chain',
          metadata: createDefaultMetadata('pending'),
          requires: ['S4_VALIDATE'],
        },
      ];

      steps.forEach(s => arch.nodes.set(s.id, s));
      analysisChain.children = steps.map(s => s.id);
    }

    const edges: AEdge[] = [
      { source: 'start', target: 'S1_RESEARCH', dataFlow: createDataFlow('control', '开始调研') },
      { source: 'S1_RESEARCH', target: 'S2_ANALYSIS', dataFlow: createDataFlow('research', '调研结果') },
      { source: 'S2_ANALYSIS', target: 'S3_DESIGN', dataFlow: createDataFlow('analysis', '分析结果') },
      { source: 'S3_DESIGN', target: 'S4_VALIDATE', dataFlow: createDataFlow('strategy', '策略设计') },
      { source: 'S4_VALIDATE', target: 'S5_EXECUTE', dataFlow: createDataFlow('validation', '验证结果') },
      { source: 'S4_VALIDATE', target: 'S3_DESIGN', dataFlow: createDataFlow('feedback', '失败反馈', true), isConditional: true },
    ];

    arch.edges = edges;
    this.architectures.set(id, arch);

    return arch;
  }

  expandToChronicle(architectureId: string, executionId: string): ChronicleGraph {
    const arch = this.architectures.get(architectureId);
    if (!arch) throw new Error(`Architecture not found: ${architectureId}`);

    const id = `chr_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    const chronicle: ChronicleGraph = {
      id,
      architectureId,
      nodes: new Map(),
      edges: [],
      executionId,
      startedAt: Date.now(),
    };

    const nodeOrder = ['start', 'S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'];
    let currentTime = Date.now();

    nodeOrder.forEach((nodeId, index) => {
      const archNode = arch.nodes.get(nodeId);
      if (!archNode) return;

      const startTime = currentTime;
      const latency = index === 0 ? 10 : 100 + Math.random() * 200;
      currentTime += latency;

      const cNode: CNode = {
        id: `${executionId}_${nodeId}`,
        architectureNodeId: nodeId,
        executionId,
        startTime,
        endTime: currentTime,
        metadata: {
          ...archNode.metadata,
          status: 'completed',
          tokenCost: index === 0 ? 0 : 500 + Math.random() * 800,
          latencyMs: latency,
          timestamp: startTime,
        },
        inputs: index === 0 ? {} : { [`input_from_${nodeOrder[index - 1]}`]: '...' },
        outputs: nodeId === 'S5_EXECUTE' ? { finalReport: '完整策略报告' } : { [`output_${nodeId}`]: '...' },
        logs: [`Step ${nodeId} executed successfully`],
      };

      chronicle.nodes.set(cNode.id, cNode);
    });

    for (let i = 0; i < nodeOrder.length - 1; i++) {
      const edge: CEdge = {
        source: `${executionId}_${nodeOrder[i]}`,
        target: `${executionId}_${nodeOrder[i + 1]}`,
        timestamp: currentTime,
        dataFlow: createDataFlow('execution', `从${nodeOrder[i]}到${nodeOrder[i + 1]}`),
        payloadSummary: `数据传递: ${nodeOrder[i]} → ${nodeOrder[i + 1]}`,
      };
      chronicle.edges.push(edge);
    }

    chronicle.completedAt = currentTime;
    this.chronicles.set(id, chronicle);

    return chronicle;
  }

  compress(chronicleId: string, targetCompressionRatio: number = 0.5): CompressionResult {
    const chronicle = this.chronicles.get(chronicleId);
    if (!chronicle) throw new Error(`Chronicle not found: ${chronicleId}`);

    const arch = this.architectures.get(chronicle.architectureId);
    const blueprint = this.blueprints.get(arch?.blueprintId || '');

    const originalSize = this.calculateGraphSize(chronicle);
    
    const compressedChronicle = this.createCompressedChronicle(chronicle, targetCompressionRatio);
    const compressedArchitecture = this.createCompressedArchitecture(arch!, chronicle);
    
    const compressedSize = this.calculateGraphSize(compressedChronicle);
    const compressionRatio = compressedSize / originalSize;

    const discardedDetails = this.findDiscardedDetails(chronicle, compressedChronicle);

    return {
      compressedChronicle,
      compressedArchitecture,
      blueprint: blueprint!,
      compressionRatio,
      retainedContext: (1 - compressionRatio) * 100,
      discardedDetails,
    };
  }

  private calculateGraphSize(graph: ChronicleGraph): number {
    let size = 0;
    graph.nodes.forEach(node => {
      size += JSON.stringify(node).length;
    });
    graph.edges.forEach(edge => {
      size += JSON.stringify(edge).length;
    });
    return size;
  }

  private createCompressedChronicle(chronicle: ChronicleGraph, targetRatio: number): ChronicleGraph {
    const compressed: ChronicleGraph = {
      ...chronicle,
      nodes: new Map(),
      edges: [],
    };

    const nodesArray = Array.from(chronicle.nodes.values());
    const nodesToKeep = Math.ceil(nodesArray.length * (1 - targetRatio));

    const sortedNodes = [...nodesArray].sort((a, b) => {
      const aCost = a.metadata.tokenCost + a.metadata.latencyMs;
      const bCost = b.metadata.tokenCost + b.metadata.latencyMs;
      return bCost - aCost;
    });

    const keepIds = new Set(sortedNodes.slice(0, nodesToKeep).map(n => n.id));

    chronicle.nodes.forEach((node, id) => {
      if (keepIds.has(id)) {
        const compressedNode: CNode = {
          ...node,
          inputs: node.metadata.status === 'completed' ? { summary: '已处理' } : {},
          outputs: node.metadata.status === 'completed' ? { summary: node.metadata.outputSummary || '已完成' } : {},
          logs: node.logs.slice(0, 1),
        };
        compressed.nodes.set(id, compressedNode);
      } else {
        const compressedNode: CNode = {
          ...node,
          metadata: {
            ...node.metadata,
            status: 'compressed',
            outputSummary: `[已压缩] ${node.name}`,
          },
          inputs: {},
          outputs: {},
          logs: [],
        };
        compressed.nodes.set(id, compressedNode);
      }
    });

    chronicle.edges.forEach(edge => {
      if (keepIds.has(edge.source) || keepIds.has(edge.target)) {
        compressed.edges.push(edge);
      }
    });

    return compressed;
  }

  private createCompressedArchitecture(arch: ArchitectureGraph, chronicle: ChronicleGraph): ArchitectureGraph {
    const compressed: ArchitectureGraph = {
      ...arch,
      nodes: new Map(),
      edges: [],
    };

    const completedNodes = new Set<string>();
    chronicle.nodes.forEach(node => {
      if (node.metadata.status === 'completed') {
        completedNodes.add(node.architectureNodeId);
      }
    });

    arch.nodes.forEach((node, id) => {
      if (completedNodes.has(id)) {
        compressed.nodes.set(id, node);
      }
    });

    arch.edges.forEach(edge => {
      if (completedNodes.has(edge.source) && completedNodes.has(edge.target)) {
        compressed.edges.push(edge);
      }
    });

    return compressed;
  }

  private findDiscardedDetails(original: ChronicleGraph, compressed: ChronicleGraph): { nodeId: string; reason: string }[] {
    const discarded: { nodeId: string; reason: string }[] = [];

    original.nodes.forEach((originalNode, id) => {
      const compressedNode = compressed.nodes.get(id);
      if (!compressedNode) return;

      const originalLogs = originalNode.logs.length;
      const compressedLogs = compressedNode.logs.length;
      const originalInputs = Object.keys(originalNode.inputs).length;
      const compressedInputs = Object.keys(compressedNode.inputs).length;
      const originalOutputs = Object.keys(originalNode.outputs).length;
      const compressedOutputs = Object.keys(compressedNode.outputs).length;

      const reasons: string[] = [];
      if (originalLogs > compressedLogs) reasons.push(`丢弃 ${originalLogs - compressedLogs} 条日志`);
      if (originalInputs > compressedInputs) reasons.push(`丢弃 ${originalInputs - compressedInputs} 个输入`);
      if (originalOutputs > compressedOutputs) reasons.push(`丢弃 ${originalOutputs - compressedOutputs} 个输出详情`);

      if (reasons.length > 0) {
        discarded.push({ nodeId: originalNode.architectureNodeId, reason: reasons.join('; ') });
      }
    });

    return discarded;
  }

  getBlueprint(id: string): BlueprintGraph | undefined {
    return this.blueprints.get(id);
  }

  getArchitecture(id: string): ArchitectureGraph | undefined {
    return this.architectures.get(id);
  }

  getChronicle(id: string): ChronicleGraph | undefined {
    return this.chronicles.get(id);
  }

  getAllBlueprints(): BlueprintGraph[] {
    return Array.from(this.blueprints.values());
  }

  getAllArchitectures(): ArchitectureGraph[] {
    return Array.from(this.architectures.values());
  }

  getAllChronicles(): ChronicleGraph[] {
    return Array.from(this.chronicles.values());
  }
}
