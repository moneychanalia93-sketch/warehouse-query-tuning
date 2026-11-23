import unittest

from tests.helpers import SharedDbTestCase
from tuning import db
from tuning.cases import CASES, get_case
from tuning.runner import case_params
from tuning.timing import plan_lines, same_results

REQUIRED_KEYS = {"name", "title", "problem", "fix", "slow_sql", "fast_sql", "params",
                 "before", "change", "explanation"}


# Tests for the ten cases on the shared 100,000-row database.
# We check results and query plans. We never check how long anything takes.
class CaseTests(SharedDbTestCase):
    # Run a case's setup, then return (plan before, plan after) as one text each.
    def plans(self, name):
        case = get_case(name)
        params = case_params(case, self.rows)
        db.run_statements(self.conn, case["before"])
        before = " | ".join(plan_lines(self.conn, case["slow_sql"], params))
        db.run_statements(self.conn, case["change"])
        after = " | ".join(plan_lines(self.conn, case["fast_sql"], params))
        return before, after

    def test_there_are_ten_cases_with_unique_names_and_every_key(self):
        self.assertEqual(len(CASES), 10)
        self.assertEqual(len({case["name"] for case in CASES}), 10)
        for case in CASES:
            self.assertEqual(set(case), REQUIRED_KEYS, case["name"])

    def test_slow_and_fast_sql_return_the_same_results_for_every_case(self):
        for case in CASES:
            with self.subTest(case=case["name"]):
                db.drop_lab_indexes(self.conn)
                db.run_statements(self.conn, case["before"] + case["change"])
                same, count = same_results(
                    self.conn, case["slow_sql"], case["fast_sql"], case_params(case, self.rows))
                self.assertTrue(same)
                self.assertGreater(count, 0)

    def test_full_scan_becomes_an_index_search(self):
        before, after = self.plans("full_scan_filter")
        self.assertEqual(before, "SCAN fact_shipments")
        self.assertIn("SEARCH fact_shipments USING INDEX idx_fact_customer", after)

    def test_function_on_column_scans_even_though_the_index_exists(self):
        before, after = self.plans("function_on_column")
        self.assertIn("SCAN fact_shipments", before)
        self.assertIn("SEARCH fact_shipments USING INDEX idx_fact_date (ship_date=?)", after)

    def test_select_star_becomes_a_covering_index_read(self):
        before, after = self.plans("select_star")
        self.assertNotIn("COVERING", before)
        self.assertIn("COVERING INDEX idx_fact_customer_cover", after)

    def test_leading_wildcard_scans_and_prefix_search_uses_the_index(self):
        before, after = self.plans("like_leading_wildcard")
        self.assertEqual(before, "SCAN fact_shipments")
        self.assertIn("SEARCH fact_shipments USING INDEX idx_fact_tracking", after)

    def test_join_without_index_scans_the_fact_table_and_with_index_searches_it(self):
        before, after = self.plans("missing_join_index")
        self.assertIn("SCAN f", before)
        self.assertNotIn("idx_fact_product", before)
        self.assertIn("SEARCH f USING INDEX idx_fact_product (product_id=?)", after)

    def test_wrong_column_order_uses_only_the_date_range_and_right_order_uses_both(self):
        before, after = self.plans("composite_column_order")
        self.assertIn("idx_fact_date_wh (ship_date>? AND ship_date<?)", before)
        self.assertIn("idx_fact_wh_date (warehouse_id=? AND ship_date>? AND ship_date<?)", after)

    def test_offset_scans_and_keyset_searches_the_primary_key(self):
        before, after = self.plans("offset_pagination")
        self.assertEqual(before, "SCAN fact_shipments")
        self.assertIn("SEARCH fact_shipments USING INTEGER PRIMARY KEY (rowid>?)", after)

    def test_correlated_subquery_is_gone_after_the_rewrite(self):
        before, after = self.plans("correlated_subquery")
        self.assertIn("CORRELATED SCALAR SUBQUERY", before)
        self.assertNotIn("CORRELATED SCALAR SUBQUERY", after)
        self.assertIn("MATERIALIZE", after)

    def test_count_distinct_becomes_index_lookups_and_gives_the_same_number_on_a_narrow_range(self):
        before, after = self.plans("count_distinct_range")
        self.assertIn("SCAN fact_shipments", before)
        self.assertIn("COVERING INDEX idx_fact_customer_date (customer_id=? AND ship_date>? AND ship_date<?)", after)
        # A full quarter hits all 1,000 customers, so it cannot tell a wrong rewrite
        # from a right one. One day hits only some customers, so the answers must match exactly.
        case = get_case("count_distinct_range")
        day = ("2025-03-14", "2025-03-15")
        same, _ = same_results(self.conn, case["slow_sql"], case["fast_sql"], day)
        customers = self.conn.execute(case["fast_sql"], day).fetchone()[0]
        self.assertTrue(same)
        self.assertTrue(0 < customers < 1000)

    def test_low_selectivity_index_is_used_even_though_it_is_a_poor_idea(self):
        before, after = self.plans("low_selectivity")
        self.assertIn("SCAN fact_shipments", before)
        self.assertIn("idx_fact_status (status=?)", after)


if __name__ == "__main__":
    unittest.main()
