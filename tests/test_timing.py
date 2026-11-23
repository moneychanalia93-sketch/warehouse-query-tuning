import unittest
from unittest import mock

from tuning import db, timing


# A stand-in connection that only counts how often a query is run.
class CountingConn:
    def __init__(self):
        self.calls = 0

    def execute(self, sql, params=()):
        self.calls += 1
        return self

    def fetchall(self):
        return []


# Tests for the timing helpers. No absolute times are asserted.
class TimingTests(unittest.TestCase):
    # A tiny in-memory table with 1,000 rows and no index.
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, a INTEGER, b TEXT)")
        self.conn.executemany("INSERT INTO t VALUES (?, ?, ?)", [(i, i % 10, f"x{i}") for i in range(1000)])

    def tearDown(self):
        self.conn.close()

    def test_measure_runs_one_warm_up_plus_the_timed_runs(self):
        conn = CountingConn()
        timing.measure(conn, "SELECT 1", runs=4)
        self.assertEqual(conn.calls, 5)

    def test_measure_returns_the_median_in_milliseconds(self):
        # start/stop pairs: warm-up 0 s, then 1 ms, 100 ms, 2 ms. The median is 2 ms.
        ticks = [0, 0, 0, 0.001, 0, 0.100, 0, 0.002]
        with mock.patch("tuning.timing.time") as fake_time:
            fake_time.perf_counter.side_effect = ticks
            self.assertAlmostEqual(timing.measure(CountingConn(), "SELECT 1", runs=3), 2.0)

    def test_a_slow_warm_up_cuts_the_timed_runs_to_three(self):
        conn = CountingConn()
        ticks = [0, 5.0] + [0, 0.001] * 3
        with mock.patch("tuning.timing.time") as fake_time:
            fake_time.perf_counter.side_effect = ticks
            timing.measure(conn, "SELECT 1", runs=5)
        self.assertEqual(conn.calls, 4)

    def test_speedup_divides_slow_by_fast_and_never_divides_by_zero(self):
        self.assertAlmostEqual(timing.speedup(10.0, 2.0), 5.0)
        self.assertGreater(timing.speedup(10.0, 0.0), 1000)

    def test_verdict_uses_the_two_thresholds(self):
        self.assertEqual(timing.verdict(3.0), "faster")
        self.assertEqual(timing.verdict(timing.FASTER_AT), "faster")
        self.assertEqual(timing.verdict(1.0), "no real change")
        self.assertEqual(timing.verdict(timing.SLOWER_AT), "slower")
        self.assertEqual(timing.verdict(0.3), "slower")

    def test_same_results_true_for_equal_answers_in_any_order(self):
        same, count = timing.same_results(
            self.conn, "SELECT id FROM t WHERE a = 3 ORDER BY id", "SELECT id FROM t WHERE a = 3 ORDER BY id DESC")
        self.assertTrue(same)
        self.assertEqual(count, 100)

    def test_same_results_false_for_different_answers(self):
        same, _ = timing.same_results(self.conn, "SELECT id FROM t WHERE a = 3", "SELECT id FROM t WHERE a = 4")
        self.assertFalse(same)

    def test_same_results_compares_only_the_columns_the_fixed_query_asks_for(self):
        same, _ = timing.same_results(self.conn, "SELECT * FROM t WHERE a = 3", "SELECT id, a FROM t WHERE a = 3")
        self.assertTrue(same)


if __name__ == "__main__":
    unittest.main()
