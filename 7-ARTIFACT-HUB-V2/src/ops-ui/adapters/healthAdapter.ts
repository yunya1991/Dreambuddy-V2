// Strictly typed against health-summary.v1 (L1 frozen, owner: solo)

export interface HealthContractV1 {
  service: string;
  status: "ok" | "degraded" | "error";
  timestamp: string;
  dependencies: {
    artifact_hub: "ok" | "degraded" | "error" | "unknown";
    gateway: "ok" | "degraded" | "error" | "unknown";
    meta_db: "ok" | "degraded" | "error" | "unknown";
  };
}

export interface HealthViewModel {
  service: string;
  status: "ok" | "degraded" | "error";
  timestamp: string;
  dependencyList: Array<{
    name: string;
    status: "ok" | "degraded" | "error" | "unknown";
  }>;
}

export function toHealthViewModel(data: HealthContractV1): HealthViewModel {
  return {
    service: data.service,
    status: data.status,
    timestamp: data.timestamp,
    dependencyList: Object.entries(data.dependencies).map(([name, status]) => ({
      name,
      status,
    })),
  };
}
