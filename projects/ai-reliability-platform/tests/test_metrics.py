import unittest

from gateway.metrics import Counter, GatewayMetrics, Gauge, Histogram, Registry


class MetricsTests(unittest.TestCase):
    def test_counter_renders_labels_and_rejects_decrease(self):
        c = Counter("jobs_total", "Jobs.", ("status",))
        c.inc(status="ok")
        c.inc(2, status="ok")
        c.inc(status="failed")
        text = "\n".join(c.render())
        self.assertIn("# TYPE jobs_total counter", text)
        self.assertIn('jobs_total{status="ok"} 3', text)
        self.assertIn('jobs_total{status="failed"} 1', text)
        with self.assertRaises(ValueError):
            c.inc(-1, status="ok")

    def test_label_set_must_match(self):
        c = Counter("x_total", "x", ("a",))
        with self.assertRaises(ValueError):
            c.inc(b="1")

    def test_unlabelled_counter_exports_zero_before_first_use(self):
        self.assertIn("plain_total 0", "\n".join(Counter("plain_total", "p").render()))

    def test_gauge_set_inc_dec(self):
        g = Gauge("depth", "d")
        g.set(5)
        g.inc()
        g.dec(2)
        self.assertEqual(g.value(), 4.0)

    def test_histogram_buckets_are_cumulative(self):
        h = Histogram("lat_seconds", "l", buckets=(0.1, 1.0))
        for v in (0.05, 0.5, 5.0):
            h.observe(v)
        text = "\n".join(h.render())
        self.assertIn('lat_seconds_bucket{le="0.1"} 1', text)
        self.assertIn('lat_seconds_bucket{le="1"} 2', text)
        self.assertIn('lat_seconds_bucket{le="+Inf"} 3', text)
        self.assertIn("lat_seconds_count 3", text)
        self.assertIn("lat_seconds_sum 5.55", text)

    def test_label_values_are_escaped(self):
        c = Counter("e_total", "e", ("v",))
        c.inc(v='a"b\\c')
        self.assertIn(r'e_total{v="a\"b\\c"} 1', "\n".join(c.render()))

    def test_gateway_metrics_render_is_valid_text(self):
        m = GatewayMetrics(Registry())
        m.requests.inc(outcome="ok")
        out = m.registry.render()
        self.assertTrue(out.endswith("\n"))
        self.assertIn("gateway_requests_total", out)


if __name__ == "__main__":
    unittest.main()
