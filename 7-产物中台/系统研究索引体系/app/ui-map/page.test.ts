import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

test("ui-map route entry renders the shell and uses the shell view model", () => {
  const source = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");

  assert.match(source, /export default function UIMapPage/);
  assert.match(source, /buildUIMapShellViewModel/);
  assert.match(source, /UIMapClient/);
  assert.match(source, /buildSystemResearchUIMapOverride/);
});
