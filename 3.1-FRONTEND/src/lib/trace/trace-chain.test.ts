import { validateTraceChain, type TraceArtifact } from "./trace-chain";

const T = "trace-1";

function chain(): TraceArtifact[] {
  return [
    { type: "proposal", id: "P1", trace_id: T, parent_id: "finding:F1" },
    { type: "ticket", id: "TK1", trace_id: T, parent_id: "P1" },
    { type: "verdict", id: "V1", trace_id: T, parent_id: "TK1" },
    { type: "memory", id: "M1", trace_id: T, parent_id: "V1" },
  ];
}

describe("validateTraceChain", () => {
  it("完整链路通过", () => {
    const out = validateTraceChain(chain());
    expect(out.ok).toBe(true);
    expect(out.trace_id).toBe(T);
  });

  it("缺少 trace_id 报错", () => {
    const a = chain();
    a[2].trace_id = "";
    expect(validateTraceChain(a).issues.map((i) => i.code)).toContain("missing_trace");
  });

  it("trace 不一致报错", () => {
    const a = chain();
    a[3].trace_id = "other";
    expect(validateTraceChain(a).issues.map((i) => i.code)).toContain("trace_mismatch");
  });

  it("无根节点报错", () => {
    const out = validateTraceChain([
      { type: "verdict", id: "V1", trace_id: T },
      { type: "memory", id: "M1", trace_id: T, parent_id: "V1" },
    ]);
    expect(out.ok).toBe(false);
    expect(out.issues.map((i) => i.code)).toContain("missing_ticket_root");
  });

  it("多根节点报错", () => {
    const out = validateTraceChain([
      { type: "ticket", id: "TK1", trace_id: T },
      { type: "proposal", id: "P1", trace_id: T },
    ]);
    expect(out.issues.map((i) => i.code)).toContain("multiple_roots");
  });

  it("父节点不存在报错", () => {
    const out = validateTraceChain([
      { type: "ticket", id: "TK1", trace_id: T },
      { type: "verdict", id: "V1", trace_id: T, parent_id: "missing" },
    ]);
    expect(out.issues.map((i) => i.code)).toContain("unknown_parent");
  });

  it("非法父子关系报错", () => {
    const out = validateTraceChain([
      { type: "ticket", id: "TK1", trace_id: T },
      { type: "proposal", id: "P1", trace_id: T },
      { type: "memory", id: "M1", trace_id: T, parent_id: "P1" },
    ]);
    expect(out.issues.map((i) => i.code)).toContain("invalid_lineage");
  });

  it("id 重复报错", () => {
    const out = validateTraceChain([
      { type: "ticket", id: "TK1", trace_id: T },
      { type: "verdict", id: "TK1", trace_id: T, parent_id: "TK1" },
    ]);
    expect(out.issues.map((i) => i.code)).toContain("duplicate_artifact");
  });

  it("父子成环报错", () => {
    const out = validateTraceChain([
      { type: "ticket", id: "TK1", trace_id: T },
      { type: "verdict", id: "V1", trace_id: T, parent_id: "M1" },
      { type: "memory", id: "M1", trace_id: T, parent_id: "V1" },
    ]);
    expect(out.issues.map((i) => i.code)).toContain("cycle_detected");
  });

  it("proposal 允许挂在外部 finding 上", () => {
    const out = validateTraceChain([
      { type: "proposal", id: "P1", trace_id: T, parent_id: "finding:F9" },
      { type: "ticket", id: "TK1", trace_id: T, parent_id: "P1" },
    ]);
    expect(out.ok).toBe(true);
  });

  it("空输入返回 degraded", () => {
    const out = validateTraceChain([]);
    expect(out.ok).toBe(false);
    expect(out.issues[0].code).toBe("invalid_input");
  });
});
