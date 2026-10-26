import unittest

from gateway.limits import BudgetTracker, TenantRateLimiter
from gateway.resilience import CircuitState
from gateway.router import AllProvidersFailed, BudgetExceeded, RateLimited
from tests.helpers import FakeClock, make_gateway


class GatewayFlowTests(unittest.TestCase):
    def test_happy_path_uses_primary(self):
        gw, primary, fallback, _, metrics = make_gateway()
        result = gw.chat("t1", "hello world")
        self.assertEqual((result.outcome, result.provider), ("ok", "primary"))
        self.assertEqual((primary.calls, fallback.calls), (1, 0))
        self.assertEqual(metrics.requests.value(outcome="ok"), 1)

    def test_identical_request_is_served_from_cache(self):
        gw, primary, _, _, metrics = make_gateway()
        gw.chat("t1", "same prompt")
        second = gw.chat("t1", "same prompt")
        self.assertEqual(second.outcome, "cached")
        self.assertEqual(primary.calls, 1)
        self.assertEqual(metrics.cache_events.value(event="hit"), 1)

    def test_retries_primary_before_falling_back(self):
        gw, primary, fallback, _, _ = make_gateway(primary="fail", max_attempts=3)
        result = gw.chat("t1", "hi")
        self.assertEqual((result.outcome, result.provider), ("degraded", "fallback"))
        self.assertEqual(primary.calls, 3)
        self.assertEqual(fallback.calls, 1)

    def test_breaker_opens_and_primary_is_skipped(self):
        gw, primary, fallback, _, metrics = make_gateway(primary="fail", max_attempts=1)
        for i in range(3):  # threshold = 3 consecutive failures
            gw.chat("t1", f"prompt {i}")
        self.assertIs(gw.slots[0].breaker.state, CircuitState.OPEN)
        calls_when_open = primary.calls
        for i in range(5):
            result = gw.chat("t1", f"after open {i}")
            self.assertEqual(result.outcome, "degraded")
        self.assertEqual(primary.calls, calls_when_open, "an open circuit must stop traffic to the primary")
        self.assertGreaterEqual(metrics.provider_calls.value(provider="primary", result="circuit_open"), 5)
        self.assertEqual(metrics.circuit_state.value(provider="primary"), 0.0)  # gauge only wired by server

    def test_primary_recovers_through_half_open_probe(self):
        gw, primary, _, clock, _ = make_gateway(primary="fail", max_attempts=1)
        for i in range(3):
            gw.chat("t1", f"p{i}")
        primary.mode = "ok"
        clock.advance(10)  # recovery_timeout
        result = gw.chat("t1", "probe me")
        self.assertEqual((result.outcome, result.provider), ("ok", "primary"))
        self.assertIs(gw.slots[0].breaker.state, CircuitState.CLOSED)

    def test_everything_down_returns_503_class_error(self):
        gw, *_, metrics = make_gateway(primary="fail", fallback="fail", max_attempts=2)
        with self.assertRaises(AllProvidersFailed):
            gw.chat("t1", "hi")
        self.assertEqual(metrics.requests.value(outcome="failed"), 1)

    def test_rejected_request_is_not_retried_and_does_not_trip_breaker(self):
        gw, primary, fallback, _, _ = make_gateway(primary="reject", max_attempts=3)
        result = gw.chat("t1", "hi")  # primary rejects -> fallback answers
        self.assertEqual(primary.calls, 1)
        self.assertEqual(result.provider, "fallback")
        self.assertIs(gw.slots[0].breaker.state, CircuitState.CLOSED)

    def test_rate_limit_is_per_tenant(self):
        clock = FakeClock()
        gw, *_ = make_gateway(limiter=TenantRateLimiter(rate=0.0001, burst=1, clock=clock))
        gw.chat("noisy", "one")
        with self.assertRaises(RateLimited):
            gw.chat("noisy", "two")
        gw.chat("quiet", "one")  # unaffected

    def test_token_budget_blocks_overspend(self):
        gw, *_ = make_gateway(budget=BudgetTracker(10, 3600))
        gw.chat("t1", "a b c d e f")  # 6 in + 5 out = 11 tokens, crosses the limit
        with self.assertRaises(BudgetExceeded):
            gw.chat("t1", "another one")

    def test_ready_reflects_provider_availability(self):
        gw, *_ = make_gateway(primary="fail", fallback="fail", max_attempts=1)
        self.assertTrue(gw.ready())
        for i in range(3):
            with self.assertRaises(AllProvidersFailed):
                gw.chat("t1", f"x{i}")
        self.assertFalse(gw.ready())

    def test_request_deadline_caps_total_work(self):
        gw, primary, fallback, _, _ = make_gateway(
            primary="fail", fallback="fail", max_attempts=10, request_timeout=0.05, retry_base=0.04
        )
        with self.assertRaises(AllProvidersFailed):
            gw.chat("t1", "slow")
        self.assertLess(primary.calls + fallback.calls, 10)


if __name__ == "__main__":
    unittest.main()
