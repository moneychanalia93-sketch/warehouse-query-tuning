import unittest

from tests.helpers import make_db
from tuning import db, partitions


# Tests for the monthly-partition demo, on a small database of 5,000 rows.
class PartitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = db.connect(make_db(5000))
        partitions.build_partitions(cls.conn)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_a_date_is_routed_to_its_month_table(self):
        self.assertEqual(partitions.partition_name("2025-03-14"), "fact_2025_03")
        self.assertEqual(partitions.partition_name("2025-12-31"), "fact_2025_12")

    def test_text_that_is_not_a_date_never_reaches_a_table_name(self):
        for bad in ["2025-03", "x; DROP TABLE fact_shipments", "2025-03-14 OR 1=1"]:
            with self.assertRaises(ValueError):
                partitions.partition_name(bad)

    def test_a_range_inside_one_month_touches_one_partition(self):
        self.assertEqual(partitions.partitions_for_range("2025-03-01", "2025-04-01"), ["fact_2025_03"])

    def test_a_range_across_months_touches_each_month_once_and_the_end_is_not_included(self):
        names = partitions.partitions_for_range("2025-02-15", "2025-04-01")
        self.assertEqual(names, ["fact_2025_02", "fact_2025_03"])

    def test_a_range_outside_the_stored_year_is_refused(self):
        with self.assertRaises(ValueError):
            partitions.partitions_for_range("2026-01-01", "2026-02-01")

    def test_the_twelve_partitions_hold_every_row_once_and_only_their_own_month(self):
        total = 0
        for month in range(1, 13):
            name = f"fact_2025_{month:02d}"
            total += db.table_count(self.conn, name)
            low, high = self.conn.execute(f"SELECT MIN(ship_date), MAX(ship_date) FROM {name}").fetchone()
            self.assertTrue(low.startswith(f"2025-{month:02d}") and high.startswith(f"2025-{month:02d}"))
        self.assertEqual(total, db.table_count(self.conn, "fact_shipments"))

    def test_partition_query_gives_the_same_answer_as_the_big_table(self):
        sql, params = partitions.partition_query("2025-02-15", "2025-05-10")
        from_partitions = tuple(self.conn.execute(sql, params).fetchone())
        from_big_table = tuple(self.conn.execute(partitions.BIG_SQL, ("2025-02-15", "2025-05-10")).fetchone())
        self.assertEqual(from_partitions, from_big_table)
        self.assertEqual(len(params), 2 * 4)

    def test_compare_reads_one_partition_and_agrees_with_the_big_table(self):
        report = partitions.compare_partitions(self.conn, "2025-03-01", "2025-04-01", runs=1)
        self.assertTrue(report["same_answer"])
        self.assertEqual(report["touched"], ["fact_2025_03"])
        self.assertLess(report["rows_touched"], report["rows_total"])
        plan = " ".join(report["ways"][2]["plan"])
        self.assertIn("fact_2025_03", plan)
        self.assertNotIn("fact_shipments", plan)


if __name__ == "__main__":
    unittest.main()
