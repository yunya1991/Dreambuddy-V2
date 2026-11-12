// ============================================
// ToolCard 组件测试 — 四态 + 折叠阈值 + 复制降级
// ============================================

import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { ToolCard, TOOL_FOLD_LINE_THRESHOLD } from '../ToolCard';
import type { AgentPart } from '@/types/agent-message';

// react-markdown v10 为 ESM-only，jest 不转译 node_modules；直接降级为纯文本容器
jest.mock('react-markdown', () => {
  const ReactActual = jest.requireActual<typeof import('react')>('react');
  return {
    __esModule: true,
    default: ({ children }: { children?: React.ReactNode }) => ReactActual.createElement('div', null, children),
  };
});

function toolPart(overrides: Partial<Extract<AgentPart, { type: 'tool' }>>): Extract<AgentPart, { type: 'tool' }> {
  return { type: 'tool', callId: 'c1', toolName: 'l0.shell.mcp.recall', state: 'pending', ...overrides };
}

describe('ToolCard 四态', () => {
  it('pending 显示排队中', () => {
    render(<ToolCard part={toolPart({ state: 'pending' })} />);
    expect(screen.getByTestId('tool-state-label')).toHaveTextContent('排队中');
    expect(screen.getByTestId('tool-card')).toHaveAttribute('data-state', 'pending');
  });

  it('running 显示进行中', () => {
    render(<ToolCard part={toolPart({ state: 'running' })} />);
    expect(screen.getByTestId('tool-state-label')).toHaveTextContent('进行中');
  });

  it('success 默认折叠，展开显示结果摘要与耗时', () => {
    const { container } = render(
      <ToolCard part={toolPart({ state: 'success', result: '第 1 行\n第 2 行', durationMs: 2500 })} />,
    );
    expect(screen.getByTestId('tool-state-label')).toHaveTextContent('完成');
    expect(container.querySelector('[aria-expanded="false"]')).not.toBeNull();
    expect(screen.getByTestId('tool-card')).toHaveTextContent('2.5s');

    fireEvent.click(screen.getByRole('button', { name: /展开结果/ }));
    expect(screen.getByText(/第 2 行/)).toBeInTheDocument();
  });

  it('error 默认展开并显示错误首行与重试按钮（仅注入 onRetry 时）', () => {
    const onRetry = jest.fn();
    const { container } = render(
      <ToolCard part={toolPart({ state: 'error', error: '连接超时\ndetail' })} onRetry={onRetry} />,
    );
    expect(screen.getByTestId('tool-error')).toHaveTextContent('连接超时');
    const retry = screen.getByRole('button', { name: '重试' });
    fireEvent.click(retry);
    expect(onRetry).toHaveBeenCalled();
    expect(container.querySelector('[aria-expanded="true"]')).not.toBeNull();
  });

  it('未注入 onRetry 时 error 态不显示重试', () => {
    render(<ToolCard part={toolPart({ state: 'error', error: 'x' })} />);
    expect(screen.queryByRole('button', { name: '重试' })).toBeNull();
  });
});

describe('ToolCard 折叠与复制', () => {
  it(`结果超过 ${TOOL_FOLD_LINE_THRESHOLD} 行显示展开全部`, () => {
    const lines = Array.from({ length: TOOL_FOLD_LINE_THRESHOLD + 3 }, (_, i) => `行 ${i + 1}`);
    render(<ToolCard part={toolPart({ state: 'success', result: lines.join('\n') })} />);
    fireEvent.click(screen.getByRole('button', { name: /展开结果/ }));
    expect(screen.getByRole('button', { name: new RegExp(`展开全部.*${lines.length} 行`) })).toBeInTheDocument();
    expect(screen.queryByText(new RegExp(`行 ${TOOL_FOLD_LINE_THRESHOLD + 3}`))).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: /展开全部/ }));
    expect(screen.getByText(new RegExp(`行 ${TOOL_FOLD_LINE_THRESHOLD + 3}`))).toBeInTheDocument();
  });

  it('不足阈值行数不出现展开全部', () => {
    render(<ToolCard part={toolPart({ state: 'success', result: 'a\nb' })} />);
    fireEvent.click(screen.getByRole('button', { name: /展开结果/ }));
    expect(screen.queryByRole('button', { name: /展开全部/ })).toBeNull();
  });

  it('clipboard 不可用降级提示', () => {
    const original = navigator.clipboard;
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
    render(<ToolCard part={toolPart({ state: 'success', result: '内容' })} />);
    fireEvent.click(screen.getByRole('button', { name: /展开结果/ }));
    fireEvent.click(screen.getByRole('button', { name: /复制/ }));
    expect(screen.getByTestId('tool-copy-label')).toHaveTextContent('复制不可用');
    Object.defineProperty(navigator, 'clipboard', { value: original, configurable: true });
  });
});
