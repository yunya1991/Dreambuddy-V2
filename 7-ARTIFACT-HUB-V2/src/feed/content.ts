import fs from "node:fs";
import path from "node:path";
import { normalizeWorkflowType } from "../chain-workflow-guard.js";
import matter from "gray-matter";
import { CATEGORY_TO_DEPARTMENT } from "../category.js";
import type { FeedDetail, FeedHomepageSummary, FeedListItem, FeedQuery, FeedStats } from "./types.js";
import { countBy, normalizeArtifactId, normalizeTags, stripMarkdown } from "./utils.js";

const FIXED_STAGE_LABELS = ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9"] as const;

interface RawArtifactIndexItem {
  artifact_id?: string;
  id?: string;
  title?: string;
  filename?: string; // legacy field name
  file?: string;     // actual field name used by sync_artifact.py
  type?: string;
  status?: string;
  tags?: unknown;
  chain_phase?: string;
  date?: string;
  excerpt?: string;
  workflow_id?: string;
  workflow_type?: string;
  trace_id?: string;
}

interface RawArtifactIndexFile {
  last_updated?: string;
  artifacts?: RawArtifactIndexItem[];
}

function resolveDepartmentLabel(item: {
  category: string;
  tags: string[];
  title: string;
  type?: string;
  chainPhase?: string;
}): string {
  if (item.category === "trading") return "交易部";
  if (item.category === "governance") return "治理部";

  const dreamSignals = [item.title, item.tags.join(" ")].join(" ").toLowerCase();
  if (dreamSignals.includes("dream") || dreamSignals.includes("oneirology")) return "做梦部";

  // Temporary bridge for current real research data: the existing A3 strategy
  // artifact stands in for the dream entry until dedicated dream artifacts land.
  if (item.category === "research" && item.type === "strategy" && item.chainPhase === "A3") {
    return "做梦部";
  }

  return "知识库";
}

export class FeedContentStore {
  private cache: FeedListItem[] | null = null;

  constructor(private readonly artifactsRoot: string) {}

  listArtifacts(query: FeedQuery = {}): FeedListItem[] {
    const items = this.cache ?? (this.cache = this.scanArtifacts());

    const filtered = items.filter((item) => {
      if (query.category && item.category !== query.category) return false;
      if (
        query.department &&
        item.department !== query.department &&
        item.departmentLabel !== query.department
      ) {
        return false;
      }
      if (query.status && item.status !== query.status) return false;
      if (query.chainPhase && item.chainPhase !== query.chainPhase) return false;

      if (query.q) {
        const needle = query.q.toLowerCase();
        const haystack = [item.title, item.excerpt || "", item.tags.join(" "), item.category].join(" ").toLowerCase();
        return haystack.includes(needle);
      }

      return true;
    });

    const offset = Math.max(0, query.offset ?? 0);
    const limit = query.limit ?? filtered.length;
    return filtered.slice(offset, offset + Math.max(0, limit));
  }

  getStats(): FeedStats {
    const items = this.listArtifacts();
    return {
      total: items.length,
      byDepartment: countBy(items.map((item) => item.department)),
      byType: countBy(items.map((item) => item.type)),
      byStatus: countBy(items.map((item) => item.status)),
      byChainPhase: countBy(items.map((item) => item.chainPhase))
    };
  }

  getHomepageSummary(): FeedHomepageSummary {
    const items = this.listArtifacts();

    const departmentEntries = ["交易部", "做梦部", "治理部", "知识库"].map((label) => ({
      label,
      count: items.filter((item) => item.departmentLabel === label).length,
      href: `/feed?department=${encodeURIComponent(label)}`
    }));

    const stageEntries = FIXED_STAGE_LABELS.map((label) => ({
      label,
      count: items.filter((item) => item.chainPhase === label).length,
      href: `/feed?chainPhase=${encodeURIComponent(label)}`
    }));

    return { departmentEntries, stageEntries };
  }

  getArtifactDetail(category: string, artifactId: string): FeedDetail | null {
    const item = this.listArtifacts({ category }).find((entry) => entry.artifactId === artifactId);
    if (!item) return null;

    // Try multiple filename candidates:
    // 1. item.filename from the scan (respects "file" field in index.json)
    // 2. artifactId.md as fallback
    const candidates = [
      item.filename ? path.join(this.artifactsRoot, category, item.filename) : null,
      path.join(this.artifactsRoot, category, `${artifactId}.md`),
    ].filter(Boolean) as string[];

    let rawPath = "";
    for (const candidate of candidates) {
      if (fs.existsSync(candidate)) {
        rawPath = candidate;
        break;
      }
    }
    if (!rawPath) {
      const indexPath = path.join(this.artifactsRoot, category, "index.json");
      if (!fs.existsSync(indexPath)) return null;

      return {
        ...item,
        content: this.renderIndexFallbackContent(item),
        rawPath: indexPath,
        governanceContext: this.buildGovernanceContext(item)
      };
    }

    const source = fs.readFileSync(rawPath, "utf-8");
    const parsed = matter(source);

    return {
      ...item,
      title: typeof parsed.data.title === "string" ? parsed.data.title : item.title,
      department: typeof parsed.data.department === "string" ? parsed.data.department : item.department,
      type: typeof parsed.data.type === "string" ? parsed.data.type : item.type,
      status: typeof parsed.data.status === "string" ? parsed.data.status : item.status,
      date: typeof parsed.data.date === "string" ? parsed.data.date : item.date,
      tags: normalizeTags(parsed.data.tags).length > 0 ? normalizeTags(parsed.data.tags) : item.tags,
      content: parsed.content,
      rawPath,
      governanceContext: this.buildGovernanceContext(item)
    };
  }

  private buildGovernanceContext(item: FeedListItem) {
    return {
      workflowId: item.workflowId ?? "",
      workflowType: item.workflowType ?? "legacy_chain",
      traceId: item.traceId ?? "",
      chainPhase: item.chainPhase
    };
  }

  private renderIndexFallbackContent(item: FeedListItem): string {
    const lines = [
      `# ${item.title}`,
      "",
      `- Category: ${item.category}`,
      `- Department: ${item.department}`,
      `- Type: ${item.type}`,
      `- Status: ${item.status}`,
      `- Date: ${item.date}`
    ];

    if (item.chainPhase) {
      lines.push(`- Chain Phase: ${item.chainPhase}`);
    }

    if (item.tags.length > 0) {
      lines.push(`- Tags: ${item.tags.join(", ")}`);
    }

    if (item.excerpt) {
      lines.push("", item.excerpt);
    }

    return lines.join("\n");
  }

  private scanArtifacts(): FeedListItem[] {
    if (!fs.existsSync(this.artifactsRoot)) return [];

    const categories = fs.readdirSync(this.artifactsRoot).filter((entry) => {
      const fullPath = path.join(this.artifactsRoot, entry);
      return fs.statSync(fullPath).isDirectory() && !entry.startsWith(".");
    });

    const items: FeedListItem[] = [];

    for (const category of categories) {
      if (category === "tasks" || category === "results") continue;

      const categoryDir = path.join(this.artifactsRoot, category);
      const indexFile = path.join(categoryDir, "index.json");
      if (!fs.existsSync(indexFile)) continue;

      const parsed = this.safeReadIndex(indexFile);
      if (!parsed) continue;

      const list: RawArtifactIndexItem[] =
        Array.isArray(parsed) ? parsed :
        Array.isArray((parsed as RawArtifactIndexFile).artifacts) ? (parsed as RawArtifactIndexFile).artifacts! : [];
      const parsedAsFile = parsed as RawArtifactIndexFile;
      const lastUpdated = typeof parsedAsFile.last_updated === "string" ? parsedAsFile.last_updated : new Date().toISOString();

      for (const entry of list) {
        const rawId = String(entry.artifact_id || entry.id || "unknown");
        const artifactId = normalizeArtifactId(rawId);
        // Support both "filename" (legacy) and "file" (used by sync_artifact.py)
        const filename = typeof entry.filename === "string" ? entry.filename :
                         typeof entry.file === "string" ? entry.file :
                         `${artifactId}.md`;
        const markdownPath = path.join(categoryDir, filename);
        const tags = normalizeTags(entry.tags);
        const departmentLabel = resolveDepartmentLabel({
          category,
          title: entry.title || artifactId,
          tags,
          type: entry.type,
          chainPhase: entry.chain_phase
        });
        const type = entry.type || "knowledge";
        const excerpt = fs.existsSync(markdownPath)
          ? stripMarkdown(matter(fs.readFileSync(markdownPath, "utf-8")).content).slice(0, 200)
          : undefined;

        items.push({
          id: `${category}/${artifactId}`,
          category,
          artifactId,
          filename, // preserve real filename for detail lookup
          title: entry.title || artifactId,
          department: CATEGORY_TO_DEPARTMENT[category] || category,
          departmentLabel,
          type,
          typeLabel: type,
          status: entry.status || "completed",
          date: entry.date || lastUpdated,
          chainPhase: entry.chain_phase || "",
          tags,
          excerpt: entry.excerpt ? stripMarkdown(String(entry.excerpt)) : excerpt,
          url: `/feed/${category}/${artifactId}`,
          workflowId: typeof entry.workflow_id === "string" ? entry.workflow_id : undefined,
          workflowType: normalizeWorkflowType(typeof entry.workflow_type === "string" ? entry.workflow_type : undefined),
          traceId: typeof entry.trace_id === "string" ? entry.trace_id : undefined
        });
      }
    }

    items.sort((a, b) => b.date.localeCompare(a.date));
    return items;
  }

  private safeReadIndex(indexFile: string): RawArtifactIndexFile | RawArtifactIndexItem[] | null {
    try {
      return JSON.parse(fs.readFileSync(indexFile, "utf-8")) as RawArtifactIndexFile | RawArtifactIndexItem[];
    } catch {
      return null;
    }
  }
}
