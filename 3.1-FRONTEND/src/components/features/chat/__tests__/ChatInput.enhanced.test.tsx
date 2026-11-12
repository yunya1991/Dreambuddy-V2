import React, { useState } from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { ChatInput } from '../ChatInput';

function Harness(props: Partial<React.ComponentProps<typeof ChatInput>>) {
  const [value, setValue] = useState(props.value ?? '');
  return (
    <ChatInput
      {...props}
      value={value}
      onChange={(next) => {
        setValue(next);
        props.onChange?.(next);
      }}
      onSend={props.onSend ?? (() => {})}
    />
  );
}

describe('ChatInput T-B9 增强', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it('基线行为不变：Enter 触发发送、Shift+Enter 不发送', () => {
    const onSend = jest.fn();
    render(<Harness value="你好" onSend={onSend} />);
    const textarea = screen.getByPlaceholderText('输入你的问题...');
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.keyDown(textarea, { key: 'Enter' });
    expect(onSend).toHaveBeenCalledTimes(1);
  });

  it('草稿自动保存并在重新挂载后恢复', () => {
    const { unmount } = render(<Harness draftKey="d1" />);
    const textarea = screen.getByPlaceholderText('输入你的问题...');
    fireEvent.change(textarea, { target: { value: '未发送的草稿' } });
    expect(window.sessionStorage.getItem('dreambuddy.chat.draft:d1')).toBe('未发送的草稿');
    unmount();

    render(<Harness draftKey="d1" />);
    expect((screen.getByPlaceholderText('输入你的问题...') as HTMLTextAreaElement).value).toBe('未发送的草稿');
  });

  it('输入历史上/下键回填（最多保留 50 条）', () => {
    window.sessionStorage.setItem(
      'dreambuddy.chat.history:h1',
      JSON.stringify(['第一条', '第二条']),
    );
    render(<Harness historyKey="h1" />);
    const textarea = screen.getByPlaceholderText('输入你的问题...') as HTMLTextAreaElement;

    fireEvent.keyDown(textarea, { key: 'ArrowUp' });
    expect(textarea.value).toBe('第二条');
    fireEvent.keyDown(textarea, { key: 'ArrowUp' });
    expect(textarea.value).toBe('第一条');
    fireEvent.keyDown(textarea, { key: 'ArrowDown' });
    expect(textarea.value).toBe('第二条');
  });

  it('发送后写入输入历史', () => {
    const onSend = jest.fn();
    render(<Harness value="记录我" historyKey="h2" onSend={onSend} />);
    fireEvent.keyDown(screen.getByPlaceholderText('输入你的问题...'), { key: 'Enter' });
    expect(onSend).toHaveBeenCalled();
    const saved = JSON.parse(window.sessionStorage.getItem('dreambuddy.chat.history:h2') || '[]');
    expect(saved).toContain('记录我');
  });

  it('@ 触发候选并用 Enter 插入', () => {
    render(
      <Harness
        value="@"
        suggestions={[
          { label: '行情分析', value: '@行情分析' },
          { label: '风控检查', value: '@风控检查' },
        ]}
      />,
    );
    expect(screen.getByTestId('chat-input-suggestions')).toBeInTheDocument();
    const textarea = screen.getByPlaceholderText('输入你的问题...') as HTMLTextAreaElement;
    fireEvent.keyDown(textarea, { key: 'ArrowDown' });
    fireEvent.keyDown(textarea, { key: 'Enter' });
    expect(textarea.value).toBe('@风控检查 ');
  });

  it('loading 时显示停止入口并回调 onStop', () => {
    const onStop = jest.fn();
    render(<Harness value="" loading onStop={onStop} />);
    fireEvent.click(screen.getByTestId('chat-input-stop'));
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it('附件只展示文件名，发送时回传文件名列表', () => {
    const onSend = jest.fn();
    const onAttachFiles = jest.fn();
    render(<Harness value="看附件" onSend={onSend} onAttachFiles={onAttachFiles} />);

    const input = screen.getByTestId('chat-input-file') as HTMLInputElement;
    const file = new File(['hello'], 'note.txt', { type: 'text/plain' });
    act(() => {
      fireEvent.change(input, { target: { files: [file] } });
    });

    expect(screen.getByTestId('chat-input-attachments')).toHaveTextContent('note.txt');
    expect(onAttachFiles).toHaveBeenCalledWith(['note.txt']);

    fireEvent.keyDown(screen.getByPlaceholderText('输入你的问题...'), { key: 'Enter' });
    expect(onSend).toHaveBeenCalledWith(['note.txt']);
  });
});
