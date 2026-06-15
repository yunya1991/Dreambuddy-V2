import fs from "node:fs";
import path from "node:path";
import { CATEGORY_TO_DEPARTMENT } from "./category.js";
import type { ArtifactIndexItem } from "./types.js";

const A_PHASE_REGEX = /^A([0-9])$/i;

function extractAPhase(filename: string, chainPhase?: string): string {
  if (chainPhase && A_PHASE_REGEX.test(chainPhase.toUpperCase())) return chainPhase.toUpperCase();
  const match = filename.match(/A([0-9])/i);
  if (match) return `A${match[1]}`;
  return chainPhase || "";
}

function cleanExcerpt(input: string): string {
  return input
    .replace(/^#+\s+/gm, "")
    .replace(/[\r\n]+/g, " ")
    .replace(/\*+/g, "")
    .replace(/`[^`]*`/g, "")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/<[^>]*>/g, "")
    .replace(/\|/g, " ")
    .replace(/-+/g, " ")
    .replace(/\s{2,}/g, " ")
    .trim()
    .slice(0, 200);
}

function safeReadJson(p: string): unknown | null {
  try {
    return JSON.parse(fs.readFileSync(p, "utf-8"));
  } catch {
    return null;
  }
}

export class ArtifactStore {
  constructor(private readonly artifactsRoot: string) {}

  getArtifactsIndex(): ArtifactIndexItem[] {
    if (!fs.existsSync(this.artifactsRoot)) return [];

    const categories = fs.readdirSync(this.artifactsRoot).filter((f) => {
      const fp = path.join(this.artifactsRoot, f);
      return fs.statSync(fp).isDirectory() && !f.startsWith(".");
    });

    const index: ArtifactIndexItem[] = [];

    for (const category of categories) {
      if (category === "tasks" || category === "results") continue;

      const catDir = path.join(this.artifactsRoot, category);
      const department = CATEGORY_TO_DEPARTMENT[category] || "knowledge";
      const indexFile = path.join(catDir, "index.json");

      const parsed = safeReadJson(indexFile);
      if (!parsed) continue;

      const data = parsed as any;
      const items: any[] = Array.isArray(data) ? data : (Array.isArray(data.artifacts) ? data.artifacts : []);
      const lastUpdated = typeof data.last_updated === "string" ? data.last_updated : new Date().toISOString();

      for (const item of items) {
        const rawId = item.artifact_id || item.id || "unknown";
        const artifactId = String(rawId).includes("/") ? String(rawId).split("/").pop() : String(rawId);
        const filename = item.filename || `${artifactId}.md`;
        const chainPhase = extractAPhase(String(filename), item.chain_phase || "");
        const tags =
          Array.isArray(item.tags) ? item.tags.join(" ") : (typeof item.tags === "string" ? item.tags : "");

        index.push({
          id: `${category}/${artifactId}`,
          title: item.title || artifactId,
          department,
          type: item.type || "knowledge",
          date: String(item.date || lastUpdated),
          status: item.status || "completed",
          chain_phase: chainPhase,
          url: `/feed/${category}/${artifactId}`,
          tags,
          workflow_id: typeof item.workflow_id === 'string' ? item.workflow_id : undefined,
          workflow_type: item.workflow_type === 'trading_v2' ? 'trading_v2' : (item.workflow_type === 'legacy_chain' ? 'legacy_chain' : undefined),
          excerpt: item.excerpt ? cleanExcerpt(String(item.excerpt)) : undefined
        });
      }
    }

    index.sort((a, b) => String(b.date || "").localeCompare(String(a.date || "")));
    return index;
  }

  getArtifact(artifactId: string): ArtifactIndexItem | null {
    const index = this.getArtifactsIndex();
    return index.find(a => a.id === artifactId) || null;
  }
}


