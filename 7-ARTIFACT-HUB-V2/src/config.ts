import fs from "node:fs";
import path from "node:path";

export interface HubConfig {
  server: { host: string; port: number };
  paths: { artifacts_root: string; meta_root: string };
}

export function resolveRepoRoot(): string {
  return path.resolve(process.cwd(), "..");
}

export function loadConfig(repoRoot: string): HubConfig {
  const p = path.join(repoRoot, "dreambuddy", "config", "artifact-hub.config.json");
  const raw = fs.readFileSync(p, "utf-8");
  return JSON.parse(raw) as HubConfig;
}
