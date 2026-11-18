from dreambuddy_evolution.execution.ledger_guards import LedgerGuards


class _Gw:
    def __init__(self, rows, cooldowns):
        self._rows = rows
        self._cd = cooldowns

    def list_positions(self):
        return self._rows

    def get_cooldown(self, inst_id):
        return self._cd.get(inst_id)

    def is_in_cooldown(self, inst_id, sec):
        return inst_id in self._cd and sec > 0


def _gw():
    rows = [
        {"inst_id": "AMZN-USDT-SWAP", "pos_side": "short", "qty": 5, "source": "bcrm"},
        {"inst_id": "ETHFI-USDT-SWAP", "pos_side": "long", "qty": 12, "source": "evolution"},
        {"inst_id": "BTC-USDT-SWAP", "pos_side": "long", "qty": 0.1, "source": "11-yijing"},
        {"inst_id": "XAU-USDT-SWAP", "pos_side": "long", "qty": 0, "source": "bcrm"},
    ]
    return _Gw(rows, {"NFLX-USDT-SWAP": {"exit_reason": "atr_retrace"}})


def test_has_position_counts_all_open_positions():
    g = LedgerGuards(_gw())
    assert g.has_position("AMZN-USDT-SWAP") is True
    assert g.has_position("ETHFI-USDT-SWAP") is True
    # 11 域/对账写入的仓位同样占仓，重复建仓必须拦截（source 不可作为豁免依据）
    assert g.has_position("BTC-USDT-SWAP") is True
    assert g.has_position("DOGE-USDT-SWAP") is False


def test_has_position_blocks_reconciled_source():
    """回归：22 对账回填的 source 不属于 23 标签，但仍必须拦住重复建仓。"""
    gw = _Gw(
        [{"inst_id": "ETH-USDT-SWAP", "pos_side": "long", "qty": 10.8, "source": "22-reconciled"}],
        {},
    )
    assert LedgerGuards(gw).has_position("ETH-USDT-SWAP") is True


def test_subpool_counts_ignore_closed_and_foreign():
    assert LedgerGuards(_gw()).subpool() == {"count": 2, "long": 1, "short": 1}


def test_cooldown_reads_22_ledger():
    g = LedgerGuards(_gw(), cooldown_sec=1800)
    assert g.cooldown("NFLX-USDT-SWAP") == (True, "atr_retrace")
    assert g.cooldown("AMZN-USDT-SWAP") == (False, "")
    assert LedgerGuards(_gw(), cooldown_sec=0).cooldown("NFLX-USDT-SWAP") == (False, "")


def test_missing_gateway_is_fail_open():
    g = LedgerGuards(None)
    assert g.has_position("ANY") is False
    assert g.cooldown("ANY") == (False, "")
    assert g.subpool() == {"count": 0, "long": 0, "short": 0}
