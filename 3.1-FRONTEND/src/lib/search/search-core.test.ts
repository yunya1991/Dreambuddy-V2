/**
 * search-core.test.ts — 搜索核心逻辑单测
 * 覆盖：索引构建、模糊搜索、模块过滤、高亮、最近搜索（方案 §3.4 验收）
 */
import {
  getSearchIndex,
  buildHighlight,
  getRecentSearches,
  addRecentSearch,
  clearRecentSearches,
  SearchItem,
} from "./search-core";

const sampleItems: SearchItem[] = [
  { id: "report-1", moduleId: "T-1001", module: "report", title: "黄金多头策略报告", subtitle: "T-1001", href: "/reports?taskId=T-1001" },
  { id: "strategy-1", moduleId: "s1", module: "strategy", title: "动量突破策略", subtitle: "RUNNING", href: "/config/strategies/s1" },
  { id: "memory-1", moduleId: "m1", module: "memory", title: "用户偏好：低风险稳健型", href: "/notebook" },
  { id: "doc-1", moduleId: "d1", module: "doc", title: "部署文档", keywords: "deploy docker", href: "/docs/d1" },
];

describe("SearchIndex", () => {
  beforeEach(() => {
    const idx = getSearchIndex();
    idx.replaceAll(sampleItems);
  });

  test("全量替换后索引条目数正确", () => {
    expect(getSearchIndex().size).toBe(4);
  });

  test("精确关键词可命中目标", () => {
    const results = getSearchIndex().search("部署文档");
    expect(results.length).toBeGreaterThan(0);
    expect(results[0].id).toBe("doc-1");
  });

  test("部分输入（前缀）可命中", () => {
    const results = getSearchIndex().search("黄金");
    expect(results.some((r) => r.id === "report-1")).toBe(true);
  });

  test("英文关键词可命中", () => {
    const results = getSearchIndex().search("deploy");
    expect(results.some((r) => r.id === "doc-1")).toBe(true);
  });

  test("模块过滤生效", () => {
    const results = getSearchIndex().search("策略", 20, "strategy");
    expect(results.length).toBeGreaterThan(0);
    expect(results.every((r) => r.module === "strategy")).toBe(true);
  });

  test("空查询返回空数组", () => {
    expect(getSearchIndex().search("   ")).toEqual([]);
  });

  test("增量添加与移除生效", () => {
    const idx = getSearchIndex();
    idx.add([{ id: "report-2", moduleId: "T-1002", module: "report", title: "原油对冲报告", href: "/reports?taskId=T-1002" }]);
    expect(idx.size).toBe(5);
    idx.remove(["report-2"]);
    expect(idx.size).toBe(4);
    expect(idx.search("原油").length).toBe(0);
  });

  test("结果按相关性排序（标题命中优先）", () => {
    const idx = getSearchIndex();
    idx.add([{ id: "doc-2", moduleId: "d2", module: "doc", title: "策略配置说明", keywords: "策略", href: "/docs/d2" }]);
    const results = idx.search("策略");
    expect(results.length).toBeGreaterThan(1);
    expect(results[0].score).toBeGreaterThanOrEqual(results[1].score);
  });
});

describe("buildHighlight", () => {
  test("命中词被 mark 标签包裹", () => {
    const html = buildHighlight(
      { id: "x", moduleId: "x", module: "doc", title: "部署文档指南", href: "/x" },
      ["部署"]
    );
    expect(html).toContain("<mark>部署</mark>");
  });

  test("HTML 特殊字符被转义", () => {
    const html = buildHighlight(
      { id: "x", moduleId: "x", module: "doc", title: "a<b>c", href: "/x" },
      []
    );
    expect(html).toBe("a&lt;b&gt;c");
  });
});

describe("最近搜索记录", () => {
  beforeEach(() => {
    clearRecentSearches();
  });

  test("添加后可读取且去重置顶", () => {
    addRecentSearch("黄金");
    addRecentSearch("策略");
    addRecentSearch("黄金");
    const list = getRecentSearches();
    expect(list[0]).toBe("黄金");
    expect(list.length).toBe(2);
  });

  test("清空后为空", () => {
    addRecentSearch("x");
    clearRecentSearches();
    expect(getRecentSearches()).toEqual([]);
  });
});
