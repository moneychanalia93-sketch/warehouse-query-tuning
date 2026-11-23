import json
import os
import tempfile
import unittest

from tests.helpers import SharedDbTestCase
from tuning import db, runner
from tuning.cases import get_case


# Tests for the runner: the result of one case, the printed text, the cleanup.
class RunnerTests(SharedDbTestCase):
    def test_run_case_reports_plans_timings_and_same_results(self):
        result = runner.run_case(self.conn, get_case("full_scan_filter"), self.rows, runs=1)
        self.assertTrue(result["same_results"])
        self.assertEqual(result["plan_before"], ["SCAN fact_shipments"])
        self.assertIn("idx_fact_customer", result["plan_after"][0])
        self.assertAlmostEqual(result["speedup"], result["slow_ms"] / result["fast_ms"])
        self.assertIn(result["verdict"], ["faster", "slower", "no real change"])

    def test_run_all_prints_every_chosen_case_and_a_table_and_leaves_no_indexes(self):
        lines = []
        runner.run_all(self.conn, ["full_scan_filter", "offset_pagination"], runs=1, out=lines.append)
        text = "\n".join(lines)
        self.assertIn("[1/2] full_scan_filter", text)
        self.assertIn("[2/2] offset_pagination", text)
        self.assertIn("speed-up", text)
        self.assertNotIn("why:", text)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'idx%'").fetchone()[0], 0)

    def test_run_all_with_an_unknown_case_name_raises(self):
        with self.assertRaises(ValueError):
            runner.run_all(self.conn, ["nope"], runs=1, out=lambda text: None)

    def test_results_can_be_written_to_a_json_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "results.json")
            runner.run_all(self.conn, ["select_star"], runs=1, json_path=path, out=lambda text: None)
            with open(path, encoding="utf-8") as file:
                saved = json.load(file)
        self.assertEqual([item["name"] for item in saved], ["select_star"])

    def test_a_case_with_different_results_is_flagged_in_the_text(self):
        result = {"slow_ms": 2.0, "fast_ms": 1.0, "speedup": 2.0, "verdict": "faster",
                  "same_results": False, "row_count": 3, "plan_before": ["SCAN t"], "plan_after": ["SCAN t"]}
        text = runner.format_block(1, 1, get_case("select_star"), result)
        self.assertIn("NO - DIFFERENT RESULTS", text)


if __name__ == "__main__":
    unittest.main()
