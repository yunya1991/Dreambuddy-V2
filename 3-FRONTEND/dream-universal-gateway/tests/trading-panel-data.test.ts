import test from "node:test";
import assert from "node:assert/strict";

import {
  getDefaultTradingPanelData,
  normalizeTradingPanelData,
} from "../src/app/dashboard/trading-panel-data";

test("normalizeTradingPanelData falls back to defaults for malformed payload", () => {
  const normalized = normalizeTradingPanelData({});
  const defaults = getDefaultTradingPanelData();

  assert.deepEqual(normalized, defaults);
});

test("normalizeTradingPanelData preserves provided values and fills missing fields", () => {
  const normalized = normalizeTradingPanelData({
    params: {
      tradeMode: "SWAP_MODE",
      leverageMax: 5,
      availableCapital: 1200,
    },
    liveStatus: {
      todayLoss: 12.5,
      status: "PAUSED",
    },
    exchangeStatus: {
      provider: "okx",
      isConfigured: true,
      isVerified: false,
      environment: "demo",
    },
  });

  assert.equal(normalized.params.tradeMode, "SWAP_MODE");
  assert.equal(normalized.params.leverageMax, 5);
  assert.equal(normalized.params.availableCapital, 1200);
  assert.equal(normalized.params.dailyLossLimit, 500);
  assert.equal(normalized.liveStatus.todayLoss, 12.5);
  assert.equal(normalized.liveStatus.totalLoss, 0);
  assert.equal(normalized.liveStatus.status, "PAUSED");
  assert.equal(normalized.exchangeStatus?.provider, "okx");
});
