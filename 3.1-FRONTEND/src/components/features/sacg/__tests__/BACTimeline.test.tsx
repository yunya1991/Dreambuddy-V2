/**
 * BACTimeline 生命周期回归测试
 *
 * 场景：数据请求未返回就卸载组件，返回后不得再写入状态（cancelled 守卫）。
 */

import { render, act } from '@testing-library/react';

jest.mock('@/lib/api-client', () => ({
  __esModule: true,
  default: { get: jest.fn() },
}));

import api from '@/lib/api-client';
import { BACTimeline } from '../BACTimeline';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe('BACTimeline 卸载守卫', () => {
  it('卸载后返回的数据不触发状态写入', async () => {
    const slow = deferred<unknown>();
    (api.get as jest.Mock).mockReturnValue(slow.promise);
    const errorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});

    const { unmount } = render(<BACTimeline />);
    unmount();

    await act(async () => {
      slow.resolve({ stats: {}, sessions: [] });
    });

    expect(errorSpy).not.toHaveBeenCalled();
    errorSpy.mockRestore();
  });

  it('卸载时 abort 请求 signal（真正中断在途请求）', () => {
    (api.get as jest.Mock).mockReturnValue(new Promise(() => {}));

    const { unmount } = render(<BACTimeline />);
    // 取最后一次调用：StrictMode 双挂载时首次 effect 的 controller 已被清理
    const calls = (api.get as jest.Mock).mock.calls;
    const options = calls[calls.length - 1][2] as { signal: AbortSignal };
    expect(options.signal.aborted).toBe(false);

    unmount();
    expect(options.signal.aborted).toBe(true);
  });
});
