from __future__ import annotations

from threading import Lock
from time import monotonic
from typing import Callable


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, recovery_timeout: float = 30.0, clock: Callable[[], float] = monotonic):
        if failure_threshold < 1 or recovery_timeout <= 0:
            raise ValueError("熔断阈值必须为正数，恢复等待必须大于 0 秒")
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.clock = clock
        self.lock = Lock()
        self.state = "closed"
        self.failures = 0
        self.opened_at = 0.0
        self.short_circuits = 0

    def before_call(self) -> bool:
        with self.lock:
            if self.state == "closed":
                return True
            if self.state == "half_open":
                self.short_circuits += 1
                return False
            if self.clock() - self.opened_at < self.recovery_timeout:
                self.short_circuits += 1
                return False
            self.state = "half_open"
            return True

    def after_call(self, success: bool) -> None:
        with self.lock:
            if success:
                self.state = "closed"
                self.failures = 0
                return
            self.failures += 1
            if self.state == "half_open" or self.failures >= self.failure_threshold:
                self.state = "open"
                self.opened_at = self.clock()
            else:
                self.state = "closed"

    def snapshot(self) -> dict[str, int | float | str]:
        with self.lock:
            return {
                "state": self.state,
                "consecutive_failures": self.failures,
                "failure_threshold": self.failure_threshold,
                "recovery_timeout_seconds": self.recovery_timeout,
                "short_circuits": self.short_circuits,
            }
