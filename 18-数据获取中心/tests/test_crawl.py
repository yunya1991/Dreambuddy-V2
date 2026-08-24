"""Dispatcher _fetch_web + CLI crawl 测试 — 爬虫轨接入。

_fetch_web 走 CrawlerRunner → DataRecord(category=web)；
CLI crawl --config sites.yaml 端到端输出 JSON。
"""
import json

import pytest
from typer.testing import CliRunner

from data_center.cli.app import app
from data_center.core.contract import DataRecord
from data_center.core.dispatcher import DataCenter

RUNNER_MOD = "data_center.crawler.runner.CrawlerRunner"

YAML_CONFIG = """
sites:
  test_site:
    enabled: true
    source: test
    sub_category: page
    url: "http://example.com"
    js_render: false
    selectors:
      item: "a"
      title: "text"
      link: "href"
"""

cli_runner = CliRunner()


def test_fetch_web_routes_to_crawler(mocker, tmp_path):
    config_path = str(tmp_path / "sites.yaml")
    tmp_path.joinpath("sites.yaml").write_text(YAML_CONFIG)

    mock_runner_cls = mocker.patch(RUNNER_MOD)
    mock_runner = mock_runner_cls.return_value
    mock_runner.run.return_value = [
        DataRecord(
            source="test", category="web", sub_category="page",
            timestamp="2026-08-24T12:00:00+08:00",
            metrics={"title": "hello"}, events=[], timeseries=[], raw={},
        )
    ]
    dc = DataCenter()
    recs = dc.fetch("web", config=config_path)

    mock_runner_cls.assert_called_once_with(config_path=config_path)
    mock_runner.run.assert_called_once()
    assert len(recs) == 1
    assert recs[0].category == "web"
    assert recs[0].source == "test"


def test_fetch_web_with_site_name(mocker, tmp_path):
    config_path = str(tmp_path / "sites.yaml")
    tmp_path.joinpath("sites.yaml").write_text(YAML_CONFIG)

    mock_runner_cls = mocker.patch(RUNNER_MOD)
    mock_runner = mock_runner_cls.return_value
    mock_runner.run.return_value = []

    dc = DataCenter()
    dc.fetch("web", config=config_path, site="test_site")

    mock_runner.run.assert_called_once_with("test_site")


def test_cli_crawl_outputs_json(mocker, tmp_path):
    config_path = str(tmp_path / "sites.yaml")
    tmp_path.joinpath("sites.yaml").write_text(YAML_CONFIG)

    mock_runner_cls = mocker.patch(RUNNER_MOD)
    mock_runner = mock_runner_cls.return_value
    mock_runner.run.return_value = [
        DataRecord(
            source="test", category="web", sub_category="page",
            timestamp="2026-08-24T12:00:00+08:00",
            metrics={"title": "hello"}, events=[], timeseries=[], raw={},
        )
    ]

    result = cli_runner.invoke(app, ["crawl", "--config", config_path])
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    assert len(out) == 1
    assert out[0]["source"] == "test"
    assert out[0]["category"] == "web"
    assert out[0]["metrics"]["title"] == "hello"


def test_cli_crawl_with_site_option(mocker, tmp_path):
    config_path = str(tmp_path / "sites.yaml")
    tmp_path.joinpath("sites.yaml").write_text(YAML_CONFIG)

    mock_runner_cls = mocker.patch(RUNNER_MOD)
    mock_runner = mock_runner_cls.return_value
    mock_runner.run.return_value = []

    result = cli_runner.invoke(
        app, ["crawl", "--config", config_path, "--site", "test_site"]
    )
    assert result.exit_code == 0, result.stdout
    mock_runner.run.assert_called_once_with("test_site")


def test_cli_crawl_list_sites(mocker, tmp_path):
    config_path = str(tmp_path / "sites.yaml")
    tmp_path.joinpath("sites.yaml").write_text(YAML_CONFIG)

    mock_runner_cls = mocker.patch(RUNNER_MOD)
    mock_runner = mock_runner_cls.return_value
    mock_runner.list_sites.return_value = ["test_site", "other_site"]

    result = cli_runner.invoke(
        app, ["crawl", "--config", config_path, "--list-sites"]
    )
    assert result.exit_code == 0, result.stdout
    assert "test_site" in result.stdout
    assert "other_site" in result.stdout
