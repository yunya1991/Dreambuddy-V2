/**
 * runtime-paths — 运行时路径与解释器的唯一解析入口
 *
 * 背景：历史代码把 `/home/luke/dreambuddy/...`、`/home/luke/venv-trading/bin/python`
 * 写死在 14 处，换机器即 spawn ENOENT（指针错误）。本模块统一解析：
 *   1. 仓库根：以同时存在 `3.1-FRONTEND` + `1-ARCHITECTURE` 为特征，从 cwd 向上回溯；
 *   2. Python：环境变量优先（TRADING_PYTHON / COGNITIVE_PYTHON / PYTHON），缺省 python3；
 *   3. 子系统目录：按 `NN-名称` 相对仓库根拼接，不写绝对路径。
 *
 * 仅可在服务端（Node runtime / route handler）使用。
 */

import * as fs from 'fs';
import * as path from 'path';

function resolveRepoRoot(): string {
  const cwd = process.cwd();
  const candidates = [
    cwd,
    path.resolve(cwd, '..'),
    path.resolve(cwd, '..', '..'),
    path.resolve(cwd, '..', '..', '..'),
  ];
  for (const dir of candidates) {
    if (
      fs.existsSync(path.join(dir, '3.1-FRONTEND')) &&
      fs.existsSync(path.join(dir, '1-ARCHITECTURE'))
    ) {
      return dir;
    }
  }
  // 兼容 env 显式指定（容器/云端正向部署）
  const envRoot = process.env.REPO_ROOT?.trim();
  if (envRoot && fs.existsSync(envRoot)) return envRoot;
  // fallback：dev server 通常在 3.1-FRONTEND 启动
  return path.resolve(cwd, '..');
}

/** 仓库根目录（绝对路径） */
export const REPO_ROOT = resolveRepoRoot();

/** 前端目录 */
export const FRONTEND_DIR = path.join(REPO_ROOT, '3.1-FRONTEND');

/** 34 前端应用训练系统（核心 DSH 桥接层所在） */
export const TRAINING_SYSTEM_DIR = path.join(REPO_ROOT, '34-前端应用训练系统');

/** 子系统目录解析：systemDir('40-周期神经网络系统') */
export function systemDir(name: string): string {
  return path.join(REPO_ROOT, name);
}

/**
 * Python 解释器：优先显式环境变量，其次项目内 venv（存在则用），最后 python3。
 * 远端/云端通过 PYTHON / TRADING_PYTHON 覆盖。
 */
export const PYTHON_BIN = (() => {
  const explicit =
    process.env.TRADING_PYTHON?.trim() ||
    process.env.COGNITIVE_PYTHON?.trim() ||
    process.env.PYTHON?.trim();
  if (explicit) return explicit;
  const venvCandidates = [
    path.join(REPO_ROOT, '.venv', 'bin', 'python'),
    path.join(REPO_ROOT, 'venv-trading', 'bin', 'python'),
  ];
  for (const candidate of venvCandidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return 'python3';
})();

/** 34 系统脚本路径 */
export function trainingScript(name: string): string {
  return path.join(TRAINING_SYSTEM_DIR, 'scripts', name);
}

/** 34 系统数据/日志文件路径 */
export function trainingFile(name: string): string {
  return path.join(TRAINING_SYSTEM_DIR, name);
}
