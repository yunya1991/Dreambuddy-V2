import test from "node:test";
import assert from "node:assert/strict";

import { navigateToRecharge } from "../src/app/dashboard/navigation";

test("navigateToRecharge pushes recharge route", () => {
  let pushedPath = "";

  navigateToRecharge({
    push(path: string) {
      pushedPath = path;
    },
  });

  assert.equal(pushedPath, "/recharge");
});
