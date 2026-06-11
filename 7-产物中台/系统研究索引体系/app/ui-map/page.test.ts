import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

test("ui-map route entry renders the shell and wires all five real-data adapters", () => {
  const source = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");

  assert.match(source, /export default function UIMapPage/);
  assert.match(source, /buildUIMapShellViewModel/);
  assert.match(source, /UIMapClient/);

  assert.match(source, /buildSystemResearchUIMapOverride/, "page.tsx should wire the system-research real-data adapter");
  assert.match(source, /buildResearchChainUIMapOverride/, "page.tsx should wire the research-chain real-data adapter");
  assert.match(source, /buildOperationsUIMapOverride/, "page.tsx should wire the operations real-data adapter");
  assert.match(source, /buildStrategyUIMapOverride/, "page.tsx should wire the strategy real-data adapter");
  assert.match(source, /buildUserContextUIMapOverride/, "page.tsx should wire the user-context real-data adapter");
});
