"""异常体系测试 — 对齐 TECHNICAL_DESIGN.md §8.1。"""
import pytest

from data_center.core import errors as E

ALL_EXC = [
    E.ContractError,
    E.SourceUnavailableError,
    E.RateLimitError,
    E.ParseError,
    E.NetworkError,
]


@pytest.mark.parametrize("exc_cls", ALL_EXC)
def test_all_inherit_data_center_error(exc_cls):
    assert issubclass(exc_cls, E.DataCenterError)


@pytest.mark.parametrize("exc_cls", ALL_EXC)
def test_raisable_and_catchable_as_base(exc_cls):
    with pytest.raises(E.DataCenterError):
        raise exc_cls("boom")
