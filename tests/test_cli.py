import contextlib
import io
import os
import tempfile
import unittest

from tuning import cli


# Tests for the command line. Each test works in its own temporary folder.
class CliTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.folder.name, "cli.db")

    def tearDown(self):
        self.folder.cleanup()

    # Run the CLI with these arguments and return everything it printed.
    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(list(args))
        return out.getvalue()

    def test_seed_builds_the_database_and_reports_the_row_counts(self):
        text = self.run_cli("seed", "--db", self.db_path, "--rows", "1500")
        self.assertIn("fact_shipments: 1,500 rows", text)
        self.assertIn("dim_customer: 1,000 rows", text)
        self.assertTrue(os.path.exists(self.db_path))

    def test_run_on_a_missing_database_says_to_seed_first_and_creates_no_file(self):
        with self.assertRaisesRegex(SystemExit, "python -m tuning seed"):
            self.run_cli("run", "--db", self.db_path)
        self.assertFalse(os.path.exists(self.db_path))

    def test_run_prints_the_table_for_the_chosen_case_and_rejects_an_unknown_one(self):
        self.run_cli("seed", "--db", self.db_path, "--rows", "1500")
        text = self.run_cli("run", "--db", self.db_path, "--case", "full_scan_filter", "--runs", "1")
        self.assertIn("full_scan_filter", text)
        self.assertIn("same results: yes", text)
        self.assertNotIn("why:", text)
        explained = self.run_cli("run", "--db", self.db_path, "--case", "select_star", "--runs", "1", "--explain")
        self.assertIn("why: The plain customer index", explained)
        with self.assertRaisesRegex(SystemExit, "unknown case"):
            self.run_cli("run", "--db", self.db_path, "--case", "nope")

    def test_partitions_command_prints_the_partitions_it_touched(self):
        self.run_cli("seed", "--db", self.db_path, "--rows", "1500")
        text = self.run_cli("partitions", "--db", self.db_path, "--runs", "1")
        self.assertIn("Partitions touched: fact_2025_03", text)
        self.assertIn("Same answer from all three ways: yes", text)


if __name__ == "__main__":
    unittest.main()
