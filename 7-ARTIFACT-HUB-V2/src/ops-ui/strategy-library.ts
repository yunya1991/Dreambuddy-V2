import fs from "node:fs";
import path from "node:path";
import { loadConfig, resolveRepoRoot } from "../config.js";

export interface StrategyLibraryItem {
  id: string;
  title: string;
  relative_path: string;
  absolute_path: string;
  size_bytes: number;
  mtime_ms: number;
  frontmatter: Record<string, string>;
}

export interface StrategyListResult {
  generated_at: string;
  strategy_root: string;
  total: number;
  items: StrategyLibraryItem[];
}

export interface StrategyDoc {
  id: string;
  title: string;
  relative_path: string;
  absolute_path: string;
  size_bytes: number;
  mtime_ms: number;
  frontmatter: Record<string, string>;
  content: string;
}

function resolveArtifactsRoot(): string {
  const override = process.env.ARTIFACTS_ROOT?.trim();
  if (override && override.length > 0) return override;

  const repoRoot = resolveRepoRoot();
  const config = loadConfig(repoRoot);
  return path.join(repoRoot, config.paths.artifacts_root);
}

function resolveStrategyRoot(): string {
  const override = process.env.STRATEGY_ROOT?.trim();
  if (override && override.length > 0) return override;
  return path.join(resolveArtifactsRoot(), "strategy");
}

function readFrontmatter(raw: string): { frontmatter: Record<string, string>; body: string } {
  const lines = raw.split(/\r?\n/);
  if (lines[0] !== "---") return { frontmatter: {}, body: raw };

  const out: Record<string, string> = {};
  let endIdx = -1;
  for (let i = 1; i < lines.length; i += 1) {
    if (lines[i] === "---") {
      endIdx = i;
      break;
    }
  }

  if (endIdx === -1) return { frontmatter: {}, body: raw };

  for (let i = 1; i < endIdx; i += 1) {
    const line = lines[i].trim();
    if (!line) continue;
    const sep = line.indexOf(":");
    if (sep <= 0) continue;
    const key = line.slice(0, sep).trim();
    let value = line.slice(sep + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    if (key) out[key] = value;
  }

  return { frontmatter: out, body: lines.slice(endIdx + 1).join("\n") };
}

function extractTitle(params: { frontmatter: Record<string, string>; body: string; fallback: string }): string {
  const fmTitle = params.frontmatter.title?.trim();
  if (fmTitle && fmTitle.length > 0) return fmTitle;

  const m = /^\s*#\s+(.+?)\s*$/m.exec(params.body);
  if (m?.[1]) return m[1].trim();

  return params.fallback;
}

function listMdFilesRecursive(root: string, dir: string): string[] {
  if (!fs.existsSync(dir)) return [];
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  const out: string[] = [];
  for (const e of entries) {
    const abs = path.join(dir, e.name);
    if (e.isDirectory()) {
      out.push(...listMdFilesRecursive(root, abs));
      continue;
    }
    if (e.isFile() && e.name.toLowerCase().endsWith(".md")) {
      out.push(abs);
    }
  }
  return out;
}

function toPosixPath(p: string): string {
  return p.split(path.sep).join("/");
}

export function listStrategies(): StrategyListResult {
  const strategyRoot = resolveStrategyRoot();
  const rootResolved = path.resolve(strategyRoot);
  const files = listMdFilesRecursive(rootResolved, rootResolved);

  const items = files
    .map((absolute_path): StrategyLibraryItem => {
      const st = fs.statSync(absolute_path);
      const relative = toPosixPath(path.relative(rootResolved, absolute_path));
      const raw = fs.readFileSync(absolute_path, "utf-8");
      const { frontmatter, body } = readFrontmatter(raw);
      const fallback = path.basename(relative, ".md");
      const title = extractTitle({ frontmatter, body, fallback });
      return {
        id: relative,
        title,
        relative_path: relative,
        absolute_path,
        size_bytes: st.size,
        mtime_ms: st.mtimeMs,
        frontmatter
      };
    })
    .sort((a, b) => {
      const ta = a.title.toLowerCase();
      const tb = b.title.toLowerCase();
      if (ta < tb) return -1;
      if (ta > tb) return 1;
      return a.id.localeCompare(b.id);
    });

  return {
    generated_at: new Date().toISOString(),
    strategy_root: rootResolved,
    total: items.length,
    items
  };
}

function resolveStrategyFile(rootResolved: string, id: string): string {
  const cleaned = id.trim();
  if (!cleaned) throw new Error("invalid_strategy_id");
  if (cleaned.includes("\0")) throw new Error("invalid_strategy_id");
  if (path.isAbsolute(cleaned)) throw new Error("invalid_strategy_id");

  const target = path.resolve(rootResolved, cleaned);
  if (target === rootResolved || !target.startsWith(rootResolved + path.sep)) throw new Error("invalid_strategy_id");

  if (!target.toLowerCase().endsWith(".md")) throw new Error("invalid_strategy_id");
  if (!fs.existsSync(target)) throw new Error("strategy_not_found");

  const st = fs.statSync(target);
  if (!st.isFile()) throw new Error("strategy_not_found");

  return target;
}

export function readStrategy(id: string): StrategyDoc {
  const strategyRoot = resolveStrategyRoot();
  const rootResolved = path.resolve(strategyRoot);
  const absolute = resolveStrategyFile(rootResolved, id);
  const st = fs.statSync(absolute);
  const relative = toPosixPath(path.relative(rootResolved, absolute));
  const raw = fs.readFileSync(absolute, "utf-8");
  const { frontmatter, body } = readFrontmatter(raw);
  const fallback = path.basename(relative, ".md");
  const title = extractTitle({ frontmatter, body, fallback });

  return {
    id: relative,
    title,
    relative_path: relative,
    absolute_path: absolute,
    size_bytes: st.size,
    mtime_ms: st.mtimeMs,
    frontmatter,
    content: raw
  };
}
