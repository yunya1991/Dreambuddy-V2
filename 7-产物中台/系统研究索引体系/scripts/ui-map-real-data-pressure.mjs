// Offline data-layer pressure check for the five ui-map real-data adapters.
//
// Scope:
//   - buildSystemResearchUIMapOverride
//   - buildResearchChainUIMapOverride
//   - buildOperationsUIMapOverride
//   - buildStrategyUIMapOverride
//   - buildUserContextUIMapOverride
//
// This script does NOT start a Next.js dev server. It boots a temporary artifact
// index in the OS temp directory, publishes a few realtime events, and then
// exercises all five adapters in a tight loop to verify they stay deterministic
// and never throw across many invocations.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, "..");

// ---- Boot: temporary artifact index -----------------------------------------
const root = fs.mkdtempSync(path.join(os.tmpdir(), "ui-map-real-data-pressure-"));
const tradingDir = path.join(root, "trading");
fs.mkdirSync(tradingDir, { recursive: true });

const artifacts = [
  { artifact_id: "trading/s-001", title: "S1", department: "trading", type: "strategy", status: "completed", date: "2026-06-09T08:00:00Z", chain_phase: "A3", tags: ["signal"], filename: "s1.md" },
  { artifact_id: "trading/s-002", title: "S2", department: "trading", type: "strategy", status: "active", date: "2026-06-09T08:00:00Z", chain_phase: "A4", tags: ["signal"], filename: "s2.md" },
  { artifact_id: "trading/s-003", title: "S3", department: "trading", type: "strategy", status: "completed", date: "2026-06-09T08:00:00Z", chain_phase: "A4", tags: ["signal"], filename: "s3.md" },
  { artifact_id: "trading/r-001", title: "R1", department: "trading", type: "research", status: "active", date: "2026-06-08T08:00:00Z", chain_phase: "A5", tags: ["summary"], filename: "r1.md" },
  { artifact_id: "trading/r-002", title: "R2", department: "trading", type: "research", status: "completed", date: "2026-06-08T08:00:00Z", chain_phase: "A6", tags: ["summary"], filename: "r2.md" },
  { artifact_id: "trading/k-001", title: "K1", department: "knowledge", type: "knowledge", status: "active", date: "2026-06-10T08:00:00Z", chain_phase: "A2", tags: [], filename: "k1.md" },
];

fs.writeFileSync(
  path.join(tradingDir, "index.json"),
  JSON.stringify({ last_updated: "2026-06-09T08:00:00Z", artifacts }),
);

process.env.WORKBUDDY_ARTIFACTS_ROOT = root;

// ---- Boot: realtime hub events ----------------------------------------------
const { buildSystemResearchUIMapOverride, buildResearchChainUIMapOverride, buildOperationsUIMapOverride, buildStrategyUIMapOverride, buildUserContextUIMapOverride } = await import(path.join(PROJECT_ROOT, "lib/ui-map-real-data.ts"));
const { getRealtimeHub } = await import(path.join(PROJECT_ROOT, "lib/realtime-hub.ts"));

const hub = getRealtimeHub();
hub.publish("dream-agent", { level: "info", message: "agent-query-1" });
hub.publish("meeting", { level: "info", message: "meeting-start" });
hub.publish("system", { level: "info", message: "status-ping" });
hub.publish("meeting", { level: "info", message: "meeting-update" });

// ---- Pressure loop ---------------------------------------------------------
const ROUNDS = 200;
const results = {
  systemResearch: { calls: 0, nulls: 0, nonNulls: 0 },
  researchChain: { calls: 0, nulls: 0, nonNulls: 0 },
  operations: { calls: 0, nulls: 0, nonNulls: 0 },
  strategy: { calls: 0, nulls: 0, nonNulls: 0 },
  userContext: { calls: 0, nulls: 0, nonNulls: 0 },
};

const firstResults = {};

for (let round = 0; round < ROUNDS; round++) {
  const sr = buildSystemResearchUIMapOverride();
  const rc = buildResearchChainUIMapOverride();
  const op = buildOperationsUIMapOverride();
  const st = buildStrategyUIMapOverride();
  const uc = buildUserContextUIMapOverride();

  results.systemResearch.calls++;
  results.systemResearch[sr === null ? "nulls" : "nonNulls"]++;

  results.researchChain.calls++;
  results.researchChain[rc === null ? "nulls" : "nonNulls"]++;

  results.operations.calls++;
  results.operations[op === null ? "nulls" : "nonNulls"]++;

  results.strategy.calls++;
  results.strategy[st === null ? "nulls" : "nonNulls"]++;

  results.userContext.calls++;
  results.userContext[uc === null ? "nulls" : "nonNulls"]++;

  if (round === 0) {
    firstResults.systemResearch = sr;
    firstResults.researchChain = rc;
    firstResults.operations = op;
    firstResults.strategy = st;
    firstResults.userContext = uc;
  } else {
    // Determinism check: serialise to JSON and compare against round 0
    if (JSON.stringify(sr) !== JSON.stringify(firstResults.systemResearch)) {
      throw new Error(`buildSystemResearchUIMapOverride non-deterministic at round ${round}`);
    }
    if (JSON.stringify(rc) !== JSON.stringify(firstResults.researchChain)) {
      throw new Error(`buildResearchChainUIMapOverride non-deterministic at round ${round}`);
    }
    if (JSON.stringify(op) !== JSON.stringify(firstResults.operations)) {
      throw new Error(`buildOperationsUIMapOverride non-deterministic at round ${round}`);
    }
    if (JSON.stringify(st) !== JSON.stringify(firstResults.strategy)) {
      throw new Error(`buildStrategyUIMapOverride non-deterministic at round ${round}`);
    }
    if (JSON.stringify(uc) !== JSON.stringify(firstResults.userContext)) {
      throw new Error(`buildUserContextUIMapOverride non-deterministic at round ${round}`);
    }
  }
}

// ---- Assertions -------------------------------------------------------------
const requiredNonNull = ["systemResearch", "researchChain", "operations", "strategy", "userContext"];
for (const name of requiredNonNull) {
  if (results[name].nulls > 0) {
    throw new Error(`${name} unexpectedly returned null ${results[name].nulls} / ${results[name].calls} times`);
  }
  if (results[name].nonNulls !== ROUNDS) {
    throw new Error(`${name} nonNulls=${results[name].nonNulls} !== ROUNDS=${ROUNDS}`);
  }
}

// Sanity: strategy summary-only text must NOT leak sensitive config
const strategyOverride = firstResults.strategy;
if (!strategyOverride || !strategyOverride.convergenceLabel || !strategyOverride.convergenceLabel.includes("summary-only")) {
  throw new Error("buildStrategyUIMapOverride missing summary-only label");
}

// Sanity: user-context summary-only text must NOT leak sensitive config
const userContextOverride = firstResults.userContext;
if (!userContextOverride || !userContextOverride.description.includes("summary-only")) {
  throw new Error("buildUserContextUIMapOverride missing summary-only label");
}
if (!userContextOverride.summaryNote || !userContextOverride.summaryNote.includes("未透出")) {
  throw new Error("buildUserContextUIMapOverride missing summary-only disclaimer");
}

console.log(`ui-map real-data pressure ok (${ROUNDS} rounds × 5 adapters)`);
console.log(JSON.stringify(results, null, 2));

// ---- Teardown ---------------------------------------------------------------
delete process.env.WORKBUDDY_ARTIFACTS_ROOT;
fs.rmSync(root, { recursive: true, force: true });
