import { extractJsonObject, loadGateClientConfig } from "./gate-client";

describe("gate-client", () => {
  it("缺少任一凭据即返回 null", () => {
    expect(loadGateClientConfig({})).toBeNull();
    expect(
      loadGateClientConfig({
        MODEL_GATE_BASE_URL: "https://example.com/v1",
        MODEL_GATE_API_KEY: "k",
      }),
    ).toBeNull();
  });

  it("读取配置并去掉末尾斜杠", () => {
    const config = loadGateClientConfig({
      MODEL_GATE_BASE_URL: "https://example.com/v1/",
      MODEL_GATE_API_KEY: "k",
      MODEL_GATE: "qwen4-max",
      MODEL_GATE_DISABLE_THINKING: "1",
    });
    expect(config).toMatchObject({
      baseUrl: "https://example.com/v1",
      model: "qwen4-max",
      timeoutMs: 20000,
      maxTokens: 600,
      disableThinking: true,
    });
  });

  it("能从代码围栏中提取 JSON", () => {
    expect(
      extractJsonObject('```json\n{"verdict":"pass"}\n```'),
    ).toEqual({ verdict: "pass" });
  });

  it("非 JSON 内容直接抛错（由上层降级为 needs_human）", () => {
    expect(() => extractJsonObject("not json")).toThrow();
    expect(() => extractJsonObject("")).toThrow();
  });
});
