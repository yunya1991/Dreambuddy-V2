// ============================================
// PlanCardView 组件测试 — 合法渲染 / 未知工具标红 / 缺字段降级
// ============================================

import React from 'react';
import { render, screen } from '@testing-library/react';
import { PlanCardView } from '../PlanCardView';

const VALID_CARD = {
  id: 'pc-1',
  intent: '复现并优化均值回归策略',
  context_refs: ['c-ref'],
  plan_steps: [
    { step: 1, action: '拉取历史行情', tool: 'l0.data.mcp.query' },
    { step: 2, action: '回测统计', tool: 'l0.engine.mcp.backtest' },
  ],
  risk_flags: ['过拟合风险', '样本外失效'],
  cost_estimate: { tokens: 5000, tool_calls: 8 },
  expected_outcome: '夏普 > 1.5',
  validation: { evaluator_refs: ['45.eval_system@0.1.0'] },
  debate_meta: { debate_id: 'd1', side: 'A', verdict: 'WIN' },
};

describe('PlanCardView', () => {
  it('合法 fixture 渲染 id/intent/步骤/风险/验收引用/verdict', () => {
    render(<PlanCardView card={VALID_CARD} />);
    expect(screen.getByTestId('plan-card')).toBeInTheDocument();
    expect(screen.getByText('pc-1')).toBeInTheDocument();
    expect(screen.getByText('复现并优化均值回归策略')).toBeInTheDocument();
    expect(screen.getByText('拉取历史行情')).toBeInTheDocument();
    expect(screen.getByText('l0.data.mcp.query')).toBeInTheDocument();
    expect(screen.getByTestId('plan-risk-flags')).toHaveTextContent('过拟合风险');
    expect(screen.getByText('45.eval_system@0.1.0')).toBeInTheDocument();
    expect(screen.getByTestId('plan-verdict')).toHaveTextContent('胜出');
    // 合法工具名不标红
    expect(screen.queryByTestId('plan-tool-unknown')).toBeNull();
  });

  it('工具名不符合注册规范时标红并提示', () => {
    render(
      <PlanCardView
        card={{ ...VALID_CARD, plan_steps: [{ step: 1, action: 'x', tool: 'not_registered_tool' }] }}
      />,
    );
    expect(screen.getByTestId('plan-tool-unknown')).toBeInTheDocument();
    const tool = screen.getByTestId('plan-step-tool');
    expect(tool).toHaveTextContent('not_registered_tool');
    expect(tool).toHaveClass('text-red-400');
  });

  it('knownTools 提供时按注册表精确判定', () => {
    render(<PlanCardView card={VALID_CARD} knownTools={new Set(['l0.data.mcp.query'])} />);
    // 第一个工具已注册、第二个未注册
    const unknown = screen.getAllByTestId('plan-tool-unknown');
    expect(unknown).toHaveLength(1);
    const tools = screen.getAllByTestId('plan-step-tool');
    expect(tools[0]).toHaveTextContent('l0.data.mcp.query');
    expect(tools[0]).not.toHaveTextContent('未注册工具');
    expect(tools[1]).toHaveTextContent('l0.engine.mcp.backtest');
    expect(tools[1]).toHaveTextContent('未注册工具');
  });

  it('缺必填字段（缺 validation）时降级为 JSON 折叠，不抛错', () => {
    const invalid = { ...VALID_CARD, validation: undefined };
    render(<PlanCardView card={invalid} />);
    const fallback = screen.getByTestId('plan-card-fallback');
    expect(fallback).toHaveTextContent('PlanCard 数据不符合契约');
    expect(fallback).toHaveTextContent('"plan_steps"');
  });

  it('tool 命名规范合法但 id 非法时同样降级', () => {
    render(<PlanCardView card={{ ...VALID_CARD, id: 'bad-id' }} />);
    expect(screen.getByTestId('plan-card-fallback')).toBeInTheDocument();
  });
});
