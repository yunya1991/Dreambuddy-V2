import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { buildArtifactRelations } from "../../lib/artifact-relations.ts";
import { findArtifactChainRelation } from "./feed-chain-link.ts";

test("feed detail can build a chain locator link from artifact relations", () => {
  const relation = findArtifactChainRelation(
    "feed-001",
    buildArtifactRelations([
      {
        id: "trading/feed-001",
        artifactId: "feed-001",
        category: "trading",
        department: "trading",
        type: "strategy",
        status: "completed",
        date: "2026-05-21T14:00:00Z",
        chainPhase: "A5",
        tags: [],
        title: "Feed detail",
        excerpt: "x",
        sourcePath: "/tmp/feed.md",
        sourceFile: "feed.md",
        sourceType: "markdown",
        detailUrl: "/feed/trading/feed-001",
      },
    ]),
  );

  assert.ok(relation);

  const html = renderToStaticMarkup(
    React.createElement("a", { href: relation.chainHref }, "查看 Chain 定位"),
  );

  assert.ok(html.includes('href="/chain?phase=A5&amp;artifact=feed-001"'));
  assert.ok(html.includes("查看 Chain 定位"));
});
