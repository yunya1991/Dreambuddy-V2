
import React, { useEffect, useMemo, useState } from 'react';
import { MetricsCard } from './components/MetricsCard';
import { ConfigCard } from './components/ConfigCard';
import { OrdersTable } from './components/OrdersTable';
import { SignalsTable } from './components/SignalsTable';
import { LayoutDashboard, LineChart, Trophy, Layers, LogOut, List, ChevronDown, ChevronRight, Target } from 'lucide-react';
import { BrowserRouter as Router, Routes, Route, Link, Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Button } from './components/ui/button';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { authLogin, authLogout, authMe, fetchAutomationStrategiesState, fetchConfig, fetchHealth, fetchMacroBtcEthOverview, fetchMacroBtcRegimeBacktest, fetchMacroViz, fetchMetrics, fetchSignalRejectStats, fetchTrackerStats, fetchUniverseStatus, getConfigToken, getExecuteToken, getMaintenanceToken, getUiEnv, setConfigToken, setExecuteToken, setMaintenanceToken, subscribeConfigToken, subscribeExecuteToken, subscribeMaintenanceToken } from './lib/api';
import { Badge } from './components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from './components/ui/card';
import { Input } from './components/ui/input';

import { ModelEvaluationPage } from './components/ModelEvaluationPage';
import { ArenaPage } from './components/ArenaPage';
import { UniversePage } from './components/UniversePage';
import { StrategyPage } from './components/StrategyPage';
import { ActiveStrategyPage } from './components/ActiveStrategyPage';
import { ExitSystemPage } from './components/ExitSystemPage';
import { MacroPage } from './components/MacroPage';
import { RegimeEvolutionPage } from './components/RegimeEvolutionPage';
import { EngineeringIndexPage } from './components/EngineeringIndexPage';
import { DocsPage } from './components/DocsPage';
import { AgentConsolePage } from './components/AgentConsolePage';
import { Activity } from 'lucide-react';
import { AgentObservabilityPage } from './components/AgentObservabilityPage';
import { ApprovalReviewPage } from './components/ApprovalReviewPage';

const UI_SESSION_STORAGE_KEY = 'ui_session_ok';

const _getSessionOk = (): boolean => {
  try {
    if (typeof window === 'undefined') return false;
    const v = window.sessionStorage.getItem(UI_SESSION_STORAGE_KEY);
    return v === '1' || v === 'true';
  } catch {
    return false;
  }
};

const _setSessionOk = (ok: boolean): void => {
  try {
    if (typeof window === 'undefined') return;
    if (ok) window.sessionStorage.setItem(UI_SESSION_STORAGE_KEY, '1');
    else window.sessionStorage.removeItem(UI_SESSION_STORAGE_KEY);
  } catch {
    void 0;
  }
};

const NavLink: React.FC<{ to: string; icon: React.ReactNode; label: string }> = ({ to, icon, label }) => {
  const location = useLocation();
  const isActive = location.pathname === to;
  return (
    <Link to={to}>
      <Button variant={isActive ? "secondary" : "ghost"} className="gap-2 justify-start w-full md:w-auto">
        {icon}
        {label}
      </Button>
    </Link>
  );
};

const ExecuteTokenPanel: React.FC = () => {
  const [token, setToken] = useState<string>(() => getExecuteToken());
  const [configToken, setConfigTokenLocal] = useState<string>(() => getConfigToken());
  const [maintenanceToken, setMaintenanceTokenLocal] = useState<string>(() => getMaintenanceToken());
  const nav = useNavigate();
  const queryClient = useQueryClient();

  const { data: authMeData } = useQuery({
    queryKey: ['authMe'],
    queryFn: authMe,
    refetchInterval: 30000,
    refetchOnWindowFocus: true,
    retry: false,
  });

  const isAuthed = Boolean(authMeData?.ok);
  const authActor = isAuthed ? String(authMeData?.actor ?? '') : '';
  const authRole = isAuthed ? String(authMeData?.role ?? '') : '';

  const logoutMutation = useMutation({
    mutationFn: authLogout,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['authMe'] });
    },
  });

  useEffect(() => {
    const unsub = subscribeExecuteToken((t) => setToken(String(t || '')));
    const unsubConfig = subscribeConfigToken((t) => setConfigTokenLocal(String(t || '')));
    const unsubMaintenance = subscribeMaintenanceToken((t) => setMaintenanceTokenLocal(String(t || '')));
    const onStorage = (e: StorageEvent) => {
      if (e.key === 'execute_token') setToken(getExecuteToken());
      if (e.key === 'config_token') setConfigTokenLocal(getConfigToken());
      if (e.key === 'maintenance_token') setMaintenanceTokenLocal(getMaintenanceToken());
    };
    window.addEventListener('storage', onStorage);
    return () => {
      unsub();
      unsubConfig();
      unsubMaintenance();
      window.removeEventListener('storage', onStorage);
    };
  }, []);

  const hasExecuteToken = Boolean(token.trim());
  const hasConfigToken = Boolean(configToken.trim());
  const hasMaintenanceToken = Boolean(maintenanceToken.trim());
  const hasOperatorToken = hasExecuteToken || hasConfigToken || hasMaintenanceToken;

  return (
    <div className="rounded border bg-white p-3">
      <div className="text-xs text-slate-500">Access</div>
      <div className={hasOperatorToken ? 'text-sm font-semibold text-emerald-700' : 'text-sm font-semibold text-slate-700'}>
        {hasOperatorToken ? 'Operator' : 'Read-only'}
      </div>
      <div className="mt-2">
        <div className="text-xs text-slate-500">Admin</div>
        <div className={isAuthed ? 'text-sm font-semibold text-blue-700' : 'text-sm font-semibold text-slate-700'}>
          {isAuthed ? (authActor ? `${authActor} (${authRole || 'admin'})` : 'Authenticated') : 'Not logged in'}
        </div>
        <div className="mt-2 flex gap-2">
          {!isAuthed ? (
            <Button type="button" variant="outline" className="w-full" onClick={() => nav('/login')}>
              Admin Login
            </Button>
          ) : (
            <Button type="button" variant="outline" className="w-full" onClick={() => logoutMutation.mutate()} disabled={logoutMutation.isPending}>
              Admin Logout
            </Button>
          )}
        </div>
      </div>
      <div className="mt-2">
        <div className="text-xs text-slate-500 mb-1">execute_token</div>
        <Input
          type="password"
          value={token}
          onChange={(e) => setExecuteToken(String(e.target.value ?? ''))}
          placeholder="WEBHOOK_EXECUTE_TOKEN"
          autoComplete="off"
        />
        <div className="mt-2 flex gap-2">
          <Button type="button" variant="outline" className="w-full" onClick={() => setExecuteToken('')} disabled={!hasExecuteToken}>
            Clear
          </Button>
          <Button
            type="button"
            variant="outline"
            className="w-full"
            onClick={() => {
              setExecuteToken('');
              _setSessionOk(false);
              nav('/login');
            }}
          >
            Lock
          </Button>
        </div>
      </div>
      <div className="mt-3">
        <div className="text-xs text-slate-500 mb-1">config_token</div>
        <Input
          type="password"
          value={configToken}
          onChange={(e) => setConfigToken(String(e.target.value ?? ''))}
          placeholder="CONFIG_TOKEN（不填则默认用 execute_token）"
          autoComplete="off"
        />
        <div className="mt-2 flex gap-2">
          <Button type="button" variant="outline" className="w-full" onClick={() => setConfigToken('')} disabled={!hasConfigToken}>
            Clear
          </Button>
        </div>
      </div>
      <div className="mt-3">
        <div className="text-xs text-slate-500 mb-1">maintenance_token</div>
        <Input
          type="password"
          value={maintenanceToken}
          onChange={(e) => setMaintenanceToken(String(e.target.value ?? ''))}
          placeholder="MAINTENANCE_TOKEN（不填则默认用 execute_token）"
          autoComplete="off"
        />
        <div className="mt-2 flex gap-2">
          <Button type="button" variant="outline" className="w-full" onClick={() => setMaintenanceToken('')} disabled={!hasMaintenanceToken}>
            Clear
          </Button>
        </div>
      </div>
    </div>
  );
};

const RequireSession: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const loc = useLocation();
  const ok = import.meta.env.DEV ? true : _getSessionOk();
  if (!ok) {
    const next = `${loc.pathname || '/'}${loc.search || ''}${loc.hash || ''}`;
    return <Navigate to="/login" replace state={{ from: next }} />;
  }
  return children;
};

const RequireProdUi: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const env = useMemo(() => getUiEnv(), []);
  if (env !== 'prod' && env !== 'explore' && env !== 'pilot') return <Navigate to="/ml" replace />;
  return children;
};

const LoginPage: React.FC = () => {
  const nav = useNavigate();
  const loc = useLocation();
  const from = String(((loc.state as { from?: unknown } | null | undefined)?.from ?? '/ml'));
  const queryClient = useQueryClient();

  const [token, setToken] = useState<string>(() => getExecuteToken());
  const [configToken, setConfigTokenLocal] = useState<string>(() => getConfigToken());
  const [maintenanceToken, setMaintenanceTokenLocal] = useState<string>(() => getMaintenanceToken());

  useEffect(() => {
    const unsub = subscribeExecuteToken((t) => setToken(String(t || '')));
    const unsubConfig = subscribeConfigToken((t) => setConfigTokenLocal(String(t || '')));
    const unsubMaintenance = subscribeMaintenanceToken((t) => setMaintenanceTokenLocal(String(t || '')));
    return () => {
      unsub();
      unsubConfig();
      unsubMaintenance();
    };
  }, []);

  const hasExecuteToken = Boolean(token.trim());
  const hasConfigToken = Boolean(configToken.trim());
  const hasMaintenanceToken = Boolean(maintenanceToken.trim());
  const hasOperatorToken = hasExecuteToken || hasConfigToken || hasMaintenanceToken;
  const { data: authMeData } = useQuery({
    queryKey: ['authMe'],
    queryFn: authMe,
    refetchInterval: 15000,
    refetchOnWindowFocus: true,
    retry: false,
  });
  const isAuthed = Boolean(authMeData?.ok);

  const [authUserInput, setAuthUserInput] = useState<string>('admin');
  const [authPwdInput, setAuthPwdInput] = useState<string>('');

  const loginMutation = useMutation({
    mutationFn: () => authLogin({ username: authUserInput, password: authPwdInput }),
    onSuccess: () => {
      setAuthPwdInput('');
      queryClient.invalidateQueries({ queryKey: ['authMe'] });
    },
  });

  const logoutMutation = useMutation({
    mutationFn: authLogout,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['authMe'] });
    },
  });

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 via-slate-50 to-slate-100">
      <div className="mx-auto flex min-h-screen max-w-6xl items-center px-4 py-10">
        <div className="w-full grid grid-cols-1 md:grid-cols-2 gap-6 items-stretch">
          <Card className="hidden md:block">
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Activity className="h-5 w-5 text-blue-600" />
                  <span>交易系统面板</span>
                </div>
                <Badge variant="outline">Zero Trust</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-sm text-slate-700 leading-relaxed">
                邮箱认证由 Cloudflare Access 在网关层完成；此页面仅负责进入系统会话，并可选设置执行令牌，用于解锁写配置/执行类操作。
              </div>

              <div className="mt-4 grid grid-cols-2 gap-2">
                <div className="rounded border bg-white p-3">
                  <div className="text-xs text-slate-500">默认权限</div>
                  <div className="mt-1 font-semibold text-slate-800">Read-only</div>
                  <div className="mt-1 text-xs text-slate-500">浏览、监控、查看指标</div>
                </div>
                <div className="rounded border bg-white p-3">
                  <div className="text-xs text-slate-500">提升权限</div>
                  <div className="mt-1 font-semibold text-slate-800">Operator</div>
                  <div className="mt-1 text-xs text-slate-500">需要 execute_token</div>
                </div>
              </div>

              <div className="mt-4 rounded border bg-white p-3">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-semibold text-slate-800">模块入口</div>
                    <Badge variant={hasOperatorToken ? 'secondary' : 'outline'}>{hasOperatorToken ? 'token detected' : 'no token'}</Badge>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2 text-sm text-slate-700">
                  <div className="flex items-center gap-2"><LayoutDashboard className="h-4 w-4" />ML trade</div>
                  <div className="flex items-center gap-2"><Activity className="h-4 w-4" />AI Agent</div>
                  <div className="flex items-center gap-2"><Trophy className="h-4 w-4" />Arena</div>
                  <div className="flex items-center gap-2"><Target className="h-4 w-4" />Universe</div>
                </div>
              </div>

              <div className="mt-4 text-xs text-slate-500 leading-relaxed">
                提示：进入系统会话保存在 sessionStorage（关闭标签页即失效）；execute_token 保存在 localStorage（仅本机浏览器）。
              </div>
            </CardContent>
          </Card>

          <div className="flex items-center justify-center">
            <Card className="w-full max-w-md shadow-sm">
              <CardHeader>
                <CardTitle className="flex items-center justify-between">
                  <span>登录</span>
                  <Badge variant={hasOperatorToken ? 'secondary' : 'outline'}>{hasOperatorToken ? 'Operator Ready' : 'Read-only'}</Badge>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-sm text-slate-700">
                  已通过邮箱门禁后，在此选择进入模式；如需修改参数/执行操作，请填写执行令牌。
                </div>

                <div className="mt-4 rounded border bg-white p-3">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-semibold text-slate-800">execute_token</div>
                    <Badge variant="outline">可选</Badge>
                  </div>
                  <div className="mt-2">
                    <Input
                      type="password"
                      value={token}
                      onChange={(e) => setExecuteToken(String(e.target.value ?? ''))}
                      placeholder="CONFIG_TOKEN / WEBHOOK_EXECUTE_TOKEN"
                      autoComplete="off"
                    />
                    <div className="mt-2 text-xs text-slate-500">
                      仅用于解锁写接口；不建议使用可猜测的短密码。
                    </div>
                  </div>
                </div>
                <div className="mt-3 rounded border bg-white p-3">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-semibold text-slate-800">config_token</div>
                    <Badge variant="outline">可选</Badge>
                  </div>
                  <div className="mt-2">
                    <Input
                      type="password"
                      value={configToken}
                      onChange={(e) => setConfigToken(String(e.target.value ?? ''))}
                      placeholder="CONFIG_TOKEN（不填则默认用 execute_token）"
                      autoComplete="off"
                    />
                  </div>
                </div>
                <div className="mt-3 rounded border bg-white p-3">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-semibold text-slate-800">maintenance_token</div>
                    <Badge variant="outline">可选</Badge>
                  </div>
                  <div className="mt-2">
                    <Input
                      type="password"
                      value={maintenanceToken}
                      onChange={(e) => setMaintenanceToken(String(e.target.value ?? ''))}
                      placeholder="MAINTENANCE_TOKEN（不填则默认用 execute_token）"
                      autoComplete="off"
                    />
                  </div>
                </div>

                <div className="mt-4 grid grid-cols-1 gap-2">
                  <Button
                    type="button"
                    onClick={() => {
                      _setSessionOk(true);
                      nav(from);
                    }}
                  >
                    进入只读
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={!hasOperatorToken}
                    onClick={() => {
                      _setSessionOk(true);
                      nav(from);
                    }}
                  >
                    作为 Operator 进入
                  </Button>
                  <div className="grid grid-cols-2 gap-2">
                    <Button type="button" variant="outline" onClick={() => setExecuteToken('')} disabled={!hasExecuteToken}>
                      清空令牌
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => {
                        setConfigToken('');
                        setMaintenanceToken('');
                      }}
                      disabled={!hasConfigToken && !hasMaintenanceToken}
                    >
                      清空专用令牌
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => {
                        setExecuteToken('');
                        _setSessionOk(false);
                      }}
                    >
                      清空会话
                    </Button>
                  </div>

                  <div className="mt-2 rounded border bg-white p-3">
                    <div className="flex items-center justify-between">
                      <div className="text-sm font-semibold text-slate-800">Admin 登录</div>
                      <Badge variant={isAuthed ? 'secondary' : 'outline'}>{isAuthed ? 'authenticated' : 'not logged in'}</Badge>
                    </div>
                    <div className="mt-2 grid grid-cols-1 gap-2">
                      <Input
                        value={authUserInput}
                        onChange={(e) => setAuthUserInput(String(e.target.value || ''))}
                        placeholder="username"
                        disabled={isAuthed}
                      />
                      <Input
                        value={authPwdInput}
                        onChange={(e) => setAuthPwdInput(String(e.target.value || ''))}
                        placeholder="password"
                        type="password"
                        disabled={isAuthed}
                      />
                      <div className="flex gap-2">
                        {!isAuthed ? (
                          <Button
                            type="button"
                            variant="outline"
                            onClick={() => loginMutation.mutate()}
                            disabled={loginMutation.isPending || !authUserInput.trim() || !authPwdInput.trim()}
                            className="w-full"
                          >
                            登录
                          </Button>
                        ) : (
                          <Button type="button" variant="outline" onClick={() => logoutMutation.mutate()} disabled={logoutMutation.isPending} className="w-full">
                            退出登录
                          </Button>
                        )}
                      </div>
                      <div className="text-xs text-slate-500">
                        {!isAuthed ? (loginMutation.error ? `登录失败：${String((loginMutation.error as { message?: unknown } | null | undefined)?.message ?? loginMutation.error)}` : '登录成功后，写配置将使用 Cookie + CSRF 保护') : '已登录，可直接保存配置（无需 token）'}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="mt-4 text-xs text-slate-500">
                  目标页：{from}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
};

class AppErrorBoundary extends React.Component<{ children: React.ReactNode }, { error: Error | null }> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  override render() {
    if (this.state.error) {
      return (
        <div className="p-6">
          <Card>
            <CardHeader>
              <CardTitle>Dashboard Runtime Error</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-sm text-slate-700">{String(this.state.error.message ?? this.state.error)}</div>
              <div className="mt-4 flex gap-2">
                <Button variant="outline" onClick={() => window.location.reload()}>Reload</Button>
                <Button variant="ghost" onClick={() => this.setState({ error: null })}>Dismiss</Button>
              </div>
            </CardContent>
          </Card>
        </div>
      );
    }
    return this.props.children;
  }
}

const ShellLayout: React.FC = () => {
  const env = useMemo(() => getUiEnv(), []);
  const showTradingModules = env === 'prod' || env === 'explore' || env === 'pilot';
  return (
    <div className="min-h-screen bg-slate-50/50">
      <div className="grid grid-cols-12">
        <aside className="col-span-12 md:col-span-2 bg-white border-r min-h-screen p-4 space-y-3">
          <div className="font-bold text-lg mb-2 flex items-center gap-2">
            <Activity className="h-5 w-5 text-blue-600" />
            <span>核心模块</span>
          </div>
          <ExecuteTokenPanel />
          <NavLink to="/agent" icon={<Activity className="h-4 w-4" />} label="系统观测" />
          <NavLink to="/ml" icon={<LayoutDashboard className="h-4 w-4" />} label="ML trade" />
          <div className="mt-6 font-semibold text-xs text-slate-500">策略管理</div>
          <NavLink to="/strategy" icon={<Layers className="h-4 w-4" />} label="在用策略" />
          <NavLink to="/library" icon={<Layers className="h-4 w-4" />} label="策略资产库" />
          {showTradingModules ? <NavLink to="/exit" icon={<LogOut className="h-4 w-4" />} label="离场(Exit)" /> : null}
          <div className="mt-6 font-semibold text-xs text-slate-500">其他</div>
          <NavLink to="/arena" icon={<Trophy className="h-4 w-4" />} label="Arena" />
          <NavLink to="/universe" icon={<Layers className="h-4 w-4" />} label="Universe" />
          <NavLink to="/macro" icon={<LineChart className="h-4 w-4" />} label="Macro" />
          <NavLink to="/evolution" icon={<LineChart className="h-4 w-4" />} label="形态演化" />
          <NavLink to="/evaluation" icon={<LineChart className="h-4 w-4" />} label="Evaluation" />
          <NavLink to="/index" icon={<List className="h-4 w-4" />} label="Index" />
        </aside>
        <main className="col-span-12 md:col-span-10">
          <div className="container mx-auto py-8 px-4">
            <AppErrorBoundary>
              <Outlet />
            </AppErrorBoundary>
          </div>
        </main>
      </div>
    </div>
  );
};

const AgentHomePage: React.FC = () => {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-2xl font-bold">系统观测 & 治理</div>
          <div className="text-sm text-slate-600">量化金融核心管理与运行态概览</div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline">/agent</Badge>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>运行态观测</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="text-sm text-slate-600">自动化 KPI、ParamOpt 统计与 Explore 收益对比</div>
            <Link to="/agent/observability"><Button variant="outline" className="w-full">进入</Button></Link>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>概览</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="text-sm text-slate-600">Feeder / Scheduler / Gate 监控哨兵与信号链路健康</div>
            <Link to="/agent/overview"><Button variant="outline" className="w-full">进入</Button></Link>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>草案审批</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="text-sm text-slate-600">ParamOpt / 变更包的人工审批简报与一键同意 / 拒绝</div>
            <Link to="/agent/approvals"><Button variant="outline" className="w-full">进入</Button></Link>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>沙箱</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="text-sm text-slate-600">回测 / 训练 / 稳健性 / 评估的隔离执行环境</div>
            <Link to="/agent/sandbox"><Button variant="outline" className="w-full">进入</Button></Link>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>安全测试</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="text-sm text-slate-600">Red Team 渗透测试 / 压力测试 / Prompt 注入检测</div>
            <Link to="/agent/redteam"><Button variant="outline" className="w-full">进入</Button></Link>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>审计</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="text-sm text-slate-600">告警 / 数据质量 / 执行质量与门禁基线对比</div>
            <Link to="/agent/audit"><Button variant="outline" className="w-full">进入</Button></Link>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

function _msToCompact(ms: number): string {
  const x = Math.max(0, Math.floor(ms));
  const sec = Math.floor(x / 1000);
  const m = Math.floor(sec / 60);
  const h = Math.floor(m / 60);
  const d = Math.floor(h / 24);
  if (d > 0) return `${d}d${h % 24}h`;
  if (h > 0) return `${h}h${m % 60}m`;
  if (m > 0) return `${m}m`;
  return `${sec}s`;
}

const DashboardHealthCard: React.FC = () => {
  const [collapsed, setCollapsed] = useState<boolean>(false);
  const [routeMarks, setRouteMarks] = useState<Record<'overview' | 'viz' | 'tracker', { lastSuccessMs: number; lastErrorMs: number }>>({
    overview: { lastSuccessMs: 0, lastErrorMs: 0 },
    viz: { lastSuccessMs: 0, lastErrorMs: 0 },
    tracker: { lastSuccessMs: 0, lastErrorMs: 0 },
  });
  const _markSuccessAt = (key: 'overview' | 'viz' | 'tracker', atMs: number) => {
    setRouteMarks((prev) => ({ ...prev, [key]: { ...prev[key], lastSuccessMs: atMs } }));
  };
  const _markErrorAt = (key: 'overview' | 'viz' | 'tracker', atMs: number) => {
    setRouteMarks((prev) => ({ ...prev, [key]: { ...prev[key], lastErrorMs: atMs } }));
  };

  const { data: health, isLoading: healthLoading, error: healthError } = useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    refetchInterval: 5000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const backendUp = Boolean((health as { ok?: unknown } | undefined)?.ok);

  const { data: metrics } = useQuery({
    queryKey: ['metrics'],
    queryFn: fetchMetrics,
    refetchInterval: 3000,
    refetchOnWindowFocus: false,
    enabled: backendUp,
    retry: false,
  });

  const nowMs = Number((metrics as { ts?: number } | undefined)?.ts ?? 0);

  const { data: universe } = useQuery({
    queryKey: ['universe', 'status'],
    queryFn: fetchUniverseStatus,
    refetchInterval: 10000,
    refetchOnWindowFocus: false,
    enabled: backendUp,
    retry: false,
  });

  const { data: automation } = useQuery({
    queryKey: ['automation', 'state'],
    queryFn: fetchAutomationStrategiesState,
    refetchInterval: 5000,
    refetchOnWindowFocus: false,
    enabled: backendUp,
    retry: false,
  });

  const { data: tracker, isError: trackerError, isFetching: trackerFetching } = useQuery({
    queryKey: ['tracker', 'sync', false, 'ui'],
    queryFn: async () => {
      try {
        const d = await fetchTrackerStats({ sync: false, view: 'ui' });
        _markSuccessAt('tracker', Date.now());
        return d;
      } catch (e) {
        _markErrorAt('tracker', Date.now());
        throw e;
      }
    },
    refetchInterval: 5000,
    refetchOnWindowFocus: false,
    enabled: backendUp,
    retry: false,
  });

  const { data: rejectStats } = useQuery({
    queryKey: ['signals', 'reject_stats', 2000],
    queryFn: () => fetchSignalRejectStats(2000),
    refetchInterval: 10000,
    refetchOnWindowFocus: false,
    enabled: backendUp,
    retry: false,
  });

  const { data: macroOverview, isError: overviewError, isFetching: overviewFetching } = useQuery({
    queryKey: ['macro', 'btceth', 'overview', 'ml'],
    queryFn: async () => {
      try {
        const d = await fetchMacroBtcEthOverview({ lookback_days: 120, flow_lookback_days: 120 });
        if ((d as { ok?: unknown } | undefined)?.ok === true) _markSuccessAt('overview', Date.now());
        else _markErrorAt('overview', Date.now());
        return d;
      } catch (e) {
        _markErrorAt('overview', Date.now());
        throw e;
      }
    },
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
    retry: false,
    enabled: backendUp,
  });
  const { data: macroViz, isError: vizError, isFetching: vizFetching } = useQuery({
    queryKey: ['macro', 'viz', 'ml-health', 24],
    queryFn: async () => {
      try {
        const d = await fetchMacroViz({ shape_n: 20, signal_window_h: 24 });
        if ((d as { ok?: unknown } | undefined)?.ok === true) _markSuccessAt('viz', Date.now());
        else _markErrorAt('viz', Date.now());
        return d;
      } catch (e) {
        _markErrorAt('viz', Date.now());
        throw e;
      }
    },
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
    retry: false,
    enabled: backendUp,
  });

  const feeder = (tracker as { feeders?: Record<string, unknown> } | undefined)?.feeders ?? null;
  const scheduler = (tracker as { scheduler?: Record<string, unknown> } | undefined)?.scheduler ?? null;
  const openPosN = Object.keys(((tracker as { open_positions?: Record<string, unknown> } | undefined)?.open_positions ?? {})).length;
  const cooldownN = Object.keys(((tracker as { cooldowns?: Record<string, unknown> } | undefined)?.cooldowns ?? {})).length;
  const postCloseN = Object.keys(((tracker as { post_close_cooldowns?: Record<string, unknown> } | undefined)?.post_close_cooldowns ?? {})).length;
  const macroHardAuto = ((tracker as { macro_btceth_hard_gate_auto?: Record<string, unknown> } | undefined)?.macro_btceth_hard_gate_auto ?? null) as Record<string, unknown> | null;
  const gateHistory = useMemo(() => {
    return Array.isArray((tracker as { gate_history?: unknown } | undefined)?.gate_history)
      ? ((tracker as { gate_history: Record<string, unknown>[] }).gate_history)
      : [];
  }, [tracker]);

  const uniLastMs = useMemo(() => {
    const v = Number((universe as { last_update?: number } | undefined)?.last_update ?? 0);
    if (!Number.isFinite(v) || v <= 0) return 0;
    return v < 1e11 ? v * 1000 : v;
  }, [universe]);

  const uniCoreN = Array.isArray((universe as { core?: unknown } | undefined)?.core) ? ((universe as { core: unknown[] }).core.length) : 0;

  const feederTs = Number((feeder as Record<string, unknown> | null)?.ts ?? 0);
  const feederAge = feederTs > 0 && nowMs > 0 ? nowMs - feederTs : null;
  const feederErrors = Number((feeder as Record<string, unknown> | null)?.errors ?? 0);
  const feederIngested = Number((feeder as Record<string, unknown> | null)?.ingested ?? 0);
  const feederCalls = Number((feeder as Record<string, unknown> | null)?.calls ?? 0);
  const feederCoreN = Number((feeder as Record<string, unknown> | null)?.n_core ?? 0);

  const schedTs = Number((scheduler as Record<string, unknown> | null)?.ts ?? 0);
  const schedAge = schedTs > 0 && nowMs > 0 ? nowMs - schedTs : null;
  const schedTick = Number((scheduler as Record<string, unknown> | null)?.tick ?? 0);

  const decisions = (rejectStats as { by_decision?: Record<string, number> } | undefined)?.by_decision ?? {};
  const reasons = (rejectStats as { by_reason?: Record<string, number> } | undefined)?.by_reason ?? {};
  const topReasons = Object.entries(reasons)
    .sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0))
    .slice(0, 6);

  const gateTopReasons = useMemo(() => {
    const by: Record<string, number> = {};
    for (const it of gateHistory) {
      const ok = Boolean(it.ok);
      if (ok) continue;
      const r = (it.reason === null || it.reason === undefined) ? '' : String(it.reason);
      const key = r.trim() || 'none';
      by[key] = (by[key] ?? 0) + 1;
    }
    return Object.entries(by)
      .sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0))
      .slice(0, 6);
  }, [gateHistory]);

  const auto = (automation as { automation?: Record<string, unknown> } | undefined)?.automation ?? {};
  const feedersEnabled = Boolean(auto.enable_strategy_feeders);
  const feedersPeriod = Number(auto.feeders_period_seconds ?? 0);
  const useCore = Boolean(auto.use_universe_core);

  const uniBadge = uniCoreN > 0 ? 'default' : 'destructive';
  const feederBadge = feedersEnabled ? (feederErrors > 0 ? 'destructive' : 'secondary') : 'outline';
  const schedBadge = schedAge !== null && schedAge < 120000 ? 'secondary' : 'outline';

  const shape = (macroOverview as { macro_btceth_shape?: Record<string, unknown> | null } | undefined)?.macro_btceth_shape ?? null;
  const shapeTs = Number((shape as Record<string, unknown> | null)?.ts ?? 0);
  const shapeName = String((shape as Record<string, unknown> | null)?.shape ?? '-');
  const riskW = Number((shape as Record<string, unknown> | null)?.risk_w ?? Number.NaN);
  const valueW = Number((shape as Record<string, unknown> | null)?.value_w ?? Number.NaN);
  const controls = ((shape as Record<string, unknown> | null)?.controls ?? null) as Record<string, unknown> | null;
  const policy = ((shape as Record<string, unknown> | null)?.policy ?? null) as Record<string, unknown> | null;
  const sizeLong = Number((controls as Record<string, unknown> | null)?.size_mult_long ?? Number.NaN);
  const sizeShort = Number((controls as Record<string, unknown> | null)?.size_mult_short ?? Number.NaN);
  const cdLong = Number((controls as Record<string, unknown> | null)?.cooldown_mult_long ?? Number.NaN);
  const cdShort = Number((controls as Record<string, unknown> | null)?.cooldown_mult_short ?? Number.NaN);
  const counterMaxFrac = Number((policy as Record<string, unknown> | null)?.counter_max_signals_frac ?? Number.NaN);
  const dir0Block = Boolean((policy as Record<string, unknown> | null)?.dir0_block_nonhedge ?? false);
  const counterRequireHedge = Boolean((policy as Record<string, unknown> | null)?.counter_require_hedge ?? false);
  const counterBlockHighRisk = Boolean((policy as Record<string, unknown> | null)?.block_counter_when_high_risk ?? false);
  const tri = (macroOverview as { macro_tri_layer?: Record<string, unknown> | null } | undefined)?.macro_tri_layer ?? null;
  const triTs = Number((tri as Record<string, unknown> | null)?.ts ?? 0);
  const triDirW = Number((tri as Record<string, unknown> | null)?.dir_w ?? 0);
  const triDirD = Number((tri as Record<string, unknown> | null)?.dir_d ?? 0);
  const triDir1h = Number((tri as Record<string, unknown> | null)?.dir_short ?? 0);
  const triTier = String((tri as Record<string, unknown> | null)?.risk_budget_tier ?? '-');
  const triAllowOpen = Boolean((tri as Record<string, unknown> | null)?.allow_open ?? false);
  const triAllowAddon = Boolean((tri as Record<string, unknown> | null)?.allow_addon ?? false);
  const triCrash = Boolean((tri as Record<string, unknown> | null)?.crash_switch ?? false);
  const triTargetNetBias = Number((tri as Record<string, unknown> | null)?.target_net_bias ?? Number.NaN);
  const triMaxNetExposure = Number((tri as Record<string, unknown> | null)?.max_net_exposure ?? Number.NaN);
  const triChgSpeedD = Number((tri as Record<string, unknown> | null)?.chg_speed_d ?? Number.NaN);
  const triChgStrength = Number((tri as Record<string, unknown> | null)?.chg_strength ?? Number.NaN);
  const vizOk = ((macroViz as { ok?: unknown } | undefined)?.ok) === true;
  const vizTargetSource = String((((macroViz as { position_budget?: Record<string, unknown> } | undefined)?.position_budget ?? {}) as Record<string, unknown>)?.target ? ((((macroViz as { position_budget?: Record<string, unknown> } | undefined)?.position_budget ?? {}) as Record<string, unknown>).target as Record<string, unknown>).target_source ?? '' : '');
  const effectiveTargetSource = vizOk ? vizTargetSource : (triTs > 0 ? 'tri_layer' : 'shape12h_baseline');
  const triTrace = (((macroViz as { tri_layer?: Record<string, unknown> } | undefined)?.tri_layer ?? {}) as Record<string, unknown>)?.trace as Record<string, unknown> | undefined;
  const triReasonMatch = triTrace?.reason_match === true;
  const triObservedBlocks = Number(triTrace?.observed_macro_blocks ?? Number.NaN);
  const triWarning = String(triTrace?.warning ?? '');
  const fallbackActive = (effectiveTargetSource === 'shape12h_baseline') || !vizOk;
  const normalDisabled = fallbackActive || !triAllowOpen;

  const mhMode = String((macroHardAuto as Record<string, unknown> | null)?.mode ?? '-');
  const mhEnabled = Boolean((macroHardAuto as Record<string, unknown> | null)?.enabled_effective ?? false);
  const mhMinRisk = Number((macroHardAuto as Record<string, unknown> | null)?.min_risk ?? Number.NaN);
  const mhThr = Number((macroHardAuto as Record<string, unknown> | null)?.risk_thr ?? Number.NaN);
  const mhDataValid = Boolean((macroHardAuto as Record<string, unknown> | null)?.data_valid ?? false);
  const mhApplied = Boolean((macroHardAuto as Record<string, unknown> | null)?.applied ?? false);

  const _fmtPct = (x: number): string => (Number.isFinite(x) ? `${(x * 100).toFixed(1)}%` : '-');
  const _fmtN = (x: number): string => (Number.isFinite(x) ? x.toFixed(2) : '-');
  const _fmtMark = (ms: number): string => {
    if (!Number.isFinite(ms) || ms <= 0) return '-';
    const t = new Date(ms).toLocaleTimeString('zh-CN', { hour12: false });
    if (!Number.isFinite(nowMs) || nowMs <= 0) return t;
    return `${t} (${_msToCompact(nowMs - ms)}前)`;
  };
  const _routeBadgeVariant = (status: 'green' | 'yellow' | 'red'): 'outline' | 'secondary' | 'destructive' => {
    if (status === 'green') return 'outline';
    if (status === 'yellow') return 'secondary';
    return 'destructive';
  };
  type RouteLightItem = { key: 'overview' | 'viz' | 'tracker'; label: string; status: 'green' | 'yellow' | 'red'; detail: string };
  const routeLights: RouteLightItem[] = [
    (() => {
      if (!backendUp) return { key: 'overview', label: 'overview', status: 'red' as const, detail: 'backend down' };
      if (overviewError) return { key: 'overview', label: 'overview', status: 'red' as const, detail: 'http 5xx / fetch error' };
      if (overviewFetching && !macroOverview) return { key: 'overview', label: 'overview', status: 'yellow' as const, detail: 'loading' };
      if ((macroOverview as { ok?: unknown } | undefined)?.ok === true) return { key: 'overview', label: 'overview', status: 'green' as const, detail: 'ok' };
      return { key: 'overview', label: 'overview', status: 'yellow' as const, detail: 'degraded' };
    })(),
    (() => {
      if (!backendUp) return { key: 'viz', label: 'viz', status: 'red' as const, detail: 'backend down' };
      if (vizError) return { key: 'viz', label: 'viz', status: 'red' as const, detail: 'http 5xx / fetch error' };
      if (vizFetching && !macroViz) return { key: 'viz', label: 'viz', status: 'yellow' as const, detail: 'loading' };
      if (vizOk) return { key: 'viz', label: 'viz', status: 'green' as const, detail: 'ok' };
      return { key: 'viz', label: 'viz', status: 'yellow' as const, detail: 'fallback only' };
    })(),
    (() => {
      if (!backendUp) return { key: 'tracker', label: 'tracker', status: 'red' as const, detail: 'backend down' };
      if (trackerError) return { key: 'tracker', label: 'tracker', status: 'red' as const, detail: 'http 5xx / fetch error' };
      if (trackerFetching && !tracker) return { key: 'tracker', label: 'tracker', status: 'yellow' as const, detail: 'loading' };
      if (tracker && typeof tracker === 'object') return { key: 'tracker', label: 'tracker', status: 'green' as const, detail: 'ok' };
      return { key: 'tracker', label: 'tracker', status: 'yellow' as const, detail: 'degraded' };
    })(),
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>Automation / Health</span>
          <div className="flex gap-2 items-center">
            <Badge variant={backendUp ? 'secondary' : 'destructive'}>
              API {backendUp ? 'OK' : (healthLoading ? '...' : 'DOWN')}
            </Badge>
            <Badge variant={uniBadge}>Universe {uniCoreN}</Badge>
            <Badge variant={feederBadge}>Feeder {feedersEnabled ? 'ON' : 'OFF'}</Badge>
            <Badge variant={schedBadge}>Scheduler {schedTick > 0 ? String(schedTick) : '-'}</Badge>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 px-2"
              onClick={() => setCollapsed(v => !v)}
            >
              {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
              <span className="ml-1 text-xs">{collapsed ? '展开' : '折叠'}</span>
            </Button>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {collapsed ? null : (
          <>
            {!backendUp && !healthLoading ? (
              <div className="mb-3 rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-900">
                后端服务不可达（默认端口 8092）。请启动 [ml_trade_service.py](file:///Users/zhangjiangtao/ft_userdata/%E7%BB%8F%E5%85%B8%E6%8C%87%E6%A0%87%E6%9C%BA%E5%99%A8%E5%AD%A6%E4%B9%A0%E7%B3%BB%E7%BB%9F/ml_trade_service.py) 后刷新页面。
                {healthError ? <div className="mt-1 text-xs text-rose-800">{String((healthError as { message?: unknown } | null | undefined)?.message ?? healthError)}</div> : null}
              </div>
            ) : null}
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 text-sm">
              <div className="border rounded p-3 bg-white">
                <div className="font-semibold mb-2">Universe</div>
                <div className="flex justify-between"><span>core</span><span>{uniCoreN}</span></div>
                <div className="flex justify-between"><span>last_update</span><span>{uniLastMs > 0 ? _msToCompact(nowMs - uniLastMs) : '-'}</span></div>
                <div className="flex justify-between"><span>use_universe_core</span><span>{useCore ? 'true' : 'false'}</span></div>
              </div>

              <div className="border rounded p-3 bg-white">
                <div className="font-semibold mb-2">Feeders</div>
                <div className="flex justify-between"><span>enabled</span><span>{feedersEnabled ? 'true' : 'false'}</span></div>
                <div className="flex justify-between"><span>period</span><span>{feedersPeriod > 0 ? `${feedersPeriod}s` : '-'}</span></div>
                <div className="flex justify-between"><span>last_tick</span><span>{feederAge !== null ? _msToCompact(feederAge) : '-'}</span></div>
                <div className="flex justify-between"><span>core_n</span><span>{feederCoreN || '-'}</span></div>
                <div className="flex justify-between"><span>calls</span><span>{feederCalls || '-'}</span></div>
                <div className="flex justify-between"><span>ingested</span><span>{feederIngested || '-'}</span></div>
                <div className="flex justify-between"><span>errors</span><span>{feederErrors || 0}</span></div>
              </div>

              <div className="border rounded p-3 bg-white">
                <div className="font-semibold mb-2">Signals</div>
                <div className="flex justify-between"><span>enter</span><span>{decisions.enter ?? 0}</span></div>
                <div className="flex justify-between"><span>observe</span><span>{decisions.observe ?? 0}</span></div>
                <div className="flex justify-between"><span>hold</span><span>{decisions.hold ?? 0}</span></div>
                <div className="mt-2 text-xs text-slate-600">Top reject reasons</div>
                <div className="mt-1 flex flex-wrap gap-2">
                  {topReasons.length ? topReasons.map(([k, v]) => (
                    <Badge key={k} variant="outline">{k}:{v}</Badge>
                  )) : <span className="text-slate-400">-</span>}
                </div>
              </div>

              <div className="border rounded p-3 bg-white">
                <div className="font-semibold mb-2">Gate</div>
                <div className="flex justify-between"><span>cooldowns</span><span>{cooldownN}</span></div>
                <div className="flex justify-between"><span>post_close</span><span>{postCloseN}</span></div>
                <div className="flex justify-between"><span>history</span><span>{gateHistory.length}</span></div>
                <div className="mt-2 text-xs text-slate-600">Macro BTC/ETH hard gate</div>
                <div className="flex justify-between"><span>auto_mode</span><span>{mhMode}</span></div>
                <div className="flex justify-between"><span>enabled</span><span>{mhEnabled ? 'ON' : 'OFF'}</span></div>
                <div className="flex justify-between"><span>min_risk / thr</span><span>{_fmtPct(mhMinRisk)} / {_fmtPct(mhThr)}</span></div>
                <div className="mt-1 flex flex-wrap gap-2">
                  <Badge variant="outline">data_valid {mhDataValid ? 'yes' : 'no'}</Badge>
                  <Badge variant="outline">applied {mhApplied ? 'yes' : 'no'}</Badge>
                </div>
                <div className="mt-2 text-xs text-slate-600">Top reject reasons</div>
                <div className="mt-1 flex flex-wrap gap-2">
                  {gateTopReasons.length ? gateTopReasons.map(([k, v]) => (
                    <Badge key={k} variant="outline">{k}:{v}</Badge>
                  )) : <span className="text-slate-400">-</span>}
                </div>
              </div>

              <div className="border rounded p-3 bg-white">
                <div className="font-semibold mb-2">链路健康灯</div>
                <div className="space-y-2">
                  {routeLights.map((x) => (
                    <div key={x.key} className="py-1 border-b last:border-b-0">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-slate-700">{x.label}</span>
                        <div className="flex items-center gap-2">
                          <Badge variant={_routeBadgeVariant(x.status)}>
                            {x.status === 'green' ? '绿' : x.status === 'yellow' ? '黄' : '红'}
                          </Badge>
                          <span className="text-xs text-slate-500">{x.detail}</span>
                        </div>
                      </div>
                      <div className="mt-1 grid grid-cols-2 gap-2 text-xs text-slate-500">
                        <span>最近成功：{_fmtMark(routeMarks[x.key].lastSuccessMs)}</span>
                        <span>最近错误：{_fmtMark(routeMarks[x.key].lastErrorMs)}</span>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="mt-2 text-xs text-slate-600">
                  放量门槛：三路均绿可放量；有黄维持灰度；任一路红保持常规禁用并排查上游。
                </div>
              </div>

              <div className="border rounded p-3 bg-white">
                <div className="font-semibold mb-2">Tri-layer（主口径）</div>
                <div className="flex justify-between"><span>target_source</span><span>{effectiveTargetSource || '-'}</span></div>
                <div className="flex justify-between"><span>ts</span><span>{triTs > 0 && nowMs > 0 ? _msToCompact(nowMs - triTs) : '-'}</span></div>
                <div className="flex justify-between"><span>DirW / DirD / Dir1h</span><span>{`${triDirW || 0} / ${triDirD || 0} / ${triDir1h || 0}`}</span></div>
                <div className="flex justify-between"><span>tier</span><span>{triTier}</span></div>
                <div className="flex justify-between"><span>target_net_bias / max_net</span><span>{`${_fmtN(triTargetNetBias)} / ${_fmtN(triMaxNetExposure)}`}</span></div>
                <div className="flex justify-between"><span>allow_open / addon</span><span>{`${triAllowOpen ? 'yes' : 'no'} / ${triAllowAddon ? 'yes' : 'no'}`}</span></div>
                <div className="flex justify-between"><span>ChgSpeedD / ChgStrength1h</span><span>{`${_fmtN(triChgSpeedD)} / ${_fmtN(triChgStrength)}`}</span></div>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Badge variant={fallbackActive ? 'destructive' : 'outline'}>{fallbackActive ? 'fallback shape12h_baseline' : 'primary tri_layer'}</Badge>
                  <Badge variant={normalDisabled ? 'destructive' : 'outline'}>{normalDisabled ? '常规禁用' : '允许开仓'}</Badge>
                  <Badge variant={triReasonMatch ? 'outline' : 'secondary'}>trace {triReasonMatch ? 'matched' : 'unmatched'}</Badge>
                  <Badge variant="outline">crash {triCrash ? 'on' : 'off'}</Badge>
                  <Badge variant="outline">observed_blocks {Number.isFinite(triObservedBlocks) ? String(Math.trunc(triObservedBlocks)) : '-'}</Badge>
                  <Badge variant={vizOk ? 'outline' : 'destructive'}>viz {vizOk ? 'ok' : 'error'}</Badge>
                </div>
                {triWarning ? <div className="mt-2 text-xs text-amber-700">{triWarning}</div> : null}
                <div className="mt-2 text-xs text-slate-600">fallback基线：{shapeName} · risk_w/value_w {_fmtPct(riskW)} / {_fmtPct(valueW)} · gross_mult {_fmtN(sizeLong)}/{_fmtN(sizeShort)} · cd_mult {_fmtN(cdLong)}/{_fmtN(cdShort)} · hedge_cap {Number.isFinite(counterMaxFrac) ? `${(counterMaxFrac * 100).toFixed(0)}%` : '-'} · dir0_block {dir0Block ? 'on' : 'off'} · counter_hedge {counterRequireHedge ? 'on' : 'off'} · block_high_risk {counterBlockHighRisk ? 'on' : 'off'} · age {shapeTs > 0 && nowMs > 0 ? _msToCompact(nowMs - shapeTs) : '-'}</div>
              </div>

              <div className="border rounded p-3 bg-white">
                <div className="font-semibold mb-2">Positions</div>
                <div className="flex justify-between"><span>open_positions</span><span>{openPosN}</span></div>
                <div className="flex justify-between"><span>signals_total</span><span>{Number((metrics as { signals?: number } | undefined)?.signals ?? 0)}</span></div>
                <div className="flex justify-between"><span>orders_total</span><span>{Number((metrics as { orders?: number } | undefined)?.orders ?? 0)}</span></div>
              </div>

              <div className="border rounded p-3 bg-white">
                <div className="font-semibold mb-2">Scheduler</div>
                <div className="flex justify-between"><span>tick</span><span>{schedTick || '-'}</span></div>
                <div className="flex justify-between"><span>last_heartbeat</span><span>{schedAge !== null ? _msToCompact(schedAge) : '-'}</span></div>
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
};

const DashboardMacroCard: React.FC = () => {
  const { data: metrics } = useQuery({
    queryKey: ['metrics'],
    queryFn: fetchMetrics,
    refetchInterval: 3000,
    refetchOnWindowFocus: false,
  });

  const nowMs = Number((metrics as { ts?: number } | undefined)?.ts ?? 0);

  const { data: ov } = useQuery({
    queryKey: ['macro', 'btceth', 'overview'],
    queryFn: () => fetchMacroBtcEthOverview({ lookback_days: 400, flow_lookback_days: 240 }),
    refetchInterval: 30000,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const { data: viz } = useQuery({
    queryKey: ['macro', 'viz', 'macro-card', 24],
    queryFn: () => fetchMacroViz({ shape_n: 20, signal_window_h: 24 }),
    refetchInterval: 30000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const { data: bt } = useQuery({
    queryKey: ['macro', 'btc', 'regime_backtest', 260],
    queryFn: () => fetchMacroBtcRegimeBacktest({
      lookback_days: 260,
      flow_lookback_days: 240,
      r_mid_q: 0.6,
      r_high_q: 0.8,
      atr_p80_q: 0.8,
      atr_p95_q: 0.95,
      dom_q: 0.8,
    }),
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const std1h = (ov as { std_1h?: Record<string, unknown> } | undefined)?.std_1h ?? null;
  const gateStd1h = (ov as { gate_std1h?: Record<string, unknown> } | undefined)?.gate_std1h ?? null;
  const gateCfg = (ov as { gate_config?: Record<string, unknown> } | undefined)?.gate_config ?? null;
  const tri = (ov as { macro_tri_layer?: Record<string, unknown> } | undefined)?.macro_tri_layer ?? null;

  const lastRow = useMemo(() => {
    const rows = (bt as { rows?: unknown[] } | undefined)?.rows;
    if (!Array.isArray(rows) || rows.length === 0) return null;
    const r = rows[rows.length - 1];
    return (r && typeof r === 'object') ? (r as Record<string, unknown>) : null;
  }, [bt]);

  const regime = String(lastRow?.regime ?? '-').trim() || '-';
  const regimeTs = Number(lastRow?.ts ?? 0);
  const regimeAge = (regimeTs > 0) ? (nowMs - (regimeTs < 1e11 ? regimeTs * 1000 : regimeTs)) : null;

  const stdTs = Number((std1h as Record<string, unknown> | null)?.ts ?? 0);
  const stdAge = (stdTs > 0) ? (nowMs - (stdTs < 1e11 ? stdTs * 1000 : stdTs)) : null;
  const stdValid = Boolean((std1h as Record<string, unknown> | null)?.valid ?? false);

  const gateEnabled = Boolean((gateCfg as Record<string, unknown> | null)?.enabled ?? false);
  const gateFailOpen = Boolean((gateCfg as Record<string, unknown> | null)?.fail_open ?? true);
  const gateEffRecRaw = String((gateStd1h as Record<string, unknown> | null)?.effective_recommend ?? '').trim() || '-';
  const gateEffLongRaw = Boolean((gateStd1h as Record<string, unknown> | null)?.effective_long_ok ?? true);
  const gateEffShortRaw = Boolean((gateStd1h as Record<string, unknown> | null)?.effective_short_ok ?? true);
  const gateEffRec = gateEnabled ? gateEffRecRaw : 'disabled';
  const gateEffLong = gateEnabled ? gateEffLongRaw : false;
  const gateEffShort = gateEnabled ? gateEffShortRaw : false;
  const gateEffLongText = gateEnabled ? String(gateEffLong) : '-';
  const gateEffShortText = gateEnabled ? String(gateEffShort) : '-';
  const triAllowOpen = Boolean((tri as Record<string, unknown> | null)?.allow_open ?? false);
  const triAllowAddon = Boolean((tri as Record<string, unknown> | null)?.allow_addon ?? false);
  const triTier = String((tri as Record<string, unknown> | null)?.risk_budget_tier ?? '-');
  const triTargetNetBias = Number((tri as Record<string, unknown> | null)?.target_net_bias ?? Number.NaN);
  const triMaxNetExposure = Number((tri as Record<string, unknown> | null)?.max_net_exposure ?? Number.NaN);
  const vizTargetSource = String((((viz as { position_budget?: Record<string, unknown> } | undefined)?.position_budget ?? {}) as Record<string, unknown>)?.target ? ((((viz as { position_budget?: Record<string, unknown> } | undefined)?.position_budget ?? {}) as Record<string, unknown>).target as Record<string, unknown>).target_source ?? '' : '');
  const triMode = vizTargetSource === 'tri_layer' ? 'tri_layer' : (vizTargetSource === 'shape12h_baseline' ? 'fallback_shape12h' : 'degraded');
  const cardDecision = (!gateEnabled) ? '常规禁用' : ((triMode !== 'tri_layer' || !triAllowOpen) ? '常规禁用' : '可放行');

  const thresholds = (bt as { thresholds?: Record<string, unknown> } | undefined)?.thresholds ?? null;
  const rMid = Number((thresholds as Record<string, unknown> | null)?.r_mid ?? NaN);
  const rHigh = Number((thresholds as Record<string, unknown> | null)?.r_high ?? NaN);
  const atrP95 = Number((thresholds as Record<string, unknown> | null)?.atr_p95 ?? NaN);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>Macro Regime / Gate</span>
          <Link to="/macro">
            <Button variant="outline" size="sm">Macro</Button>
          </Link>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap gap-2 items-center text-sm">
          <Badge variant="secondary">BTC Regime {regime}</Badge>
          <Badge variant="outline">RegimeAge {regimeAge !== null ? _msToCompact(regimeAge) : '-'}</Badge>
          <Badge variant={gateEnabled ? 'secondary' : 'outline'}>std1hGate {gateEnabled ? 'ON' : 'OFF'}</Badge>
          <Badge variant={stdValid ? 'secondary' : 'destructive'}>std1h {stdValid ? 'valid' : 'invalid'}</Badge>
          <Badge variant="outline">std1hAge {stdAge !== null ? _msToCompact(stdAge) : '-'}</Badge>
          <Badge variant={!gateEnabled ? 'outline' : (gateEffLong ? 'secondary' : 'destructive')}>Long {!gateEnabled ? '-' : (gateEffLong ? 'ok' : 'block')}</Badge>
          <Badge variant={!gateEnabled ? 'outline' : (gateEffShort ? 'secondary' : 'destructive')}>Short {!gateEnabled ? '-' : (gateEffShort ? 'ok' : 'block')}</Badge>
          <Badge variant="outline">Rec {gateEffRec}</Badge>
          <Badge variant="outline">fail_open {String(gateFailOpen)}</Badge>
          <Badge variant={cardDecision === '可放行' ? 'secondary' : 'destructive'}>{cardDecision}</Badge>
        </div>
        <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3 text-xs text-slate-700">
          <div className="border rounded p-3 bg-white">
            <div className="font-semibold mb-2">Quantile Thresholds</div>
            <div className="flex justify-between"><span>R_mid</span><span>{Number.isFinite(rMid) ? rMid.toFixed(4) : '-'}</span></div>
            <div className="flex justify-between"><span>R_high</span><span>{Number.isFinite(rHigh) ? rHigh.toFixed(4) : '-'}</span></div>
            <div className="flex justify-between"><span>P95(atr_pct)</span><span>{Number.isFinite(atrP95) ? atrP95.toFixed(4) : '-'}</span></div>
          </div>
          <div className="border rounded p-3 bg-white">
            <div className="font-semibold mb-2">std1h Snapshot</div>
            <div className="flex justify-between"><span>ts</span><span>{stdTs > 0 ? String(stdTs) : '-'}</span></div>
            <div className="flex justify-between"><span>valid</span><span>{String(stdValid)}</span></div>
            <div className="flex justify-between"><span>gate_fail_open</span><span>{String(gateFailOpen)}</span></div>
          </div>
          <div className="border rounded p-3 bg-white">
            <div className="font-semibold mb-2">Gate Effective</div>
            <div className="flex justify-between"><span>recommend</span><span>{gateEffRec}</span></div>
            <div className="flex justify-between"><span>long_ok</span><span>{gateEffLongText}</span></div>
            <div className="flex justify-between"><span>short_ok</span><span>{gateEffShortText}</span></div>
            <div className="flex justify-between"><span>target_source</span><span>{vizTargetSource || '-'}</span></div>
            <div className="flex justify-between"><span>tri_tier</span><span>{triTier}</span></div>
            <div className="flex justify-between"><span>tri_allow_open/addon</span><span>{`${triAllowOpen ? 'yes' : 'no'} / ${triAllowAddon ? 'yes' : 'no'}`}</span></div>
            <div className="flex justify-between"><span>tri_target/max_net</span><span>{`${Number.isFinite(triTargetNetBias) ? triTargetNetBias.toFixed(3) : '-'} / ${Number.isFinite(triMaxNetExposure) ? triMaxNetExposure.toFixed(3) : '-'}`}</span></div>
            <div className="flex justify-between"><span>mode</span><span>{triMode}</span></div>
            <div className="flex justify-between"><span>decision</span><span>{cardDecision}</span></div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};

const MlTradePage: React.FC = () => {
  const loc = useLocation();

  const overrides = useMemo(() => {
    try {
      const sp = new URLSearchParams(String(loc.search ?? ''));
      const abOwner = String(sp.get('ab_owner') ?? '').trim();
      const bookId = String(sp.get('book_id') ?? '').trim();
      const strategyId = String(sp.get('strategy_id') ?? '').trim();
      return {
        abOwner: abOwner || undefined,
        bookId: bookId || undefined,
        strategyId: strategyId || undefined,
      };
    } catch {
      return { abOwner: undefined, bookId: undefined, strategyId: undefined };
    }
  }, [loc.search]);

  const { data: configData } = useQuery({
    queryKey: ['config'],
    queryFn: fetchConfig,
    refetchInterval: 30000,
    refetchOnWindowFocus: true,
    retry: false,
  });

  const strategyShadowModeEnabled = useMemo(() => {
    try {
      return Boolean((configData as unknown as Record<string, unknown> | null | undefined)?.serving_shadow_mode);
    } catch {
      return false;
    }
  }, [configData]);

  const tableFilters = useMemo(() => {
    return { abOwner: overrides.abOwner ?? 'strategy', bookId: overrides.bookId ?? 'strategy', strategyId: overrides.strategyId };
  }, [overrides.abOwner, overrides.bookId, overrides.strategyId]);

  const jumpTo = (id: string) => {
    try {
      const el = document.getElementById(id);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch {
      void 0;
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="text-xl font-bold">ML Trade Dashboard</div>
        <div className="flex items-center gap-2">
          <div className="text-xs text-slate-500">快捷跳转</div>
          <Button type="button" variant="outline" size="sm" onClick={() => jumpTo('ml-metrics')}>Metrics</Button>
          <Button type="button" variant="outline" size="sm" onClick={() => jumpTo('ml-orders')}>Orders</Button>
          <Button type="button" variant="outline" size="sm" onClick={() => jumpTo('ml-signals')}>Signals</Button>
          <Button type="button" variant="outline" size="sm" onClick={() => jumpTo('ml-config')}>Config</Button>
        </div>
      </div>

      <div id="ml-metrics">
        <MetricsCard />
      </div>
      <div id="ml-health">
        <DashboardHealthCard />
      </div>
      <div id="ml-macro">
        <DashboardMacroCard />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div id="ml-orders">
          <OrdersTable
            abOwner={tableFilters.abOwner}
            bookId={tableFilters.bookId}
            strategyId={tableFilters.strategyId}
            title="Recent Orders · Strategy"
            displayLimit={6}
          />
        </div>
        <div id="ml-signals">
          <SignalsTable
            abOwner={tableFilters.abOwner}
            bookId={tableFilters.bookId}
            strategyId={tableFilters.strategyId}
            title="Recent Signals · Strategy"
            displayLimit={20}
            showOrderInfo
            includeShadow={strategyShadowModeEnabled}
          />
        </div>
      </div>
      <div id="ml-config">
        <ConfigCard />
      </div>
    </div>
  );
};

export default function App() {
  return (
    <Router>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          element={
            <RequireSession>
              <ShellLayout />
            </RequireSession>
          }
        >
          <Route index element={<Navigate to="/agent" replace />} />
          <Route path="agent" element={<AgentHomePage />} />
          <Route path="agent/observability" element={<AgentObservabilityPage />} />
          <Route path="agent/overview" element={<AgentConsolePage mode="overview" />} />
          <Route path="agent/approvals" element={<ApprovalReviewPage />} />
          <Route path="agent/approvals/:id" element={<ApprovalReviewPage />} />
          <Route path="agent/sandbox" element={<AgentConsolePage mode="sandbox" />} />
          <Route path="agent/redteam" element={<AgentConsolePage mode="redteam" />} />
          <Route path="agent/ops" element={<AgentConsolePage mode="ops" />} />
          <Route path="agent/audit" element={<AgentConsolePage mode="audit" />} />
          <Route path="ml" element={<MlTradePage />} />
          <Route path="evaluation" element={<ModelEvaluationPage />} />
          <Route path="arena" element={<ArenaPage />} />
          <Route path="universe" element={<UniversePage />} />
          <Route path="macro" element={<MacroPage />} />
          <Route path="evolution" element={<RegimeEvolutionPage />} />
          <Route path="strategy" element={<ActiveStrategyPage />} />
          <Route path="library" element={<StrategyPage />} />
          <Route path="exit" element={<RequireProdUi><ExitSystemPage /></RequireProdUi>} />
          <Route path="index" element={<EngineeringIndexPage />} />
          <Route path="docs" element={<DocsPage />} />
          <Route path="*" element={<Navigate to="/agent" replace />} />
        </Route>
      </Routes>
    </Router>
  );
}
