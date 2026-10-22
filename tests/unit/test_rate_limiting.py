"""Spec 003, T008: MemoryRateLimiter (sliding window, locks, bounded memory, thread safety)
and LoginThrottle (attempts counted before the password, progressive lockout)."""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest

from betting_ml.adapters.memory_rate_limiter import MemoryRateLimiter
from betting_ml.application.throttle import LoginThrottle, TooManyAttemptsError
from betting_ml.domain.ports import RateLimiter

MINUTE = timedelta(minutes=1)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def limiter(clock: Clock) -> MemoryRateLimiter:
    return MemoryRateLimiter(clock=clock)


def test_it_implements_the_port(limiter: MemoryRateLimiter) -> None:
    assert isinstance(limiter, RateLimiter)


def test_sliding_window_counts_up_to_the_limit(limiter: MemoryRateLimiter, clock: Clock) -> None:
    for _ in range(3):
        assert limiter.hit("k", 3, MINUTE) is None
        clock.advance(10)
    # 3 events at t=0,10,20; the oldest leaves the window at t=60 (now t=30)
    assert limiter.hit("k", 3, MINUTE) == pytest.approx(30)
    assert limiter.count("k", MINUTE) == 3  # a rejected hit is not counted
    clock.advance(30)
    assert limiter.hit("k", 3, MINUTE) is None
    assert limiter.count("k", MINUTE) == 3


def test_keys_are_independent_and_reset(limiter: MemoryRateLimiter) -> None:
    assert limiter.hit("a", 1, MINUTE) is None
    assert limiter.hit("a", 1, MINUTE) is not None
    assert limiter.hit("b", 1, MINUTE) is None
    limiter.reset("a")
    assert limiter.hit("a", 1, MINUTE) is None


def test_limit_must_be_positive(limiter: MemoryRateLimiter) -> None:
    with pytest.raises(ValueError, match="limit"):
        limiter.hit("k", 0, MINUTE)


def test_locks_expire(limiter: MemoryRateLimiter, clock: Clock) -> None:
    assert limiter.locked_for("k") is None
    limiter.lock("k", timedelta(minutes=5))
    clock.advance(60)
    assert limiter.locked_for("k") == pytest.approx(240)
    clock.advance(240)
    assert limiter.locked_for("k") is None
    limiter.lock("k", MINUTE)
    limiter.reset("k")
    assert limiter.locked_for("k") is None


def test_memory_is_bounded(clock: Clock) -> None:
    limiter = MemoryRateLimiter(clock=clock, max_keys=50)
    limiter.lock("held", timedelta(hours=1))
    for i in range(500):  # spraying keys (IPs)
        limiter.hit(f"ip:{i}", 5, MINUTE)
    assert len(limiter._events) + len(limiter._locks) <= 50
    assert limiter.locked_for("held") is not None  # live locks are never evicted
    clock.advance(7200)
    for i in range(500, 560):
        limiter.hit(f"ip:{i}", 5, MINUTE)
    assert len(limiter._events) + len(limiter._locks) <= 50


def test_hits_are_atomic_across_threads(limiter: MemoryRateLimiter) -> None:
    accepted: list[bool] = []
    barrier = threading.Barrier(16)

    def worker() -> None:
        barrier.wait()
        for _ in range(50):
            accepted.append(limiter.hit("shared", 100, MINUTE) is None)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(accepted) == 100


def _throttle(limiter: MemoryRateLimiter) -> LoginThrottle:
    return LoginThrottle(limiter, max_attempts=5)


def _exhaust(throttle: LoginThrottle, client: str = "1.2.3.4") -> int:
    for _ in range(5):
        throttle.begin(client)
    with pytest.raises(TooManyAttemptsError) as raised:
        throttle.begin(client)
    return raised.value.retry_after


def test_sixth_attempt_in_a_minute_locks_progressively(
    limiter: MemoryRateLimiter, clock: Clock
) -> None:
    throttle = _throttle(limiter)
    assert _exhaust(throttle) == 60
    with pytest.raises(TooManyAttemptsError) as locked:
        throttle.begin("1.2.3.4")
    assert locked.value.retry_after == 60
    clock.advance(61)
    assert _exhaust(throttle) == 300
    clock.advance(301)
    assert _exhaust(throttle) == 900
    clock.advance(901)
    assert _exhaust(throttle) == 900  # capped at the last level
    assert "Vuelve a intentarlo en 900 s" in str(TooManyAttemptsError(899.2))


def test_attempts_spread_over_more_than_a_minute_are_allowed(
    limiter: MemoryRateLimiter, clock: Clock
) -> None:
    throttle = _throttle(limiter)
    for _ in range(20):
        throttle.begin("c")
        clock.advance(13)  # < 5 per minute


def test_success_clears_attempts_and_lockout_level(
    limiter: MemoryRateLimiter, clock: Clock
) -> None:
    throttle = _throttle(limiter)
    assert _exhaust(throttle) == 60
    clock.advance(61)
    throttle.begin("1.2.3.4")
    throttle.succeeded("1.2.3.4")
    assert _exhaust(throttle) == 60  # level back to the first lockout


def test_lockout_level_is_forgotten_after_a_day(limiter: MemoryRateLimiter, clock: Clock) -> None:
    throttle = _throttle(limiter)
    assert _exhaust(throttle) == 60
    clock.advance(61)
    assert _exhaust(throttle) == 300
    clock.advance(24 * 3600 + 1)
    assert _exhaust(throttle) == 60


def test_clients_do_not_lock_each_other(limiter: MemoryRateLimiter) -> None:
    throttle = _throttle(limiter)
    _exhaust(throttle, "attacker")
    throttle.begin("owner")
