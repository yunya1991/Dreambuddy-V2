/**
 * Chain page: A-series three-loop cockpit.
 *
 * Data contract (enforced by `summary-only.ts`):
 *   - Sourced from the canonical artifact index ONLY.
 *   - No direct reading of raw trading logs (exit_check_*.json).
 *   - No direct reading of raw trading markdown files.
 *   - No PnL / leverage / position-size / risk-score numbers leak into the UI.
 */

import ChainMindmap from "./ChainMindmap";
import type { StrategySummary } from "./types";
import { buildChainSummaryPayload } from "./summary-only";

export default function ChainPage({
  searchParams,
}: {
  searchParams?: { phase?: string; artifact?: string };
}) {
  const payload = buildChainSummaryPayload();

  // Transform summary-only data into the Shape the Mindmap was designed to
  // consume, but without the concrete tactical/execution numbers.
  //
  // Each phase now only receives:
  //   - count: number of products currently in that phase
  //   - latest: latest product date string in that phase
  const phases: Record<string, { count: number; latest: string }> = {};
  for (const [phase, info] of Object.entries(payload.phases)) {
    phases[phase] = {
      count: info.count,
      latest: info.latest || "",
    };
  }

  // Build a "strategy" object that only exposes phase-level counts, not the
  // specific contents of each strategy output. This keeps the cockpit page
  // aligned with the summary-only contract.
  const strategy: StrategySummary | null = payload.strategy
    ? {
        lastUpdated: payload.strategy.lastUpdated,
        a3: buildPhaseBanner("A3", payload.strategy.phaseCounts),
        a4: buildPhaseBanner("A4", payload.strategy.phaseCounts),
        a5: buildPhaseBanner("A5", payload.strategy.phaseCounts),
        a9: buildPhaseBanner("A9", payload.strategy.phaseCounts),
      }
    : null;

  return (
    <ChainMindmap
      phases={phases}
      activeLoop={payload.activeLoop}
      strategy={strategy}
      orgData={null}
      phaseArtifacts={payload.phaseArtifacts}
      focusPhase={searchParams?.phase}
      focusArtifactId={searchParams?.artifact}
    />
  );
}

/**
 * Return a lightweight, summary-only banner record for a given A-phase.
 *
 * `confidence` / `direction` / `decision` / `riskLevel` are intentionally
 * replaced by static strings so no concrete trading signal leaks out of this
 * page. The dynamic values are strictly `timestamp` (latest product date) and
 * `source` (product count label).
 */
function buildPhaseBanner(
  phase: string,
  phaseCounts: Record<string, number>,
) {
  const count = phaseCounts[phase] ?? 0;
  if (!count) return undefined;
  return {
    regime: `产物沉淀 ${count}`,
    confidence: undefined,
    direction: "summary-only",
    scenario: "summary-only",
    timestamp: "",
    source: `来源: canonical index / ${phase}`,
  };
}
