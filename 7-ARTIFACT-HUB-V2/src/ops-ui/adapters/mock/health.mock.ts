import type { HealthContractV1 } from "../healthAdapter.js";

export const mockHealth: HealthContractV1 = {
  service: "artifact-hub-v2",
  status: "ok",
  timestamp: "2026-05-16T00:00:00Z",
  dependencies: {
    artifact_hub: "ok",
    gateway: "unknown",
    meta_db: "ok",
  },
};
