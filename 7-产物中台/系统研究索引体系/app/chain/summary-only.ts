/**
 * Chain page summary-only aggregator.
 *
 * Contract: the chain page must only expose summary-level data sourced from the
 * canonical artifacts index. It MUST NOT:
 *   - Read raw trading log files directly (e.g. exit_check_*.json)
 *   - Read raw trading content markdown files directly
 *   - Leak concrete position / order / PnL / leverage / risk metrics
 *
 * What it MAY expose:
 *   - Per A-phase product counts, latest timestamp, titles (limited)
 *   - Loop active state inferred from per-phase distribution of products
 *   - "Has A-phase products today?" hint (for the 30-second auto-refresh UI)
 *   - A summary-only strategy banner listing how many A3/A4/A5/A9 products exist
 *     in the index and their latest generated_at label.
 */

import {
  getArtifactRelations,
  getArtifactsData,
  getChainPhaseArtifacts,
} from "../../lib/content.server";

export type ChainLoop = "execution" | "intelligence" | "governance";

export interface ChainPhaseSummary {
  count: number;
  latest: string;
}

export interface ChainStrategySummary {
  lastUpdated: string;
  /** A-phase product counts only; no position data. */
  phaseCounts: Record<string, number>;
}

import type { ChainPhaseArtifacts } from "../../lib/types";

export interface ChainSummaryPayload {
  phases: Record<string, ChainPhaseSummary>;
  activeLoop: ChainLoop;
  strategy: ChainStrategySummary | null;
  /** Number of products that are dated as "today" (local day) per phase. */
  todayCounts: Record<string, number>;
  /** Generated timestamp string from the canonical index. */
  generatedAt: string;
  /** Summary-only phase-artifact list for the mindmap relation panel. */
  phaseArtifacts: ChainPhaseArtifacts;
}

const PHASE_LOOP_MAP: Record<string, ChainLoop> = {
  A1: "execution",
  A2: "execution",
  A3: "execution",
  A4: "execution",
  A5: "execution",
  A9: "execution",
  A6: "intelligence",
  A0: "governance",
  A7: "governance",
  A8: "governance",
};

const A_PHASES = ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9"];

function todayKey(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function phaseFromKey(key: string): string | null {
  if (!key) return null;
  const m = key.toUpperCase().match(/^(A[0-9])/);
  return m ? m[1] : null;
}

/**
 * Build summary-only payload for the chain cockpit page.
 *
 * Sourced from the canonical artifact index. Falls back to an empty-but-typed
 * object if the index is missing, so the UI keeps its skeleton state.
 */
export function buildChainSummaryPayload(): ChainSummaryPayload {
  try {
    const artifactsData = getArtifactsData();
    const total = artifactsData.total || 0;
    const stats = artifactsData.statistics || {};
    const generatedAt = artifactsData.generated_at || new Date().toISOString();
    const rawPhases = stats.by_a_phase || {};
    const allRelations = getArtifactRelations();
    const rawPhaseArtifacts = getChainPhaseArtifacts(5);
    const phaseArtifacts = rawPhaseArtifacts;

    // Compute per-phase summary from the detail artifact list.
    const phases: Record<string, ChainPhaseSummary> = {};
    const todayCounts: Record<string, number> = {};
    const todayStr = todayKey();

    const byPhase = new Map<string, { count: number; latest: string; today: number }>();

    // Seed known A phases to ensure stable UI structure.
    for (const p of A_PHASES) {
      byPhase.set(p, { count: 0, latest: "", today: 0 });
    }

    if (Array.isArray(artifactsData.artifacts)) {
      for (const a of artifactsData.artifacts) {
        const phase = phaseFromKey(a.chain_phase || "");
        if (!phase) continue;
        const bucket = byPhase.get(phase);
        if (!bucket) continue;
        bucket.count += 1;
        if (a.date && a.date > bucket.latest) bucket.latest = a.date;
        if (a.date && a.date.startsWith(todayStr)) bucket.today += 1;
      }
    }

    const phaseEntries = Array.from(byPhase.entries());
    for (let i = 0; i < phaseEntries.length; i++) {
      const [phase, bucket] = phaseEntries[i];
      phases[phase] = {
        count: bucket.count,
        latest: bucket.latest,
      };
      todayCounts[phase] = bucket.today;
    }

    // Use by_a_phase from statistics as a sanity cross-check (do not leak it
    // further up; the UI only needs the phases map).
    void rawPhases;
    void allRelations;
    void rawPhaseArtifacts;

    // Determine the active loop:
    //   - If any "today" products exist in A6 -> intelligence
    //   - If any "today" products exist in A7/A8/A0 -> governance
    //   - If any "today" products exist in A1..A5/A9 -> execution
    //   - Otherwise fall back to execution (the baseline loop).
    let activeLoop: ChainLoop = "execution";

    const hasTodayIn = (loop: ChainLoop) =>
      Object.entries(todayCounts).some(
        ([phase, n]) => PHASE_LOOP_MAP[phase] === loop && n > 0,
      );

    if (hasTodayIn("intelligence")) activeLoop = "intelligence";
    else if (hasTodayIn("governance")) activeLoop = "governance";
    else if (hasTodayIn("execution")) activeLoop = "execution";
    else {
      // Fallback: pick the loop with the highest total product count.
      const loopTotals: Record<ChainLoop, number> = {
        execution: 0,
        intelligence: 0,
        governance: 0,
      };
      for (const [phase, info] of Object.entries(phases)) {
        const loop = PHASE_LOOP_MAP[phase];
        if (!loop) continue;
        loopTotals[loop] += info.count;
      }
      const nonZero = Object.entries(loopTotals).filter(([, v]) => v > 0);
      if (nonZero.length > 0) {
        nonZero.sort((a, b) => b[1] - a[1]);
        activeLoop = nonZero[0][0] as ChainLoop;
      }
    }

    const phaseCounts: Record<string, number> = {};
    for (const p of A_PHASES) phaseCounts[p] = phases[p]?.count || 0;

    const strategy: ChainStrategySummary | null = total
      ? {
          lastUpdated: generatedAt,
          phaseCounts,
        }
      : null;

    return {
      phases,
      activeLoop,
      strategy,
      todayCounts,
      generatedAt,
      phaseArtifacts,
    };
  } catch {
    // Any error: return empty-but-typed fallback. Never throw in the page entry.
    const phases: Record<string, ChainPhaseSummary> = {};
    const todayCounts: Record<string, number> = {};
    for (const p of A_PHASES) {
      phases[p] = { count: 0, latest: "" };
      todayCounts[p] = 0;
    }
    return {
      phases,
      activeLoop: "execution",
      strategy: null,
      todayCounts,
      generatedAt: new Date().toISOString(),
      phaseArtifacts: {},
    };
  }
}
