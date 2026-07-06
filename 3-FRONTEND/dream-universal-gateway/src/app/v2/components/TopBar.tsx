"use client";

import React from "react";

interface TopBarProps {
  pageTitle: string;
  thinkingMode: "quick" | "deep";
  onThinkingModeChange: (mode: "quick" | "deep") => void;
  lang: "zh" | "en";
  onLangChange: (lang: "zh" | "en") => void;
  credits: number;
}

export default function TopBar({
  pageTitle,
  thinkingMode,
  onThinkingModeChange,
  lang,
  onLangChange,
  credits,
}: TopBarProps) {
  const formattedCredits = credits.toLocaleString();

  return (
    <div
      className="flex items-center justify-between h-[52px] px-5 border-b"
      style={{
        backgroundColor: "var(--bg-secondary, #111827)",
        borderBottomColor: "var(--border-default, #1e293b)",
        borderBottomWidth: "1px",
        borderBottomStyle: "solid",
      }}
    >
      {/* Left side — page title */}
      <span className="text-[13px] font-medium text-[#f1f5f9]">
        {pageTitle}
      </span>

      {/* Right side — controls */}
      <div className="flex items-center gap-3">
        {/* Thinking mode toggle */}
        <div className="flex rounded-lg p-0.5 gap-0.5 bg-[#1e293b]">
          <button
            onClick={() => onThinkingModeChange("quick")}
            className={`
              text-[11px] px-3 py-1 rounded-md transition-colors
              ${
                thinkingMode === "quick"
                  ? "bg-[#3b82f6] text-white shadow-lg shadow-blue-500/20"
                  : "text-[#94a3b8] hover:text-[#f1f5f9]"
              }
            `}
          >
            ⚡ 智能思考
          </button>
          <button
            onClick={() => onThinkingModeChange("deep")}
            className={`
              text-[11px] px-3 py-1 rounded-md transition-colors
              ${
                thinkingMode === "deep"
                  ? "bg-[#8b5cf6] text-white shadow-lg shadow-purple-500/20"
                  : "text-[#94a3b8] hover:text-[#f1f5f9]"
              }
            `}
          >
            🧠 深度思考
          </button>
        </div>

        {/* Language toggle */}
        <div className="flex rounded-lg p-0.5 gap-0.5 bg-[#1e293b]">
          <button
            onClick={() => onLangChange("zh")}
            className={`
              text-[11px] px-2 py-1 rounded-md transition-colors
              ${
                lang === "zh"
                  ? "bg-[#f59e0b] text-black font-medium"
                  : "text-[#94a3b8]"
              }
            `}
          >
            中文
          </button>
          <button
            onClick={() => onLangChange("en")}
            className={`
              text-[11px] px-2 py-1 rounded-md transition-colors
              ${
                lang === "en"
                  ? "bg-[#f59e0b] text-black font-medium"
                  : "text-[#94a3b8]"
              }
            `}
          >
            EN
          </button>
        </div>

        {/* Credits badge */}
        <div className="flex items-center gap-1 bg-[#1e293b] px-3 py-1 rounded-full">
          <span>💎</span>
          <span className="font-mono text-[#f1f5f9] font-medium text-[11px]">
            {formattedCredits}
          </span>
          <span className="text-[#64748b] text-[11px]">积分</span>
        </div>

        {/* Recharge button */}
        <button className="bg-[#3b82f6] text-white px-3 py-1 rounded-lg text-[11px] font-medium hover:bg-[#60a5fa] transition-colors">
          充值
        </button>
      </div>
    </div>
  );
}
