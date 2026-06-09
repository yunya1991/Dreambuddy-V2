import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import VerifyEmailPage from "../src/app/verify-email/page";

test("verify-email page renders verification guidance", () => {
  const html = renderToStaticMarkup(React.createElement(VerifyEmailPage));

  assert.match(html, /验证邮箱/);
  assert.match(html, /继续前请先完成邮箱验证/);
});
