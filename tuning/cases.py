"""The ten tuning cases. Each case is one slow query, its fix and a plain-words reason.

A case is a dict with these keys:
  name         short id used on the command line
  title        the business question in plain words
  problem      what makes the slow query slow
  fix          the change, in a few words
  slow_sql     the slow query
  fast_sql     the fixed query (sometimes the same text: only the index changes)
  params       values for the ? marks, or a function of the fact-row count
  before       SQL run first, to set up the starting state (e.g. a wrong index)
  change       SQL run after timing the slow query (the index change); [] = rewrite only
  explanation  why it is slow and why the fix works, in plain words

The runner starts every case with no lab indexes, runs `before`, times
`slow_sql`, runs `change`, then times `fast_sql`. Index names start with idx_.
"""

IDX_CUSTOMER = "CREATE INDEX idx_fact_customer ON fact_shipments(customer_id)"
IDX_CUSTOMER_COVER = ("CREATE INDEX idx_fact_customer_cover"
                      " ON fact_shipments(customer_id, ship_date, amount_cents)")
IDX_CUSTOMER_DATE = "CREATE INDEX idx_fact_customer_date ON fact_shipments(customer_id, ship_date)"
IDX_DATE = "CREATE INDEX idx_fact_date ON fact_shipments(ship_date)"
IDX_DATE_FIRST = "CREATE INDEX idx_fact_date_wh ON fact_shipments(ship_date, warehouse_id)"
IDX_WAREHOUSE_FIRST = "CREATE INDEX idx_fact_wh_date ON fact_shipments(warehouse_id, ship_date)"
IDX_PRODUCT = "CREATE INDEX idx_fact_product ON fact_shipments(product_id)"
IDX_STATUS = "CREATE INDEX idx_fact_status ON fact_shipments(status)"
# COLLATE NOCASE matters: SQLite's LIKE ignores upper/lower case, so an index
# can only help LIKE if the index also ignores case.
IDX_TRACKING = "CREATE INDEX idx_fact_tracking ON fact_shipments(tracking_code COLLATE NOCASE)"

# Used by `python -m tuning costs` to add indexes one at a time.
COST_INDEXES = [IDX_CUSTOMER, IDX_DATE, IDX_PRODUCT, IDX_TRACKING, IDX_WAREHOUSE_FIRST, IDX_STATUS]

CASES = [
    {
        "name": "full_scan_filter",
        "title": "Order history for one customer",
        "problem": "no index on customer_id, so SQLite reads every row of the big table",
        "fix": "add an index on customer_id",
        "slow_sql": """
            SELECT shipment_id, ship_date, status, amount_cents
            FROM fact_shipments WHERE customer_id = ?""",
        "fast_sql": """
            SELECT shipment_id, ship_date, status, amount_cents
            FROM fact_shipments WHERE customer_id = ?""",
        "params": (417,),
        "before": [],
        "change": [IDX_CUSTOMER],
        "explanation": (
            "Without an index SQLite must look at every shipment to find the ones for customer 417 "
            "(a full table scan). The index is a sorted list of customer ids with a pointer to each "
            "row, so SQLite jumps straight to the right place. One customer owns about 1 in 1,000 "
            "rows, so the filter is very selective, which is when an index helps most."),
    },
    {
        "name": "function_on_column",
        "title": "Shipments and revenue on one day",
        "problem": "date(ship_date) wraps the column in a function, so the index on ship_date is ignored",
        "fix": "compare the plain column: ship_date = ? (no new index)",
        "slow_sql": """
            SELECT COUNT(*) AS shipments, SUM(amount_cents) AS revenue_cents
            FROM fact_shipments WHERE date(ship_date) = ?""",
        "fast_sql": """
            SELECT COUNT(*) AS shipments, SUM(amount_cents) AS revenue_cents
            FROM fact_shipments WHERE ship_date = ?""",
        "params": ("2025-03-14",),
        "before": [IDX_DATE],
        "change": [],
        "explanation": (
            "An index is sorted by the stored value of ship_date. SQLite cannot look up date(ship_date) "
            "in a list sorted by ship_date, so it ignores the index and scans every row, computing the "
            "function each time. The index was there all along. Writing the condition on the plain "
            "column lets SQLite use it. Rule: keep the column bare on one side of the comparison."),
    },
    {
        "name": "select_star",
        "title": "Date and amount of every shipment for one customer",
        "problem": "SELECT * reads the whole wide row, even though only two columns are needed",
        "fix": "ask for two columns and use a covering index (customer_id, ship_date, amount_cents)",
        "slow_sql": "SELECT * FROM fact_shipments WHERE customer_id = ?",
        "fast_sql": "SELECT ship_date, amount_cents FROM fact_shipments WHERE customer_id = ?",
        "params": (417,),
        "before": [IDX_CUSTOMER],
        "change": ["DROP INDEX idx_fact_customer", IDX_CUSTOMER_COVER],
        "explanation": (
            "The plain customer index finds the rows, but SELECT * then fetches each full row from the "
            "table: eleven columns, including long text. If the index itself also stores the two "
            "columns we want, SQLite answers from the index alone and never touches the table. That is "
            "a covering index. It only works when the query names its columns. Compared results use "
            "only the two requested columns."),
    },
    {
        "name": "like_leading_wildcard",
        "title": "Find shipments whose tracking code starts with EU-00123",
        "problem": "LIKE '%...' starts with a wildcard, so no index can be used",
        "fix": "drop the leading % and index tracking_code (COLLATE NOCASE)",
        "slow_sql": """
            SELECT shipment_id, tracking_code, status
            FROM fact_shipments WHERE tracking_code LIKE '%EU-00123%'""",
        "fast_sql": """
            SELECT shipment_id, tracking_code, status
            FROM fact_shipments WHERE tracking_code LIKE 'EU-00123%'""",
        "params": (),
        "before": [],
        "change": [IDX_TRACKING],
        "explanation": (
            "An index is sorted from the first letter. 'Starts with EU-00123' is easy: jump to EU-00123 "
            "and read forward. '%EU-00123%' means the text could be anywhere, so the sort order is no "
            "help and every row is checked. Every tracking code begins with its region, so the leading "
            "% was never needed and both queries return the same rows. If you truly need 'contains' "
            "search, you need another tool (for example a full-text index)."),
    },
    {
        "name": "missing_join_index",
        "title": "Shipment count and revenue for one product, found by name",
        "problem": "the join column fact_shipments.product_id has no index",
        "fix": "add an index on fact_shipments(product_id)",
        "slow_sql": """
            SELECT p.name, COUNT(*) AS shipments, SUM(f.amount_cents) AS revenue_cents
            FROM dim_product p JOIN fact_shipments f ON f.product_id = p.product_id
            WHERE p.name = ? GROUP BY p.name""",
        "fast_sql": """
            SELECT p.name, COUNT(*) AS shipments, SUM(f.amount_cents) AS revenue_cents
            FROM dim_product p JOIN fact_shipments f ON f.product_id = p.product_id
            WHERE p.name = ? GROUP BY p.name""",
        "params": ("Product 042",),
        "before": [],
        "change": [IDX_PRODUCT],
        "explanation": (
            "The small product table is easy: find 'Product 042' (500 rows). The hard part is the join: "
            "for that product id, find its shipments in the big table. With no index on "
            "fact_shipments.product_id, SQLite reads the whole fact table. Rule of thumb: index the "
            "column on the big side of a join, the foreign key that points at the dimension."),
    },
    {
        "name": "composite_column_order",
        "title": "How many shipments one warehouse sent during March",
        "problem": "the composite index is (ship_date, warehouse_id): the range column comes first",
        "fix": "rebuild the index as (warehouse_id, ship_date): equality column first",
        "slow_sql": """
            SELECT COUNT(*) AS shipments FROM fact_shipments
            WHERE warehouse_id = ? AND ship_date >= ? AND ship_date < ?""",
        "fast_sql": """
            SELECT COUNT(*) AS shipments FROM fact_shipments
            WHERE warehouse_id = ? AND ship_date >= ? AND ship_date < ?""",
        "params": (7, "2025-03-01", "2025-04-01"),
        "before": [IDX_DATE_FIRST],
        "change": ["DROP INDEX idx_fact_date_wh", IDX_WAREHOUSE_FIRST],
        "explanation": (
            "A two-column index is sorted by the first column, then by the second inside each first "
            "value, like a phone book sorted by last name, then first name. With (ship_date, warehouse_id) "
            "SQLite can narrow to March, but inside March the warehouses are mixed, so it reads every "
            "March entry. With (warehouse_id, ship_date) it jumps to warehouse 7, and inside it March is "
            "one block. Put columns tested with = first, and the range column after them."),
    },
    {
        "name": "offset_pagination",
        "title": "Show a page 90% of the way down the shipment list (50 rows per page)",
        "problem": "OFFSET makes SQLite walk past every skipped row before it returns anything",
        "fix": "keyset pagination: WHERE shipment_id > last_seen_id (no new index)",
        "slow_sql": """
            SELECT shipment_id, ship_date, status FROM fact_shipments
            ORDER BY shipment_id LIMIT 50 OFFSET ?""",
        "fast_sql": """
            SELECT shipment_id, ship_date, status FROM fact_shipments
            WHERE shipment_id > ? ORDER BY shipment_id LIMIT 50""",
        "params": lambda rows: (rows * 9 // 10,),
        "before": [],
        "change": [],
        "explanation": (
            "A big OFFSET does not jump (900,000 rows in at the full size). SQLite counts through every "
            "skipped row and throws it away, so the deeper the page, the slower it gets. Keyset "
            "pagination remembers the last id the user saw and asks for ids after it, which the primary "
            "key finds directly. The two queries match here only because ids run 1, 2, 3 with no gaps: "
            "'after id 900000' equals 'skip 900000 rows'. With gaps they would start at different rows."),
    },
    {
        "name": "correlated_subquery",
        "title": "Latest ship date for each enterprise customer in EU",
        "problem": "the subquery runs once per customer, and each run scans the whole fact table",
        "fix": "rewrite: group the fact table once, then join (no new index)",
        "slow_sql": """
            SELECT c.customer_id, c.name,
                   (SELECT MAX(f.ship_date) FROM fact_shipments f
                    WHERE f.customer_id = c.customer_id) AS last_ship
            FROM dim_customer c WHERE c.region = ? AND c.segment = ?
            ORDER BY c.customer_id""",
        "fast_sql": """
            SELECT c.customer_id, c.name, t.last_ship
            FROM dim_customer c
            LEFT JOIN (SELECT customer_id, MAX(ship_date) AS last_ship
                       FROM fact_shipments GROUP BY customer_id) t
                   ON t.customer_id = c.customer_id
            WHERE c.region = ? AND c.segment = ?
            ORDER BY c.customer_id""",
        "params": ("EU", "enterprise"),
        "before": [],
        "change": [],
        "explanation": (
            "A correlated subquery refers to the outer row, so it is repeated for every outer row. "
            "About 60 customers match, so the big table is scanned about 60 times. The rewrite reads the "
            "big table once, builds one answer per customer, and joins it. LEFT JOIN keeps customers with "
            "no shipments, just like the subquery did (it returns NULL for them)."),
    },
    {
        "name": "count_distinct_range",
        "title": "How many different customers shipped in the first quarter",
        "problem": "COUNT(DISTINCT) over a quarter of the big table: scan, then de-duplicate 250,000 values",
        "fix": "ask the small customer table instead (EXISTS) and add index (customer_id, ship_date)",
        "slow_sql": """
            SELECT COUNT(DISTINCT customer_id) AS customers FROM fact_shipments
            WHERE ship_date >= ? AND ship_date < ?""",
        "fast_sql": """
            SELECT COUNT(*) AS customers FROM dim_customer c
            WHERE EXISTS (SELECT 1 FROM fact_shipments f
                          WHERE f.customer_id = c.customer_id
                            AND f.ship_date >= ? AND f.ship_date < ?)""",
        "params": ("2025-01-01", "2025-04-01"),
        "before": [],
        "change": [IDX_CUSTOMER_DATE],
        "explanation": (
            "The slow query reads a quarter of a million rows just to find about a thousand different "
            "customer ids. The fast query turns the question around: for each of the 1,000 customers, "
            "is there at least one shipment in the range? With the (customer_id, ship_date) index each "
            "answer is one quick look, and SQLite stops at the first match. The answers agree only "
            "because every customer in the fact table also exists in dim_customer."),
    },
    {
        "name": "low_selectivity",
        "title": "Revenue per ship mode for delivered shipments",
        "problem": "status = 'delivered' matches about 70% of the rows, so an index on status is a poor idea",
        "fix": "add an index on status (this does NOT help; the lab shows that on purpose)",
        "slow_sql": """
            SELECT ship_mode, COUNT(*) AS shipments, SUM(amount_cents) AS revenue_cents
            FROM fact_shipments WHERE status = ? GROUP BY ship_mode ORDER BY ship_mode""",
        "fast_sql": """
            SELECT ship_mode, COUNT(*) AS shipments, SUM(amount_cents) AS revenue_cents
            FROM fact_shipments WHERE status = ? GROUP BY ship_mode ORDER BY ship_mode""",
        "params": ("delivered",),
        "before": [],
        "change": [IDX_STATUS],
        "explanation": (
            "An index pays off when it lets you skip most of the table. Here 7 rows in 10 match, so "
            "there is almost nothing to skip. Worse, SQLite must hop from the index to the table for "
            "each of the 700,000 matches (ship_mode and amount are not in the index). That is no "
            "cheaper than one straight read of the table, and sometimes it is slower. SQLite picks the "
            "index anyway (running ANALYZE did not change that in my test), so the plan alone does "
            "not warn you: only timing does. The honest result: no gain, maybe a loss, plus extra file "
            "size and slower inserts. Do not index a column like this."),
    },
]


# Find a case by name. Raises ValueError (listing the valid names) if it is unknown.
def get_case(name):
    for case in CASES:
        if case["name"] == name:
            return case
    raise ValueError(f"unknown case '{name}'. Choose from: {', '.join(c['name'] for c in CASES)}")
