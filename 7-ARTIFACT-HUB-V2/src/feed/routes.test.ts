import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import type { Server } from "node:http";
import { createHubServer } from "../server.js";

function listen(server: Server): Promise<{ baseUrl: string; close: () => Promise<void> }> {
  return new Promise((resolve, reject) => {
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        reject(new Error("failed_to_listen"));
        return;
      }

      resolve({
        baseUrl: `http://127.0.0.1:${address.port}`,
        close: () =>
          new Promise((done, closeReject) => {
            server.close((error) => {
              if (error) {
                closeReject(error);
                return;
              }
              done();
            });
          })
      });
    });
  });
}

test("createHubServer serves /feed list, category, and detail pages", async () => {
  const artifactsRoot = fs.mkdtempSync(path.join(os.tmpdir(), "feed-routes-artifacts-"));
  const metaRoot = fs.mkdtempSync(path.join(os.tmpdir(), "feed-routes-meta-"));
  const tradingDir = path.join(artifactsRoot, "trading");
  fs.mkdirSync(tradingDir, { recursive: true });

  fs.writeFileSync(
    path.join(tradingDir, "index.json"),
    JSON.stringify({
      last_updated: "2026-05-20T00:00:00Z",
      artifacts: [
        {
          artifact_id: "trading/a1",
          title: "Alpha Report",
          filename: "a1.md",
          type: "report",
          status: "completed",
          chain_phase: "A3",
          workflow_id: "wf-1",
          workflow_type: "legacy_chain",
          trace_id: "trace-1"
        },
        {
          artifact_id: "trading/a2",
          title: "Beta Report",
          filename: "a2.md",
          type: "report",
          status: "failed",
          chain_phase: "A5"
        }
      ]
    })
  );
  fs.writeFileSync(path.join(tradingDir, "a1.md"), "# Alpha Report\n\nBody");
  fs.writeFileSync(path.join(tradingDir, "a2.md"), "# Beta Report\n\nBody");

  const server = createHubServer({ artifactsRoot, metaRoot });
  const { baseUrl, close } = await listen(server);

  try {
    const listRes = await fetch(`${baseUrl}/feed?department=trading&status=completed&chainPhase=A3&limit=1&offset=0`);
    const categoryRes = await fetch(`${baseUrl}/feed/trading`);
    const detailRes = await fetch(`${baseUrl}/feed/trading/a1`);
    const listHtml = await listRes.text();
    const categoryHtml = await categoryRes.text();
    const detailHtml = await detailRes.text();

    assert.equal(listRes.status, 200);
    assert.match(listHtml, /Dream 产物中心|Feed Content Portal/);
    assert.match(listHtml, /组织架构/);
    assert.match(listHtml, /href="\/feed\/trading\/a1"/);
    assert.doesNotMatch(listHtml, /Beta Report/);

    assert.equal(categoryRes.status, 200);
    assert.match(categoryHtml, /Alpha Report/);
    assert.match(categoryHtml, /href="\/feed\/trading\/a1"/);

    assert.equal(detailRes.status, 200);
    assert.match(detailHtml, /Alpha Report/);
    assert.match(detailHtml, /Body/);
    assert.match(detailHtml, /trace-1/);
    assert.match(detailHtml, /查看链路监控/);
    assert.match(detailHtml, /\/chain\/legacy_chain\?artifactId=trading%2Fa1/);
  } finally {
    await close();
    fs.rmSync(artifactsRoot, { recursive: true, force: true });
    fs.rmSync(metaRoot, { recursive: true, force: true });
  }
});

test("createHubServer exposes P0 department and stage entrances on /feed", async () => {
  const artifactsRoot = fs.mkdtempSync(path.join(os.tmpdir(), "feed-routes-home-artifacts-"));
  const metaRoot = fs.mkdtempSync(path.join(os.tmpdir(), "feed-routes-home-meta-"));
  const researchDir = path.join(artifactsRoot, "research");
  const tradingDir = path.join(artifactsRoot, "trading");
  fs.mkdirSync(researchDir, { recursive: true });
  fs.mkdirSync(tradingDir, { recursive: true });

  fs.writeFileSync(
    path.join(researchDir, "index.json"),
    JSON.stringify({
      last_updated: "2026-05-20T00:00:00Z",
      artifacts: [
        {
          artifact_id: "research/dream-note-001",
          title: "Dream Note",
          type: "note",
          status: "completed",
          chain_phase: "A3",
          tags: ["dream", "oneirology"]
        }
      ]
    })
  );
  fs.writeFileSync(
    path.join(tradingDir, "index.json"),
    JSON.stringify({
      last_updated: "2026-05-20T00:00:00Z",
      artifacts: [
        {
          artifact_id: "trading/order-001",
          title: "Order",
          type: "report",
          status: "completed",
          chain_phase: "A9"
        }
      ]
    })
  );

  const server = createHubServer({ artifactsRoot, metaRoot });
  const { baseUrl, close } = await listen(server);

  try {
    const res = await fetch(`${baseUrl}/feed`);
    const html = await res.text();

    assert.equal(res.status, 200);
    assert.match(html, /做梦部/);
    assert.match(html, /A0/);
    assert.match(html, /A9/);
  } finally {
    await close();
    fs.rmSync(artifactsRoot, { recursive: true, force: true });
    fs.rmSync(metaRoot, { recursive: true, force: true });
  }
});

test("department entrance for 做梦部 returns a non-empty list using temporary research mapping", async () => {
  const artifactsRoot = fs.mkdtempSync(path.join(os.tmpdir(), "feed-routes-dream-artifacts-"));
  const metaRoot = fs.mkdtempSync(path.join(os.tmpdir(), "feed-routes-dream-meta-"));
  const researchDir = path.join(artifactsRoot, "research");
  fs.mkdirSync(researchDir, { recursive: true });

  fs.writeFileSync(
    path.join(researchDir, "index.json"),
    JSON.stringify({
      last_updated: "2026-05-20T00:00:00Z",
      artifacts: [
        {
          artifact_id: "research/dream-note-001",
          title: "Dream Note",
          type: "note",
          status: "completed",
          chain_phase: "A3",
          tags: ["dream", "oneirology"]
        },
        {
          artifact_id: "research/intel-a1",
          title: "Intel",
          type: "report",
          status: "completed",
          chain_phase: "A1",
          tags: ["market-analysis"]
        }
      ]
    })
  );

  const server = createHubServer({ artifactsRoot, metaRoot });
  const { baseUrl, close } = await listen(server);

  try {
    const res = await fetch(`${baseUrl}/feed?department=${encodeURIComponent("做梦部")}`);
    assert.equal(res.status, 200);
    const html = await res.text();

    assert.match(html, /做梦部/);
    assert.match(html, /Dream Note/);
    assert.doesNotMatch(html, /Intel/);
    assert.doesNotMatch(html, /暂无相关产物|No artifacts found/);
  } finally {
    await close();
    fs.rmSync(artifactsRoot, { recursive: true, force: true });
    fs.rmSync(metaRoot, { recursive: true, force: true });
  }
});

test("A-stage entrance for A1 returns matching items and A0 returns an explicit empty state", async () => {
  const artifactsRoot = fs.mkdtempSync(path.join(os.tmpdir(), "feed-routes-stage-artifacts-"));
  const metaRoot = fs.mkdtempSync(path.join(os.tmpdir(), "feed-routes-stage-meta-"));
  const researchDir = path.join(artifactsRoot, "research");
  fs.mkdirSync(researchDir, { recursive: true });

  fs.writeFileSync(
    path.join(researchDir, "index.json"),
    JSON.stringify({
      last_updated: "2026-05-20T00:00:00Z",
      artifacts: [
        {
          artifact_id: "research/intel-a1",
          title: "Intel",
          type: "report",
          status: "completed",
          chain_phase: "A1",
          tags: ["market-analysis"]
        },
        {
          artifact_id: "research/dream-note-001",
          title: "Dream Note",
          type: "note",
          status: "completed",
          chain_phase: "A3",
          tags: ["dream", "oneirology"]
        }
      ]
    })
  );

  const server = createHubServer({ artifactsRoot, metaRoot });
  const { baseUrl, close } = await listen(server);

  try {
    const a1 = await fetch(`${baseUrl}/feed?chainPhase=A1`);
    const a0 = await fetch(`${baseUrl}/feed?chainPhase=A0`);
    assert.equal(a1.status, 200);
    assert.equal(a0.status, 200);

    const a1Html = await a1.text();
    const a0Html = await a0.text();
    assert.match(a1Html, /A1/);
    assert.match(a1Html, /Intel/);
    assert.match(a0Html, /A0/);
    assert.match(a0Html, /暂无相关产物/);
  } finally {
    await close();
    fs.rmSync(artifactsRoot, { recursive: true, force: true });
    fs.rmSync(metaRoot, { recursive: true, force: true });
  }
});

test("feed P0 homepage exposes 做梦部 and fixed A0-A9 entrances", async () => {
  const artifactsRoot = fs.mkdtempSync(path.join(os.tmpdir(), "feed-routes-p0-home-artifacts-"));
  const metaRoot = fs.mkdtempSync(path.join(os.tmpdir(), "feed-routes-p0-home-meta-"));
  const researchDir = path.join(artifactsRoot, "research");
  const tradingDir = path.join(artifactsRoot, "trading");
  fs.mkdirSync(researchDir, { recursive: true });
  fs.mkdirSync(tradingDir, { recursive: true });

  fs.writeFileSync(
    path.join(researchDir, "index.json"),
    JSON.stringify({
      last_updated: "2026-05-20T00:00:00Z",
      artifacts: [
        {
          artifact_id: "research/dream-note-001",
          title: "Dream Note",
          type: "note",
          status: "completed",
          chain_phase: "A3",
          tags: ["dream", "oneirology"]
        },
        {
          artifact_id: "research/intel-a1",
          title: "Intel",
          type: "report",
          status: "completed",
          chain_phase: "A1",
          tags: ["market-analysis"]
        }
      ]
    })
  );
  fs.writeFileSync(
    path.join(tradingDir, "index.json"),
    JSON.stringify({
      last_updated: "2026-05-20T00:00:00Z",
      artifacts: [
        {
          artifact_id: "trading/order-001",
          title: "Order",
          type: "report",
          status: "completed",
          chain_phase: "A9"
        }
      ]
    })
  );

  const server = createHubServer({ artifactsRoot, metaRoot });
  const { baseUrl, close } = await listen(server);

  try {
    const res = await fetch(`${baseUrl}/feed`);
    const html = await res.text();

    assert.equal(res.status, 200);
    assert.match(html, /做梦部/);
    for (const label of ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9"]) {
      assert.match(html, new RegExp(label));
    }
  } finally {
    await close();
    fs.rmSync(artifactsRoot, { recursive: true, force: true });
    fs.rmSync(metaRoot, { recursive: true, force: true });
  }
});
