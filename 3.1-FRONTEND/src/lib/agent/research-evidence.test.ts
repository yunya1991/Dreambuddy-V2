import {
  buildResearchVisuals,
  fetchResearchEvidence,
  renderResearchBrief,
  researchLink,
} from "./research-evidence";

function mockJson(body: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as Response);
}

const PAYLOAD = {
  ok: true,
  as_of: "2026-11-16",
  source: { eval_at: "2026-11-17T01:41:13", data_version: "db@20261117" },
  target: {
    available: true,
    target: "ETH",
    rows: 1260,
    evaluable: 1260,
    gate_pass: 0,
    stable: 0,
    counts: { stable: 0, candidate: 1260, decayed: 0, other: 0 },
    top: [
      {
        relation: "R1",
        method: "M01",
        transform: "quintile5",
        horizon: 5,
        rank_ic: -0.0858,
        hit_rate: 0.5638,
        base_rate: 0.4755,
        holdout_hit_rate: 0.5394,
        p_adj: 0.0000027,
        n: 3372,
        status: "candidate",
        gate_pass: 0,
      },
    ],
    discovery: [
      {
        method: "B14",
        series: "ETH",
        transform: "diff",
        horizon: 5,
        rank_ic: -0.11,
        holdout_ic: -0.25,
        p_adj: 0.0057,
        stability: 1,
        n: 890,
        status: "candidate",
        eval_at: "2026-11-17T01:41:13",
        data_version: "db@20261117",
      },
      {
        method: "B14",
        series: "ETH",
        transform: "raw",
        horizon: 10,
        rank_ic: -0.09,
        holdout_ic: -0.12,
        p_adj: 0.02,
        stability: 1,
        n: 880,
        status: "candidate",
        eval_at: "2026-11-17T01:41:13",
        data_version: "db@20261117",
      },
    ],
    caveats: ["当前无通过门禁的关系；以下全部为未验证的历史候选"],
  },
};

describe("fetchResearchEvidence", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("归一 candidate-only 证据并保留口径", async () => {
    global.fetch = jest.fn(() => mockJson(PAYLOAD)) as unknown as typeof fetch;
    const evidence = await fetchResearchEvidence("ETH", { horizon: 5 });
    expect(evidence.available).toBe(true);
    expect(evidence.status).toBe("candidate_only");
    expect(evidence.gate_pass).toBe(0);
    expect(evidence.data_version).toBe("db@20261117");
    expect(evidence.as_of).toBe("2026-11-16");
    expect(evidence.top[0].method).toBe("M01");
    expect(evidence.caveats[0]).toContain("无通过门禁");

    const brief = renderResearchBrief(evidence);
    expect(brief).toContain("gate_pass=0");
    expect(brief).toContain("RankIC=-0.0858");
    expect(brief.length).toBeLessThanOrEqual(600);

    const visuals = buildResearchVisuals(evidence);
    expect(visuals[0].kind).toBe("table");
    expect(visuals[0].spec_version).toBe("1.0");
    expect(visuals[0].dataset.rows).toHaveLength(1);
    expect(visuals[1]?.kind).toBe("matrix");
  });

  it("接口 503 时 FAIL-OPEN 为 unavailable", async () => {
    global.fetch = jest.fn(() => mockJson({ ok: false }, 503)) as unknown as typeof fetch;
    const evidence = await fetchResearchEvidence("SOL");
    expect(evidence.available).toBe(false);
    expect(evidence.status).toBe("unavailable");
    expect(evidence.reason).toContain("503");
  });

  it("A 股代码不发起请求", async () => {
    const spy = jest.fn();
    global.fetch = spy as unknown as typeof fetch;
    const evidence = await fetchResearchEvidence("600519.SH");
    expect(spy).not.toHaveBeenCalled();
    expect(evidence.available).toBe(false);
    expect(evidence.reason).toContain("MERS");
  });

  it("60s 内同标的不重复请求", async () => {
    const spy = jest.fn(() => mockJson(PAYLOAD));
    global.fetch = spy as unknown as typeof fetch;
    await fetchResearchEvidence("DOGE", { horizon: 5 });
    await fetchResearchEvidence("DOGE", { horizon: 5 });
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("深链带 base 参数", () => {
    expect(researchLink("ETH/USDT")).toBe("/dashboard/visual/research?base=ETH");
  });
});
