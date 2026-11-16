// GET/POST /api/visual/cards/recommend（SPEC-54d 动态推荐卡）
// GET：只读回测制品 `54-L1架构能力聚合层/artifacts/cards/recommendation.json`；
// POST：重跑 `scripts/card_recommender.py` 后回读（人工刷新，后台不常驻）。
// 纪律：只推荐价格派生卡；制品缺失时返回空列表，由前端用静态兜底，绝不伪造收益。

import { NextRequest, NextResponse } from "next/server";
import { execFile } from "child_process";
import { promises as fs } from "fs";
import path from "path";
import { promisify } from "util";

const execFileAsync = promisify(execFile);

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const STALE_DAYS = 7;
const MAX_CARDS = 8;

function artifactPath(): string {
  return path.resolve(
    process.cwd(),
    "..",
    "54-L1架构能力聚合层",
    "artifacts",
    "cards",
    "recommendation.json",
  );
}

function scriptPath(): string {
  return path.resolve(
    process.cwd(),
    "..",
    "54-L1架构能力聚合层",
    "scripts",
    "card_recommender.py",
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function sanitizeCards(raw: unknown): Record<string, unknown>[] {
  if (!Array.isArray(raw)) return [];
  const cards: Record<string, unknown>[] = [];
  for (const item of raw) {
    if (!isRecord(item)) continue;
    const capabilityId =
      typeof item.capability_id === "string" ? item.capability_id.trim() : "";
    if (!capabilityId) continue;
    cards.push({
      capability_id: capabilityId,
      title:
        typeof item.title === "string" && item.title.trim()
          ? item.title.trim()
          : capabilityId,
      kind: typeof item.kind === "string" ? item.kind : undefined,
      args: isRecord(item.args) ? item.args : {},
      rule: typeof item.rule === "string" ? item.rule : undefined,
      desc: typeof item.desc === "string" ? item.desc : undefined,
      n_5d: typeof item.n_5d === "number" ? item.n_5d : undefined,
      n_20d: typeof item.n_20d === "number" ? item.n_20d : undefined,
      win_rate_5d:
        typeof item.win_rate_5d === "number" ? item.win_rate_5d : null,
      win_rate_20d:
        typeof item.win_rate_20d === "number" ? item.win_rate_20d : null,
      wilson_20d: typeof item.wilson_20d === "number" ? item.wilson_20d : null,
      stability_20d:
        typeof item.stability_20d === "number" ? item.stability_20d : null,
      score: typeof item.score === "number" ? item.score : undefined,
    });
    if (cards.length >= MAX_CARDS) break;
  }
  return cards;
}

function isStale(generatedAt: unknown): boolean {
  if (typeof generatedAt !== "string") return true;
  const ts = Date.parse(generatedAt);
  if (!Number.isFinite(ts)) return true;
  return Date.now() - ts > STALE_DAYS * 24 * 3600 * 1000;
}

async function readArtifact(): Promise<NextResponse> {
  try {
    const text = await fs.readFile(artifactPath(), "utf8");
    const payload = JSON.parse(text);
    const cards = sanitizeCards(isRecord(payload) ? payload.cards : null);
    if (!cards.length) {
      return NextResponse.json({
        ok: true,
        code: "builtin",
        source: "builtin",
        cards: [],
      });
    }
    return NextResponse.json({
      ok: true,
      code: "ok",
      source: "artifact",
      generated_at:
        typeof payload.generated_at === "string" ? payload.generated_at : null,
      stale: isStale(payload.generated_at),
      disclaimer:
        typeof payload.disclaimer === "string" ? payload.disclaimer : undefined,
      method: typeof payload.method === "string" ? payload.method : undefined,
      cards,
    });
  } catch {
    // FAIL-OPEN：制品缺失/损坏 → 前端用静态兜底，不阻断卡片模式
    return NextResponse.json({
      ok: true,
      code: "builtin",
      source: "builtin",
      cards: [],
    });
  }
}

export async function GET(): Promise<NextResponse> {
  return readArtifact();
}

export async function POST(_request: NextRequest): Promise<NextResponse> {
  const pythonBin =
    process.env.COGNITIVE_PYTHON || process.env.PYTHON || "python3";
  try {
    await execFileAsync(pythonBin, [scriptPath(), "--json"], {
      cwd: path.dirname(path.dirname(scriptPath())),
      timeout: 60000,
      maxBuffer: 8 * 1024 * 1024,
    });
  } catch (err) {
    return NextResponse.json(
      {
        ok: false,
        code: "refresh_failed",
        reason: err instanceof Error ? err.message : String(err),
      },
      { status: 503 },
    );
  }
  return readArtifact();
}
