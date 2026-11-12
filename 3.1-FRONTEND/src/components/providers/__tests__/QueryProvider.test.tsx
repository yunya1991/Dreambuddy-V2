import React from 'react';
import { render, waitFor, cleanup } from '@testing-library/react';
import { useQuery } from '@tanstack/react-query';
import { createQueryClient, QueryProvider, QUERY_CLIENT_DEFAULTS } from '../QueryProvider';
import { queryKey } from '@/lib/query-keys';

function Probe() {
  useQuery({ queryKey: queryKey('reports', 'list'), queryFn: () => Promise.resolve({ items: [] }) });
  return <span>probe</span>;
}

describe('QueryProvider (T-C4)', () => {
  afterEach(cleanup);

  it('默认 staleTime 30s / retry 1 / 关闭窗口聚焦刷新', () => {
    const client = createQueryClient();
    const defaults = client.getDefaultOptions().queries;
    expect(defaults?.staleTime).toBe(QUERY_CLIENT_DEFAULTS.staleTime);
    expect(defaults?.retry).toBe(1);
    expect(defaults?.refetchOnWindowFocus).toBe(false);
  });

  it('同一请求在 staleTime 内重复挂载只发 1 次', async () => {
    const client = createQueryClient();
    const spy = jest.spyOn(client, 'fetchQuery').mockImplementation(() => Promise.resolve({ items: [] }));
    const queryFn = jest.fn().mockResolvedValue({ items: [] });

    function ProbeWithFn() {
      useQuery({ queryKey: queryKey('reports', 'list'), queryFn });
      return <span>probe</span>;
    }

    const first = render(
      <QueryProvider client={client}>
        <ProbeWithFn />
      </QueryProvider>,
    );
    await waitFor(() => expect(queryFn).toHaveBeenCalledTimes(1));
    first.unmount();

    render(
      <QueryProvider client={client}>
        <ProbeWithFn />
      </QueryProvider>,
    );
    await waitFor(() => expect(client.getQueryData(queryKey('reports', 'list'))).toBeTruthy());
    expect(queryFn).toHaveBeenCalledTimes(1);
    spy.mockRestore();
  });

  it('Provider 渲染子树', () => {
    const { getByText } = render(
      <QueryProvider>
        <Probe />
      </QueryProvider>,
    );
    expect(getByText('probe')).toBeInTheDocument();
  });
});
