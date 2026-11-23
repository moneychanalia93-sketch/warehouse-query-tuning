"""The star schema (one big fact table, three small dimension tables) and the connection."""

import sqlite3

# Star schema: `fact_shipments` holds one row per shipment (the big table).
# The three `dim_` tables describe who, what and where (small lookup tables).
# Foreign keys are written for documentation only: SQLite does not check them
# unless you turn them on, and we skip that so inserts stay fast.
SCHEMA = """
DROP TABLE IF EXISTS fact_shipments;
DROP TABLE IF EXISTS dim_customer;
DROP TABLE IF EXISTS dim_product;
DROP TABLE IF EXISTS dim_warehouse;

CREATE TABLE dim_customer (
    customer_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    region TEXT NOT NULL,
    segment TEXT NOT NULL
);
CREATE TABLE dim_product (
    product_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL
);
CREATE TABLE dim_warehouse (
    warehouse_id INTEGER PRIMARY KEY,
    city TEXT NOT NULL,
    country TEXT NOT NULL
);
CREATE TABLE fact_shipments (
    shipment_id INTEGER PRIMARY KEY,
    ship_date TEXT NOT NULL,
    customer_id INTEGER NOT NULL REFERENCES dim_customer(customer_id),
    product_id INTEGER NOT NULL REFERENCES dim_product(product_id),
    warehouse_id INTEGER NOT NULL REFERENCES dim_warehouse(warehouse_id),
    status TEXT NOT NULL,
    ship_mode TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL,
    tracking_code TEXT NOT NULL,
    notes TEXT NOT NULL
);
"""


# Open the database file. Rows come back as dict-like objects.
# Two settings matter for this lab:
# - cached_statements=0: no cached statements, so a plan is never stale
#   after we create or drop an index on the same connection.
# - automatic_index = OFF: SQLite can quietly build a temporary index in the
#   middle of a query. We switch that off so a missing index shows up as a
#   slow query, which is the thing this lab wants to show.
def connect(path):
    conn = sqlite3.connect(path, cached_statements=0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA automatic_index = OFF")
    return conn


# Drop the old tables (if any) and create empty new ones.
def create_schema(conn):
    conn.executescript(SCHEMA)


# How many rows a table has. The name comes from our own code, never from a user.
def table_count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# Run a list of SQL statements one after the other.
def run_statements(conn, statements):
    for sql in statements:
        conn.execute(sql)


# Drop every index the lab created (their names all start with idx_).
# This puts the tables back to "no extra indexes", so each case starts clean.
# The names come from SQLite's own catalog, not from a user.
def drop_lab_indexes(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'idx%'")
    for name in [row["name"] for row in rows]:
        conn.execute(f"DROP INDEX {name}")
