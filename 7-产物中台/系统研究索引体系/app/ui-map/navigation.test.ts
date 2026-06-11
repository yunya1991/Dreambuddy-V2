import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

test("ui-map is promoted as hub entry and keeps dual perspective layer", () => {
  const homeSource = readFileSync(new URL("../page.tsx", import.meta.url), "utf8");
  const headerSource = readFileSync(new URL("../../components/Header.tsx", import.meta.url), "utf8");
  const shellSource = readFileSync(new URL("./UIMapShell.tsx", import.meta.url), "utf8");
  const viewModelSource = readFileSync(new URL("./ui-map-shell-view-model.ts", import.meta.url), "utf8");

  assert.match(homeSource, /redirect\(['"]\/ui-map['"]\)/);
  assert.match(headerSource, /href=['"]\/ui-map['"]/);
  assert.match(shellSource, /perspectiveLayer/);
  assert.match(viewModelSource, /系统研究链路/);
  assert.match(viewModelSource, /系统运营链路/);
});
