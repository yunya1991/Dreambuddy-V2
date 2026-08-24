"""Crawler runner 测试 — 统一编排。

读 sites.yaml → 按 js_render 分发 static/JS → adapt → DataRecord(category=web)。
"""
import pytest

from data_center.crawler.runner import CrawlerRunner
from data_center.core.contract import DataRecord

SPIDER_MOD = "data_center.crawler.runner.GenericSpider"
PW_MOD = "data_center.crawler.runner.PlaywrightFallback"

YAML_CONFIG = """
sites:
  static_site:
    enabled: true
    source: pbc
    sub_category: announcement
    url: "http://pbc.gov.cn/news"
    js_render: false
    selectors:
      item: ".newslist a"
      title: "text"
      link: "href"
  js_site:
    enabled: true
    source: binance
    sub_category: announcement
    url: "http://binance.com/announcements"
    js_render: true
    selectors:
      item: ".item"
      title: "text"
  disabled_site:
    enabled: false
    source: x
    sub_category: y
    url: "http://disabled.com"
    js_render: false
    selectors:
      item: "a"
"""


@pytest.fixture
def config_file(tmp_path):
    p = tmp_path / "sites.yaml"
    p.write_text(YAML_CONFIG)
    return str(p)


def test_static_site_uses_spider(mocker, config_file):
    mock_spider_cls = mocker.patch(SPIDER_MOD)
    mock_spider = mock_spider_cls.return_value
    mock_spider.fetch_and_parse.return_value = [{"title": "t1", "link": "l1"}]
    mocker.patch(PW_MOD)  # 确保不被调用

    runner = CrawlerRunner(config_path=config_file)
    recs = runner.run("static_site")

    mock_spider.fetch_and_parse.assert_called_once()
    assert len(recs) == 1
    assert isinstance(recs[0], DataRecord)
    assert recs[0].source == "pbc"
    assert recs[0].category == "web"
    assert recs[0].metrics["title"] == "t1"


def test_js_site_uses_playwright(mocker, config_file):
    mocker.patch(SPIDER_MOD)  # 确保不被调用
    mock_pw_cls = mocker.patch(PW_MOD)
    mock_pw = mock_pw_cls.return_value
    mock_pw.fetch_and_parse.return_value = [{"title": "js-title"}]

    runner = CrawlerRunner(config_path=config_file)
    recs = runner.run("js_site")

    mock_pw.fetch_and_parse.assert_called_once()
    assert len(recs) == 1
    assert recs[0].source == "binance"
    assert recs[0].metrics["title"] == "js-title"


def test_disabled_site_skipped(mocker, config_file):
    mock_spider_cls = mocker.patch(SPIDER_MOD)
    mock_pw_cls = mocker.patch(PW_MOD)

    runner = CrawlerRunner(config_path=config_file)
    recs = runner.run("disabled_site")

    assert recs == []
    mock_spider_cls.return_value.fetch_and_parse.assert_not_called()
    mock_pw_cls.return_value.fetch_and_parse.assert_not_called()


def test_run_all_crawls_enabled_sites(mocker, config_file):
    mock_spider_cls = mocker.patch(SPIDER_MOD)
    mock_spider = mock_spider_cls.return_value
    mock_spider.fetch_and_parse.return_value = [{"title": "s1"}]

    mock_pw_cls = mocker.patch(PW_MOD)
    mock_pw_cls.return_value.fetch_and_parse.return_value = [{"title": "j1"}]

    runner = CrawlerRunner(config_path=config_file)
    recs = runner.run_all()

    assert len(recs) == 2  # static_site + js_site
    sources = {r.source for r in recs}
    assert sources == {"pbc", "binance"}


def test_unknown_site_returns_empty(mocker, config_file):
    mocker.patch(SPIDER_MOD)
    runner = CrawlerRunner(config_path=config_file)
    assert runner.run("nonexistent") == []


def test_records_valid_category_web(mocker, config_file):
    mock_spider_cls = mocker.patch(SPIDER_MOD)
    mock_spider_cls.return_value.fetch_and_parse.return_value = [{"title": "t"}]
    runner = CrawlerRunner(config_path=config_file)
    recs = runner.run("static_site")
    assert recs[0].category == "web"
