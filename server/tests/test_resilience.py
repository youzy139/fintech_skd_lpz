from __future__ import annotations

from app.core.resilience import CircuitBreaker


def test_circuit_opens_short_circuits_and_recovers_with_single_probe():
    now = [0.0]
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=5, clock=lambda: now[0])
    assert breaker.before_call()
    breaker.after_call(False)
    assert breaker.before_call()
    breaker.after_call(False)
    assert breaker.snapshot()["state"] == "open"
    assert not breaker.before_call()
    assert breaker.snapshot()["short_circuits"] == 1
    now[0] = 6
    assert breaker.before_call()
    assert breaker.snapshot()["state"] == "half_open"
    assert not breaker.before_call()
    breaker.after_call(True)
    assert breaker.snapshot()["state"] == "closed"
    assert breaker.snapshot()["consecutive_failures"] == 0


def test_failed_half_open_probe_reopens_circuit():
    now = [0.0]
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=2, clock=lambda: now[0])
    breaker.before_call()
    breaker.after_call(False)
    now[0] = 3
    assert breaker.before_call()
    breaker.after_call(False)
    assert breaker.snapshot()["state"] == "open"
    now[0] = 4
    assert not breaker.before_call()
