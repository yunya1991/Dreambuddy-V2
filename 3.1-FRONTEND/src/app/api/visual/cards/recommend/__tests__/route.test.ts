// GET/POST /api/visual/cards/recommend 契约测试（SPEC-54d）

import { promises as fs } from "fs";

jest.mock("next/server", () => ({
  NextResponse: {
    json: (body: unknown, init?: { status?: number }) => ({
      status: init?.status ?? 200,
      json: async () => body,
    }),
  },
}));
jest.mock("fs", () => ({ promises: { readFile: jest.fn() } }));
jest.mock("child_process", () => ({
  execFile: jest.fn((...args: unknown[]) => {
    const callback = args[args.length - 1] as (
      err: unknown,
      out: unknown,
    ) => void;
    callback(null, { stdout: '{"ok":true}', stderr: "" });
  }),
}));

import { GET, POST } from "../route";

const readFile = fs.readFile as unknown as jest.Mock;

function artifact() {
  return JSON.stringify({
    generated_at: new Date().toISOString(),
    disclaimer: "历史统计，不代表未来",
    cards: [
      {
        capability_id: "D-E15",
        title: "趋势跟踪：价格 + EMA26",
        kind: "series",
        args: { symbol: "BTC", days: 750 },
        win_rate_20d: 0.5466,
        n_20d: 1727,
        score: 0.5151,
        desc: "收盘价站上 EMA26",
      },
      { capability_id: "", title: "脏数据" },
      { capability_id: "D-E01", title: "20 日动量", kind: "table", args: {} },
    ],
  });
}

beforeEach(() => {
  readFile.mockReset();
  jest.spyOn(console, "error").mockImplementation(() => undefined);
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe("GET /api/visual/cards/recommend", () => {
  it("制品存在 → source=artifact 且过滤脏卡", async () => {
    readFile.mockResolvedValue(artifact());
    const response = await GET();
    const body = await response.json();
    expect(body.ok).toBe(true);
    expect(body.source).toBe("artifact");
    expect(
      body.cards.map((card: { capability_id: string }) => card.capability_id),
    ).toEqual(["D-E15", "D-E01"]);
    expect(body.cards[0].win_rate_20d).toBe(0.5466);
    expect(body.stale).toBe(false);
  });

  it("制品缺失 → source=builtin 空列表（前端静态兜底）", async () => {
    readFile.mockRejectedValue(new Error("ENOENT"));
    const body = await (await GET()).json();
    expect(body).toEqual({
      ok: true,
      code: "builtin",
      source: "builtin",
      cards: [],
    });
  });
});

describe("POST /api/visual/cards/recommend", () => {
  it("重跑脚本成功后回读制品", async () => {
    readFile.mockResolvedValue(artifact());
    const body = await (await POST({} as Parameters<typeof POST>[0])).json();
    expect(body.ok).toBe(true);
    expect(body.source).toBe("artifact");
    expect(body.cards).toHaveLength(2);
  });
});
