"""M3 爬虫轨集成测试 — 端到端：sites.yaml → HTTP mock → parse → adapt → DataRecord → sqlite。

验证爬虫轨全链路：配置加载 → 静态站 requests+Selector → 适配 DataRecord → 去重落库。
"""
import os

import pytest

from data_center.core.contract import DataRecord
from data_center.core.dispatcher import DataCenter
from data_center.crawler.runner import CrawlerRunner
from data_center.storage.sink_sqlite import SqliteSink

REQ_MOD = "data_center.crawler.generic_spider.requests"

YAML_CONFIG = """
sites:
  test_news:
    enabled: true
    source: testnews
    sub_category: article
    url: "http://example.com/news"
    js_render: false
    selectors:
      item: ".newslist a"
      title: "text"
      link: "href"
"""

HTML = """
<html><body>
<ul class="newslist">
  <li><a href="/n/1">第一条新闻</a></li>
  <li><a href="/n/2">第二条新闻</a></li>
</ul>
</body></html>
"""


@pytest.fixture
def config_path(tmp_path):
    p = tmp_path / "sites.yaml"
    p.write_text(YAML_CONFIG)
    return str(p)


def test_crawler_e2e_parse_and_adapt(mocker, config_path):
    """sites.yaml → requests mock → Scrapy Selector parse → adapt → DataRecord。"""
    mock_req = mocker.patch(REQ_MOD)
    mock_req.get.return_value.text = HTML
    mock_req.get.return_value.status_code = 200

    runner = CrawlerRunner(config_path=config_path)
    recs = runner.run("test_news")

    assert len(recs) == 2
    r0 = recs[0]
    assert isinstance(r0, DataRecord)
    assert r0.source == "testnews"
    assert r0.category == "web"
    assert r0.sub_category == "article"
    assert r0.metrics["title"] == "第一条新闻"
    assert r0.metrics["link"] == "/n/1"


def test_crawler_e2e_through_dispatcher(mocker, config_path):
    """DataCenter.fetch("web", config=...) → CrawlerRunner → DataRecord。"""
    mock_req = mocker.patch(REQ_MOD)
    mock_req.get.return_value.text = HTML
    mock_req.get.return_value.status_code = 200

    dc = DataCenter()
    recs = dc.fetch("web", config=config_path, site="test_news")

    assert len(recs) == 2
    assert all(r.category == "web" for r in recs)
    assert recs[0].metrics["title"] == "第一条新闻"


def test_crawler_e2e_sink_to_sqlite(mocker, config_path, tmp_path):
    """爬虫结果落库 sqlite + 去重。"""
    mock_req = mocker.patch(REQ_MOD)
    mock_req.get.return_value.text = HTML
    mock_req.get.return_value.status_code = 200

    runner = CrawlerRunner(config_path=config_path)
    recs = runner.run("test_news")

    db_path = str(tmp_path / "test_crawl.db")
    sink = SqliteSink(db_path=db_path)
    inserted = sink.write(recs)
    assert inserted == 2

    # 再次写入相同记录 → 去重
    inserted_again = sink.write(recs)
    assert inserted_again == 0

    # 读回验证
    stored = sink.read_all()
    assert len(stored) == 2
    assert stored[0].source == "testnews"
    assert stored[0].category == "web"


def test_crawler_disabled_site_skipped(mocker, config_path):
    """disabled 站点不触发 requests。"""
    mock_req = mocker.patch(REQ_MOD)
    # 改 config 使站点 disabled
    import yaml
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    cfg["sites"]["test_news"]["enabled"] = False
    with open(config_path, "w") as f:
        yaml.dump(cfg, f)

    runner = CrawlerRunner(config_path=config_path)
    recs = runner.run("test_news")
    assert recs == []
    mock_req.get.assert_not_called()
