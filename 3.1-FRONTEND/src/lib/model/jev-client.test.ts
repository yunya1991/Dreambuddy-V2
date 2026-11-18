import {
  buildJevQuestions,
  loadJevClientConfig,
  mapJevResponse,
} from "./jev-client";

describe("jev-client", () => {
  it("缺少 API key 返回 null", () => {
    expect(loadJevClientConfig({})).toBeNull();
  });

  it("默认模型与超时", () => {
    const config = loadJevClientConfig({ TYPESAFE_API_KEY: "k" });
    expect(config).toMatchObject({
      baseUrl: "https://api.typesafe.ai",
      model: "jev-latest",
      timeoutMs: 10000,
    });
  });

  it("问题只包含完成度与质量，不涉及方向", () => {
    const questions = buildJevQuestions();
    expect(Object.keys(questions)).toEqual([
      "task_complete",
      "quality_score",
    ]);
    expect(JSON.stringify(questions)).toContain("不判断市场方向");
  });

  it("高置信完成 → pass", () => {
    const verdict = mapJevResponse({
      answers: {
        task_complete: { noul: 0.95 },
        quality_score: { score: 2, legend: ["a", "b", "c", "d"] },
      },
    });
    expect(verdict.verdict).toBe("pass");
    expect(verdict.confidence).toBe(0.95);
  });

  it("低完成度 → fail", () => {
    const verdict = mapJevResponse({
      answers: { task_complete: { noul: 0.3 }, quality_score: { score: 1 } },
    });
    expect(verdict.verdict).toBe("fail");
  });

  it("中间置信区间 → needs_human", () => {
    const verdict = mapJevResponse({
      answers: { task_complete: { noul: 0.6 }, quality_score: { score: 3 } },
    });
    expect(verdict.verdict).toBe("needs_human");
    expect(verdict.degraded).toBe(true);
  });

  it("degraded 或缺少 noul 一律 needs_human", () => {
    expect(mapJevResponse({ degraded: true }).verdict).toBe("needs_human");
    expect(mapJevResponse({ answers: {} }).verdict).toBe("needs_human");
  });
});
