import test from "node:test";
import assert from "node:assert/strict";

import { getAuthRuntimeOptions } from "../src/lib/auth-runtime";

test("rewrites localhost nextauth url to current app port", () => {
  const runtime = getAuthRuntimeOptions({
    NEXTAUTH_URL: "http://localhost:3456",
    PORT: "3000",
  });

  assert.equal(runtime.baseUrl, "http://localhost:3000");
});

test("keeps external nextauth url unchanged", () => {
  const runtime = getAuthRuntimeOptions({
    NEXTAUTH_URL: "https://gateway.example.com",
    PORT: "3000",
  });

  assert.equal(runtime.baseUrl, "https://gateway.example.com");
});

test("trusts localhost auth host automatically", () => {
  const runtime = getAuthRuntimeOptions({
    NEXTAUTH_URL: "http://localhost:3456",
    PORT: "3000",
  });

  assert.equal(runtime.trustHost, true);
});
