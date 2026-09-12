from __future__ import annotations

import unittest

from wikiplant.errors import ValidationError
from wikiplant.storage_metrics import ProviderMetrics, summarize_benchmark


class StorageMetricsTests(unittest.TestCase):
    def test_metrics_are_content_free_and_aggregate_calls(self):
        metric = ProviderMetrics("github", "private-operation-id")
        metric.record_call("read_ref", duration_ms=12.5, bytes_read=40)
        metric.record_call("read_ref", duration_ms=7.5, bytes_read=40, retry=True)
        metric.record_call("update_ref", duration_ms=20, bytes_written=40, conflict=True)
        actual = metric.sanitized()
        self.assertNotIn("operation_id", actual)
        self.assertEqual(actual["calls"], {"read_ref": 2, "update_ref": 1})
        self.assertEqual(actual["total_latency_ms"], 40)
        self.assertEqual(actual["bytes_read"], 80)
        self.assertEqual(actual["conflicts"], 1)
        self.assertEqual(actual["retries"], 1)

    def test_benchmark_reports_median_and_nearest_rank_tail(self):
        samples = []
        for index in range(1, 11):
            metric = ProviderMetrics("google-drive", f"op-{index}")
            metric.record_call("read", duration_ms=float(index), bytes_read=index)
            samples.append(metric)
        summary = summarize_benchmark("google-drive", "five-page-read", samples)
        self.assertEqual(summary["sample_count"], 10)
        self.assertEqual(summary["median_latency_ms"], 5.5)
        self.assertEqual(summary["p95_latency_ms"], 10)

    def test_invalid_metrics_fail_closed(self):
        with self.assertRaises(ValidationError):
            ProviderMetrics("unknown", "op")
        metric = ProviderMetrics("github", "op")
        for kwargs in ({"duration_ms": -1}, {"duration_ms": 1, "bytes_read": -1}):
            with self.assertRaises(ValidationError):
                metric.record_call("read", **kwargs)
        with self.assertRaises(ValidationError):
            summarize_benchmark("github", "read", [])


if __name__ == "__main__":
    unittest.main()
