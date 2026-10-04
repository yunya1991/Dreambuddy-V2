"""模块化开关测试。"""


def test_default_all_off():
    """默认所有层关闭。"""
    from module_switches import ModuleSwitches
    sw = ModuleSwitches()
    assert sw.all_off() is True
    assert sw.L0_observer is False
    assert sw.L1_verifiers is False
    assert sw.L2_aggregation is False
    assert sw.L3_prediction is False


def test_enable_all():
    from module_switches import ModuleSwitches
    sw = ModuleSwitches()
    sw.enable_all()
    assert sw.all_off() is False
    assert sw.L0_observer is True
    assert sw.L1_verifiers is True
    assert sw.L2_aggregation is True
    assert sw.L3_prediction is True


def test_disable_all():
    from module_switches import ModuleSwitches
    sw = ModuleSwitches()
    sw.enable_all()
    sw.disable_all()
    assert sw.all_off() is True


def test_to_dict():
    from module_switches import ModuleSwitches
    sw = ModuleSwitches(L1_verifiers=True)
    d = sw.to_dict()
    assert d["L0_observer"] is False
    assert d["L1_verifiers"] is True
    assert d["L2_aggregation"] is False
    assert d["L3_prediction"] is False


def test_from_env(monkeypatch):
    from module_switches import ModuleSwitches
    monkeypatch.setenv("COGNITIVE_L1", "1")
    monkeypatch.setenv("COGNITIVE_L3", "true")
    sw = ModuleSwitches.from_env()
    assert sw.L1_verifiers is True
    assert sw.L3_prediction is True
    assert sw.L0_observer is False
    assert sw.L2_aggregation is False


def test_independent_switches():
    """各层开关独立，互不影响。"""
    from module_switches import ModuleSwitches
    sw = ModuleSwitches(L0_observer=True, L2_aggregation=True)
    assert sw.L0_observer is True
    assert sw.L1_verifiers is False
    assert sw.L2_aggregation is True
    assert sw.L3_prediction is False
