// 确保 9094 基本面后端服务运行；未占用则后台启动并等待就绪
const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');

const PORT = 9094;
const HOST = '127.0.0.1';
const REPO_ROOT = path.resolve(__dirname, '..', '..');
const BACKEND_DIR = path.join(REPO_ROOT, '9-基本面分析');
const PYTHON = path.join(BACKEND_DIR, '.venv', 'bin', 'python');
const ENTRY = path.join(BACKEND_DIR, 'ml_trade_service_v2.py');
const LOG_FILE = '/tmp/fundamental-9094.log';

// 用 http 探测 health 端点（比纯 TCP 端口检查更准确）
const http = require('node:http');

function isAlive() {
  return new Promise((resolve) => {
    const req = http.get(
      { hostname: HOST, port: PORT, path: '/fundamental/health', timeout: 1500 },
      (res) => {
        res.resume();
        resolve(res.statusCode === 200);
      }
    );
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
  });
}

async function waitForAlive(timeoutMs = 30000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    if (await isAlive()) return true;
    await new Promise((r) => setTimeout(r, 1000));
  }
  return false;
}

async function main() {
  // 已在运行则跳过
  if (await isAlive()) {
    console.log('[fundamental-backend] 9094 已在运行，跳过启动');
    return;
  }

  // 校验依赖
  if (!fs.existsSync(PYTHON)) {
    console.warn(`[fundamental-backend] 未找到 venv python: ${PYTHON}，跳过自动启动（请手动启动 9094 后端）`);
    return;
  }
  if (!fs.existsSync(ENTRY)) {
    console.warn(`[fundamental-backend] 未找到后端入口: ${ENTRY}，跳过自动启动`);
    return;
  }

  // 后台启动（detached，输出重定向到日志文件）
  const out = fs.openSync(LOG_FILE, 'w');
  const err = fs.openSync(LOG_FILE, 'a');
  const child = spawn(PYTHON, [ENTRY, '--no-collect'], {
    cwd: BACKEND_DIR,
    detached: true,
    stdio: ['ignore', out, err],
  });
  child.unref();
  console.log(`[fundamental-backend] 启动中 pid=${child.pid}，日志: ${LOG_FILE}`);

  // 等待就绪
  process.stdout.write('[fundamental-backend] 等待就绪');
  const ok = await waitForAlive(40000);
  if (ok) {
    console.log('\n[fundamental-backend] ✓ 9094 就绪');
  } else {
    console.log('\n[fundamental-backend] ⚠ 9094 未在 40s 内就绪，前端仍会启动（API 可用前页面会显示重试）');
  }
}

main().catch((e) => {
  console.error('[fundamental-backend] 启动异常:', e.message);
  // 不阻塞前端启动
});
