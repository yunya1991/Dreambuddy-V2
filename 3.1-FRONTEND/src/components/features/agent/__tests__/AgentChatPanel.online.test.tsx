/**
 * AgentChatPanel 断网续流回归
 *
 * 场景：流因断网中断（status -> error）后，浏览器恢复联网（online 事件）
 * 自动重试该轮一次；同一中断不得重复重试。
 */

import { render, act, screen } from '@testing-library/react';
import { useChat } from '@ai-sdk/react';

jest.mock('@ai-sdk/react', () => ({
  useChat: jest.fn(),
}));

// jsdom 无 TransformStream，ai 包在导入期即构造流工具，需整体替换
jest.mock('ai', () => ({
  DefaultChatTransport: class {
    constructor(public options: unknown) {}
  },
}));

jest.mock('@/components/features/agent/PartRenderer', () => ({ PartList: () => null }));
jest.mock('@/components/features/chat/ChatInput', () => ({ ChatInput: () => null }));
jest.mock('@/stores/agent-session-store', () => ({
  useAgentSessionStore: (selector: (s: unknown) => unknown) =>
    selector({ setMessages: jest.fn(), sessions: [] }),
}));

import { AgentChatPanel } from '../AgentChatPanel';

const useChatMock = useChat as unknown as jest.Mock;

// jsdom 未实现 scrollIntoView
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = jest.fn();
}

function setOnline(value: boolean) {
  Object.defineProperty(navigator, 'onLine', { configurable: true, value });
}

const USER_MESSAGE = {
  id: 'u1',
  role: 'user',
  parts: [{ type: 'text', text: '你好' }],
};

describe('AgentChatPanel 断网续流', () => {
  const regenerate = jest.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    regenerate.mockClear();
    setOnline(true);
    useChatMock.mockReturnValue({
      messages: [USER_MESSAGE],
      sendMessage: jest.fn(),
      status: 'error',
      error: new TypeError('Failed to fetch'),
      stop: jest.fn(),
      regenerate,
    });
  });

  it('离线显示提示；恢复联网后自动重试一次，且不重复重试', () => {
    render(<AgentChatPanel sessionId="s1" title="测试会话" />);

    act(() => {
      setOnline(false);
      window.dispatchEvent(new Event('offline'));
    });
    expect(screen.getByText(/网络已断开/)).toBeTruthy();
    expect(regenerate).not.toHaveBeenCalled();

    act(() => {
      setOnline(true);
      window.dispatchEvent(new Event('online'));
    });
    expect(regenerate).toHaveBeenCalledTimes(1);

    act(() => {
      window.dispatchEvent(new Event('online'));
    });
    expect(regenerate).toHaveBeenCalledTimes(1);
  });

  it('未发生中断（status=ready）时恢复联网不触发重试', () => {
    useChatMock.mockReturnValue({
      messages: [USER_MESSAGE],
      sendMessage: jest.fn(),
      status: 'ready',
      error: undefined,
      stop: jest.fn(),
      regenerate,
    });

    render(<AgentChatPanel sessionId="s2" title="测试会话" />);

    act(() => {
      window.dispatchEvent(new Event('online'));
    });

    expect(regenerate).not.toHaveBeenCalled();
  });

  it('messages 为空时不调用 regenerate（避免 message not found 抛错）', () => {
    useChatMock.mockReturnValue({
      messages: [],
      sendMessage: jest.fn(),
      status: 'error',
      error: new TypeError('Failed to fetch'),
      stop: jest.fn(),
      regenerate,
    });

    render(<AgentChatPanel sessionId="s3" title="测试会话" />);

    act(() => {
      window.dispatchEvent(new Event('online'));
    });

    expect(regenerate).not.toHaveBeenCalled();
  });

  it('网络级失败自动重试一次，且只重试一次', () => {
    jest.useFakeTimers();
    try {
      render(<AgentChatPanel sessionId="s4" title="测试会话" />);

      act(() => {
        jest.advanceTimersByTime(900);
      });
      expect(regenerate).toHaveBeenCalledTimes(1);

      act(() => {
        jest.advanceTimersByTime(5000);
      });
      expect(regenerate).toHaveBeenCalledTimes(1);
    } finally {
      jest.useRealTimers();
    }
  });

  it('非网络错误不自动重试', () => {
    useChatMock.mockReturnValue({
      messages: [USER_MESSAGE],
      sendMessage: jest.fn(),
      status: 'error',
      error: new Error('模型未配置'),
      stop: jest.fn(),
      regenerate,
    });

    jest.useFakeTimers();
    try {
      render(<AgentChatPanel sessionId="s5" title="测试会话" />);

      act(() => {
        jest.advanceTimersByTime(900);
      });
      expect(regenerate).not.toHaveBeenCalled();
    } finally {
      jest.useRealTimers();
    }
  });
});
