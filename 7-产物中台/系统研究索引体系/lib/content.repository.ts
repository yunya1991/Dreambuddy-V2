import fs from "node:fs";
import path from "node:path";
import matter from "gray-matter";
import type {
  Artifact,
  ArtifactDetailPayload,
  ArtifactsData,
  CanonicalArtifactIndex,
  SourceArtifactRecord,
} from "./types";

function toArray(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String).filter(Boolean);
  if (typeof value === "string") return value.split(/\s+/).filter(Boolean);
  return [];
}

function extractExcerpt(content: string): string | undefined {
  const text = content
    .replace(/^#+\s+/gm, "")
    .replace(/[\r\n]+/g, " ")
    .replace(/\*+/g, "")
    .replace(/`[^`]*`/g, "")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/<[^>]*>/g, "")
    .replace(/\s{2,}/g, " ")
    .trim()
    .slice(0, 200);

  return text || undefined;
}

function readMarkdownFile(sourcePath: string): { data: Record<string, unknown>; content: string } {
  const raw = fs.readFileSync(sourcePath, "utf-8");
  try {
    const parsed = matter(raw);
    return { data: parsed.data, content: parsed.content };
  } catch {
    return { data: {}, content: raw };
  }
}

function countBy<T>(items: T[], key: keyof T): Record<string, number> {
  return items.reduce<Record<string, number>>((acc, item) => {
    const value = String(item[key] ?? "");
    if (value) acc[value] = (acc[value] || 0) + 1;
    return acc;
  }, {});
}

type IndexJsonShape = {
  last_updated?: string;
  artifacts?: Array<Record<string, unknown>>;
};

type CacheStamp = {
  indexMtime: number;
  sourceMtimes: Record<string, number>;
};

export class ContentRepository {
  private readonly artifactsRoot: string;
  private indexCache: CanonicalArtifactIndex[] | null = null;
  private detailCache = new Map<string, ArtifactDetailPayload>();
  private cacheStamp: CacheStamp | null = null;

  constructor(artifactsRoot: string) {
    this.artifactsRoot = artifactsRoot;
  }

  getArtifactsIndex(): CanonicalArtifactIndex[] {
    return this.ensureFreshIndex();
  }

  getArtifactDetailBySlug(slug: string): ArtifactDetailPayload | null {
    const index = this.ensureFreshIndex();
    const entry = index.find((item) => item.detailUrl === `/feed/${slug}`);
    if (!entry) return null;

    const cached = this.detailCache.get(slug);
    if (cached && cached.sourcePath === entry.sourcePath) {
      return cached;
    }

    if (!fs.existsSync(entry.sourcePath)) return null;

    let payload: ArtifactDetailPayload;
    if (entry.sourceType === "json") {
      const raw = fs.readFileSync(entry.sourcePath, "utf-8");
      payload = {
        artifactId: entry.artifactId,
        category: entry.category,
        frontmatter: {},
        content: raw,
        sourcePath: entry.sourcePath,
        sourceType: "json",
        canonical: entry,
      };
    } else {
      const parsed = readMarkdownFile(entry.sourcePath);
      payload = {
        artifactId: entry.artifactId,
        category: entry.category,
        frontmatter: parsed.data,
        content: parsed.content,
        sourcePath: entry.sourcePath,
        sourceType: "markdown",
        canonical: entry,
      };
    }

    this.detailCache.set(slug, payload);
    return payload;
  }

  getArtifactsData(): ArtifactsData {
    const index = this.getArtifactsIndex();
    const artifacts: Artifact[] = index.map((item) => ({
      id: item.id,
      title: item.title,
      department: item.department,
      type: item.type,
      date: item.date,
      status: item.status as Artifact["status"],
      chain_phase: item.chainPhase,
      file_path: item.sourcePath,
      relative_url: item.detailUrl,
      size_bytes: fs.existsSync(item.sourcePath) ? fs.statSync(item.sourcePath).size : 0,
      tags: item.tags,
    }));

    return {
      version: "3.0",
      generated_at: new Date().toISOString(),
      total: index.length,
      statistics: {
        by_department: countBy(index, "department"),
        by_type: countBy(index, "type"),
        by_status: countBy(index, "status"),
        by_chain_phase: countBy(index, "chainPhase"),
        by_a_phase: countBy(
          index.filter((item) => /^A[0-9]$/i.test(item.chainPhase)),
          "chainPhase",
        ),
      },
      artifacts,
    };
  }

  private ensureFreshIndex(): CanonicalArtifactIndex[] {
    const indexMtime = this.computeIndexMtime();
    if (!this.indexCache || !this.cacheStamp || this.cacheStamp.indexMtime !== indexMtime) {
      this.indexCache = this.scanIndex();
      this.cacheStamp = {
        indexMtime,
        sourceMtimes: this.getSourceMtimes(this.indexCache),
      };
      this.detailCache.clear();
      return this.indexCache;
    }

    const nextSourceMtimes = this.getSourceMtimes(this.indexCache);
    const changed = Object.entries(nextSourceMtimes).some(
      ([sourcePath, mtime]) => this.cacheStamp?.sourceMtimes[sourcePath] !== mtime,
    );
    if (changed) {
      this.indexCache = this.scanIndex();
      this.cacheStamp = {
        indexMtime,
        sourceMtimes: this.getSourceMtimes(this.indexCache),
      };
      this.detailCache.clear();
    }

    return this.indexCache;
  }

  private computeIndexMtime(): number {
    const categories = fs
      .readdirSync(this.artifactsRoot)
      .filter((name) => fs.existsSync(path.join(this.artifactsRoot, name, "index.json")));

    return categories.reduce((max, category) => {
      const file = path.join(this.artifactsRoot, category, "index.json");
      return Math.max(max, fs.statSync(file).mtimeMs);
    }, 0);
  }

  private getSourceMtimes(index: CanonicalArtifactIndex[]): Record<string, number> {
    return Object.fromEntries(
      index.map((item) => [
        item.sourcePath,
        fs.existsSync(item.sourcePath) ? fs.statSync(item.sourcePath).mtimeMs : -1,
      ]),
    );
  }

  private scanIndex(): CanonicalArtifactIndex[] {
    const categories = fs
      .readdirSync(this.artifactsRoot)
      .filter((name) => fs.existsSync(path.join(this.artifactsRoot, name, "index.json")));

    return categories.flatMap((category) => this.readCategoryIndex(category));
  }

  private readCategoryIndex(category: string): CanonicalArtifactIndex[] {
    const categoryDir = path.join(this.artifactsRoot, category);
    const parsedIndex = JSON.parse(
      fs.readFileSync(path.join(categoryDir, "index.json"), "utf-8"),
    ) as IndexJsonShape | Array<Record<string, unknown>>;
    const items = Array.isArray(parsedIndex) ? parsedIndex : (parsedIndex.artifacts ?? []);

    return items.map((item) => {
      const rawId = String(item.artifact_id ?? item.id ?? "unknown");
      const artifactId = rawId.includes("/") ? rawId.split("/").pop()! : rawId;
      const sourceFile = String(item.filename ?? item.file ?? `${artifactId}.md`);
      const sourcePath = path.join(categoryDir, sourceFile);
      const sourceType = sourceFile.endsWith(".json") ? "json" : "markdown";
      const parsedSource =
        sourceType === "markdown" && fs.existsSync(sourcePath)
          ? readMarkdownFile(sourcePath)
          : {
              data: {},
              content: fs.existsSync(sourcePath) ? fs.readFileSync(sourcePath, "utf-8") : "",
            };

      const sourceRecord: SourceArtifactRecord = {
        artifactId,
        category,
        department: String(item.department ?? category),
        type: String(item.type ?? "knowledge"),
        status: String(item.status ?? "unknown"),
        date: String(
          item.date ??
            (!Array.isArray(parsedIndex) ? parsedIndex.last_updated : undefined) ??
            new Date().toISOString(),
        ),
        chainPhase: String(item.chain_phase ?? ""),
        tags: toArray(item.tags),
        title: String(item.title ?? artifactId),
        sourceFile,
        sourceType,
      };

      return {
        id: `${category}/${artifactId}`,
        ...sourceRecord,
        excerpt: extractExcerpt(parsedSource.content),
        sourcePath,
        detailUrl: `/feed/${category}/${artifactId}`,
      };
    });
  }
}
