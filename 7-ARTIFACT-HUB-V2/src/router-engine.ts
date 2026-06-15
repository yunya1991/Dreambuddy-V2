import crypto from "node:crypto";
import type { ArtifactIndexItem, Intent, RoutingPlan } from "./types.js";

export type DecisionLevel = "L1" | "L2" | "L3";

export interface DecisionLevelConfig {
  level: DecisionLevel;
  label: string;
  description: string;
  requires_board_approval: boolean;
  auto_threshold: number; // 风险/金额阈值
}

// Decision Level thresholds
const DECISION_LEVELS: DecisionLevelConfig[] = [
  {
    level: "L1",
    label: "快速通道",
    description: "简单查询/直接返回已有产物，无需审批",
    requires_board_approval: false,
    auto_threshold: 0,
  },
  {
    level: "L2",
    label: "标准通道",
    description: "需要执行工作流，部门内审批即可",
    requires_board_approval: false,
    auto_threshold: 10000, // $10k
  },
  {
    level: "L3",
    label: "董事会通道",
    description: "高风险/重大决策，需要董事会审批",
    requires_board_approval: true,
    auto_threshold: 100000, // $100k
  },
];

export class RouterEngine {
  /**
   * Determine decision level based on intent analysis
   */
  classifyDecisionLevel(intent: Intent): DecisionLevel {
    const text = intent.text?.toLowerCase() ?? "";
    const domain = intent.domain?.toLowerCase() ?? "";

    // High-risk keywords → L3
    const highRiskKeywords = [
      "删除", "撤销", "回滚", "rollback",
      "删除", "关停", "暂停", "suspend",
      "大量", "全部", "所有", "all",
      "紧急", "立即", "现在", "now",
      "风险", "风险", "risk",
    ];

    // Medium-risk keywords → L2
    const mediumRiskKeywords = [
      "执行", "交易", "下单", "开仓",
      "平仓", "策略", "策略", "strategy",
      "创建", "新建", "添加", "add",
      "修改", "更新", "变更", "change",
    ];

    for (const kw of highRiskKeywords) {
      if (text.includes(kw) || domain.includes(kw)) {
        return "L3";
      }
    }

    for (const kw of mediumRiskKeywords) {
      if (text.includes(kw) || domain.includes(kw)) {
        return "L2";
      }
    }

    // Check intent risk_score if available
    if (typeof intent.risk_score === "number" && intent.risk_score >= 0.7) {
      return "L3";
    }
    if (typeof intent.risk_score === "number" && intent.risk_score >= 0.3) {
      return "L2";
    }

    return "L1";
  }

  /**
   * Get decision level config
   */
  getDecisionLevelConfig(level: DecisionLevel): DecisionLevelConfig {
    return DECISION_LEVELS.find(l => l.level === level) ?? DECISION_LEVELS[0];
  }

  decide(intent: Intent, artifacts: ArtifactIndexItem[]): RoutingPlan {
    const traceId = crypto.randomUUID();
    const hasAny = artifacts.length > 0;
    const mode = hasAny ? "DIRECT_RETURN" : "RUN_CHAIN";
    const decisionLevel = this.classifyDecisionLevel(intent);
    const levelConfig = this.getDecisionLevelConfig(decisionLevel);

    const nodes = [
      {
        node_id: "n1",
        type: "intent_recognition",
        status: "success",
        inputs: [{ kind: "text", ref: "intent", summary: intent.text }],
        outputs: [{ kind: "text", ref: "intent_struct" }],
        evidence: [{ kind: "rule", detail: "v0: pass-through intent" }]
      },
      {
        node_id: "n2",
        type: "decision_level_classifier",
        status: "success",
        inputs: [{ kind: "text", ref: "intent_struct" }],
        outputs: [{ kind: "text", ref: "decision_level", summary: decisionLevel }],
        evidence: [{ kind: "rule", detail: `level=${decisionLevel}: ${levelConfig.label}` }]
      },
      {
        node_id: "n3",
        type: "artifact_retrieval",
        status: "success",
        inputs: [{ kind: "text", ref: "intent_struct" }],
        outputs: [{ kind: "text", ref: "artifact_candidates", summary: String(artifacts.length) }],
        evidence: [{ kind: "rule", detail: "v0: load full index.json (no filtering yet)" }]
      },
      {
        node_id: "n4",
        type: "artifact_scoring",
        status: "success",
        inputs: [{ kind: "text", ref: "artifact_candidates" }],
        outputs: [{ kind: "text", ref: "artifact_score" }],
        evidence: [{ kind: "score", detail: `v0: hasAny=${String(hasAny)}` }]
      },
      {
        node_id: "n5",
        type: "policy_gate",
        status: "success",
        inputs: [{ kind: "text", ref: "artifact_score" }],
        outputs: [{ kind: "text", ref: "route_mode", summary: mode }],
        evidence: [{ kind: "rule", detail: "v0: DIRECT_RETURN if any artifact exists else RUN_CHAIN" }]
      }
    ] as any;

    return {
      trace_id: traceId,
      mode,
      reason: { 
        has_any_artifact: hasAny, 
        count: artifacts.length,
        decision_level: decisionLevel,
        requires_approval: levelConfig.requires_board_approval,
      },
      dag: {
        nodes,
        edges: [
          { from: "n1", to: "n2" },
          { from: "n2", to: "n3" },
          { from: "n3", to: "n4" },
          { from: "n4", to: "n5" }
        ]
      }
    };
  }
}

