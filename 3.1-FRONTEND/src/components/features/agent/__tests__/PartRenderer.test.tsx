// ============================================
// PartRenderer 组件测试 — 6 类 part + 未知类型降级
// ============================================

import React from 'react';
import { render, screen } from '@testing-library/react';
import { PartRenderer, UnknownPart } from '../PartRenderer';
import type { AgentPart } from '@/types/agent-message';

// react-markdown v10 为 ESM-only，jest 不转译 node_modules；渲染内容非本测试目标，直接降级为纯文本容器
jest.mock('react-markdown', () => {
  const ReactActual = jest.requireActual<typeof import('react')>('react');
  return {
    __esModule: true,
    default: ({ children }: { children?: React.ReactNode }) => ReactActual.createElement('div', null, children),
  };
});

describe('PartRenderer', () => {
  it('text part 渲染文本内容', () => {
    render(<PartRenderer part={{ type: 'text', text: '**粗体**' }} />);
    expect(screen.getByText('**粗体**')).toBeInTheDocument();
  });

  it('reasoning part 渲染为折叠块', () => {
    render(<PartRenderer part={{ type: 'reasoning', text: '思考内容', durationMs: 350 }} />);
    const details = screen.getByTestId('reasoning-part');
    expect(details).toHaveTextContent('推理过程');
    expect(details).toHaveTextContent('350ms');
  });

  it('tool part 委托 ToolCard', () => {
    render(<PartRenderer part={{ type: 'tool', callId: 'c1', toolName: 'l0.shell.mcp.recall', state: 'success', result: 'ok' }} />);
    expect(screen.getByTestId('tool-card')).toBeInTheDocument();
    expect(screen.getByTestId('tool-state-label')).toHaveTextContent('完成');
  });

  it('plan-card part 委托 PlanCardView', () => {
    const card = {
      id: 'pc-1',
      intent: '复现策略',
      plan_steps: [{ step: 1, action: '取数', tool: 'l0.data.mcp.query' }],
      validation: { evaluator_refs: ['45.eval@0.1.0'] },
    };
    render(<PartRenderer part={{ type: 'plan-card', card }} />);
    expect(screen.getByTestId('plan-card')).toBeInTheDocument();
  });

  it('artifact part 渲染标题与种类', () => {
    render(<PartRenderer part={{ type: 'artifact', artifactId: 'art_1', title: '每日报告', kind: 'report' }} />);
    const node = screen.getByTestId('artifact-part');
    expect(node).toHaveTextContent('报告');
    expect(node).toHaveTextContent('每日报告');
  });

  it('verification part 渲染三态徽标与证据', () => {
    render(<PartRenderer part={{ type: 'verification', verdict: 'BLOCK', evidenceRefs: ['e1'] }} />);
    const node = screen.getByTestId('verification-part');
    expect(node).toHaveTextContent('BLOCK');
    expect(node).toHaveTextContent('e1');
  });

  it('未知类型降级为 JSON 折叠，不抛错、不白屏', () => {
    const unknown = { type: 'mystery', payload: { a: 1 } };
    render(<PartRenderer part={unknown as unknown as AgentPart} />);
    const details = screen.getByTestId('unknown-part');
    expect(details).toHaveTextContent('未知消息类型：mystery');
    expect(details).toHaveTextContent('"payload"');
  });

  it('UnknownPart 单独渲染同样降级', () => {
    render(<UnknownPart part={{ type: 'mystery', raw: 'x' }} />);
    expect(screen.getByTestId('unknown-part')).toHaveTextContent('mystery');
  });
});
