"""What indexes cost: slower inserts and a bigger file. python -m tuning costs"""

import os
import random
import statistics
import tempfile
import time

from tuning import db
from tuning.cases import COST_INDEXES
from tuning.seed import FACT_INSERT, SEED, make_fact_rows

# (number of indexes, are they created before the rows go in?)
# The last level builds the same six indexes after the load, to compare.
LEVELS = [(0, True), (1, True), (3, True), (len(COST_INDEXES), True), (len(COST_INDEXES), False)]


# Build a fresh database with `index_count` indexes, insert all `data` rows and
# time it. Returns (seconds, file size in bytes).
# index_first=True: the indexes exist before the insert, so every row also
# updates every index. index_first=False: load first, then build the indexes
# (the time to build them is included).
# cache_size = -64000 gives SQLite a 64 MB page cache (the default is about 2 MB).
# With the tiny default cache, random inserts into several indexes keep
# re-reading and re-writing pages, and the cost looks much worse than in a
# normal database server. The README states this.
def insert_once(data, index_count, index_first, folder):
    path = os.path.join(folder, "costs.db")
    conn = db.connect(path)
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA cache_size = -64000")
    db.create_schema(conn)
    indexes = COST_INDEXES[:index_count]
    start = time.perf_counter()
    if index_first:
        db.run_statements(conn, indexes)
    for first in range(0, len(data), 10_000):
        conn.executemany(FACT_INSERT, data[first:first + 10_000])
    conn.commit()
    if not index_first:
        db.run_statements(conn, indexes)
    seconds = time.perf_counter() - start
    conn.close()
    size = os.path.getsize(path)
    os.remove(path)
    return seconds, size


# Measure every level. Time is the median of `repeats` runs. Returns one dict per level.
def measure_costs(rows=100_000, repeats=5, levels=LEVELS):
    data = make_fact_rows(random.Random(SEED), 1, rows)
    results = []
    with tempfile.TemporaryDirectory() as folder:
        for count, index_first in levels:
            runs = [insert_once(data, count, index_first, folder) for _ in range(repeats)]
            seconds = statistics.median(seconds for seconds, _ in runs)
            label = str(count) if index_first else f"{count}, after load"
            results.append({"indexes": label, "rows": rows, "seconds": seconds,
                            "rows_per_second": rows / seconds, "file_mb": runs[0][1] / 1_000_000})
    return results


# The costs table. "Slower" compares the time with the no-index run.
def format_costs(results):
    base = results[0]["seconds"]
    lines = [f"{'indexes':>15}{'insert s':>10}{'rows/s':>11}{'file MB':>10}{'slower':>9}"]
    for r in results:
        lines.append(f"{r['indexes']:>15}{r['seconds']:>10.2f}{r['rows_per_second']:>11,.0f}"
                     f"{r['file_mb']:>10.1f}{r['seconds'] / base:>8.1f}x")
    return "\n".join(lines)
