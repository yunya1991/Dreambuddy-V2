import test from "node:test";
import assert from "node:assert/strict";

import { shouldBypassPreviewAuth } from "../src/middleware";

test("dev preview bypass includes recharge page", () => {
  assert.equal(shouldBypassPreviewAuth("/recharge", true, false), true);
});

test("production does not bypass recharge page", () => {
  assert.equal(shouldBypassPreviewAuth("/recharge", false, false), false);
});

test("localhost preview bypass includes dashboard in production mode", () => {
  assert.equal(shouldBypassPreviewAuth("/dashboard", false, true), true);
});

test("localhost preview bypass includes recharge in production mode", () => {
  assert.equal(shouldBypassPreviewAuth("/recharge", false, true), true);
});
