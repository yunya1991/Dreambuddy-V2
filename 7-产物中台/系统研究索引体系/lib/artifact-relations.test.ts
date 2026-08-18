import test from "node:test";
import assert from "node:assert/strict";

import { buildArtifactRelations, groupRelationsByPhase } from "./artifact-relations.ts";

test("buildArtifactRelations derives feed and chain links from canonical index entries", () => {
  const relations = buildArtifactRelations([
    {
      id: "trading/a3-001",
      artifactId: "a3-001",
      category: "trading",
      department: "trading",
      type: "strategy",
      status: "completed",
      date: "2026-05-21T10:00:00Z",
      chainPhase: "A3",
      tags: ["strategy"],
      title: "A3 Strategy",
      excerpt: "x",
      sourcePath: "/tmp/a3.md",
      sourceFile: "a3.md",
      sourceType: "markdown",
      detailUrl: "/feed/trading/a3-001",
    },
  ]);

  assert.deepEqual(relations, [
    {
      artifactId: "a3-001",
      chainPhase: "A3",
      feedHref: "/feed/trading/a3-001",
      chainHref: "/chain?phase=A3&artifact=a3-001",
      nodeId: "A3",
      title: "A3 Strategy",
      date: "2026-05-21T10:00:00Z",
    },
  ]);
});

test("buildArtifactRelations skips canonical entries that do not have chainPhase", () => {
  const relations = buildArtifactRelations([
    {
      id: "knowledge/k-001",
      artifactId: "k-001",
      category: "knowledge",
      department: "knowledge",
      type: "note",
      status: "completed",
      date: "2026-05-21T11:00:00Z",
      chainPhase: "",
      tags: [],
      title: "No phase",
      excerpt: "x",
      sourcePath: "/tmp/k.md",
      sourceFile: "k.md",
      sourceType: "markdown",
      detailUrl: "/feed/knowledge/k-001",
    },
  ]);

  assert.deepEqual(relations, []);
});

test("groupRelationsByPhase keeps latest artifacts first within each phase", () => {
  const grouped = groupRelationsByPhase(
    [
      {
        artifactId: "old-a6",
        chainPhase: "A6",
        feedHref: "/feed/trading/old-a6",
        chainHref: "/chain?phase=A6&artifact=old-a6",
        nodeId: "A6",
        title: "Old A6",
        date: "2026-05-20T10:00:00Z",
      },
      {
        artifactId: "new-a6",
        chainPhase: "A6",
        feedHref: "/feed/trading/new-a6",
        chainHref: "/chain?phase=A6&artifact=new-a6",
        nodeId: "A6",
        title: "New A6",
        date: "2026-05-21T10:00:00Z",
      },
    ],
    1,
  );

  assert.equal(grouped.A6.length, 1);
  assert.equal(grouped.A6[0].artifactId, "new-a6");
});
