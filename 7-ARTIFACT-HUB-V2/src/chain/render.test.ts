import assert from "node:assert/strict";
import test from "node:test";
import { renderChainIndexHtml } from "./render.js";

test("renderChainIndexHtml includes workflow groups, anomalies, and feed links", () => {
  const html = renderChainIndexHtml(
    {
      workflowGroups: {
        legacy_chain: [
          {
            artifactId: "trading/a1",
            title: "A1",
            category: "trading",
            department: "trading",
            workflowType: "legacy_chain",
            chainPhase: "A3",
            status: "completed",
            feedUrl: "/feed/trading/a1"
          }
        ],
        trading_v2: []
      },
      anomalies: [
        { kind: "missing_result", artifactId: "trading/a2", workflowType: "trading_v2" }
      ]
    },
    "legacy_chain"
  );

  assert.match(html, /Chain Monitor/);
  assert.match(html, /legacy_chain/);
  assert.match(html, /missing_result/);
  assert.match(html, /href="\/feed\/trading\/a1"/);
});

test("renderChainIndexHtml renders selected cross-link context for a feed artifact", () => {
  const html = renderChainIndexHtml(
    {
      workflowGroups: {
        legacy_chain: [
          {
            artifactId: "trading/a1",
            title: "A1",
            category: "trading",
            department: "trading",
            workflowType: "legacy_chain",
            chainPhase: "A3",
            status: "completed",
            feedUrl: "/feed/trading/a1"
          }
        ],
        trading_v2: []
      },
      anomalies: []
    },
    "legacy_chain",
    "trading/a1"
  );

  assert.match(html, /交叉链接上下文/);
  assert.match(html, /当前产物/);
  assert.match(html, /trading\/a1/);
  assert.match(html, /href="\/feed\/trading\/a1"/);
  assert.match(html, /chain-card selected/);
});
