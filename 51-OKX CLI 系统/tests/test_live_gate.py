import pytest
from okx_venue import LIVE_CONFIRM_PHRASE, LiveGate, LiveUnlockDenied


def test_gate_starts_locked():
    gate = LiveGate()
    assert gate.is_unlocked() is False
    assert gate.status()["expires_in_s"] == 0


def test_unlock_requires_exact_phrase():
    gate = LiveGate()
    with pytest.raises(LiveUnlockDenied):
        gate.unlock("unlock live trading")
    with pytest.raises(LiveUnlockDenied):
        gate.unlock(None)
    assert gate.is_unlocked() is False


def test_unlock_then_expire():
    now = [1000.0]
    gate = LiveGate(clock=lambda: now[0])
    gate.unlock(LIVE_CONFIRM_PHRASE, ttl_s=120)
    assert gate.is_unlocked() is True
    now[0] += 121
    assert gate.is_unlocked() is False


def test_ttl_is_clamped():
    now = [0.0]
    gate = LiveGate(clock=lambda: now[0])
    status = gate.unlock(LIVE_CONFIRM_PHRASE, ttl_s=1)
    assert status["expires_in_s"] == 60
    status = gate.unlock(LIVE_CONFIRM_PHRASE, ttl_s=999999)
    assert status["expires_in_s"] == 8 * 3600


def test_lock_revokes_immediately():
    gate = LiveGate()
    gate.unlock(LIVE_CONFIRM_PHRASE)
    assert gate.is_unlocked() is True
    assert gate.lock()["unlocked"] is False
