"""Build the fake warehouse data: python -m tuning seed"""

import random
from datetime import date, timedelta

from tuning import db

SEED = 2025          # fixed seed: the same number always gives the same data
YEAR = 2025          # every shipment date falls in this year (12 monthly partitions)
CUSTOMERS, PRODUCTS = 1000, 500
FULL_ROWS, SMALL_ROWS = 1_000_000, 100_000

REGIONS = ["NA", "EU", "AP", "LA"]
SEGMENTS = ["enterprise", "midmarket", "small", "consumer"]
CATEGORIES = ["Batteries", "Cables", "Chargers", "Cases", "Lamps",
              "Speakers", "Tools", "Toys", "Books", "Kitchen"]
CITIES = [("Reno", "US"), ("Dallas", "US"), ("Atlanta", "US"), ("Seattle", "US"),
          ("Toronto", "CA"), ("Montreal", "CA"), ("Berlin", "DE"), ("Hamburg", "DE"),
          ("Lyon", "FR"), ("Madrid", "ES"), ("Milan", "IT"), ("Leeds", "GB"),
          ("Pune", "IN"), ("Chennai", "IN"), ("Osaka", "JP"), ("Sydney", "AU"),
          ("Lima", "PE"), ("Bogota", "CO"), ("Recife", "BR"), ("Monterrey", "MX")]
WAREHOUSES = len(CITIES)

# Most shipments are delivered. "returned" is rare. A column where one value
# covers 70% of the rows is a bad index candidate (case 10 shows why).
STATUSES = ["delivered", "in_transit", "delayed", "returned"]
STATUS_WEIGHTS = [70, 20, 7, 3]
SHIP_MODES = ["ground", "air", "sea", "express"]
NOTES = ["left at front door", "signed by recipient", "held at local depot",
         "rerouted after weather delay", "delivered to parcel locker", "customs check passed",
         "address corrected by carrier", "second delivery attempt"]
DAYS = [(date(YEAR, 1, 1) + timedelta(days=n)).isoformat() for n in range(365)]

FACT_INSERT = "INSERT INTO fact_shipments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"


# Fill the three small dimension tables. No randomness needed: the values
# follow the id, so they are the same on every run.
def add_dimensions(conn):
    conn.executemany("INSERT INTO dim_customer VALUES (?, ?, ?, ?)", [
        (i, f"Customer {i:04d}", REGIONS[i % 4], SEGMENTS[(i // 4) % 4])
        for i in range(1, CUSTOMERS + 1)])
    conn.executemany("INSERT INTO dim_product VALUES (?, ?, ?)", [
        (i, f"Product {i:03d}", CATEGORIES[i % 10]) for i in range(1, PRODUCTS + 1)])
    conn.executemany("INSERT INTO dim_warehouse VALUES (?, ?, ?)", [
        (i, city, country) for i, (city, country) in enumerate(CITIES, start=1)])


# Make `count` fake shipment rows with ids first_id, first_id + 1, ...
# `rng` is a seeded random generator, so the rows are repeatable.
# The tracking code looks like EU-0001234 (region prefix + the shipment id).
def make_fact_rows(rng, first_id, count):
    rows = []
    for shipment_id in range(first_id, first_id + count):
        rows.append((
            shipment_id,
            rng.choice(DAYS),
            rng.randint(1, CUSTOMERS),
            rng.randint(1, PRODUCTS),
            rng.randint(1, WAREHOUSES),
            rng.choices(STATUSES, STATUS_WEIGHTS)[0],
            rng.choice(SHIP_MODES),
            rng.randint(1, 20),
            rng.randint(500, 250_000),
            f"{rng.choice(REGIONS)}-{shipment_id:07d}",
            rng.choice(NOTES),
        ))
    return rows


# Create the schema and fill it with `rows` fact rows.
# Rows are made and saved in batches of 50,000, so memory stays small and
# executemany does the inserting in one go per batch.
# journal_mode OFF and synchronous OFF skip crash protection. That is fine
# here: if the build is interrupted we just build again.
def build(conn, rows, batch=50_000):
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")
    db.create_schema(conn)
    add_dimensions(conn)
    rng = random.Random(SEED)
    for first_id in range(1, rows + 1, batch):
        conn.executemany(FACT_INSERT, make_fact_rows(rng, first_id, min(batch, rows - first_id + 1)))
    conn.commit()
