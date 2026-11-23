import random
import re
import unittest

from tests.helpers import make_db
from tuning import db, seed


# Tests for the fake data: repeatable, the right size, believable values.
class SeedTests(unittest.TestCase):
    # Build one small database (2,000 fact rows) for the whole class.
    @classmethod
    def setUpClass(cls):
        cls.conn = db.connect(make_db(2000))

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def one(self, sql):
        return self.conn.execute(sql).fetchone()[0]

    def test_same_seed_gives_the_same_rows(self):
        first = seed.make_fact_rows(random.Random(seed.SEED), 1, 50)
        second = seed.make_fact_rows(random.Random(seed.SEED), 1, 50)
        self.assertEqual(first, second)

    def test_build_creates_the_requested_number_of_rows(self):
        self.assertEqual(self.one("SELECT COUNT(*) FROM fact_shipments"), 2000)
        self.assertEqual(self.one("SELECT MIN(shipment_id) FROM fact_shipments"), 1)
        self.assertEqual(self.one("SELECT MAX(shipment_id) FROM fact_shipments"), 2000)
        self.assertEqual(self.one("SELECT COUNT(*) FROM dim_customer"), seed.CUSTOMERS)
        self.assertEqual(self.one("SELECT COUNT(*) FROM dim_product"), seed.PRODUCTS)
        self.assertEqual(self.one("SELECT COUNT(*) FROM dim_warehouse"), seed.WAREHOUSES)

    def test_values_stay_inside_their_allowed_sets(self):
        self.assertGreaterEqual(self.one("SELECT MIN(ship_date) FROM fact_shipments"), "2025-01-01")
        self.assertLessEqual(self.one("SELECT MAX(ship_date) FROM fact_shipments"), "2025-12-31")
        statuses = {row[0] for row in self.conn.execute("SELECT DISTINCT status FROM fact_shipments")}
        self.assertTrue(statuses <= set(seed.STATUSES))
        delivered = self.one("SELECT COUNT(*) FROM fact_shipments WHERE status = 'delivered'")
        self.assertGreater(delivered, 2000 * 0.6)

    def test_tracking_code_is_region_dash_id(self):
        for code, shipment_id in self.conn.execute("SELECT tracking_code, shipment_id FROM fact_shipments LIMIT 20"):
            self.assertRegex(code, r"^(NA|EU|AP|LA)-\d{7}$")
            self.assertEqual(int(code[3:]), shipment_id)

    def test_every_fact_row_points_at_a_real_customer_product_and_warehouse(self):
        missing = self.one(
            "SELECT COUNT(*) FROM fact_shipments f"
            " LEFT JOIN dim_customer c ON c.customer_id = f.customer_id"
            " LEFT JOIN dim_product p ON p.product_id = f.product_id"
            " LEFT JOIN dim_warehouse w ON w.warehouse_id = f.warehouse_id"
            " WHERE c.customer_id IS NULL OR p.product_id IS NULL OR w.warehouse_id IS NULL")
        self.assertEqual(missing, 0)

    def test_building_again_replaces_the_old_data(self):
        conn = db.connect(make_db(300))
        seed.build(conn, 500)
        self.assertEqual(db.table_count(conn, "fact_shipments"), 500)
        conn.close()


if __name__ == "__main__":
    unittest.main()
