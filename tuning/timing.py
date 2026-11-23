"""Helpers that time a query, read its plan and compare two queries' results."""

import statistics
import time

# A change counts as "faster" or "slower" only outside this band.
# Timings on a normal computer wobble by 10-20%, so a small gap means nothing.
FASTER_AT = 1.5
SLOWER_AT = 0.8


# Median time in milliseconds for one query, with a warm cache.
# Warm cache: we run the query once first and throw that time away, so the
# file pages are already in memory. Then we time `runs` more runs and take the
# median (the middle value), so one unlucky slow run does not spoil the number.
# shortcut: if the warm-up run takes over 1 second we time only 3 runs, to keep
# the lab quick. Raise this if you need tighter numbers on very slow queries.
def measure(conn, sql, params=(), runs=5):
    start = time.perf_counter()
    conn.execute(sql, params).fetchall()
    if time.perf_counter() - start > 1.0:
        runs = min(runs, 3)
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        conn.execute(sql, params).fetchall()
        times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times)


# What SQLite says it will do, as a list of text lines.
# "SCAN" = read every row. "SEARCH ... USING INDEX" = jump to the matching rows.
def plan_lines(conn, sql, params=()):
    rows = conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    return [row["detail"] for row in rows]


# How many times faster the new query is. Below 1.0 means it got slower.
# A tiny floor on the new time stops a divide-by-zero on a timer that reads 0.
def speedup(slow_ms, fast_ms):
    return slow_ms / max(fast_ms, 0.001)


# One honest word for a speed-up number: faster, slower, or no real change.
def verdict(ratio):
    if ratio >= FASTER_AT:
        return "faster"
    if ratio <= SLOWER_AT:
        return "slower"
    return "no real change"


# Run both queries and check they give the same answer.
# Rows are sorted first, because the same rows may arrive in a different order.
# The fixed query may ask for fewer columns than the slow one (SELECT * versus
# the columns we need), so we compare only the fixed query's columns.
# Returns (same, number_of_rows).
def same_results(conn, slow_sql, fast_sql, params=()):
    cursor = conn.execute(fast_sql, params)
    names = [column[0] for column in cursor.description]
    fast = sorted((tuple(row) for row in cursor.fetchall()), key=repr)
    slow_rows = conn.execute(slow_sql, params).fetchall()
    slow = sorted((tuple(row[name] for name in names) for row in slow_rows), key=repr)
    return slow == fast, len(fast)
