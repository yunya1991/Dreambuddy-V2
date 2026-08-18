"use client";

import React, { useState } from "react";
import {
  useAutoConfigStore,
  CONFIG_STEPS_LIST,
  type AutoConfigResult,
} from "@/stores/auto-config-store";
import type {
  RiskTolerance,
  Frequency,
  ChannelType,
  PushMessageType,
} from "@/types";

// ============================================================
// UI Token Constants
// ============================================================
const COLORS = {
  bubbleBg: "#2C2C2A",
  bubbleRadius: "10px",
  bubblePadding: "12px 16px",
  inputBg: "#444441",
  inputBorder: "#5F5E5A",
  confirmDisabled: "#444441",
  confirmDisabledText: "#5F5E5A",
  confirmActive: "#378ADD",
  pillYes: "#1D9E75",
  pillNoBorder: "#888780",
  warnBg: "#A32D2D",
  progressDone: "#1D9E75",
  progressCurrent: "#378ADD",
  progressPending: "#888780",
  labelSkipped: "#BA7517",
  labelError: "#A32D2D",
} as const;

// ============================================================
// Sub-component: StepProgress (步骤进度指示器)
// ============================================================
function StepProgress() {
  const { currentStep, results } = useAutoConfigStore();

  return (
    <div className="flex items-center justify-center gap-1 mb-3">
      {CONFIG_STEPS_LIST.map((step, idx) => {
        const result = results.find((r) => r.step === idx);
        let dotColor: string = COLORS.progressPending;
        let statusIcon = "";

        if (result) {
          if (result.status === "configured") {
            dotColor = COLORS.progressDone;
            statusIcon = "✓";
          } else if (result.status === "skipped") {
            dotColor = COLORS.progressPending;
            statusIcon = "—";
          } else if (result.status === "error") {
            dotColor = COLORS.labelError;
            statusIcon = "!";
          }
        } else if (idx === currentStep) {
          dotColor = COLORS.progressCurrent;
        }

        return (
          <React.Fragment key={step.key}>
            {idx > 0 && (
              <div
                className="w-4 h-px mx-1"
                style={{
                  backgroundColor:
                    idx <= currentStep || result
                      ? COLORS.progressDone
                      : COLORS.progressPending,
                  opacity: 0.5,
                }}
              />
            )}
            <div className="flex flex-col items-center">
              <div
                className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold text-white"
                style={{ backgroundColor: dotColor }}
                title={step.label}
              >
                {statusIcon || idx + 1}
              </div>
              <span
                className="text-[9px] mt-0.5 whitespace-nowrap"
                style={{ color: COLORS.progressPending }}
              >
                {step.label}
              </span>
            </div>
          </React.Fragment>
        );
      })}
    </div>
  );
}

// ============================================================
// Sub-component: PillButtons (是/否药丸按钮)
// ============================================================
function PillButtons({
  onYes,
  onNo,
}: {
  onYes: () => void;
  onNo: () => void;
}) {
  return (
    <div className="flex gap-2 mt-3">
      <button
        onClick={onYes}
        className="px-4 py-1.5 rounded-full text-sm font-medium text-white transition-all hover:opacity-90"
        style={{ backgroundColor: COLORS.pillYes }}
      >
        是
      </button>
      <button
        onClick={onNo}
        className="px-4 py-1.5 rounded-full text-sm font-medium transition-all hover:opacity-90"
        style={{
          backgroundColor: "transparent",
          border: `1px solid ${COLORS.pillNoBorder}`,
          color: COLORS.pillNoBorder,
        }}
      >
        否
      </button>
    </div>
  );
}

// ============================================================
// Sub-component: ApiConfigForm (Step 1: API配置)
// ============================================================
function ApiConfigForm({ onSubmit }: { onSubmit: (data: Record<string, unknown>) => void }) {
  const [category, setCategory] = useState("EXCHANGE");
  const [provider, setProvider] = useState("OKX");
  const [label, setLabel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [environment, setEnvironment] = useState<"demo" | "live">("demo");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [verifyResult, setVerifyResult] = useState<"success" | "fail" | null>(null);

  const hasContent = label.trim() !== "" && apiKey.trim() !== "" && apiSecret.trim() !== "";

  const handleVerify = async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch("/api/config/api-keys/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, apiKey, secretKey: apiSecret, passphrase, environment }),
      });
      if (res.ok) {
        setVerifyResult("success");
      } else {
        const data = await res.json();
        setVerifyResult("fail");
        setError(data.error || "验证失败");
      }
    } catch {
      setVerifyResult("fail");
      setError("网络错误");
    }
    setLoading(false);
  };

  const handleSubmit = async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch("/api/config/api-keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category, provider, label, apiKey, secretKey: apiSecret, passphrase, environment }),
      });
      if (res.ok) {
        onSubmit({ category, provider, label, apiKey, secretKey: apiSecret, passphrase, environment });
      } else {
        const data = await res.json();
        setError(data.error || "保存失败");
      }
    } catch {
      setError("网络错误，请重试");
    }
    setLoading(false);
  };

  return (
    <div className="space-y-3 mt-3">
      <div>
        <label className="text-xs text-[#8a8a8a] mb-1 block">
          账户名 <span className="text-red-400">*</span>
        </label>
        <input
          type="text"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="如: 模拟盘1 / 实盘主账户"
          className="w-full px-3 py-2 rounded text-sm text-white placeholder-[#5F5E5A] focus:outline-none focus:border-[#378ADD]"
          style={{ backgroundColor: COLORS.inputBg, border: `1px solid ${COLORS.inputBorder}` }}
        />
      </div>

      <div>
        <label className="text-xs text-[#8a8a8a] mb-1 block">Exchange Provider</label>
        <select
          value={provider}
          onChange={(e) => setProvider(e.target.value)}
          className="w-full px-3 py-2 rounded text-sm text-white focus:outline-none"
          style={{ backgroundColor: COLORS.inputBg, border: `1px solid ${COLORS.inputBorder}` }}
        >
          <option value="OKX">OKX</option>
        </select>
      </div>

      {[
        { label: "API Key", value: apiKey, setter: setApiKey, placeholder: "sk-xxxxx..." },
        { label: "API Secret", value: apiSecret, setter: setApiSecret, placeholder: "xxxxx..." },
        { label: "Passphrase", value: passphrase, setter: setPassphrase, placeholder: "xxxxx..." },
      ].map(({ label, value, setter, placeholder }) => (
        <div key={label}>
          <label className="text-xs text-[#8a8a8a] mb-1 block">{label}</label>
          <input
            type="password"
            value={value}
            onChange={(e) => setter(e.target.value)}
            placeholder={placeholder}
            className="w-full px-3 py-2 rounded text-sm text-white placeholder-[#5F5E5A] focus:outline-none focus:border-[#378ADD]"
            style={{ backgroundColor: COLORS.inputBg, border: `1px solid ${COLORS.inputBorder}` }}
          />
        </div>
      ))}

      <div>
        <label className="text-xs text-[#8a8a8a] mb-1 block">环境</label>
        <div className="flex gap-4">
          {(["demo", "live"] as const).map((env) => (
            <label key={env} className="flex items-center gap-2 text-sm text-white cursor-pointer">
              <input
                type="radio"
                name="env"
                value={env}
                checked={environment === env}
                onChange={() => setEnvironment(env)}
                className="accent-[#378ADD]"
              />
              {env === "demo" ? "Demo (模拟)" : "Live (实盘)"}
            </label>
          ))}
        </div>
      </div>

      {verifyResult === "success" && (
        <div className="text-xs text-green-400 bg-green-500/10 px-3 py-2 rounded">✅ 连接验证成功</div>
      )}
      {verifyResult === "fail" && error && (
        <div className="text-xs text-red-400 bg-red-500/10 px-3 py-2 rounded">❌ {error}</div>
      )}
      {!verifyResult && error && (
        <div className="text-xs text-red-400 bg-red-500/10 px-3 py-2 rounded">❌ {error}</div>
      )}

      <div className="flex gap-2">
        <button
          onClick={handleVerify}
          disabled={loading || !apiKey}
          className="px-3 py-1.5 text-xs rounded transition"
          style={{
            backgroundColor: "#444441",
            color: apiKey ? "#378ADD" : COLORS.confirmDisabledText,
            border: `1px solid ${apiKey ? "#378ADD" : COLORS.inputBorder}`,
          }}
        >
          🔗 验证连接
        </button>
        <button
          onClick={handleSubmit}
          disabled={loading || !hasContent}
          className="px-4 py-1.5 text-xs rounded font-medium text-white transition ml-auto"
          style={{
            backgroundColor: hasContent ? COLORS.confirmActive : COLORS.confirmDisabled,
            color: hasContent ? "#fff" : COLORS.confirmDisabledText,
          }}
        >
          {loading ? "保存中..." : "确认"}
        </button>
      </div>
    </div>
  );
}

// ============================================================
// Sub-component: TradingConfigForm (Step 2: 交易设置)
// ============================================================
function TradingConfigForm({ onSubmit }: { onSubmit: (data: Record<string, unknown>) => void }) {
  const [capital, setCapital] = useState("");
  const [tradeType, setTradeType] = useState<"SPOT" | "SWAP">("SWAP");
  const [leverageMax, setLeverageMax] = useState(5);
  const [dailyLossLimit, setDailyLossLimit] = useState("5");
  const [riskTolerance, setRiskTolerance] = useState<RiskTolerance>("MODERATE");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const hasContent = dailyLossLimit.trim() !== "";

  const handleSubmit = async () => {
    setLoading(true);
    setError("");
    try {
      const body: Record<string, unknown> = {
        tradeType,
        leverageMax,
        dailyLossLimit: parseFloat(dailyLossLimit),
        riskTolerance,
      };
      if (capital.trim()) body.availableCapital = parseFloat(capital);

      const res = await fetch("/api/config/trading-params", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        onSubmit(body);
      } else {
        const data = await res.json();
        setError(data.error || "保存失败");
      }
    } catch {
      setError("网络错误，请重试");
    }
    setLoading(false);
  };

  const riskOptions: { value: RiskTolerance; label: string }[] = [
    { value: "CONSERVATIVE", label: "保守" },
    { value: "MODERATE", label: "稳健" },
    { value: "AGGRESSIVE", label: "激进" },
  ];

  return (
    <div className="space-y-3 mt-3">
      <div>
        <label className="text-xs text-[#8a8a8a] mb-1 block">可用资金 (USDT) <span className="text-[#5F5E5A]">选填</span></label>
        <input
          type="number"
          value={capital}
          onChange={(e) => setCapital(e.target.value)}
          placeholder="例如: 10000"
          className="w-full px-3 py-2 rounded text-sm text-white placeholder-[#5F5E5A] focus:outline-none focus:border-[#378ADD]"
          style={{ backgroundColor: COLORS.inputBg, border: `1px solid ${COLORS.inputBorder}` }}
        />
      </div>

      <div>
        <label className="text-xs text-[#8a8a8a] mb-1 block">交易类型</label>
        <div className="flex gap-4">
          {(["SWAP", "SPOT"] as const).map((t) => (
            <label key={t} className="flex items-center gap-2 text-sm text-white cursor-pointer">
              <input
                type="radio"
                name="tradeType"
                value={t}
                checked={tradeType === t}
                onChange={() => setTradeType(t)}
                className="accent-[#378ADD]"
              />
              {t === "SWAP" ? "永续合约" : "现货"}
            </label>
          ))}
        </div>
      </div>

      <div>
        <label className="text-xs text-[#8a8a8a] mb-1 block">最大杠杆: {leverageMax}x</label>
        <input
          type="range"
          min={1}
          max={20}
          value={leverageMax}
          onChange={(e) => setLeverageMax(parseInt(e.target.value))}
          className="w-full accent-[#378ADD]"
        />
        <div className="flex justify-between text-[10px] text-[#5F5E5A]">
          <span>1x</span><span>10x</span><span>20x</span>
        </div>
      </div>

      <div>
        <label className="text-xs text-[#8a8a8a] mb-1 block">每日亏损限制 (%)</label>
        <input
          type="number"
          value={dailyLossLimit}
          onChange={(e) => setDailyLossLimit(e.target.value)}
          placeholder="例如: 5"
          className="w-full px-3 py-2 rounded text-sm text-white placeholder-[#5F5E5A] focus:outline-none focus:border-[#378ADD]"
          style={{ backgroundColor: COLORS.inputBg, border: `1px solid ${COLORS.inputBorder}` }}
        />
      </div>

      <div>
        <label className="text-xs text-[#8a8a8a] mb-1 block">风险偏好</label>
        <select
          value={riskTolerance}
          onChange={(e) => setRiskTolerance(e.target.value as RiskTolerance)}
          className="w-full px-3 py-2 rounded text-sm text-white focus:outline-none"
          style={{ backgroundColor: COLORS.inputBg, border: `1px solid ${COLORS.inputBorder}` }}
        >
          {riskOptions.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>

      {error && (
        <div className="text-xs text-red-400 bg-red-500/10 px-3 py-2 rounded">❌ {error}</div>
      )}

      <div className="flex justify-end">
        <button
          onClick={handleSubmit}
          disabled={loading || !hasContent}
          className="px-4 py-1.5 text-xs rounded font-medium text-white transition"
          style={{
            backgroundColor: hasContent ? COLORS.confirmActive : COLORS.confirmDisabled,
            color: hasContent ? "#fff" : COLORS.confirmDisabledText,
          }}
        >
          {loading ? "保存中..." : "确认"}
        </button>
      </div>
    </div>
  );
}

// ============================================================
// Sub-component: StrategyConfigForm (Step 3: 策略设置)
// ============================================================
function StrategyConfigForm({ onSubmit }: { onSubmit: (data: Record<string, unknown>) => void }) {
  const [strategyTemplate, setStrategyTemplate] = useState("default_moderate");
  const [frequency, setFrequency] = useState<Frequency>("FOUR_H");
  const [riskTolerance, setRiskTolerance] = useState<RiskTolerance>("MODERATE");
  const [allowedSymbols, setAllowedSymbols] = useState<string[]>(["BTC-USDT-SWAP"]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [symbolInput, setSymbolInput] = useState("");

  const hasContent = true; // select/radio always have values

  const symbolOptions = [
    "BTC-USDT-SWAP",
    "ETH-USDT-SWAP",
    "SOL-USDT-SWAP",
    "DOGE-USDT-SWAP",
    "XRP-USDT-SWAP",
    "ADA-USDT-SWAP",
    "AVAX-USDT-SWAP",
    "LINK-USDT-SWAP",
  ];

  const addSymbol = () => {
    const sym = symbolInput.trim().toUpperCase();
    if (sym && !allowedSymbols.includes(sym)) {
      setAllowedSymbols([...allowedSymbols, sym]);
    }
    setSymbolInput("");
  };

  const removeSymbol = (sym: string) => {
    setAllowedSymbols(allowedSymbols.filter((s) => s !== sym));
  };

  const handleSubmit = async () => {
    setLoading(true);
    setError("");
    try {
      const body = {
        strategyTemplate,
        executionFrequency: frequency,
        riskTolerance,
        allowedSymbols,
      };
      const res = await fetch("/api/config/strategies", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        onSubmit(body);
      } else {
        const data = await res.json();
        setError(data.error || "保存失败");
      }
    } catch {
      setError("网络错误，请重试");
    }
    setLoading(false);
  };

  const frequencyOptions: { value: Frequency; label: string }[] = [
    { value: "ONE_H", label: "1小时 (1h)" },
    { value: "FOUR_H", label: "4小时 (4h)" },
    { value: "ONE_D", label: "每日 (1d)" },
  ];

  const templateOptions = [
    { value: "default_conservative", label: "默认保守策略" },
    { value: "default_moderate", label: "默认稳健策略" },
    { value: "default_aggressive", label: "默认激进策略" },
  ];

  const riskOptions: { value: RiskTolerance; label: string }[] = [
    { value: "CONSERVATIVE", label: "保守" },
    { value: "MODERATE", label: "稳健" },
    { value: "AGGRESSIVE", label: "激进" },
  ];

  return (
    <div className="space-y-3 mt-3">
      <div>
        <label className="text-xs text-[#8a8a8a] mb-1 block">策略模板</label>
        <select
          value={strategyTemplate}
          onChange={(e) => setStrategyTemplate(e.target.value)}
          className="w-full px-3 py-2 rounded text-sm text-white focus:outline-none"
          style={{ backgroundColor: COLORS.inputBg, border: `1px solid ${COLORS.inputBorder}` }}
        >
          {templateOptions.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>

      <div>
        <label className="text-xs text-[#8a8a8a] mb-1 block">执行频率</label>
        <div className="flex gap-3">
          {frequencyOptions.map((opt) => (
            <label key={opt.value} className="flex items-center gap-2 text-sm text-white cursor-pointer">
              <input
                type="radio"
                name="frequency"
                value={opt.value}
                checked={frequency === opt.value}
                onChange={() => setFrequency(opt.value)}
                className="accent-[#378ADD]"
              />
              {opt.label}
            </label>
          ))}
        </div>
      </div>

      <div>
        <label className="text-xs text-[#8a8a8a] mb-1 block">风险偏好</label>
        <select
          value={riskTolerance}
          onChange={(e) => setRiskTolerance(e.target.value as RiskTolerance)}
          className="w-full px-3 py-2 rounded text-sm text-white focus:outline-none"
          style={{ backgroundColor: COLORS.inputBg, border: `1px solid ${COLORS.inputBorder}` }}
        >
          {riskOptions.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>

      <div>
        <label className="text-xs text-[#8a8a8a] mb-1 block">交易标的 <span className="text-[#5F5E5A]">可选</span></label>
        <div className="flex flex-wrap gap-1 mb-2">
          {allowedSymbols.map((sym) => (
            <span
              key={sym}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] bg-[#378ADD]/20 text-[#378ADD] border border-[#378ADD]/30 cursor-pointer hover:bg-red-500/20 hover:text-red-400 hover:border-red-500/30 transition"
              onClick={() => removeSymbol(sym)}
            >
              {sym} ×
            </span>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            value={symbolInput}
            onChange={(e) => setSymbolInput(e.target.value)}
            placeholder="输入交易对 (如 BTC-USDT-SWAP)"
            className="flex-1 px-3 py-1.5 rounded text-xs text-white placeholder-[#5F5E5A] focus:outline-none focus:border-[#378ADD]"
            style={{ backgroundColor: COLORS.inputBg, border: `1px solid ${COLORS.inputBorder}` }}
            onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addSymbol())}
          />
          <button
            onClick={addSymbol}
            className="px-2 py-1 text-xs bg-[#444441] text-[#8a8a8a] rounded hover:text-white transition"
          >
            +
          </button>
        </div>
        <div className="flex flex-wrap gap-1 mt-1.5">
          {symbolOptions
            .filter((s) => !allowedSymbols.includes(s))
            .slice(0, 4)
            .map((sym) => (
              <span
                key={sym}
                className="text-[10px] text-[#5F5E5A] cursor-pointer hover:text-[#378ADD] transition"
                onClick={() => setAllowedSymbols([...allowedSymbols, sym])}
              >
                +{sym}
              </span>
            ))}
        </div>
      </div>

      {error && (
        <div className="text-xs text-red-400 bg-red-500/10 px-3 py-2 rounded">❌ {error}</div>
      )}

      <div className="flex justify-end">
        <button
          onClick={handleSubmit}
          disabled={loading}
          className="px-4 py-1.5 text-xs rounded font-medium text-white transition"
          style={{
            backgroundColor: hasContent ? COLORS.confirmActive : COLORS.confirmDisabled,
            color: hasContent ? "#fff" : COLORS.confirmDisabledText,
          }}
        >
          {loading ? "保存中..." : "确认"}
        </button>
      </div>
    </div>
  );
}

// ============================================================
// Sub-component: ChannelConfigForm (Step 4: 通信渠道)
// ============================================================
function ChannelConfigForm({ onSubmit }: { onSubmit: (data: Record<string, unknown>) => void }) {
  const [channelType, setChannelType] = useState<ChannelType>("TELEGRAM");
  const [botToken, setBotToken] = useState("");
  const [pushTypes, setPushTypes] = useState<PushMessageType[]>(["trade_signal", "risk_alert"]);
  const [silentStart, setSilentStart] = useState("23:00");
  const [silentEnd, setSilentEnd] = useState("08:00");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const hasContent = botToken.trim() !== "";

  const allPushTypes: { value: PushMessageType; label: string }[] = [
    { value: "trade_signal", label: "交易信号" },
    { value: "risk_alert", label: "风险告警" },
    { value: "intel_update", label: "情报更新" },
    { value: "daily_report", label: "每日报告" },
    { value: "dream_insight", label: "做梦洞察" },
    { value: "system_notice", label: "系统通知" },
  ];

  const channelOptions: { value: ChannelType; label: string }[] = [
    { value: "TELEGRAM", label: "Telegram" },
    { value: "WECHAT_SERVERCHAN", label: "微信 (Server酱)" },
    { value: "WECHAT_WORK", label: "企业微信" },
    { value: "EMAIL_SMTP", label: "Email" },
    { value: "DISCORD", label: "Discord" },
  ];

  const togglePushType = (type: PushMessageType) => {
    if (pushTypes.includes(type)) {
      setPushTypes(pushTypes.filter((t) => t !== type));
    } else {
      setPushTypes([...pushTypes, type]);
    }
  };

  const handleSubmit = async () => {
    setLoading(true);
    setError("");
    try {
      const body = {
        channelType,
        botToken,
        pushTypes,
        silentStart,
        silentEnd,
      };
      const res = await fetch("/api/config/channels", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        onSubmit(body);
      } else {
        const data = await res.json();
        setError(data.error || "保存失败");
      }
    } catch {
      setError("网络错误，请重试");
    }
    setLoading(false);
  };

  return (
    <div className="space-y-3 mt-3">
      <div>
        <label className="text-xs text-[#8a8a8a] mb-1 block">渠道类型</label>
        <select
          value={channelType}
          onChange={(e) => setChannelType(e.target.value as ChannelType)}
          className="w-full px-3 py-2 rounded text-sm text-white focus:outline-none"
          style={{ backgroundColor: COLORS.inputBg, border: `1px solid ${COLORS.inputBorder}` }}
        >
          {channelOptions.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>

      <div>
        <label className="text-xs text-[#8a8a8a] mb-1 block">
          {channelType === "TELEGRAM" ? "Bot Token" : channelType === "EMAIL_SMTP" ? "SMTP 配置" : "Webhook URL"}
        </label>
        <input
          type="password"
          value={botToken}
          onChange={(e) => setBotToken(e.target.value)}
          placeholder={channelType === "TELEGRAM" ? "123456:ABC-DEF..." : channelType === "EMAIL_SMTP" ? "smtp://user:pass@host" : "https://hooks.example.com/..."}
          className="w-full px-3 py-2 rounded text-sm text-white placeholder-[#5F5E5A] focus:outline-none focus:border-[#378ADD]"
          style={{ backgroundColor: COLORS.inputBg, border: `1px solid ${COLORS.inputBorder}` }}
        />
      </div>

      <div>
        <label className="text-xs text-[#8a8a8a] mb-1 block">推送类型</label>
        <div className="flex flex-wrap gap-1.5">
          {allPushTypes.map((pt) => (
            <label
              key={pt.value}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] cursor-pointer transition"
              style={{
                backgroundColor: pushTypes.includes(pt.value) ? "#378ADD/20" : COLORS.inputBg,
                border: `1px solid ${pushTypes.includes(pt.value) ? "#378ADD" : COLORS.inputBorder}`,
                color: pushTypes.includes(pt.value) ? "#378ADD" : "#8a8a8a",
              }}
              onClick={() => togglePushType(pt.value)}
            >
              <input
                type="checkbox"
                checked={pushTypes.includes(pt.value)}
                onChange={() => togglePushType(pt.value)}
                className="accent-[#378ADD] w-3 h-3"
              />
              {pt.label}
            </label>
          ))}
        </div>
      </div>

      <div>
        <label className="text-xs text-[#8a8a8a] mb-1 block">静默时段 <span className="text-[#5F5E5A]">选填</span></label>
        <div className="flex items-center gap-2">
          <input
            type="time"
            value={silentStart}
            onChange={(e) => setSilentStart(e.target.value)}
            className="px-3 py-1.5 rounded text-sm text-white focus:outline-none"
            style={{ backgroundColor: COLORS.inputBg, border: `1px solid ${COLORS.inputBorder}` }}
          />
          <span className="text-xs text-[#5F5E5A]">至</span>
          <input
            type="time"
            value={silentEnd}
            onChange={(e) => setSilentEnd(e.target.value)}
            className="px-3 py-1.5 rounded text-sm text-white focus:outline-none"
            style={{ backgroundColor: COLORS.inputBg, border: `1px solid ${COLORS.inputBorder}` }}
          />
        </div>
      </div>

      {error && (
        <div className="text-xs text-red-400 bg-red-500/10 px-3 py-2 rounded">❌ {error}</div>
      )}

      <div className="flex justify-end">
        <button
          onClick={handleSubmit}
          disabled={loading || !hasContent}
          className="px-4 py-1.5 text-xs rounded font-medium text-white transition"
          style={{
            backgroundColor: hasContent ? COLORS.confirmActive : COLORS.confirmDisabled,
            color: hasContent ? "#fff" : COLORS.confirmDisabledText,
          }}
        >
          {loading ? "保存中..." : "确认"}
        </button>
      </div>
    </div>
  );
}

// ============================================================
// Main Export: AutoConfigBubble
// ============================================================
export default function AutoConfigBubble() {
  const {
    phase,
    currentStep,
    results,
    handleYes,
    handleNo,
    handleSubmit,
    handleExitYes,
    handleExitNo,
    isActive,
  } = useAutoConfigStore();

  if (!isActive) return null;

  const currentConfig = CONFIG_STEPS_LIST[currentStep];
  if (!currentConfig) return null;

  // ===== Phase: asking =====
  if (phase === "asking") {
    return (
      <div className="flex justify-start">
        <div
          className="max-w-[85%] rounded-lg"
          style={{ backgroundColor: COLORS.bubbleBg, padding: COLORS.bubblePadding, borderRadius: COLORS.bubbleRadius }}
        >
          <StepProgress />
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[#06b6d4] text-xs">🤖 Dream Gateway</span>
          </div>
          <p className="text-sm text-white">
            是否帮您配置「{currentConfig.icon} {currentConfig.label}」？
          </p>
          <PillButtons onYes={handleYes} onNo={handleNo} />
        </div>
      </div>
    );
  }

  // ===== Phase: inputting =====
  if (phase === "inputting") {
    const renderForm = () => {
      switch (currentConfig.key) {
        case "api":
          return <ApiConfigForm onSubmit={handleSubmit} />;
        case "trading":
          return <TradingConfigForm onSubmit={handleSubmit} />;
        case "strategy":
          return <StrategyConfigForm onSubmit={handleSubmit} />;
        case "channels":
          return <ChannelConfigForm onSubmit={handleSubmit} />;
        default:
          return null;
      }
    };

    return (
      <div className="flex justify-start">
        <div
          className="max-w-[85%] rounded-lg"
          style={{ backgroundColor: COLORS.bubbleBg, padding: COLORS.bubblePadding, borderRadius: COLORS.bubbleRadius }}
        >
          <StepProgress />
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[#06b6d4] text-xs">🤖 Dream Gateway</span>
          </div>
          <p className="text-sm text-white mb-1">
            请填写 {currentConfig.icon} {currentConfig.label} 信息：
          </p>
          {renderForm()}
        </div>
      </div>
    );
  }

  // ===== Phase: exit_confirm =====
  if (phase === "exit_confirm") {
    return (
      <div className="flex justify-start">
        <div
          className="max-w-[80%] rounded-lg"
          style={{
            backgroundColor: COLORS.warnBg,
            padding: COLORS.bubblePadding,
            borderRadius: COLORS.bubbleRadius,
          }}
        >
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs text-white/80">⚠️ 退出确认</span>
          </div>
          <p className="text-sm text-white">
            检测到您连续跳过了 2 项配置，是否退出自动化配置？<br />
            <span className="text-xs text-white/70 mt-1 inline-block">
              已完成 {results.filter((r) => r.status === "configured").length} 项配置
            </span>
          </p>
          <PillButtons onYes={handleExitYes} onNo={handleExitNo} />
        </div>
      </div>
    );
  }

  return null;
}
