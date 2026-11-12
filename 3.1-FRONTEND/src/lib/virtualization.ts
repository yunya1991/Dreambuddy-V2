// ============================================
// 长会话虚拟化阈值（SPEC-20261111-B §3.8 / T-B8）
// ============================================
// 零依赖策略：先启用 content-visibility，由浏览器跳过屏外消息的布局与绘制。
// 阈值以下不启用，避免短会话引入额外样式开销。

export const VIRTUALIZE_THRESHOLD = 50;

/** 消息数是否达到虚拟化阈值（>50 条启用） */
export function shouldVirtualize(messageCount: number): boolean {
  return Number.isFinite(messageCount) && messageCount > VIRTUALIZE_THRESHOLD;
}

/**
 * 屏外消息行的内联样式（`content-visibility: auto` + 估算高度占位）。
 * 仅在 shouldVirtualize 为 true 时应用。
 */
export const VIRTUALIZED_ROW_STYLE = {
  contentVisibility: 'auto',
  containIntrinsicSize: 'auto 120px',
} as const;
