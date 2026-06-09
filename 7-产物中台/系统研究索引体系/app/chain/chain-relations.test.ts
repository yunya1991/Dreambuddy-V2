import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { ChainRelatedArtifactsPanel } from "./chain-related-artifacts.ts";

test("ChainRelatedArtifactsPanel renders related feed artifacts for a phase", () => {
  const html = renderToStaticMarkup(
    React.createElement(ChainRelatedArtifactsPanel, {
      phaseArtifacts: {
        A6: [
          {
            artifactId: "intel-001",
            chainPhase: "A6",
            feedHref: "/feed/trading/intel-001",
            chainHref: "/chain?phase=A6&artifact=intel-001",
            nodeId: "A6",
            title: "A6 情报简报",
            date: "2026-05-21T15:00:00Z",
          },
        ],
      },
      focusPhase: "A6",
      focusArtifactId: "intel-001",
    }),
  );

  assert.ok(html.includes("最近关联产物"));
  assert.ok(html.includes("A6 情报简报"));
  assert.ok(html.includes('href="/feed/trading/intel-001"'));
});
