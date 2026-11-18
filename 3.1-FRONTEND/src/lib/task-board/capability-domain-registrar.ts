/**
 * 能力域注册器（T4）：从 SKILL.md manifest 显式字段注册能力域。
 *
 * 现状约束：现有 SKILL.md frontmatter 只有 name/description/version/category，
 * 不携带 capabilities / evidence_types / acceptance。因此本注册器**不做任何推断**：
 * 字段不全的 skill 一律跳过并报告原因，宁可不注册也不猜映射。
 *
 * 支持的 manifest 写法（frontmatter）：
 *   name: xxx
 *   description: xxx
 *   version: 1.0.0
 *   acceptance: 每个结论必须引用证据
 *   capabilities: [market.price, market.series]
 *   evidence_types:
 *     - tool_result
 *     - quote_snapshot
 *   domain: domain:market_data        # 可选，缺省由 name 生成
 */

import fs from "fs";
import path from "path";
import { DOMAINS, type CapabilityDomain } from "./capability-domain";
export interface DomainManifestParseResult {
  domainId?: string;
  domain?: CapabilityDomain;
  errors: string[];
}

export interface DomainRegistrationResult {
  registered: string[];
  skipped: Array<{ path: string; errors: string[] }>;
  duplicates: string[];
}

const REQUIRED_FIELDS = [
  "name",
  "description",
  "acceptance",
  "capabilities",
  "evidence_types",
  "version",
] as const;

/** 只解析 frontmatter：单行 key: value + 紧随其后的 "- item" 列表 */
function readFrontmatter(markdown: string): Record<string, string | string[]> {
  const lines = markdown.split("\n");
  if (lines[0]?.trim() !== "---") return {};
  const result: Record<string, string | string[]> = {};
  let currentListKey: string | null = null;

  for (let i = 1; i < lines.length; i += 1) {
    const line = lines[i];
    if (line.trim() === "---") break;

    const itemMatch = /^\s+-\s+(.+)$/.exec(line);
    if (itemMatch && currentListKey) {
      const prev = result[currentListKey];
      result[currentListKey] = [
        ...(Array.isArray(prev) ? prev : []),
        itemMatch[1].trim().replace(/^["']|["']$/g, ""),
      ];
      continue;
    }

    const match = /^([a-zA-Z0-9_-]+):\s*(.*)$/.exec(line);
    if (!match) continue;
    const key = match[1];
    const raw = match[2].trim().replace(/^["']|["']$/g, "");
    if (raw === "") {
      currentListKey = key;
      result[key] = [];
    } else {
      currentListKey = null;
      result[key] = raw;
    }
  }
  return result;
}

/** 单行数组 [a, b] 或逗号分隔 → 字符串数组 */
function toList(value: string | string[] | undefined): string[] {
  if (Array.isArray(value)) return value.map((item) => item.trim()).filter(Boolean);
  if (!value) return [];
  const inner = value.replace(/^\[|\]$/g, "");
  return inner
    .split(",")
    .map((item) => item.trim().replace(/^["']|["']$/g, ""))
    .filter(Boolean);
}

function text(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value.join("；").trim();
  return (value ?? "").trim();
}

function slug(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

/** 解析单个 SKILL.md；字段不全返回 errors，绝不补默认值 */
export function parseDomainManifest(markdown: string): DomainManifestParseResult {
  const fm = readFrontmatter(markdown);
  const errors: string[] = [];

  for (const field of REQUIRED_FIELDS) {
    const value = fm[field];
    const empty = Array.isArray(value) ? value.length === 0 : !text(value);
    if (empty) errors.push(`missing:${field}`);
  }
  const capabilities = toList(fm.capabilities);
  const evidenceTypes = toList(fm.evidence_types);
  if (capabilities.length === 0) errors.push("capabilities_empty");
  if (evidenceTypes.length === 0) errors.push("evidence_types_empty");

  if (errors.length > 0) return { errors };

  const name = text(fm.name);
  const domainId = text(fm.domain) || `domain:${slug(name)}`;
  return {
    domainId,
    errors,
    domain: {
      name,
      description: text(fm.description),
      capabilities,
      acceptance: text(fm.acceptance),
      evidence_types: evidenceTypes,
      version: text(fm.version),
    },
  };
}

/** 扫描目录（skills/<name>/SKILL.md）；目录不存在返回空结果，不抛异常 */
export function loadDomainManifests(dirPath: string): {
  loaded: Array<{ path: string; domainId: string; domain: CapabilityDomain }>;
  skipped: Array<{ path: string; errors: string[] }>;
} {
  const loaded: Array<{ path: string; domainId: string; domain: CapabilityDomain }> = [];
  const skipped: Array<{ path: string; errors: string[] }> = [];
  if (!dirPath || !fs.existsSync(dirPath)) return { loaded, skipped };

  for (const entry of fs.readdirSync(dirPath, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const filePath = path.join(dirPath, entry.name, "SKILL.md");
    if (!fs.existsSync(filePath)) continue;
    try {
      const parsed = parseDomainManifest(fs.readFileSync(filePath, "utf-8"));
      if (parsed.domain && parsed.domainId) {
        loaded.push({ path: filePath, domainId: parsed.domainId, domain: parsed.domain });
      } else {
        skipped.push({ path: filePath, errors: parsed.errors });
      }
    } catch (e) {
      skipped.push({
        path: filePath,
        errors: [e instanceof Error ? e.message : "read_failed"],
      });
    }
  }
  return { loaded, skipped };
}

/** 注册到目标能力域表；同名域不覆盖（返回 duplicates），避免静默改写线上归属 */
export function registerDomainsFromDir(
  dirPath: string,
  target: Record<string, CapabilityDomain> = DOMAINS,
): DomainRegistrationResult {
  const { loaded, skipped } = loadDomainManifests(dirPath);
  const registered: string[] = [];
  const duplicates: string[] = [];

  for (const item of loaded) {
    if (target[item.domainId]) {
      duplicates.push(item.domainId);
      continue;
    }
    target[item.domainId] = item.domain;
    registered.push(item.domainId);
  }

  return { registered, skipped, duplicates };
}

/** 进程内已扫描过的目录，避免每次请求都读盘 */
const ensuredDirs = new Set<string>();

export interface EnsureDomainsOptions {
  /** 显式目录；缺省读 CAPABILITY_SKILL_DIRS（path.delimiter 分隔），再缺省 6-TRADING/skills */
  dirs?: string[];
  target?: Record<string, CapabilityDomain>;
  /** 忽略进程内缓存，强制重扫 */
  force?: boolean;
  env?: Record<string, string | undefined>;
}

/** 默认 skills 目录：仓库根下 6-TRADING/skills（Next 进程 cwd 为 3.1-FRONTEND） */
function defaultSkillDirs(env: Record<string, string | undefined>): string[] {
  const configured = (env.CAPABILITY_SKILL_DIRS || "").trim();
  if (configured) {
    return configured
      .split(path.delimiter)
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return [path.join(process.cwd(), "..", "6-TRADING", "skills")];
}

/**
 * 启用能力域注册：扫描 manifest → 注册进 DOMAINS。
 * FAIL-OPEN：目录缺失/无权限只返回空结果，不影响主链路。
 */
export function ensureDomainsRegistered(
  options: EnsureDomainsOptions = {},
): DomainRegistrationResult[] {
  const env = options.env ?? process.env;
  const target = options.target ?? DOMAINS;
  const dirs = options.dirs ?? defaultSkillDirs(env);
  const cacheKey = (dir: string) => `${path.resolve(dir)}|${options.target ? "custom" : "default"}`;
  const results: DomainRegistrationResult[] = [];

  for (const dir of dirs) {
    const key = cacheKey(dir);
    if (!options.force && ensuredDirs.has(key)) {
      results.push({ registered: [], skipped: [], duplicates: [] });
      continue;
    }
    try {
      const result = registerDomainsFromDir(dir, target);
      ensuredDirs.add(key);
      results.push(result);
    } catch (e) {
      results.push({
        registered: [],
        skipped: [
          {
            path: dir,
            errors: [e instanceof Error ? e.message : "scan_failed"],
          },
        ],
        duplicates: [],
      });
      ensuredDirs.add(key);
    }
  }
  return results;
}
