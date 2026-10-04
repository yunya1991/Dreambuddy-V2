"use client";

import { useRouter } from "next/navigation";
import type { ClassicSystemData } from "../hooks/useClassicSystemData";

export type ClassicSubTab =
  | "library"
  | "strategies"
  | "sandbox"
  | "approvals"
  | "signals"
  | "filter"
  | "execution"
  | "exit"
  | "arena"
  | "universe"
  | "macro"
  | "evaluation";

interface ClassicSubTabContentProps {
  subTab: ClassicSubTab;
  data: ClassicSystemData;
}

/**
 * 经典交易体系子 Tab 内容组件
 *
 * 从 dashboard/page.tsx 提取，按 subTab 渲染对应内容。
 * 数据由 useClassicSystemData hook 提供。
 */
export function ClassicSubTabContent({ subTab, data }: ClassicSubTabContentProps) {
  const router = useRouter();
  const {
    classicHealth,
    strategyList,
    signalList,
    approvalList,
    automationCards,
    exitStats,
    arenaState,
    universeState,
    macroState,
    evaluationState,
    settlements,
    backtestResults,
    sandboxState,
    pipelineState,
    gateCheck,
    isLoadingClassicData,
    loadClassicSystemData,
  } = data;

  // ---------- 策略库 ----------
  if (subTab === "library") {
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold text-white mb-2">📚 策略库 (Strategy Registry)</h2>
          <div className="flex items-center gap-2">
            {isLoadingClassicData && (
              <span className="text-xs text-[#8b5cf6] animate-pulse">加载中...</span>
            )}
            <button
              onClick={loadClassicSystemData}
              className="px-3 py-1 text-xs bg-[#8b5cf6] text-white rounded-md hover:bg-[#7c3aed] transition"
            >
              🔄 刷新
            </button>
          </div>
        </div>
        <p className="text-[#8a8a8a] text-sm">已验证并可复用的经典策略集合。来源于 10-经典指标系统 策略注册表。</p>

        <div className="flex items-center gap-2 text-sm">
          <span className={`w-2 h-2 rounded-full ${classicHealth.ok ? "bg-green-500" : "bg-red-500"}`}></span>
          <span className="text-[#8a8a8a]">
            经典交易系统: {classicHealth.ok ? "在线" : "离线"}
            {!classicHealth.ok && classicHealth.error && (
              <span className="text-xs ml-2">({classicHealth.error})</span>
            )}
          </span>
        </div>

        {strategyList.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 mt-4">
            {strategyList.map((s, idx) => (
              <div key={idx} className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] hover:border-[#8b5cf6] transition cursor-pointer">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-white font-medium">{s.strategy || "Unknown Strategy"}</h3>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    s.status === "active" ? "bg-green-500/20 text-green-400" :
                    s.status === "inactive" ? "bg-gray-500/20 text-gray-400" :
                    "bg-yellow-500/20 text-yellow-400"}`}
                  >
                    {s.status || "unknown"}
                  </span>
                </div>
                <div className="text-xs text-[#8a8a8a] space-y-1">
                  {s.book_id && <p>📖 Book: {s.book_id}</p>}
                  {s.ab_owner && <p>👤 Owner: {s.ab_owner}</p>}
                  {s.metrics && (
                    <>
                      {s.metrics.win_rate !== undefined && <p>🎯 胜率: {(s.metrics.win_rate * 100).toFixed(1)}%</p>}
                      {s.metrics.sharpe_ratio !== undefined && <p>📊 夏普率: {s.metrics.sharpe_ratio.toFixed(2)}</p>}
                      {s.metrics.max_drawdown !== undefined && <p>⚠️ 最大回撤: {(s.metrics.max_drawdown * 100).toFixed(1)}%</p>}
                    </>
                  )}
                  {s.last_update && <p>🕐 更新: {new Date(s.last_update * 1000).toLocaleString("zh-CN")}</p>}
                </div>
                <button
                  onClick={() => router.push(`/dashboard?ref=strategy&name=${encodeURIComponent(s.strategy || "")}`)}
                  className="mt-3 text-xs text-[#8b5cf6] hover:text-white transition"
                >
                  💬 在对话中引用 →
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-4 text-center text-[#8a8a8a] py-8">
            {classicHealth.ok ? "暂无注册策略" : "系统离线，请检查 10-经典指标系统 服务"}
          </div>
        )}
      </div>
    );
  }

  // ---------- 策略上线通道 ----------
  if (subTab === "strategies") {
    return (
      <div className="space-y-3">
        <h2 className="text-xl font-semibold text-white mb-2">🛠 策略上线通道</h2>
        <p className="text-[#8a8a8a] text-sm">完整治理流程：Draft → Gate 评估 → 审批 → Apply 应用 → Audit 记录。只有通过全部流程的策略才会真正上线到 Freqtrade。</p>

        <div className="mt-4 bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
          <h3 className="text-white font-medium mb-3">📝 策略治理管线</h3>
          <div className="space-y-2">
            {[
              { step: "① Draft（起草）", status: pipelineState.phase === "draft" ? "进行中" : pipelineState.current ? "已完成" : "待处理", detail: "用户在对话中生成策略代码" },
              { step: "② Gate（门槛）", status: gateCheck.passed ? "已通过" : gateCheck.ok ? "未通过" : "待处理", detail: "自动化合规/风险检查" },
              { step: "③ Approval（审批）", status: pipelineState.approval_id ? "已提交" : "待处理", detail: "风控/运营人工确认" },
              { step: "④ Apply（应用）", status: pipelineState.phase === "apply" ? "进行中" : pipelineState.phase === "live" ? "已上线" : "待处理", detail: "部署到 Freqtrade 执行引擎" },
              { step: "⑤ Audit（审计）", status: "自动记录", detail: "运行数据记录与回测归档" },
            ].map((item, idx) => {
              const isActive = item.status === "进行中" || item.status === "已通过" || item.status === "已提交" || item.status === "已上线";
              const isPending = item.status === "待处理" || item.status === "未通过";
              return (
                <div key={idx} className="flex items-center gap-3 text-sm p-2 bg-[#0d0d0d] rounded">
                  <span className="text-white font-medium w-56">{item.step}</span>
                  <span className="text-[#8a8a8a] flex-1">{item.detail}</span>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    isActive ? "bg-green-500/20 text-green-400" :
                    isPending ? "bg-gray-500/20 text-[#8a8a8a]" :
                    "bg-yellow-500/20 text-yellow-400"}`}
                  >
                    {item.status}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {gateCheck.ok && gateCheck.checks && (
          <div className="mt-4 bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
            <h3 className="text-white font-medium mb-3">🚪 Gate Check 详情</h3>
            <div className="grid grid-cols-4 gap-3 text-sm">
              {Object.entries(gateCheck.checks).map(([key, passed]) => (
                <div key={key} className="flex items-center gap-2">
                  <span className="text-[#8a8a8a]">{key}:</span>
                  <span className={passed ? "text-green-400" : "text-red-400"}>{passed ? "✓" : "✗"}</span>
                </div>
              ))}
            </div>
            {gateCheck.metrics && (
              <div className="mt-3 text-xs text-[#8a8a8a]">
                Metrics: PF={gateCheck.metrics.pf?.toFixed(2) || "-"}, WinRate={((gateCheck.metrics.winrate || 0) * 100).toFixed(1)}%, MaxDD={((gateCheck.metrics.maxdd || 0) * 100).toFixed(1)}%
              </div>
            )}
          </div>
        )}

        {pipelineState.candidate && (
          <div className="mt-4 bg-[#1a1a1a] rounded-lg p-4 border border-[#8b5cf6]/30">
            <h3 className="text-white font-medium mb-2">🎯 当前候选策略</h3>
            <div className="text-sm">
              <span className="text-white font-medium">{pipelineState.candidate}</span>
              {pipelineState.gate_result && (
                <span className={`ml-2 text-xs px-2 py-0.5 rounded-full ${pipelineState.gate_result.passed ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"}`}>
                  {pipelineState.gate_result.passed ? "Gate通过" : "Gate未通过"}
                </span>
              )}
            </div>
          </div>
        )}
      </div>
    );
  }

  // ---------- 沙箱测试 ----------
  if (subTab === "sandbox") {
    return (
      <div className="space-y-3">
        <h2 className="text-xl font-semibold text-white mb-2">🧪 沙箱测试 (Sandbox Testing)</h2>
        <p className="text-[#8a8a8a] text-sm">策略上线前的模拟运行环境。使用历史数据 + 实时行情进行回测与模拟交易，不会产生任何真实下单。</p>

        <div className="mt-4 grid grid-cols-3 gap-3">
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
            <p className="text-[#8a8a8a] text-xs mb-1">📊 运行中任务</p>
            <p className="text-2xl font-bold text-white">{sandboxState.running || 0}</p>
            <p className="text-xs text-[#6a6a6a] mt-1">正在实时模拟</p>
          </div>
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
            <p className="text-[#8a8a8a] text-xs mb-1">⏳ 队列等待</p>
            <p className="text-2xl font-bold text-yellow-400">{sandboxState.queued || 0}</p>
            <p className="text-xs text-[#6a6a6a] mt-1">待执行任务</p>
          </div>
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
            <p className="text-[#8a8a8a] text-xs mb-1">🎯 最大并发</p>
            <p className="text-2xl font-bold text-[#8b5cf6]">{sandboxState.max_slots || 3}</p>
            <p className="text-xs text-[#6a6a6a] mt-1">并发槽位</p>
          </div>
        </div>

        <div className="mt-4 bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-white font-medium">🔬 最新回测结果</h3>
            <span className="text-xs text-[#8a8a8a]">共 {backtestResults.length} 条记录</span>
          </div>
          {backtestResults.length > 0 ? (
            <div className="space-y-2 text-sm max-h-64 overflow-y-auto">
              {backtestResults.slice(0, 10).map((bt, idx) => (
                <div key={idx} className="flex items-center gap-3 p-2 bg-[#0d0d0d] rounded border-l-2 border-[#8b5cf6]">
                  <span className="text-white font-medium w-40 truncate">{bt.strategy || bt.zip?.replace(".zip", "") || "Unknown"}</span>
                  <span className="text-[#8a8a8a] flex-1 text-xs">
                    {bt.ts ? new Date(bt.ts).toLocaleDateString("zh-CN") : "-"}
                  </span>
                  {bt.metrics_summary && (
                    <>
                      <span className={`text-xs ${bt.metrics_summary.pf !== undefined && bt.metrics_summary.pf >= 1 ? "text-green-400" : "text-red-400"}`}>
                        PF: {bt.metrics_summary.pf?.toFixed(2) || "-"}
                      </span>
                      <span className="text-xs text-[#8a8a8a]">
                        WR: {((bt.metrics_summary.winrate || 0) * 100).toFixed(0)}%
                      </span>
                    </>
                  )}
                  <span className={`text-xs px-2 py-0.5 rounded-full ${bt.ok ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"}`}>
                    {bt.ok ? "成功" : "失败"}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center text-[#8a8a8a] py-8">
              {isLoadingClassicData ? "加载中..." : "暂无回测记录"}
            </div>
          )}
        </div>
      </div>
    );
  }

  // ---------- 审计与审批 ----------
  if (subTab === "approvals") {
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold text-white mb-2">✅ 审计与审批</h2>
          <button
            onClick={loadClassicSystemData}
            className="px-3 py-1 text-xs bg-[#8b5cf6] text-white rounded-md hover:bg-[#7c3aed] transition"
          >
            🔄 刷新
          </button>
        </div>
        <p className="text-[#8a8a8a] text-sm">经过沙箱测试后，策略需要经过审计（代码安全、参数合规、风险披露）。审计通过后，再提交审批流程。</p>

        <div className="mt-3 bg-[#1a1a1a] rounded-lg p-4 border border-[#8b5cf6]/30">
          <h3 className="text-white font-medium text-sm mb-2">🤖 自动化状态</h3>
          <div className="flex gap-4 text-xs">
            <div className="flex items-center gap-1">
              <span className="text-[#8a8a8a]">审批待办:</span>
              <span className={`font-medium ${approvalList.filter((a) => a.status === "pending").length > 0 ? "text-yellow-400" : "text-green-400"}`}>
                {approvalList.filter((a) => a.status === "pending").length}
              </span>
            </div>
            {(() => {
              const pc = automationCards.find((c) => c.card_id === "paramopt_automation");
              if (!pc) return null;
              const status = String(pc.status || "").toUpperCase();
              const isRunning = status === "RUNNING";
              const isError = status === "ERROR" || status === "STUCK" || pc.stuck;
              return (
                <div className="flex items-center gap-1">
                  <span className="text-[#8a8a8a]">参数优化:</span>
                  <span className={`font-medium ${isRunning ? "text-green-400" : isError ? "text-red-400" : "text-[#8a8a8a]"}`}>
                    {isRunning ? "运行中" : isError ? "异常" : pc.status || "空闲"}
                  </span>
                </div>
              );
            })()}
          </div>
        </div>

        <div className="mt-4 bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
          <h3 className="text-white font-medium mb-3">📋 待审批策略</h3>
          {approvalList.length > 0 ? (
            <div className="space-y-2 text-sm">
              {approvalList.map((a, idx) => (
                <div key={idx} className="flex items-center justify-between p-2 bg-[#0d0d0d] rounded">
                  <div>
                    <p className="text-white">{a.strategy_name || "Unknown Strategy"}</p>
                    <p className="text-xs text-[#8a8a8a]">
                      类型: {a.request_type || "strategy_deployment"}
                      {a.created_at && <span> · {new Date(a.created_at * 1000).toLocaleString("zh-CN")}</span>}
                    </p>
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    a.status === "approved" ? "bg-green-500/20 text-green-400" :
                    a.status === "rejected" ? "bg-red-500/20 text-red-400" :
                    "bg-yellow-500/20 text-yellow-400"}`}
                  >
                    {a.status || "pending"}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center text-[#8a8a8a] py-4">
              {isLoadingClassicData ? "加载中..." : "暂无待审批项"}
            </div>
          )}
        </div>
      </div>
    );
  }

  // ---------- 信号触发 ----------
  if (subTab === "signals") {
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold text-white mb-2">🎯 信号触发 (Freqtrade)</h2>
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${classicHealth.ok ? "bg-green-500 animate-pulse" : "bg-red-500"}`}></span>
            <span className="text-xs text-[#8a8a8a]">{classicHealth.ok ? "LIVE" : "OFFLINE"}</span>
            <button
              onClick={loadClassicSystemData}
              className="px-3 py-1 text-xs bg-[#8b5cf6] text-white rounded-md hover:bg-[#7c3aed] transition"
            >
              🔄 刷新
            </button>
          </div>
        </div>
        <p className="text-[#8a8a8a] text-sm">经典策略通过 Freqtrade 执行引擎产生入场/离场信号。此处显示所有已上线策略的实时信号。</p>

        <div className="mt-4 bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-white font-medium">📡 实时信号流</h3>
            <span className="text-xs text-[#8a8a8a]">共 {signalList.length} 条信号</span>
          </div>
          {signalList.length > 0 ? (
            <div className="space-y-2 text-sm max-h-96 overflow-y-auto">
              {signalList.map((s, idx) => (
                <div key={idx} className="flex items-center gap-3 p-2 bg-[#0d0d0d] rounded border-l-2 border-[#8b5cf6]">
                  <span className="text-[#6a6a6a] text-xs w-20">
                    {s.timestamp ? new Date(s.timestamp * 1000).toLocaleTimeString("zh-CN") : "-"}
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    s.signal === "enter" || s.signal === "entry" ? "bg-green-500/20 text-green-400" :
                    s.signal === "exit" || s.signal === "close" ? "bg-blue-500/20 text-blue-400" :
                    "bg-gray-500/20 text-gray-400"}`}
                  >
                    {s.signal || "unknown"}
                  </span>
                  <span className="text-white font-medium w-28">{s.strategy || "-"}</span>
                  <span className="text-[#8a8a8a] flex-1 text-xs">
                    {s.direction === "long" ? "📈 LONG" : s.direction === "short" ? "📉 SHORT" : "➡️ NEUTRAL"}
                  </span>
                  {s.confidence !== undefined && (
                    <span className={`text-xs px-2 py-0.5 rounded-full ${
                      s.confidence >= 0.7 ? "bg-green-500/20 text-green-400" :
                      s.confidence >= 0.4 ? "bg-yellow-500/20 text-yellow-400" :
                      "bg-gray-500/20 text-gray-400"}`}
                    >
                      {(s.confidence * 100).toFixed(0)}%
                    </span>
                  )}
                  {s.entry_price && <span className="text-white text-sm">${s.entry_price}</span>}
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center text-[#8a8a8a] py-8">
              {isLoadingClassicData ? "加载中..." : (classicHealth.ok ? "暂无信号" : "系统离线")}
            </div>
          )}
        </div>
      </div>
    );
  }

  // ---------- 信号过滤 ----------
  if (subTab === "filter") {
    return (
      <div className="space-y-3">
        <h2 className="text-xl font-semibold text-white mb-2">🔍 信号过滤</h2>
        <p className="text-[#8a8a8a] text-sm">全局过滤器避免在不利市场条件下执行信号。包括：波动率阈值、资金费率阈值、趋势方向确认、黑窗口时段屏蔽等。</p>

        <div className="mt-4 bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
          <h3 className="text-white font-medium mb-3">🚪 Gate Thresholds（门槛阈值）</h3>
          {gateCheck.ok && gateCheck.thresholds ? (
            <div className="space-y-2">
              {[
                { key: "pf", name: "📊 Profit Factor", desc: "盈亏比阈值", defaultVal: "≥ 1.05" },
                { key: "dd", name: "⚠️ Max Drawdown", desc: "最大回撤限制", defaultVal: "≤ 95%" },
                { key: "trades", name: "🎯 交易次数", desc: "最小交易次数比例", defaultVal: "≥ 70%" },
                { key: "winrate", name: "🏆 胜率", desc: "胜率阈值", defaultVal: "≥ 95%" },
              ].map((item, idx) => {
                const val = gateCheck.thresholds?.[item.key];
                const checkPassed = gateCheck.checks?.[item.key];
                return (
                  <div key={idx} className="flex items-center justify-between p-3 bg-[#0d0d0d] rounded">
                    <div className="flex-1">
                      <p className="text-white text-sm font-medium">{item.name}</p>
                      <p className="text-xs text-[#8a8a8a] mt-1">{item.desc}: {val !== undefined ? (item.key === "dd" ? `≤ ${(val * 100).toFixed(0)}%` : item.key === "winrate" ? `≥ ${(val * 100).toFixed(0)}%` : item.key === "pf" ? `≥ ${val.toFixed(2)}` : `≥ ${(val * 100).toFixed(0)}%`) : item.defaultVal}</p>
                    </div>
                    <span className={`text-xs px-2 py-1 rounded-full ${
                      checkPassed ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"}`}
                    >
                      {checkPassed ? "✓ 通过" : "✗ 未通过"}
                    </span>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="text-center text-[#8a8a8a] py-4">
              {isLoadingClassicData ? "加载中..." : "暂无阈值配置"}
            </div>
          )}
        </div>

        {gateCheck.ok && (
          <div className="mt-4 bg-[#1a1a1a] rounded-lg p-4 border border-[#8b5cf6]/30">
            <div className="flex items-center justify-between">
              <h3 className="text-white font-medium">🚪 Gate Check 状态</h3>
              <span className={`text-xs px-3 py-1 rounded-full ${gateCheck.passed ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"}`}>
                {gateCheck.passed ? "✓ 全部通过" : "✗ 存在未通过项"}
              </span>
            </div>
            {gateCheck.metrics && (
              <div className="mt-3 grid grid-cols-4 gap-3 text-xs">
                <div className="text-center">
                  <div className="text-[#8a8a8a]">Profit Factor</div>
                  <div className={`text-lg font-bold ${gateCheck.metrics.pf >= 1 ? "text-green-400" : "text-red-400"}`}>
                    {gateCheck.metrics.pf?.toFixed(2) || "-"}
                  </div>
                </div>
                <div className="text-center">
                  <div className="text-[#8a8a8a]">Win Rate</div>
                  <div className="text-lg font-bold text-white">
                    {((gateCheck.metrics.winrate || 0) * 100).toFixed(1)}%
                  </div>
                </div>
                <div className="text-center">
                  <div className="text-[#8a8a8a]">Max DD</div>
                  <div className={`text-lg font-bold ${gateCheck.metrics.maxdd <= 0.1 ? "text-green-400" : "text-red-400"}`}>
                    {((gateCheck.metrics.maxdd || 0) * 100).toFixed(1)}%
                  </div>
                </div>
                <div className="text-center">
                  <div className="text-[#8a8a8a]">Trades</div>
                  <div className="text-lg font-bold text-white">{gateCheck.metrics.trades || "-"}</div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    );
  }

  // ---------- 信号执行 ----------
  if (subTab === "execution") {
    return (
      <div className="space-y-3">
        <h2 className="text-xl font-semibold text-white mb-2">⚡ 信号执行</h2>
        <p className="text-[#8a8a8a] text-sm">已通过过滤的信号触发交易所下单。显示最近的结算记录（ab_settlements）。</p>

        <div className="grid grid-cols-4 gap-3">
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
            <div className="text-2xl font-bold text-white">{settlements.length}</div>
            <div className="text-xs text-[#8a8a8a] mt-1">总结算数</div>
          </div>
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
            <div className="text-2xl font-bold text-green-400">
              {settlements.filter((s) => s.pnl_usdc > 0).length}
            </div>
            <div className="text-xs text-[#8a8a8a] mt-1">盈利次数</div>
          </div>
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
            <div className="text-2xl font-bold text-red-400">
              {settlements.filter((s) => s.pnl_usdc < 0).length}
            </div>
            <div className="text-xs text-[#8a8a8a] mt-1">亏损次数</div>
          </div>
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
            <div className="text-2xl font-bold text-yellow-400">
              {settlements.length > 0 ? (settlements.reduce((sum, s) => sum + s.pnl_usdc, 0)).toFixed(2) : "-"}
            </div>
            <div className="text-xs text-[#8a8a8a] mt-1">总盈亏 USDC</div>
          </div>
        </div>

        <div className="mt-4 bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
          <h3 className="text-white font-medium mb-3">💼 最近执行记录</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[#8a8a8a] text-xs border-b border-[#1f1f1f]">
                  <th className="py-2 px-3 text-left">时间</th>
                  <th className="py-2 px-3 text-left">策略</th>
                  <th className="py-2 px-3 text-left">交易对</th>
                  <th className="py-2 px-3 text-left">原因</th>
                  <th className="py-2 px-3 text-right">名义金额</th>
                  <th className="py-2 px-3 text-right">盈亏</th>
                  <th className="py-2 px-3 text-right">收益率</th>
                </tr>
              </thead>
              <tbody>
                {settlements.slice(0, 20).map((s, idx) => (
                  <tr key={s.event_id || idx} className="border-b border-[#1f1f1f] hover:bg-[#161616]">
                    <td className="py-2 px-3 text-[#6a6a6a]">
                      {s.ts ? new Date(s.ts).toLocaleString("zh-CN", { hour12: false, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "-"}
                    </td>
                    <td className="py-2 px-3 text-white">{s.strategy_id || "-"}</td>
                    <td className="py-2 px-3 text-white">{s.pair || "-"}</td>
                    <td className="py-2 px-3 text-[#8a8a8a]">{s.reason || "-"}</td>
                    <td className="py-2 px-3 text-right text-white">{s.notional_usdc?.toFixed(0) || "-"}</td>
                    <td className={`py-2 px-3 text-right ${s.pnl_usdc >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {s.pnl_usdc != null ? (s.pnl_usdc >= 0 ? "+" : "") + s.pnl_usdc.toFixed(2) : "-"}
                    </td>
                    <td className={`py-2 px-3 text-right ${s.ret_ratio >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {s.ret_ratio != null ? (s.ret_ratio >= 0 ? "+" : "") + (s.ret_ratio * 100).toFixed(2) + "%" : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {settlements.length === 0 && (
            <div className="text-center text-[#8a8a8a] py-8">
              {isLoadingClassicData ? "加载中..." : "暂无执行记录"}
            </div>
          )}
        </div>
      </div>
    );
  }

  // ---------- 离场管理 ----------
  if (subTab === "exit") {
    return (
      <div className="space-y-3">
        <h2 className="text-xl font-semibold text-white mb-2">🏁 离场管理</h2>
        <p className="text-[#8a8a8a] text-sm">策略离场管理。支持：固定止盈止损、移动止损（Trailing Stop）、时间止损、波动率自适应离场等。</p>

        <div className="grid grid-cols-3 gap-3">
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
            <div className="text-2xl font-bold text-white">{Object.keys(exitStats.open_positions).length}</div>
            <div className="text-xs text-[#8a8a8a] mt-1">当前持仓</div>
          </div>
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
            <div className="text-2xl font-bold text-green-400">{exitStats.exit_owner_state?.weights?.exit_feeder != null ? `${Math.round((exitStats.exit_owner_state.weights.exit_feeder || 0) * 100)}%` : "-"}</div>
            <div className="text-xs text-[#8a8a8a] mt-1">Exit Feeder 权重</div>
          </div>
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
            <div className="text-2xl font-bold text-yellow-400">{exitStats.exit_owner_state?.weights?.strategy != null ? `${Math.round((exitStats.exit_owner_state.weights.strategy || 0) * 100)}%` : "-"}</div>
            <div className="text-xs text-[#8a8a8a] mt-1">策略退出权重</div>
          </div>
        </div>

        {Object.keys(exitStats.open_positions).length > 0 ? (
          <div className="space-y-2">
            {Object.entries(exitStats.open_positions).map(([pair, pos]: [string, any]) => (
              <div key={pair} className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-3">
                    <span className="text-white font-medium">{pair}</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full ${pos.side === "long" ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"}`}>
                      {pos.side?.toUpperCase()}
                    </span>
                    <span className={`text-xs px-2 py-0.5 rounded-full ${pos.mode === "live" ? "bg-red-500/20 text-red-400" : "bg-yellow-500/20 text-yellow-400"}`}>
                      {pos.mode}
                    </span>
                  </div>
                  <span className="text-xs text-[#8a8a8a]">
                    {pos.strategy_id || pos.system_id}
                  </span>
                </div>
                <div className="grid grid-cols-4 gap-2 text-xs">
                  <div>
                    <span className="text-[#8a8a8a]">入场时间: </span>
                    <span className="text-white">{pos.entry_ts ? new Date(pos.entry_ts).toLocaleString("zh-CN", { hour12: false }) : "-"}</span>
                  </div>
                  <div>
                    <span className="text-[#8a8a8a]">持仓金额: </span>
                    <span className="text-white">{pos.notional_usdc?.toFixed(1)} USDC</span>
                  </div>
                  <div>
                    <span className="text-[#8a8a8a]">杠杆: </span>
                    <span className="text-white">{pos.leverage}x</span>
                  </div>
                  <div>
                    <span className="text-[#8a8a8a]">离场决策: </span>
                    <span className={pos.exit_l1_last_decision?.action === "hold" ? "text-green-400" : "text-yellow-400"}>
                      {pos.exit_l1_last_decision?.action || "-"}
                    </span>
                  </div>
                </div>
                <div className="mt-2 flex gap-4 text-xs">
                  <div>
                    <span className="text-[#8a8a8a]">持有价值: </span>
                    <span className={pos.hold_value >= 0.9 ? "text-green-400" : pos.hold_value >= 0.7 ? "text-yellow-400" : "text-red-400"}>
                      {(pos.hold_value * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div>
                    <span className="text-[#8a8a8a]">持有风险: </span>
                    <span className="text-red-400">{(pos.hold_risk * 100).toFixed(1)}%</span>
                  </div>
                  <div>
                    <span className="text-[#8a8a8a]">退出方: </span>
                    <span className="text-white">{pos.exit_owner || "-"}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center text-[#8a8a8a] py-8 bg-[#1a1a1a] rounded-lg border border-[#1f1f1f]">
            {isLoadingClassicData ? "加载中..." : "暂无持仓"}
          </div>
        )}
      </div>
    );
  }

  // ---------- 多模型投票 ----------
  if (subTab === "arena") {
    return (
      <div className="space-y-3">
        <h2 className="text-xl font-semibold text-white mb-2">🎲 多模型投票 (Arena)</h2>
        <p className="text-[#8a8a8a] text-sm">多模型竞争与投票机制，决定哪个模型负责执行交易。</p>

        <div className="grid grid-cols-3 gap-3">
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
            <div className="text-2xl font-bold text-white">{arenaState.enabled ? "运行中" : "未启用"}</div>
            <div className="text-xs text-[#8a8a8a] mt-1">Arena 状态</div>
          </div>
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
            <div className="text-2xl font-bold text-green-400">{arenaState.models ? Object.keys(arenaState.models).length : 0}</div>
            <div className="text-xs text-[#8a8a8a] mt-1">参与模型数</div>
          </div>
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
            <div className="text-2xl font-bold text-yellow-400">{arenaState.pool_u != null ? arenaState.pool_u.toFixed(2) : "-"}</div>
            <div className="text-xs text-[#8a8a8a] mt-1">Pool U</div>
          </div>
        </div>

        {arenaState.models && Object.keys(arenaState.models).length > 0 ? (
          <div className="space-y-2">
            {Object.entries(arenaState.models).map(([modelId, model]: [string, any]) => (
              <div key={modelId} className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-white font-medium">{model.name || modelId}</span>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${model.eligible ? "bg-green-500/20 text-green-400" : "bg-[#2a2a2a] text-[#8a8a8a]"}`}>
                    {model.eligible ? "合格" : "待观察"}
                  </span>
                </div>
                <div className="grid grid-cols-4 gap-2 text-xs">
                  <div>
                    <span className="text-[#8a8a8a]">Capital U: </span>
                    <span className="text-white">{model.capital_u?.toFixed(2) || "-"}</span>
                  </div>
                  <div>
                    <span className="text-[#8a8a8a]">Sharpe: </span>
                    <span className="text-white">{model.sharpe?.toFixed(2) || "-"}</span>
                  </div>
                  <div>
                    <span className="text-[#8a8a8a]">Win Rate: </span>
                    <span className="text-white">{model.win_rate?.toFixed(2) || "-"}</span>
                  </div>
                  <div>
                    <span className="text-[#8a8a8a]">LogLoss: </span>
                    <span className="text-white">{model.avg_logloss?.toFixed(4) || "-"}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center text-[#8a8a8a] py-8 bg-[#1a1a1a] rounded-lg border border-[#1f1f1f]">
            {isLoadingClassicData ? "加载中..." : "暂无模型数据"}
          </div>
        )}
      </div>
    );
  }

  // ---------- 代币筛选 ----------
  if (subTab === "universe") {
    return (
      <div className="space-y-3">
        <h2 className="text-xl font-semibold text-white mb-2">🌐 代币筛选 (Universe)</h2>
        <p className="text-[#8a8a8a] text-sm">核心代币池 + 观察池 + 影子池。策略只在这些代币对中生成信号。</p>

        <div className="grid grid-cols-3 gap-3">
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
            <div className="text-2xl font-bold text-green-400">{universeState.core?.length || 0}</div>
            <div className="text-xs text-[#8a8a8a] mt-1">核心币 (Core)</div>
          </div>
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
            <div className="text-2xl font-bold text-yellow-400">{universeState.watchlist?.length || 0}</div>
            <div className="text-xs text-[#8a8a8a] mt-1">观察列表 (Watchlist)</div>
          </div>
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
            <div className="text-2xl font-bold text-blue-400">{universeState.shadow?.length || 0}</div>
            <div className="text-xs text-[#8a8a8a] mt-1">影子池 (Shadow)</div>
          </div>
        </div>

        <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
          <h3 className="text-white font-medium mb-3">核心代币 (Core) - {universeState.core?.length || 0} 个</h3>
          <div className="flex flex-wrap gap-2">
            {universeState.core?.slice(0, 30).map((coin: string) => (
              <span key={coin} className="px-2 py-1 bg-[#2a2a2a] rounded-md text-xs text-green-400">
                {coin}
              </span>
            ))}
          </div>
          {universeState.core && universeState.core.length > 30 && (
            <div className="text-xs text-[#8a8a8a] mt-2">还有 {universeState.core.length - 30} 个...</div>
          )}
        </div>

        {universeState.watchlist && universeState.watchlist.length > 0 && (
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
            <h3 className="text-white font-medium mb-3">观察列表 (Watchlist) - {universeState.watchlist.length} 个</h3>
            <div className="flex flex-wrap gap-2">
              {universeState.watchlist.map((coin: string) => (
                <span key={coin} className="px-2 py-1 bg-[#2a2a2a] rounded-md text-xs text-yellow-400">
                  {coin}
                </span>
              ))}
            </div>
          </div>
        )}

        {universeState.shadow && universeState.shadow.length > 0 && (
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
            <h3 className="text-white font-medium mb-3">影子池 (Shadow) - {universeState.shadow.length} 个</h3>
            <div className="flex flex-wrap gap-2">
              {universeState.shadow.slice(0, 20).map((coin: string) => (
                <span key={coin} className="px-2 py-1 bg-[#2a2a2a] rounded-md text-xs text-blue-400">
                  {coin}
                </span>
              ))}
            </div>
          </div>
        )}

        <div className="text-xs text-[#8a8a8a]">
          最后更新: {universeState.last_update ? new Date(universeState.last_update).toLocaleString("zh-CN", { hour12: false }) : "-"}
        </div>
      </div>
    );
  }

  // ---------- 宏观门控 ----------
  if (subTab === "macro") {
    return (
      <div className="space-y-3">
        <h2 className="text-xl font-semibold text-white mb-2">📊 宏观门控 (Macro)</h2>
        <p className="text-[#8a8a8a] text-sm">BTC/ETH 市场整体状态。门控决定在特定市场环境下是否允许开仓。</p>

        <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
          <h3 className="text-white font-medium mb-3">Gate 状态</h3>
          <div className="grid grid-cols-2 gap-3">
            <div className="text-center">
              <div className={`text-2xl font-bold ${macroState.gate_std1h?.effective_long_ok ? "text-green-400" : "text-red-400"}`}>
                {macroState.gate_std1h?.effective_long_ok ? "允许做多" : "禁止做多"}
              </div>
              <div className="text-xs text-[#8a8a8a] mt-1">Long Direction</div>
            </div>
            <div className="text-center">
              <div className={`text-2xl font-bold ${macroState.gate_std1h?.effective_short_ok ? "text-green-400" : "text-red-400"}`}>
                {macroState.gate_std1h?.effective_short_ok ? "允许做空" : "禁止做空"}
              </div>
              <div className="text-xs text-[#8a8a8a] mt-1">Short Direction</div>
            </div>
          </div>
          <div className="mt-3 text-center text-xs text-[#8a8a8a]">
            当前推荐: <span className="text-white">{macroState.gate_std1h?.effective_recommend || "-"}</span>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
            <h3 className="text-white font-medium mb-3">BTC</h3>
            <div className="space-y-1 text-xs">
              {(() => {
                const energyRows = (macroState.btc?.energy as any)?.rows || [];
                const trendRows = (macroState.btc?.trend as any)?.rows || [];
                const latestEnergy = energyRows[energyRows.length - 1] || {};
                const latestTrend = trendRows[trendRows.length - 1] || {};
                return (
                  <>
                    <div><span className="text-[#8a8a8a]">Close: </span><span className="text-white">{latestEnergy.close?.toFixed(2) || "-"}</span></div>
                    <div><span className="text-[#8a8a8a]">Regime: </span><span className="text-white">{latestTrend.time_regime || "-"}</span></div>
                    <div><span className="text-[#8a8a8a]">Shape: </span><span className="text-white">{latestTrend.trend_shape_5 || "-"}</span></div>
                  </>
                );
              })()}
            </div>
          </div>
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
            <h3 className="text-white font-medium mb-3">ETH</h3>
            <div className="space-y-1 text-xs">
              {(() => {
                const energyRows = (macroState.eth?.energy as any)?.rows || [];
                const trendRows = (macroState.eth?.trend as any)?.rows || [];
                const latestEnergy = energyRows[energyRows.length - 1] || {};
                const latestTrend = trendRows[trendRows.length - 1] || {};
                return (
                  <>
                    <div><span className="text-[#8a8a8a]">Close: </span><span className="text-white">{latestEnergy.close?.toFixed(2) || "-"}</span></div>
                    <div><span className="text-[#8a8a8a]">Regime: </span><span className="text-white">{latestTrend.time_regime || "-"}</span></div>
                    <div><span className="text-[#8a8a8a]">Shape: </span><span className="text-white">{latestTrend.trend_shape_5 || "-"}</span></div>
                  </>
                );
              })()}
            </div>
          </div>
        </div>

        {macroState.macro_btceth_shape && (
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
            <h3 className="text-white font-medium mb-3">Shape 状态</h3>
            <div className="space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-[#8a8a8a]">方向判断:</span>
                <span className={`${macroState.macro_btceth_shape.dir_12h === "long" ? "text-green-400" : macroState.macro_btceth_shape.dir_12h === "short" ? "text-red-400" : "text-white"}`}>
                  {macroState.macro_btceth_shape.dir_12h || "-"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#8a8a8a]">允许做多:</span>
                <span className={macroState.macro_btceth_shape.dir_long_any ? "text-green-400" : "text-red-400"}>
                  {macroState.macro_btceth_shape.dir_long_any ? "是" : "否"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#8a8a8a]">允许做空:</span>
                <span className={macroState.macro_btceth_shape.dir_short_any ? "text-red-400" : "text-green-400"}>
                  {macroState.macro_btceth_shape.dir_short_any ? "是" : "否"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#8a8a8a]">OK:</span>
                <span className={macroState.macro_btceth_shape.ok ? "text-green-400" : "text-yellow-400"}>
                  {macroState.macro_btceth_shape.ok ? "正常" : "警告"}
                </span>
              </div>
            </div>
          </div>
        )}

        {macroState.macro_tri_layer && (
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
            <h3 className="text-white font-medium mb-3">Tri-Layer 控制</h3>
            <div className="space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-[#8a8a8a]">允许开仓:</span>
                <span className={macroState.macro_tri_layer.allow_open ? "text-green-400" : "text-red-400"}>
                  {macroState.macro_tri_layer.allow_open ? "是" : "否"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#8a8a8a]">允许附加:</span>
                <span className={macroState.macro_tri_layer.allow_addon ? "text-green-400" : "text-red-400"}>
                  {macroState.macro_tri_layer.allow_addon ? "是" : "否"}
                </span>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }

  // ---------- 模型评估 ----------
  if (subTab === "evaluation") {
    return (
      <div className="space-y-3">
        <h2 className="text-xl font-semibold text-white mb-2">📈 模型评估 (Evaluation)</h2>
        <p className="text-[#8a8a8a] text-sm">模型接受度、在线学习、版本控制与晋升机制。</p>

        <div className="grid grid-cols-4 gap-3">
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
            <div className="text-2xl font-bold text-white">{evaluationState.orders?.total ?? "-"}</div>
            <div className="text-xs text-[#8a8a8a] mt-1">总订单数</div>
          </div>
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
            <div className="text-2xl font-bold text-green-400">{evaluationState.orders?.window ?? "-"}</div>
            <div className="text-xs text-[#8a8a8a] mt-1">窗口期订单</div>
          </div>
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
            <div className="text-2xl font-bold text-yellow-400">{evaluationState.profit_window?.profit_factor?.toFixed(2) || "-"}</div>
            <div className="text-xs text-[#8a8a8a] mt-1">Profit Factor</div>
          </div>
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
            <div className="text-2xl font-bold text-blue-400">v{evaluationState.online?.version || "-"}</div>
            <div className="text-xs text-[#8a8a8a] mt-1">模型版本</div>
          </div>
        </div>

        {evaluationState.acceptance && (
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
            <h3 className="text-white font-medium mb-3">接受度控制</h3>
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="space-y-1">
                <div className="flex justify-between">
                  <span className="text-[#8a8a8a]">采样阶段:</span>
                  <span className="text-white">{String(evaluationState.acceptance.sampling_phase)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[#8a8a8a]">利润阶段:</span>
                  <span className="text-white">{String(evaluationState.acceptance.profit_phase)}</span>
                </div>
              </div>
              <div className="space-y-1">
                <div className="flex justify-between">
                  <span className="text-[#8a8a8a]">主释放门:</span>
                  <span className={evaluationState.acceptance.main_release_gate ? "text-green-400" : "text-yellow-400"}>
                    {String(evaluationState.acceptance.main_release_gate)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[#8a8a8a]">回滚状态:</span>
                  <span className="text-white">{String(evaluationState.acceptance.rollback)}</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {evaluationState.online && (
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
            <h3 className="text-white font-medium mb-3">在线学习状态</h3>
            <div className="space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-[#8a8a8a]">上次训练:</span>
                <span className="text-white">
                  {evaluationState.online.last_train_ms ? new Date(evaluationState.online.last_train_ms).toLocaleString("zh-CN", { hour12: false }) : "-"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#8a8a8a]">上次晋升:</span>
                <span className="text-white">
                  {evaluationState.online.last_promote_ms ? new Date(evaluationState.online.last_promote_ms).toLocaleString("zh-CN", { hour12: false }) : "-"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#8a8a8a]">训练样本:</span>
                <span className="text-white">{evaluationState.online.train_sample_count ?? "-"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#8a8a8a]">ART 训练:</span>
                <span className={evaluationState.online.artifact_trained ? "text-green-400" : "text-yellow-400"}>
                  {String(evaluationState.online.artifact_trained)}
                </span>
              </div>
            </div>
          </div>
        )}

        {evaluationState.profit_window && (
          <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
            <h3 className="text-white font-medium mb-3">利润窗口 ({evaluationState.profit_window.days || "-"} 天)</h3>
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="flex justify-between">
                <span className="text-[#8a8a8a]">样本数:</span>
                <span className="text-white">{evaluationState.profit_window.n || "-"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#8a8a8a]">最大回撤 U:</span>
                <span className="text-red-400">{evaluationState.profit_window.max_drawdown_u?.toFixed(2) || "-"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#8a8a8a]">Profit Factor:</span>
                <span className={evaluationState.profit_window.profit_factor >= 2 ? "text-green-400" : "text-yellow-400"}>
                  {evaluationState.profit_window.profit_factor?.toFixed(2) || "-"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#8a8a8a]">最大恢复耗时:</span>
                <span className="text-white">{evaluationState.profit_window.max_recovery_ms || "-"}</span>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }

  // Fallback
  return null;
}
