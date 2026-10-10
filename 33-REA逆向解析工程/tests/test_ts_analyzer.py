"""RED 测试：TSAnalyzer — TypeScript/JavaScript AST 分析器。"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.ts_analyzer import TSAnalyzer


SAMPLE_TS = '''
import { Component, OnInit } from '@angular/core';
import * as _ from 'lodash';
import axios from 'axios';

const API_URL = 'https://api.example.com';

export class UserService {
  private api: string;

  constructor() {
    this.api = API_URL;
  }

  async getUsers(): Promise<any[]> {
    const res = await axios.get(this.api);
    return res.data;
  }

  static create(): UserService {
    return new UserService();
  }
}

export function formatDate(date: Date): string {
  return date.toISOString();
}

const log = (msg: string): void => {
  console.log(msg);
};

export default class AppComponent {
  title = 'app';
}
'''


SAMPLE_JS = '''
const express = require('express');
const router = express.Router();

class ApiClient {
  constructor(baseURL) {
    this.baseURL = baseURL;
  }

  async fetch(endpoint) {
    const res = await fetch(this.baseURL + endpoint);
    return res.json();
  }
}

function helper(x) {
  return x * 2;
}

const arrow = (a, b) => a + b;

module.exports = { ApiClient, helper };
'''


def test_ts_analyzer_extracts_imports():
    """RED: 应提取 import / require 语句。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "user_service.ts")
        Path(f).write_text(SAMPLE_TS)
        analyzer = TSAnalyzer()
        result = analyzer.analyze(f)
        imports = result.raw.get("imports", [])
        assert len(imports) >= 3
        assert any(i.get("module") == "@angular/core" for i in imports)
        assert any(i.get("module") == "lodash" for i in imports)
        assert any(i.get("module") == "axios" for i in imports)


def test_ts_analyzer_extracts_classes():
    """RED: 应提取类定义（含方法和装饰器）。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "user_service.ts")
        Path(f).write_text(SAMPLE_TS)
        analyzer = TSAnalyzer()
        result = analyzer.analyze(f)
        classes = result.raw.get("classes", [])
        assert any(c["name"] == "UserService" for c in classes)
        assert any(c["name"] == "AppComponent" for c in classes)
        # UserService should have getUsers and create methods
        svc = [c for c in classes if c["name"] == "UserService"][0]
        method_names = [m["name"] for m in svc.get("methods", [])]
        assert "getUsers" in method_names
        assert "create" in method_names


def test_ts_analyzer_extracts_functions():
    """RED: 应提取函数（普通函数和箭头函数）。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "user_service.ts")
        Path(f).write_text(SAMPLE_TS)
        analyzer = TSAnalyzer()
        result = analyzer.analyze(f)
        functions = result.raw.get("functions", [])
        func_names = [fn["name"] for fn in functions]
        assert "formatDate" in func_names
        assert "log" in func_names


def test_ts_analyzer_extracts_exports():
    """RED: 应提取 export 声明。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "user_service.ts")
        Path(f).write_text(SAMPLE_TS)
        analyzer = TSAnalyzer()
        result = analyzer.analyze(f)
        exports = result.raw.get("exports", [])
        export_names = [e.get("name") for e in exports]
        assert "UserService" in export_names
        assert "formatDate" in export_names
        assert "AppComponent" in export_names


def test_ts_analyzer_parses_javascript():
    """RED: 应支持 .js 文件解析。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "client.js")
        Path(f).write_text(SAMPLE_JS)
        analyzer = TSAnalyzer()
        result = analyzer.analyze(f)
        imports = result.raw.get("imports", [])
        assert any(i.get("module") == "express" for i in imports)
        classes = result.raw.get("classes", [])
        assert any(c["name"] == "ApiClient" for c in classes)
        functions = result.raw.get("functions", [])
        func_names = [fn["name"] for fn in functions]
        assert "helper" in func_names
        assert "arrow" in func_names


def test_ts_analyzer_returns_evidence():
    """RED: 分析结果应包含 Evidence。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "sample.ts")
        Path(f).write_text(SAMPLE_TS)
        analyzer = TSAnalyzer()
        result = analyzer.analyze(f)
        assert len(result.evidence) > 0
        e0 = result.evidence[0]
        assert e0.provenance is not None
        assert 0.0 <= e0.confidence <= 1.0
        assert isinstance(e0.known_gaps, list)


def test_ts_analyzer_known_gaps_for_dynamic_features():
    """RED: known_gaps 应标注 TS 动态特性无法静态解析。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "sample.ts")
        Path(f).write_text(SAMPLE_TS)
        analyzer = TSAnalyzer()
        result = analyzer.analyze(f)
        all_gaps = []
        for e in result.evidence:
            all_gaps.extend(e.known_gaps)
        assert any("动态" in g or "dynamic" in g.lower() for g in all_gaps)


def test_ts_analyzer_invalid_file():
    """RED: 非有效 TS/JS 文件应降级返回。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "readme.md")
        Path(f).write_text("# Hello")
        analyzer = TSAnalyzer()
        result = analyzer.analyze(f)
        assert "error" in result.raw or len(result.evidence) > 0


def test_ts_analyzer_supported_targets():
    """RED: supported_targets 返回 typescript + javascript。"""
    analyzer = TSAnalyzer()
    targets = analyzer.supported_targets()
    assert "typescript" in targets or ".ts" in targets
    assert "javascript" in targets or ".js" in targets


def test_ts_analyzer_summary():
    """RED: 应返回可读摘要。"""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "sample.ts")
        Path(f).write_text(SAMPLE_TS)
        analyzer = TSAnalyzer()
        result = analyzer.analyze(f)
        assert len(result.summary) > 0
