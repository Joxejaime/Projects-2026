import random
import unittest

from gateway.limits import BudgetTracker, TenantRateLimiter, TokenBucket
from gateway.providers import ProviderError, ProviderRejected
from gateway.resilience import CircuitBreaker, CircuitState, call_with_retries
from tests.helpers import FakeClock


class CircuitBreakerTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.changes = []
        self.cb = CircuitBreaker(
            "p",
            failure_threshold=3,
            recovery_timeout=10,
            clock=self.clock,
            on_state_change=lambda n, o, new: self.changes.append((o.name, new.name)),
        )

    def trip(self):
        for _ in range(3):
            self.assertTrue(self.cb.allow())
            self.cb.record_failure()

    def test_opens_after_consecutive_failures(self):
        self.trip()
        self.assertIs(self.cb.state, CircuitState.OPEN)
        self.assertFalse(self.cb.allow())
        self.assertEqual(self.changes, [("CLOSED", "OPEN")])

    def test_success_resets_failure_count(self):
        for _ in range(2):
            self.cb.allow()
            self.cb.record_failure()
        self.cb.allow()
        self.cb.record_success()
        for _ in range(2):
            self.cb.allow()
            self.cb.record_failure()
        self.assertIs(self.cb.state, CircuitState.CLOSED)

    def test_half_open_probe_success_closes(self):
        self.trip()
        self.clock.advance(10)
        self.assertTrue(self.cb.allow())  # the probe
        self.assertIs(self.cb.state, CircuitState.HALF_OPEN)
        self.assertFalse(self.cb.allow())  # only one probe at a time
        self.cb.record_success()
        self.assertIs(self.cb.state, CircuitState.CLOSED)

    def test_half_open_probe_failure_reopens_and_restarts_timer(self):
        self.trip()
        self.clock.advance(10)
        self.cb.allow()
        self.cb.record_failure()
        self.assertIs(self.cb.state, CircuitState.OPEN)
        self.clock.advance(9)
        self.assertFalse(self.cb.allow())
        self.clock.advance(1)
        self.assertTrue(self.cb.allow())

    def test_available_is_non_mutating(self):
        self.trip()
        self.assertFalse(self.cb.available())
        self.clock.advance(10)
        self.assertTrue(self.cb.available())
        self.assertIs(self.cb.state, CircuitState.OPEN)  # still open until a real call


class RetryTests(unittest.TestCase):
    def test_retries_then_succeeds(self):
        clock, calls = FakeClock(), {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ProviderError("transient")
            return "done"

        result = call_with_retries(flaky, attempts=3, clock=clock, sleep=clock.sleep, rng=random.Random(1))
        self.assertEqual((result, calls["n"]), ("done", 3))

    def test_non_retryable_error_fails_fast(self):
        calls = {"n": 0}

        def rejected():
            calls["n"] += 1
            raise ProviderRejected("nope")

        with self.assertRaises(ProviderRejected):
            call_with_retries(rejected, attempts=5, sleep=lambda s: None)
        self.assertEqual(calls["n"], 1)

    def test_gives_up_when_attempts_exhausted(self):
        calls = {"n": 0}

        def always_fails():
            calls["n"] += 1
            raise ProviderError("down")

        with self.assertRaises(ProviderError):
            call_with_retries(always_fails, attempts=3, sleep=lambda s: None)
        self.assertEqual(calls["n"], 3)

    def test_respects_overall_deadline(self):
        clock, calls = FakeClock(), {"n": 0}

        def always_fails():
            calls["n"] += 1
            raise ProviderError("down")

        with self.assertRaises(ProviderError):
            # deadline is "now": any backoff sleep would overshoot, so no retry happens
            call_with_retries(always_fails, attempts=5, deadline=clock(), clock=clock, sleep=clock.sleep)
        self.assertEqual(calls["n"], 1)

    def test_backoff_is_bounded_by_cap(self):
        delays = []
        calls = {"n": 0}

        def always_fails():
            calls["n"] += 1
            raise ProviderError("down")

        with self.assertRaises(ProviderError):
            call_with_retries(
                always_fails,
                attempts=8,
                base_delay=1.0,
                max_delay=2.0,
                sleep=delays.append,
                rng=random.Random(3),
            )
        self.assertEqual(len(delays), 7)
        self.assertTrue(all(0 <= d <= 2.0 for d in delays))


class LimitTests(unittest.TestCase):
    def test_token_bucket_refills(self):
        clock = FakeClock()
        bucket = TokenBucket(rate=1, capacity=2, clock=clock)
        self.assertTrue(bucket.allow())
        self.assertTrue(bucket.allow())
        self.assertFalse(bucket.allow())
        clock.advance(1)
        self.assertTrue(bucket.allow())

    def test_limiter_isolates_tenants_and_bounds_memory(self):
        clock = FakeClock()
        limiter = TenantRateLimiter(rate=0.001, burst=1, max_tenants=2, clock=clock)
        self.assertTrue(limiter.allow("a"))
        self.assertFalse(limiter.allow("a"))
        self.assertTrue(limiter.allow("b"))
        limiter.allow("c")  # evicts the least recently used tenant ("a")
        self.assertEqual(len(limiter._buckets), 2)

    def test_budget_window_resets(self):
        clock = FakeClock()
        budget = BudgetTracker(100, window_seconds=60, clock=clock)
        budget.charge("t", 100)
        self.assertFalse(budget.has_budget("t"))
        self.assertTrue(budget.has_budget("other"))
        clock.advance(60)
        self.assertTrue(budget.has_budget("t"))


if __name__ == "__main__":
    unittest.main()
