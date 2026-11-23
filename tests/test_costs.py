import unittest

from tuning import costs


# Tests for the index-cost measurement, on 2,000 rows. We check sizes and
# labels, never how long the inserts took.
class CostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = costs.measure_costs(rows=2000, repeats=1)

    def test_one_result_per_level_with_the_right_labels(self):
        self.assertEqual([r["indexes"] for r in self.results], ["0", "1", "3", "6", "6, after load"])
        self.assertTrue(all(r["seconds"] > 0 and r["rows"] == 2000 for r in self.results))

    def test_more_indexes_make_a_bigger_file(self):
        sizes = [r["file_mb"] for r in self.results]
        self.assertLess(sizes[0], sizes[1])
        self.assertLess(sizes[1], sizes[2])
        self.assertLess(sizes[2], sizes[3])
        lines = costs.format_costs(self.results).splitlines()
        self.assertEqual(len(lines), 6)
        self.assertTrue(lines[1].rstrip().endswith("1.0x"))


if __name__ == "__main__":
    unittest.main()
