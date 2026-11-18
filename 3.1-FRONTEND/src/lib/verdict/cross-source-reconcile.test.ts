import {
  buildU3Verdict,
  canonicalUrl,
  reconcileSources,
  type SourceRecord,
} from "./cross-source-reconcile";

const NOW = Date.UTC(2026, 10, 18);
const DAY = 24 * 60 * 60 * 1000;

function src(
  overrides: Partial<SourceRecord> & { source_id: string; origin: string },
): SourceRecord {
  return { stance: "support", published_at: NOW - DAY, ...overrides };
}

describe("U3 跨源对账", () => {
  it("URL 规范化：去协议/www/锚点/跟踪参数并排序保留参数", () => {
    expect(
      canonicalUrl("https://www.Example.com/a/?utm_source=x&id=2#section"),
    ).toBe("example.com/a?id=2");
    expect(canonicalUrl("http://example.com/a")).toBe("example.com/a");
  });

  it("两个独立来源支持 → supported，证据两条", () => {
    const result = reconcileSources(
      [
        src({ source_id: "s1", origin: "reuters" }),
        src({ source_id: "s2", origin: "bloomberg" }),
      ],
      { now: NOW },
    );
    expect(result.verdict_signal).toBe("supported");
    expect(result.ok).toBe(true);
    expect(result.evidence).toHaveLength(2);
    expect(result.agreement_ratio).toBe(1);
  });

  it("同 origin 转载只计 1 个独立来源", () => {
    const result = reconcileSources(
      [
        src({ source_id: "s1", origin: "reuters" }),
        src({ source_id: "s2", origin: "Reuters" }),
      ],
      { now: NOW },
    );
    expect(result.independent).toHaveLength(1);
    expect(result.duplicates).toEqual([
      { source_id: "s2", duplicate_of: "s1", reason: "same_origin" },
    ]);
    expect(result.verdict_signal).toBe("inconclusive");
    expect(result.reasons).toContain("insufficient_independent_sources");
  });

  it("同内容指纹跨域转载按 same_content 去重", () => {
    const result = reconcileSources(
      [
        src({ source_id: "s1", origin: "a", content_hash: "h1" }),
        src({ source_id: "s2", origin: "b", content_hash: "h1" }),
      ],
      { now: NOW },
    );
    expect(result.duplicates[0].reason).toBe("same_content");
    expect(result.independent).toHaveLength(1);
  });

  it("规范化 URL 相同的转载按 same_url 去重", () => {
    const result = reconcileSources(
      [
        src({ source_id: "s1", origin: "a", url: "https://x.com/p/1?utm_source=a" }),
        src({ source_id: "s2", origin: "b", url: "http://www.x.com/p/1/" }),
      ],
      { now: NOW },
    );
    expect(result.duplicates[0].reason).toBe("same_url");
  });

  it("过期来源被剔除，不参与结论", () => {
    const result = reconcileSources(
      [
        src({ source_id: "old", origin: "a", published_at: NOW - 40 * DAY }),
        src({ source_id: "s2", origin: "b" }),
      ],
      { now: NOW },
    );
    expect(result.stale).toEqual(["old"]);
    expect(result.independent).toHaveLength(1);
    expect(result.verdict_signal).toBe("inconclusive");
    expect(result.reasons).toContain("stale_excluded");
  });

  it("字段冲突 → inconclusive 并列出冲突值", () => {
    const result = reconcileSources(
      [
        src({ source_id: "s1", origin: "a", fields: { revenue: 100 } }),
        src({ source_id: "s2", origin: "b", fields: { revenue: 120 } }),
      ],
      { now: NOW },
    );
    expect(result.verdict_signal).toBe("inconclusive");
    expect(result.reasons).toContain("field_conflict");
    expect(result.field_conflicts[0].field).toBe("revenue");
    expect(result.field_conflicts[0].values).toHaveLength(2);
  });

  it("数值差异在容差内不算冲突", () => {
    const result = reconcileSources(
      [
        src({ source_id: "s1", origin: "a", fields: { revenue: 100 } }),
        src({ source_id: "s2", origin: "b", fields: { revenue: 100.4 } }),
      ],
      { now: NOW, numeric_tolerance: 0.01 },
    );
    expect(result.field_conflicts).toEqual([]);
    expect(result.verdict_signal).toBe("supported");
  });

  it("反证来源占多数 → contradicted", () => {
    const result = reconcileSources(
      [
        src({ source_id: "s1", origin: "a", stance: "refute" }),
        src({ source_id: "s2", origin: "b", stance: "refute" }),
        src({ source_id: "s3", origin: "c", stance: "support" }),
      ],
      { now: NOW },
    );
    expect(result.verdict_signal).toBe("contradicted");
    expect(result.evidence.filter((item) => item.contradicts)).toHaveLength(2);
  });
});

describe("U3 裁决", () => {
  it("对账 inconclusive 时不得被来源数量凑成 supported", () => {
    const { verdict, reconciliation, issues } = buildU3Verdict({
      task_id: "task-1",
      trace_id: "trace-1",
      claim: "该公司 2025 年营收为 100 亿",
      sources: [
        src({ source_id: "s1", origin: "a", fields: { revenue: 100 } }),
        src({ source_id: "s2", origin: "b", fields: { revenue: 120 } }),
      ],
      reconciliation: { now: NOW },
      confidence: 0.9,
    });
    expect(reconciliation.verdict_signal).toBe("inconclusive");
    expect(verdict.verdict).toBe("inconclusive");
    expect(issues.some((item) => item.code === "reconcile_inconclusive")).toBe(true);
  });

  it("多源一致 + 置信度 → supported，level 为 U3", () => {
    const { verdict } = buildU3Verdict({
      task_id: "task-1",
      trace_id: "trace-1",
      claim: "该公司 2025 年营收为 100 亿",
      sources: [
        src({ source_id: "s1", origin: "a", fields: { revenue: 100 } }),
        src({ source_id: "s2", origin: "b", fields: { revenue: 100 } }),
      ],
      rea: [
        {
          ref: "rea:module:revenue-parser",
          kind: "rea",
          origin: "repo",
          fresh: true,
          replayable: true,
        },
      ],
      reconciliation: { now: NOW },
      confidence: 0.86,
    });
    expect(verdict.verdict).toBe("supported");
    expect(verdict.level).toBe("U3");
    expect(verdict.evidence_refs.length).toBeGreaterThanOrEqual(3);
  });

  it("反证多数 → contradicted", () => {
    const { verdict } = buildU3Verdict({
      task_id: "task-1",
      trace_id: "trace-1",
      claim: "该接口不返回营收字段",
      sources: [
        src({ source_id: "s1", origin: "a", stance: "refute" }),
        src({ source_id: "s2", origin: "b", stance: "refute" }),
        src({ source_id: "s3", origin: "c", stance: "support" }),
      ],
      reconciliation: { now: NOW },
      confidence: 0.8,
    });
    expect(verdict.verdict).toBe("contradicted");
  });
});
