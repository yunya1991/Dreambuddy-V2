const mockExecFile = jest.fn();

jest.mock('child_process', () => ({
  execFile: (...args: unknown[]) => mockExecFile(...args),
}));

jest.mock('util', () => ({
  promisify: (fn: unknown) => fn,
}));

jest.mock('next/server', () => ({
  NextResponse: {
    json: (body: unknown, init?: { status?: number }) => ({
      body,
      status: init?.status ?? 200,
    }),
  },
}));

const ENV_KEYS = ['COGNITIVE_PYTHON', 'PYTHON'] as const;
const originalEnv = Object.fromEntries(ENV_KEYS.map(key => [key, process.env[key]]));

async function runOverview(env: Partial<Record<(typeof ENV_KEYS)[number], string>>) {
  for (const key of ENV_KEYS) delete process.env[key];
  Object.assign(process.env, env);
  jest.resetModules();
  mockExecFile.mockReset();
  mockExecFile.mockResolvedValue({ stdout: '{"ok":true,"visuals":[],"recommended":[]}' });

  const { GET } = require('./route') as typeof import('./route');
  const request = { nextUrl: { searchParams: { get: () => null } } };
  await GET(request as any);
  return mockExecFile.mock.calls[0][0];
}

afterAll(() => {
  for (const key of ENV_KEYS) {
    const value = originalEnv[key];
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
});

describe('GET /api/visual/overview Python 解释器', () => {
  it('优先使用 COGNITIVE_PYTHON', async () => {
    await expect(
      runOverview({ COGNITIVE_PYTHON: '/venv/bin/python', PYTHON: '/other/bin/python' }),
    ).resolves.toBe('/venv/bin/python');
  });

  it('COGNITIVE_PYTHON 缺失时使用 PYTHON', async () => {
    await expect(runOverview({ PYTHON: '/other/bin/python' })).resolves.toBe('/other/bin/python');
  });

  it('环境变量均缺失时回退 python3', async () => {
    await expect(runOverview({})).resolves.toBe('python3');
  });
});
