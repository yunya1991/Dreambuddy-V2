export interface TradingPanelData {
  params: {
    availableCapital?: number | null;
    capitalPercentage: number;
    tradeType: string;
    tradeMode: string;
    marginMode?: string | null;
    positionMode: string;
    leverageMax: number;
    dailyLossLimit: number;
    dailyLossPercent: number;
    accountLossLimit: number;
    accountLossPercent: number;
    allowedSymbols: string[];
    allowedTradeModes: string[];
    isTradingEnabled: boolean;
    optionsType?: string | null;
    expiryDate?: string | null;
    riskTolerance: string;
    preferredFrequency?: string | null;
  };
  liveStatus: {
    todayLoss: number;
    todayTradeCount: number;
    totalLoss: number;
    totalTradeCount: number;
    status: string;
    lastResetDate: string;
  };
  exchangeStatus: {
    provider: string;
    isConfigured: boolean;
    isVerified: boolean;
    environment: string;
    lastVerifiedAt?: string;
  } | null;
}

function asNumber(value: unknown, fallback: number) {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asString(value: unknown, fallback: string) {
  return typeof value === "string" && value.length > 0 ? value : fallback;
}

function asStringArray(value: unknown, fallback: string[]) {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
    ? value
    : fallback;
}

export function getDefaultTradingPanelData(): TradingPanelData {
  return {
    params: {
      availableCapital: null,
      capitalPercentage: 0.1,
      tradeType: "SPOT",
      tradeMode: "SPOT_MODE",
      marginMode: null,
      positionMode: "NET",
      leverageMax: 3,
      dailyLossLimit: 500,
      dailyLossPercent: 0.05,
      accountLossLimit: 2000,
      accountLossPercent: 0.2,
      allowedSymbols: ["BTC-USDT-SWAP"],
      allowedTradeModes: ["SPOT_MODE"],
      isTradingEnabled: false,
      optionsType: null,
      expiryDate: null,
      riskTolerance: "MODERATE",
      preferredFrequency: "FOUR_H",
    },
    liveStatus: {
      todayLoss: 0,
      todayTradeCount: 0,
      totalLoss: 0,
      totalTradeCount: 0,
      status: "ACTIVE",
      lastResetDate: new Date().toISOString().split("T")[0],
    },
    exchangeStatus: null,
  };
}

export function normalizeTradingPanelData(value: unknown): TradingPanelData {
  const defaults = getDefaultTradingPanelData();
  const source = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  const rawParams =
    source.params && typeof source.params === "object"
      ? (source.params as Record<string, unknown>)
      : {};
  const rawLiveStatus =
    source.liveStatus && typeof source.liveStatus === "object"
      ? (source.liveStatus as Record<string, unknown>)
      : {};
  const rawExchangeStatus =
    source.exchangeStatus && typeof source.exchangeStatus === "object"
      ? (source.exchangeStatus as Record<string, unknown>)
      : null;

  return {
    params: {
      availableCapital:
        typeof rawParams.availableCapital === "number" && Number.isFinite(rawParams.availableCapital)
          ? rawParams.availableCapital
          : defaults.params.availableCapital,
      capitalPercentage: asNumber(rawParams.capitalPercentage, defaults.params.capitalPercentage),
      tradeType: asString(rawParams.tradeType, defaults.params.tradeType),
      tradeMode: asString(rawParams.tradeMode, defaults.params.tradeMode),
      marginMode: typeof rawParams.marginMode === "string" ? rawParams.marginMode : defaults.params.marginMode,
      positionMode: asString(rawParams.positionMode, defaults.params.positionMode),
      leverageMax: asNumber(rawParams.leverageMax, defaults.params.leverageMax),
      dailyLossLimit: asNumber(rawParams.dailyLossLimit, defaults.params.dailyLossLimit),
      dailyLossPercent: asNumber(rawParams.dailyLossPercent, defaults.params.dailyLossPercent),
      accountLossLimit: asNumber(rawParams.accountLossLimit, defaults.params.accountLossLimit),
      accountLossPercent: asNumber(rawParams.accountLossPercent, defaults.params.accountLossPercent),
      allowedSymbols: asStringArray(rawParams.allowedSymbols, defaults.params.allowedSymbols),
      allowedTradeModes: asStringArray(rawParams.allowedTradeModes, defaults.params.allowedTradeModes),
      isTradingEnabled:
        typeof rawParams.isTradingEnabled === "boolean"
          ? rawParams.isTradingEnabled
          : defaults.params.isTradingEnabled,
      optionsType: typeof rawParams.optionsType === "string" ? rawParams.optionsType : defaults.params.optionsType,
      expiryDate: typeof rawParams.expiryDate === "string" ? rawParams.expiryDate : defaults.params.expiryDate,
      riskTolerance: asString(rawParams.riskTolerance, defaults.params.riskTolerance),
      preferredFrequency:
        typeof rawParams.preferredFrequency === "string"
          ? rawParams.preferredFrequency
          : defaults.params.preferredFrequency,
    },
    liveStatus: {
      todayLoss: asNumber(rawLiveStatus.todayLoss, defaults.liveStatus.todayLoss),
      todayTradeCount: asNumber(rawLiveStatus.todayTradeCount, defaults.liveStatus.todayTradeCount),
      totalLoss: asNumber(rawLiveStatus.totalLoss, defaults.liveStatus.totalLoss),
      totalTradeCount: asNumber(rawLiveStatus.totalTradeCount, defaults.liveStatus.totalTradeCount),
      status: asString(rawLiveStatus.status, defaults.liveStatus.status),
      lastResetDate: asString(rawLiveStatus.lastResetDate, defaults.liveStatus.lastResetDate),
    },
    exchangeStatus: rawExchangeStatus
      ? {
          provider: asString(rawExchangeStatus.provider, ""),
          isConfigured:
            typeof rawExchangeStatus.isConfigured === "boolean"
              ? rawExchangeStatus.isConfigured
              : false,
          isVerified:
            typeof rawExchangeStatus.isVerified === "boolean" ? rawExchangeStatus.isVerified : false,
          environment: asString(rawExchangeStatus.environment, "demo"),
          lastVerifiedAt:
            typeof rawExchangeStatus.lastVerifiedAt === "string"
              ? rawExchangeStatus.lastVerifiedAt
              : undefined,
        }
      : null,
  };
}
