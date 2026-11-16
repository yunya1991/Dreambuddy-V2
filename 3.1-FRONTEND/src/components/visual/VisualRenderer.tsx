'use client';

// SPEC-54 图规格统一渲染入口：按 kind 分派（table/series/tree/graph），未知 kind 走空态

import { V3Badge, V3Empty } from '@/components';
import { GraphView } from './GraphView';
import { MatrixView } from './MatrixView';
import { SeriesView } from './SeriesView';
import { TableView } from './TableView';
import { TreeView } from './TreeView';
import type { VisualColumn, VisualNode, VisualPoint, VisualSpec } from './types';

const SCOPE_LABEL: Record<string, string> = {
  global: '全局样本',
  per_row: '逐行样本',
  per_cell: '逐格样本',
};

function renderBody(visual: VisualSpec) {
  const dataset = visual.dataset as Record<string, any>;

  if (visual.kind === 'tree') {
    const root = dataset?.root as VisualNode | undefined;
    if (!root) return <V3Empty title="树结构为空" description="后端未返回 dataset.root" />;
    return <TreeView root={root} />;
  }

  if (visual.kind === 'graph') {
    const nodes = (dataset?.nodes ?? []) as { id: string; label: string; group?: string | null }[];
    const edges = (dataset?.edges ?? []) as {
      src: string;
      dst: string;
      kind: string;
      weight: number | null;
      p_adj: number | null;
    }[];
    if (nodes.length === 0) return <V3Empty title="网络为空" description="后端未返回可用节点" />;
    return (
      <GraphView nodes={nodes} edges={edges} meta={(dataset?.meta ?? {}) as Record<string, any>} />
    );
  }

  if (visual.kind === 'series') {
    const points = (dataset?.points ?? []) as VisualPoint[];
    if (points.length === 0) return <V3Empty title="曲线无数据点" description="当前样本不足以产图" />;
    return <SeriesView points={points} meta={(dataset?.meta ?? {}) as Record<string, any>} />;
  }

  if (visual.kind === 'matrix') {
    const rowLabels = (dataset?.row_labels ?? []) as string[];
    const colLabels = (dataset?.col_labels ?? []) as string[];
    const values = (dataset?.values ?? []) as (number | null)[][];
    if (rowLabels.length === 0 || colLabels.length === 0) {
      return <V3Empty title="矩阵无数据" description="后端未返回 matrix 的行列标签" />;
    }
    return (
      <MatrixView
        rowLabels={rowLabels}
        colLabels={colLabels}
        values={values}
        annotations={visual.annotations}
      />
    );
  }

  if (visual.kind === 'table') {
    const columns = (dataset?.columns ?? []) as VisualColumn[];
    const rows = (dataset?.rows ?? []) as Record<string, unknown>[];
    if (columns.length === 0 || rows.length === 0) {
      return <V3Empty title="表格无数据" description="当前样本不足以产表" />;
    }
    return <TableView columns={columns} rows={rows} />;
  }

  return <V3Empty title="暂不支持的图类型" description={`kind=${visual.kind}`} />;
}

export function VisualRenderer({ visual, showTitle = true }: { visual: VisualSpec; showTitle?: boolean }) {
  return (
    <div className="space-y-2">
      {showTitle && (
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm font-medium text-slate-200 truncate">{visual.title}</p>
            <p className="text-[10px] text-slate-500">
              {visual.source_capability} · {SCOPE_LABEL[visual.n_scope] ?? visual.n_scope} · spec{' '}
              {visual.spec_version}
              {visual.truncated ? ' · 已截断' : ''}
            </p>
          </div>
          <V3Badge variant="default" label={visual.kind} />
        </div>
      )}
      {renderBody(visual)}
      <p className="text-[10px] text-amber-500/70">{visual.caveat}</p>
    </div>
  );
}

export default VisualRenderer;
