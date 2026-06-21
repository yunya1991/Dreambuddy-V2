from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal


@dataclass(frozen=True)
class BackendRoute:
  path: str
  methods: tuple[str, ...]
  handler: str | None
  file: str
  decorator_line: int
  handler_line: int | None


@dataclass(frozen=True)
class FrontendCall:
  method: Literal['get', 'post', 'put', 'patch', 'delete']
  path: str
  caller: str | None
  file: str
  line: int


@dataclass(frozen=True)
class SymbolDef:
  kind: Literal['function', 'class', 'const']
  name: str
  file: str
  line: int


@dataclass(frozen=True)
class SymbolRef:
  name: str
  file: str
  line: int


@dataclass(frozen=True)
class ConfigKeyRef:
  key: str
  owner: str | None
  kind: Literal['def', 'get', 'subscript', 'setdefault', 'pop']
  file: str
  line: int


@dataclass(frozen=True)
class StringLitRef:
  value: str
  file: str
  line: int


_ROUTE_RE = re.compile(
  r"^\s*@(?P<obj>[A-Za-z_][A-Za-z0-9_\.]*)\.route\(\s*(?P<q>['\"])(?P<path>.+?)(?P=q)",
  re.IGNORECASE,
)
_METHODS_RE = re.compile(r"methods\s*=\s*(?P<val>\[[^\]]*\]|\([^\)]*\))", re.IGNORECASE)
_DEF_RE = re.compile(r"^\s*def\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(")

_TS_FUNC_DEF_RE = re.compile(r"^\s*(?:export\s+)?function\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\s*\(")
_TS_CLASS_DEF_RE = re.compile(r"^\s*(?:export\s+)?class\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\b")
_TS_CONST_ARROW_DEF_RE = re.compile(
  r"^\s*(?:export\s+)?const\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][A-Za-z0-9_$]*)\s*=>",
)
_TS_CONST_FN_DEF_RE = re.compile(
  r"^\s*(?:export\s+)?const\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?function\b",
)
_TS_CALL_RE = re.compile(r"\b(?P<name>[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*)\s*\(")

_DEFAULT_IGNORE = (
  '.git/',
  '.mypy_cache/',
  '.pytest_cache/',
  '__pycache__/',
  'node_modules/',
  '.venv/',
  'venv/',
  'dist/',
  'build/',
  '.next/',
  '.turbo/',
  'cache/',
  'backups/',
)

_JS_CALL_KEYWORDS = {
  'if',
  'for',
  'while',
  'switch',
  'catch',
  'function',
  'return',
  'new',
  'await',
  'typeof',
  'void',
  'delete',
  'in',
  'instanceof',
  'super',
  'class',
  'constructor',
  'import',
  'export',
  'from',
  'as',
  'try',
  'finally',
  'throw',
}


def _load_ignore_patterns(root: Path, ignore_file: Path | None, extra: list[str]) -> list[str]:
  patterns: list[str] = []
  patterns.extend(_DEFAULT_IGNORE)

  auto_gitignore = root / '.gitignore'
  if ignore_file is None and auto_gitignore.exists():
    ignore_file = auto_gitignore

  if ignore_file is not None and ignore_file.exists():
    for raw in ignore_file.read_text(encoding='utf-8', errors='replace').splitlines():
      s = raw.strip()
      if not s or s.startswith('#'):
        continue
      if s.startswith('!'):
        continue
      patterns.append(s)

  patterns.extend([p for p in extra if p])
  out: list[str] = []
  for p in patterns:
    for n in _normalize_ignore_patterns(p):
      out.append(n)
  return out


def _normalize_ignore_patterns(p: str) -> list[str]:
  s = p.strip().replace('\\', '/')
  if not s:
    return []

  anchored = s.startswith('/')
  if anchored:
    s = s[1:]

  dir_only = s.endswith('/')
  if dir_only:
    s = s[:-1]

  if not s:
    return []

  bases: list[str]
  if '/' not in s and not anchored:
    bases = [s, f"**/{s}"]
  else:
    bases = [s]

  if dir_only:
    return [f"{b}/**" for b in bases]
  return bases


def _is_ignored(rel_posix: str, patterns: Iterable[str]) -> bool:
  p = rel_posix.lstrip('./')
  for pat in patterns:
    if fnmatch.fnmatch(p, pat):
      return True
  return False


def iter_source_files(root: Path, ignore_patterns: list[str]) -> Iterable[Path]:
  exts = {'.py', '.ts', '.tsx', '.js', '.jsx'}
  for dirpath, dirnames, filenames in os.walk(root):
    dir_rel = Path(dirpath).relative_to(root)
    dir_rel_posix = dir_rel.as_posix()
    if dir_rel_posix == '.':
      dir_rel_posix = ''
    kept: list[str] = []
    for d in dirnames:
      rel = f"{dir_rel_posix}/{d}" if dir_rel_posix else d
      if _is_ignored(f"{rel}/", ignore_patterns) or _is_ignored(rel, ignore_patterns):
        continue
      kept.append(d)
    dirnames[:] = kept

    for fn in filenames:
      p = Path(dirpath) / fn
      rel = p.relative_to(root).as_posix()
      if _is_ignored(rel, ignore_patterns):
        continue
      if p.suffix.lower() not in exts:
        continue
      yield p


def _call_name(expr: ast.AST) -> str | None:
  if isinstance(expr, ast.Name):
    return expr.id
  if isinstance(expr, ast.Attribute):
    parts: list[str] = [expr.attr]
    cur: ast.AST = expr.value
    while isinstance(cur, ast.Attribute):
      parts.append(cur.attr)
      cur = cur.value
    if isinstance(cur, ast.Name):
      parts.append(cur.id)
      return '.'.join(reversed(parts))
    return expr.attr
  return None


def parse_python_symbols(py_path: Path) -> tuple[list[SymbolDef], list[SymbolRef]]:
  text = py_path.read_text(encoding='utf-8', errors='replace')
  try:
    tree = ast.parse(text)
  except SyntaxError:
    return ([], [])

  defs: list[SymbolDef] = []
  refs: list[SymbolRef] = []

  for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
      defs.append(SymbolDef(kind='function', name=node.name, file=str(py_path), line=int(getattr(node, 'lineno', 1))))
    elif isinstance(node, ast.ClassDef):
      defs.append(SymbolDef(kind='class', name=node.name, file=str(py_path), line=int(getattr(node, 'lineno', 1))))
    elif isinstance(node, ast.Call):
      n = _call_name(node.func)
      if n:
        refs.append(SymbolRef(name=n, file=str(py_path), line=int(getattr(node, 'lineno', 1))))

  return (defs, refs)


def _py_docstring_lines(tree: ast.AST) -> set[int]:
  out: set[int] = set()

  def mark_docstring(n: ast.AST) -> None:
    body = getattr(n, 'body', None)
    if not body or not isinstance(body, list):
      return
    first = body[0]
    if not isinstance(first, ast.Expr):
      return
    v = getattr(first, 'value', None)
    if isinstance(v, ast.Constant) and isinstance(v.value, str):
      ln = int(getattr(first, 'lineno', 0) or 0)
      if ln:
        out.add(ln)

  for node in ast.walk(tree):
    if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
      mark_docstring(node)

  return out


def parse_python_config_and_strings(py_path: Path) -> tuple[list[ConfigKeyRef], list[StringLitRef]]:
  text = py_path.read_text(encoding='utf-8', errors='replace')
  try:
    tree = ast.parse(text)
  except SyntaxError:
    return ([], [])

  config_refs: list[ConfigKeyRef] = []
  string_refs: list[StringLitRef] = []
  doc_ln = _py_docstring_lines(tree)

  def str_const(n: ast.AST | None) -> str | None:
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
      return n.value
    return None

  def owner_name(n: ast.AST) -> str | None:
    if isinstance(n, ast.Name):
      return n.id
    return None

  def add_key(key: str, owner: str | None, kind: str, node: ast.AST) -> None:
    ln = int(getattr(node, 'lineno', 0) or 0) or 1
    config_refs.append(ConfigKeyRef(key=key, owner=owner, kind=kind, file=str(py_path), line=ln))

  for node in ast.walk(tree):
    if isinstance(node, ast.Assign):
      for tgt in node.targets:
        if isinstance(tgt, ast.Name) and tgt.id == 'CONFIG' and isinstance(node.value, ast.Dict):
          for k in node.value.keys:
            ks = str_const(k)
            if ks:
              add_key(ks, 'CONFIG', 'def', node)

    if isinstance(node, ast.Subscript):
      owner = owner_name(node.value)
      if owner:
        ks = str_const(getattr(node, 'slice', None))
        if ks:
          add_key(ks, owner, 'subscript', node)

    if isinstance(node, ast.Call):
      if isinstance(node.func, ast.Attribute):
        owner = owner_name(node.func.value)
        if owner and node.args:
          ks = str_const(node.args[0])
          if ks and node.func.attr in {'get', 'setdefault', 'pop'}:
            add_key(ks, owner, str(node.func.attr), node)

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
      ln = int(getattr(node, 'lineno', 0) or 0) or 1
      if ln in doc_ln:
        continue
      v = node.value.strip()
      if not v:
        continue
      if len(v) > 200:
        continue
      string_refs.append(StringLitRef(value=v, file=str(py_path), line=ln))

  return (config_refs, string_refs)


def parse_ts_symbols(ts_path: Path) -> tuple[list[SymbolDef], list[SymbolRef]]:
  defs: list[SymbolDef] = []
  refs: list[SymbolRef] = []
  lines = ts_path.read_text(encoding='utf-8', errors='replace').splitlines()

  def_names_on_line: set[str]

  for i, line in enumerate(lines, start=1):
    def_names_on_line = set()

    m = _TS_FUNC_DEF_RE.match(line)
    if m:
      name = m.group('name')
      defs.append(SymbolDef(kind='function', name=name, file=str(ts_path), line=i))
      def_names_on_line.add(name)

    m = _TS_CLASS_DEF_RE.match(line)
    if m:
      name = m.group('name')
      defs.append(SymbolDef(kind='class', name=name, file=str(ts_path), line=i))
      def_names_on_line.add(name)

    m = _TS_CONST_ARROW_DEF_RE.match(line) or _TS_CONST_FN_DEF_RE.match(line)
    if m:
      name = m.group('name')
      defs.append(SymbolDef(kind='const', name=name, file=str(ts_path), line=i))
      def_names_on_line.add(name)

    for cm in _TS_CALL_RE.finditer(line):
      full = cm.group('name')
      last = full.split('.')[-1]
      if last in _JS_CALL_KEYWORDS:
        continue
      if last in def_names_on_line:
        continue
      refs.append(SymbolRef(name=full, file=str(ts_path), line=i))

  return (defs, refs)


_TS_STRING_RE = re.compile(r"(?P<q>['\"`])(?P<v>(?:\\.|(?!\1).)*)\1")


def parse_ts_strings(ts_path: Path) -> list[StringLitRef]:
  out: list[StringLitRef] = []
  lines = ts_path.read_text(encoding='utf-8', errors='replace').splitlines()
  for i, line in enumerate(lines, start=1):
    for m in _TS_STRING_RE.finditer(line):
      q = m.group('q')
      v = (m.group('v') or '').strip()
      if not v:
        continue
      if len(v) > 200:
        continue
      if q == '`' and '${' in v:
        continue
      out.append(StringLitRef(value=v, file=str(ts_path), line=i))
  return out


def _parse_methods(raw: str | None) -> tuple[str, ...]:
  if not raw:
    return ("GET",)
  m = _METHODS_RE.search(raw)
  if not m:
    return ("GET",)
  val = m.group('val')
  xs = re.findall(r"['\"](?P<m>[A-Za-z]+)['\"]", val)
  if not xs:
    return ("GET",)
  return tuple(str(x).upper() for x in xs)


def parse_flask_routes(py_path: Path) -> list[BackendRoute]:
  routes: list[BackendRoute] = []
  pending: dict[str, object] | None = None
  lines = py_path.read_text(encoding='utf-8', errors='replace').splitlines()

  for i, line in enumerate(lines, start=1):
    m = _ROUTE_RE.match(line)
    if m:
      pending = {
        'path': m.group('path').strip(),
        'methods': _parse_methods(line),
        'decorator_line': i,
      }
      continue

    if pending is not None:
      if line.strip().startswith('@'):
        continue
      dm = _DEF_RE.match(line)
      if dm:
        routes.append(
          BackendRoute(
            path=str(pending['path']),
            methods=tuple(pending['methods']),
            handler=dm.group('name'),
            file=str(py_path),
            decorator_line=int(pending['decorator_line']),
            handler_line=i,
          )
        )
        pending = None
        continue

      if line.strip() and not line.lstrip().startswith('#'):
        routes.append(
          BackendRoute(
            path=str(pending['path']),
            methods=tuple(pending['methods']),
            handler=None,
            file=str(py_path),
            decorator_line=int(pending['decorator_line']),
            handler_line=None,
          )
        )
        pending = None

  if pending is not None:
    routes.append(
      BackendRoute(
        path=str(pending['path']),
        methods=tuple(pending['methods']),
        handler=None,
        file=str(py_path),
        decorator_line=int(pending['decorator_line']),
        handler_line=None,
      )
    )

  return routes


_EXPORT_CONST_RE = re.compile(r"^\s*export\s+const\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*", re.IGNORECASE)
_API_CALL_RE = re.compile(
  r"\bapi\.(?P<method>get|post|put|patch|delete)\s*(?:<[^>]*>)?\s*\(\s*(?P<q>['\"])(?P<path>\/[^'\"]+)(?P=q)",
  re.IGNORECASE,
)


def parse_frontend_calls(ts_path: Path) -> list[FrontendCall]:
  calls: list[FrontendCall] = []
  cur_fn: str | None = None
  lines = ts_path.read_text(encoding='utf-8', errors='replace').splitlines()
  for i, line in enumerate(lines, start=1):
    em = _EXPORT_CONST_RE.match(line)
    if em:
      cur_fn = em.group('name')

    cm = _API_CALL_RE.search(line)
    if not cm:
      continue
    calls.append(
      FrontendCall(
        method=str(cm.group('method')).lower(),
        path=str(cm.group('path')),
        caller=cur_fn,
        file=str(ts_path),
        line=i,
      )
    )
  return calls


def _load_prev_index(prev_index_path: Path) -> dict | None:
  if not prev_index_path.exists():
    return None
  try:
    return json.loads(prev_index_path.read_text(encoding='utf-8'))
  except Exception:
    return None


def build_index(
  root: Path,
  prev: dict | None = None,
  ignore_file: Path | None = None,
  extra_ignores: list[str] | None = None,
  incremental: bool = True,
) -> dict:
  extra_ignores = extra_ignores or []
  ignore_patterns = _load_ignore_patterns(root, ignore_file, extra_ignores)

  prev_files = (prev or {}).get('files') if incremental else None
  if not isinstance(prev_files, dict):
    prev_files = None

  files: dict[str, dict] = {}
  backend_routes_all: list[dict] = []
  frontend_calls_all: list[dict] = []
  defs_all: list[dict] = []
  refs_all: list[dict] = []
  config_keys_all: list[dict] = []
  strings_all: list[dict] = []

  for p in iter_source_files(root, ignore_patterns):
    rel = p.relative_to(root).as_posix()
    st = p.stat()
    prev_rec = prev_files.get(rel) if prev_files else None
    if (
      incremental
      and prev_rec
      and isinstance(prev_rec, dict)
      and prev_rec.get('mtime_ns') == st.st_mtime_ns
      and prev_rec.get('size') == st.st_size
    ):
      rec = prev_rec
    else:
      defs: list[SymbolDef] = []
      refs: list[SymbolRef] = []
      backend_routes: list[BackendRoute] = []
      frontend_calls: list[FrontendCall] = []
      config_keys: list[ConfigKeyRef] = []
      strings: list[StringLitRef] = []

      if p.suffix.lower() == '.py':
        defs, refs = parse_python_symbols(p)
        backend_routes = parse_flask_routes(p)
        config_keys, strings = parse_python_config_and_strings(p)
      elif p.suffix.lower() in {'.ts', '.tsx', '.js', '.jsx'}:
        defs, refs = parse_ts_symbols(p)
        strings = parse_ts_strings(p)
        if p.name in {'api.ts', 'api.js'} or '/frontend/' in str(p).replace('\\', '/'):
          frontend_calls = parse_frontend_calls(p)

      rec = {
        'mtime_ns': st.st_mtime_ns,
        'size': st.st_size,
        'defs': [d.__dict__ for d in defs],
        'refs': [r.__dict__ for r in refs],
        'config_keys': [c.__dict__ for c in config_keys],
        'strings': [s.__dict__ for s in strings],
        'backend_routes': [
          {
            'path': r.path,
            'methods': list(r.methods),
            'handler': r.handler,
            'file': r.file,
            'decorator_line': r.decorator_line,
            'handler_line': r.handler_line,
          }
          for r in backend_routes
        ],
        'frontend_calls': [
          {
            'method': c.method,
            'path': c.path,
            'caller': c.caller,
            'file': c.file,
            'line': c.line,
          }
          for c in frontend_calls
        ],
      }

    files[rel] = rec
    backend_routes_all.extend(rec.get('backend_routes') or [])
    frontend_calls_all.extend(rec.get('frontend_calls') or [])
    defs_all.extend(rec.get('defs') or [])
    refs_all.extend(rec.get('refs') or [])
    config_keys_all.extend(rec.get('config_keys') or [])
    strings_all.extend(rec.get('strings') or [])

  return {
    'version': 3,
    'generated_at_ms': int(time.time() * 1000),
    'root': str(root),
    'ignore': ignore_patterns,
    'backend': backend_routes_all,
    'frontend': frontend_calls_all,
    'config_keys': config_keys_all,
    'strings': strings_all,
    'symbols': {
      'defs': defs_all,
      'refs': refs_all,
    },
    'files': files,
  }


def _match(s: str, q: str) -> bool:
  return q.lower() in s.lower()


def query_index(idx: dict, q: str, limit: int) -> dict:
  backend = idx.get('backend') or []
  frontend = idx.get('frontend') or []
  config_keys = idx.get('config_keys') or []
  strings = idx.get('strings') or []
  symbols = idx.get('symbols') or {}
  defs = symbols.get('defs') or []
  refs = symbols.get('refs') or []

  b_hits = [
    r
    for r in backend
    if _match(str(r.get('path', '')), q)
    or _match(' '.join(map(str, r.get('methods') or [])), q)
    or _match(str(r.get('handler', '') or ''), q)
  ][:limit]

  f_hits = [
    r
    for r in frontend
    if _match(str(r.get('path', '')), q)
    or _match(str(r.get('method', '')), q)
    or _match(str(r.get('caller', '') or ''), q)
  ][:limit]

  d_hits = [
    r
    for r in defs
    if _match(str(r.get('name', '')), q) or _match(str(r.get('kind', '')), q) or _match(str(r.get('file', '')), q)
  ][:limit]

  r_hits = [
    r
    for r in refs
    if _match(str(r.get('name', '')), q) or _match(str(r.get('file', '')), q)
  ][:limit]

  ck_hits = [
    r
    for r in config_keys
    if _match(str(r.get('key', '')), q)
    or _match(str(r.get('owner', '') or ''), q)
    or _match(str(r.get('kind', '') or ''), q)
    or _match(str(r.get('file', '') or ''), q)
  ][:limit]

  s_hits = [r for r in strings if _match(str(r.get('value', '')), q) or _match(str(r.get('file', '') or ''), q)][:limit]

  return {'backend': b_hits, 'frontend': f_hits, 'defs': d_hits, 'refs': r_hits, 'config_keys': ck_hits, 'strings': s_hits}


def _print_hits(hits: dict) -> None:
  b = hits.get('backend') or []
  f = hits.get('frontend') or []
  d = hits.get('defs') or []
  rfs = hits.get('refs') or []
  ck = hits.get('config_keys') or []
  ss = hits.get('strings') or []

  if b:
    print('BACKEND')
    for r in b:
      methods = ','.join(r.get('methods') or [])
      handler = r.get('handler') or '-'
      file = r.get('file')
      line = r.get('decorator_line')
      print(f"  {methods:9s} {r.get('path'):35s}  {handler}  ({file}:{line})")

  if f:
    print('FRONTEND')
    for r in f:
      caller = r.get('caller') or '-'
      file = r.get('file')
      line = r.get('line')
      print(f"  {str(r.get('method')).upper():6s} {r.get('path'):35s}  {caller}  ({file}:{line})")

  if d:
    print('DEFS')
    for r in d:
      kind = str(r.get('kind') or '-')
      name = str(r.get('name') or '-')
      file = r.get('file')
      line = r.get('line')
      print(f"  {kind:9s} {name:35s}  ({file}:{line})")

  if rfs:
    print('REFS')
    for r in rfs:
      name = str(r.get('name') or '-')
      file = r.get('file')
      line = r.get('line')
      print(f"  {name:45s}  ({file}:{line})")

  if ck:
    print('CONFIG_KEYS')
    for r in ck:
      key = str(r.get('key') or '-')
      owner = str(r.get('owner') or '-')
      kind = str(r.get('kind') or '-')
      file = r.get('file')
      line = r.get('line')
      print(f"  {owner:12s} {kind:10s} {key:35s}  ({file}:{line})")

  if ss:
    print('STRINGS')
    for r in ss:
      v = str(r.get('value') or '-')
      file = r.get('file')
      line = r.get('line')
      if len(v) > 80:
        v = v[:77] + '...'
      print(f"  {v:80s}  ({file}:{line})")


def main(argv: list[str]) -> int:
  ap = argparse.ArgumentParser(prog='lite_code_index')
  ap.add_argument('--root', default=None)
  sub = ap.add_subparsers(dest='cmd', required=True)

  ap_build = sub.add_parser('build')
  ap_build.add_argument('--out', default='cache/code_index_lite.json')
  ap_build.add_argument('--full', action='store_true')
  ap_build.add_argument('--ignore-file', default=None)
  ap_build.add_argument('--ignore', action='append', default=[])

  ap_query = sub.add_parser('query')
  ap_query.add_argument('q')
  ap_query.add_argument('--in', dest='inp', default='cache/code_index_lite.json')
  ap_query.add_argument('--limit', type=int, default=30)

  args = ap.parse_args(argv)

  root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent

  if args.cmd == 'build':
    outp = (root / str(args.out)).resolve()
    prev = None if args.full else _load_prev_index(outp)
    ignore_file = Path(args.ignore_file).resolve() if args.ignore_file else None
    idx = build_index(
      root,
      prev=prev,
      ignore_file=ignore_file,
      extra_ignores=list(args.ignore or []),
      incremental=not args.full,
    )
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(idx, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    defs_n = len((idx.get('symbols') or {}).get('defs') or [])
    refs_n = len((idx.get('symbols') or {}).get('refs') or [])
    ck_n = len(idx.get('config_keys') or [])
    s_n = len(idx.get('strings') or [])
    print(
      f"ok=1 backend={len(idx['backend'])} frontend={len(idx['frontend'])} defs={defs_n} refs={refs_n} config_keys={ck_n} strings={s_n} files={len(idx.get('files') or {})} out={outp}"
    )
    return 0

  if args.cmd == 'query':
    inp = (root / str(args.inp)).resolve()
    if inp.exists():
      idx = json.loads(inp.read_text(encoding='utf-8'))
    else:
      idx = build_index(root)
    hits = query_index(idx, args.q, args.limit)
    _print_hits(hits)
    return 0

  return 2


if __name__ == '__main__':
  raise SystemExit(main(sys.argv[1:]))
