"use client";

// ============================================================
// ModuleDrawer — 模块库抽屉
// 版本: v1.0 | Phase 1
// 从顶部"模块库"按钮展开，承载原 Left Sidebar 的数据卡片 + 设置折叠模块
// ============================================================

import { useState } from "react";

export type ModuleDrawerPanel =
  | "analysis" | "market" | "signal" | "position" | "api" | "trading"
  | "strategy" | "communication" | "llm" | "report" | "monitor" | "memory"
  | "notebook" | "graph-compression" | "orchestration";

interface Props {
  open: boolean;
  onClose: () => void;
  onShowPanel: (type: ModuleDrawerPanel) => void;
  onAutoConfig?: () => void;
}

export default function ModuleDrawer({ open, onClose, onShowPanel, onAutoConfig }: Props) {
  const [dataCardExpanded, setDataCardExpanded] = useState(true);
  const [settingsExpanded, setSettingsExpanded] = useState(false);

  if (!open) return null;

  const handleSelect = (type: ModuleDrawerPanel) => {
    onShowPanel(type);
    onClose();
  };

  return (
    <>
      {/* Overlay backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/50 transition-opacity"
        onClick={onClose}
      />

      {/* Drawer panel — slides from top */}
      <div
        className="fixed top-11 left-0 right-0 z-50 bg-[#1a1a1a] border-b border-[#2a2a2a] shadow-2xl overflow-hidden"
        style={{ maxHeight: "70vh", overflowY: "auto" }}
      >
        <div className="p-4">
          {/* Header */}
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-[#3b82f6]">📋 模块库</h2>
            <button
              onClick={onClose}
              className="p-1 hover:bg-[#2a2a2a] rounded transition text-[#8a8a8a]"
              title="关闭"
            >
              ✕
            </button>
          </div>

          <div className="grid grid-cols-3 gap-3">
            {/* 数据卡片模块 */}
            <div className="space-y-1">
              <div
                className="collapsible-header cursor-pointer"
                onClick={() => setDataCardExpanded(!dataCardExpanded)}
              >
                <span className="flex items-center gap-2 text-sm text-[#e0e0e0]">📊 数据卡片</span>
                <span className={`arrow ${dataCardExpanded ? "expanded" : ""} text-[10px] text-[#8a8a8a]`}>▶</span>
              </div>
              {dataCardExpanded && (
                <div className="space-y-1 pl-2">
                  <div className="collapsible-item text-xs text-[#8a8a8a] hover:text-[#3b82f6] cursor-pointer" onClick={() => handleSelect("market")}>📈 行情卡片</div>
                  <div className="collapsible-item text-xs text-[#8a8a8a] hover:text-[#3b82f6] cursor-pointer" onClick={() => handleSelect("signal")}>📊 评分卡片</div>
                  <div className="collapsible-item text-xs text-[#8a8a8a] hover:text-[#3b82f6] cursor-pointer" onClick={() => handleSelect("position")}>💼 持仓卡片</div>
                </div>
              )}
            </div>

            {/* 自动化配置 */}
            <div
              className="collapsible-header cursor-pointer rounded-md p-2"
              style={{ backgroundColor: "#0f3460" }}
              onClick={() => {
                onAutoConfig?.();
                onClose();
              }}
            >
              <span className="flex items-center gap-2 text-sm text-white">🚀 自动化配置</span>
              <span className="text-[10px] text-[#8a8a8a]">4步快速配置</span>
            </div>

            {/* 设置模块 */}
            <div className="space-y-1">
              <div
                className="collapsible-header cursor-pointer"
                onClick={() => setSettingsExpanded(!settingsExpanded)}
              >
                <span className="flex items-center gap-2 text-sm text-[#e0e0e0]">⚙️ 设置</span>
                <span className={`arrow ${settingsExpanded ? "expanded" : ""} text-[10px] text-[#8a8a8a]`}>▶</span>
              </div>
              {settingsExpanded && (
                <div className="space-y-1 pl-2">
                  <div className="collapsible-item text-xs text-[#8a8a8a] hover:text-[#3b82f6] cursor-pointer" onClick={() => handleSelect("llm")}>🤖 大模型配置</div>
                  <div className="collapsible-item text-xs text-[#8a8a8a] hover:text-[#3b82f6] cursor-pointer" onClick={() => handleSelect("api")}>⚙️ 交易所API</div>
                  <div className="collapsible-item text-xs text-[#8a8a8a] hover:text-[#3b82f6] cursor-pointer" onClick={() => handleSelect("trading")}>💰 交易设置</div>
                  <div className="collapsible-item text-xs text-[#8a8a8a] hover:text-[#3b82f6] cursor-pointer" onClick={() => handleSelect("strategy")}>🎯 策略设置</div>
                  <div className="collapsible-item text-xs text-[#8a8a8a] hover:text-[#3b82f6] cursor-pointer" onClick={() => handleSelect("communication")}>📡 通信渠道</div>
                  <div className="collapsible-item text-xs text-[#8a8a8a] hover:text-[#3b82f6] cursor-pointer" onClick={() => handleSelect("monitor")}>📡 传递监控</div>
                  <div className="collapsible-item text-xs text-[#8a8a8a] hover:text-[#3b82f6] cursor-pointer" onClick={() => handleSelect("memory")}>🧠 意图记忆库</div>
                  <div className="collapsible-item text-xs text-[#8a8a8a] hover:text-[#3b82f6] cursor-pointer" onClick={() => handleSelect("notebook")}>📒 笔记本</div>
                  <div className="collapsible-item text-xs text-[#8a8a8a] hover:text-[#3b82f6] cursor-pointer" onClick={() => handleSelect("graph-compression")}>🗜️ 图压缩</div>
                </div>
              )}
            </div>
          </div>

          {/* 快捷面板 */}
          <div className="mt-4 pt-3 border-t border-[#2a2a2a]">
            <div className="text-xs text-[#8a8a8a] mb-2">快捷面板</div>
            <div className="flex gap-2 flex-wrap">
              <button onClick={() => handleSelect("analysis")} className="px-2 py-1 text-[11px] bg-[#1a1a1a] text-[#8a8a8a] hover:text-[#3b82f6] rounded">📊 分析</button>
              <button onClick={() => handleSelect("memory")} className="px-2 py-1 text-[11px] bg-[#1a1a1a] text-[#8a8a8a] hover:text-[#3b82f6] rounded">🧠 记忆</button>
              <button onClick={() => handleSelect("notebook")} className="px-2 py-1 text-[11px] bg-[#1a1a1a] text-[#8a8a8a] hover:text-[#3b82f6] rounded">📒 笔记</button>
              <button onClick={() => handleSelect("orchestration")} className="px-2 py-1 text-[11px] bg-[#1a1a1a] text-[#8a8a8a] hover:text-[#3b82f6] rounded">🔀 编排</button>
              <button onClick={() => handleSelect("graph-compression")} className="px-2 py-1 text-[11px] bg-[#1a1a1a] text-[#8a8a8a] hover:text-[#3b82f6] rounded">🗜️ 图压缩</button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
