/**
 * 门禁机器预审编排：Qwen（主）+ JEV（副）异构会签。
 *
 * 只产出「预审意见」，不写入门禁状态；high / critical 门仍需人工确认。
 */

import type { TaskBoardSnapshot, TaskGate } from "@/types/task-board";
import { getModelRegistry, type ModelSpec } from "@/lib/model/model-registry";
import { createGateCaller, loadGateClientConfig } from "@/lib/model/gate-client";
import { createJevCaller, loadJevClientConfig } from "@/lib/model/jev-client";
import {
  runGatePrecheck,
  type GateModelCaller,
  type GatePrecheckInput,
  type GateVerdict,
} from "./gate-model";
import { combineGateVotes, type GateVote, type QuorumResult } from "./gate-quorum";
import { resolveGatePolicy } from "./gate-policy";
import { appendGateAudit } from "./gate-audit";

export interface GatePrecheckOutcome {
  gate_id: string;
  kind: TaskGate["kind"];
  evidence_ref: string;
  verdict: GateVerdict;
  quorum: QuorumResult;
  evidence_digest: Record<string, unknown>;
}

function clip(text: string | undefined, max = 400): string {
  if (!text) return "";
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

/** 只发送结构化摘要，不发送原始行情、持仓或完整推理链 */
export function buildEvidenceDigest(
  snapshot: TaskBoardSnapshot,
  gate: TaskGate,
): Record<string, unknown> {
  return {
    task_id: snapshot.task_id,
    gate_kind: gate.kind,
    evidence_ref: gate.evidence_ref,
    objective: snapshot.objective
      ? {
          title: snapshot.objective.title,
          progress: snapshot.objective.progress,
          confidence_threshold: snapshot.objective.confidence_threshold,
        }
      : null,
    krs: snapshot.krs.map((kr) => ({
      node_id: kr.node_id,
      criteria: clip(kr.criteria, 200),
      verify: kr.verify,
      verdict: kr.verdict,
      evidence_count: kr.evidence_count,
    })),
    agents: snapshot.agents.map((agent) => ({
      role: agent.role,
      state: agent.state,
      evidence_count: agent.evidence_count,
      summary: clip(agent.summary, 200),
    })),
    acceptance: snapshot.acceptance.map((item) => ({
      role: item.role,
      node_id: item.node_id,
      verdict: item.verdict,
      reason: clip(item.reason, 200),
      evidence_count: item.evidence_refs.length,
    })),
    summary: snapshot.summary
      ? {
          conclusion: clip(snapshot.summary.conclusion),
          key_points: snapshot.summary.key_points.map((point) => clip(point, 120)),
          confidence: snapshot.summary.confidence ?? null,
        }
      : null,
    missing: (snapshot.summary?.data_quality ?? []).map((item) => ({
      item: item.item,
      status: item.status,
    })),
  };
}

async function runVote(
  spec: ModelSpec,
  caller: GateModelCaller,
  input: GatePrecheckInput,
): Promise<GateVote> {
  const started = Date.now();
  const verdict = await runGatePrecheck(input, {
    caller,
    modelId: spec.id,
  });
  return {
    model_id: spec.id,
    provider: spec.provider,
    family: spec.family,
    verdict: verdict.verdict,
    confidence: verdict.confidence,
    latency_ms: Date.now() - started,
    degraded: verdict.degraded,
  };
}

export async function precheckGate(
  snapshot: TaskBoardSnapshot,
  gate: TaskGate,
): Promise<GatePrecheckOutcome> {
  const evidence = buildEvidenceDigest(snapshot, gate);
  const input: GatePrecheckInput = {
    gate_kind: gate.kind,
    evidence_ref: gate.evidence_ref,
    evidence,
  };

  const registry = getModelRegistry();
  const tasks: Array<Promise<GateVote>> = [];

  const qwenConfig = loadGateClientConfig();
  if (qwenConfig && registry.gate) {
    tasks.push(
      runVote(registry.gate, createGateCaller(qwenConfig), input),
    );
  }

  const jevConfig = loadJevClientConfig();
  if (jevConfig && registry.gate_secondary) {
    tasks.push(
      runVote(registry.gate_secondary, createJevCaller(jevConfig), input),
    );
  }

  const votes = await Promise.all(tasks);
  const risk = gate.kind === "acceptance" ? "high" : "medium";
  const policy = resolveGatePolicy(gate.kind, risk);
  const quorum = combineGateVotes(votes, {
    quorum: policy.gate_model.quorum,
    minDistinctModels: policy.gate_model.min_distinct_models,
    requireDistinctFamilies: policy.gate_model.deny_same_family,
  });

  const outcome: GatePrecheckOutcome = {
    gate_id: gate.gate_id,
    kind: gate.kind,
    evidence_ref: gate.evidence_ref,
    verdict: quorum.verdict,
    quorum,
    evidence_digest: evidence,
  };

  await appendGateAudit({
    ts: Date.now(),
    task_id: snapshot.task_id,
    gate_id: gate.gate_id,
    evidence_ref: gate.evidence_ref,
    verdict: quorum.verdict,
    votes: quorum.votes.map((vote) => ({
      model_id: vote.model_id,
      family: vote.family,
      verdict: vote.verdict,
      confidence: vote.confidence,
      latency_ms: vote.latency_ms,
      degraded: vote.degraded,
    })),
    reasons: quorum.reasons,
  });

  return outcome;
}
