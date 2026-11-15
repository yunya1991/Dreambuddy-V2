'use client';

// T3 思维导图渲染：缩进折叠树；缺源叶显式显示 meta.reason（前端不做任何统计）

import { useState } from 'react';
import { IconChevronDown, IconChevronRight } from '@/components';
import { formatValue, type VisualNode } from './types';

function NodeRow({ node, depth }: { node: VisualNode; depth: number }) {
  const children = node.children ?? [];
  const hasChildren = children.length > 0;
  const [open, setOpen] = useState(depth < 2);

  return (
    <div>
      <button
        type="button"
        onClick={() => hasChildren && setOpen(v => !v)}
        className={`w-full flex items-center gap-1.5 py-1 pr-2 rounded text-left ${
          hasChildren ? 'hover:bg-slate-800/60' : 'cursor-default'
        }`}
        style={{ paddingLeft: 8 + depth * 14 }}
      >
        <span className="w-3 shrink-0 text-slate-500">
          {hasChildren && (open ? <IconChevronDown size={12} /> : <IconChevronRight size={12} />)}
        </span>
        <span className={`text-xs ${hasChildren ? 'text-slate-200 font-medium' : 'text-slate-400'}`}>
          {node.label}
        </span>
        {!hasChildren && (
          <span className="ml-auto flex items-center gap-2 min-w-0">
            <span
              className={`text-xs tabular-nums shrink-0 ${node.value === null ? 'text-slate-600' : 'text-slate-200'}`}
            >
              {formatValue(node.value, node.meta?.unit)}
            </span>
            {node.meta?.reason && (
              <span
                className="text-[10px] text-amber-500/70 truncate max-w-[200px]"
                title={node.meta.reason}
              >
                {node.meta.reason}
              </span>
            )}
          </span>
        )}
      </button>
      {hasChildren && open && children.map(child => <NodeRow key={child.id} node={child} depth={depth + 1} />)}
    </div>
  );
}

export function TreeView({ root }: { root: VisualNode }) {
  return (
    <div className="max-h-[520px] overflow-auto rounded-lg border border-slate-800/60 bg-slate-900/30 py-1">
      <NodeRow node={root} depth={0} />
    </div>
  );
}

export default TreeView;
