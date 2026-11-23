"""A local simulation of date partitions: one table per month. python -m tuning partitions

In S3, Hive and Athena a partition is a folder such as sales/year=2025/month=03/.
A query that filters on month reads only that folder and skips the rest. Here a
"partition" is a SQLite table named fact_2025_03. This is only a small imitation
of the idea on one machine. It is not how Redshift or Athena work inside.
"""

import re
from datetime import date, timedelta

from tuning import db
from tuning.seed import YEAR
from tuning.timing import measure, plan_lines

MONTHS = [(YEAR, month) for month in range(1, 13)]
DATE_TEXT = re.compile(r"^\d{4}-\d{2}-\d{2}$")
COVERING_INDEX = "CREATE INDEX idx_fact_date_amount ON fact_shipments(ship_date, amount_cents)"


# The partition table for one date, like "2025-03-14" -> "fact_2025_03".
# The date is checked first, so only digits can ever reach a table name.
def partition_name(ship_date):
    if not DATE_TEXT.match(ship_date):
        raise ValueError(f"not a date like 2025-03-14: {ship_date!r}")
    return f"fact_{ship_date[:4]}_{ship_date[5:7]}"


# Routing: which partitions does the range start <= date < end touch?
# Skipping all the other months is called partition pruning.
def partitions_for_range(start, end):
    first = date.fromisoformat(start)
    last = date.fromisoformat(end) - timedelta(days=1)
    names = [partition_name(f"{year}-{month:02d}-01") for year, month in MONTHS
             if (first.year, first.month) <= (year, month) <= (last.year, last.month)]
    if not names:
        raise ValueError("no stored month falls inside this date range")
    return names


# Copy the fact table into 12 monthly tables (old ones are replaced).
# The partition tables get no index: skipping months is all they do.
def build_partitions(conn):
    for year, month in MONTHS:
        name = partition_name(f"{year}-{month:02d}-01")
        first = date(year, month, 1).isoformat()
        after = (date(year + month // 12, month % 12 + 1, 1)).isoformat()
        conn.execute(f"DROP TABLE IF EXISTS {name}")
        conn.execute(f"CREATE TABLE {name} AS SELECT * FROM fact_shipments"
                     " WHERE ship_date >= ? AND ship_date < ?", (first, after))
    conn.commit()


# The same question asked of the big table: count and revenue in a date range.
BIG_SQL = ("SELECT COUNT(*) AS shipments, SUM(amount_cents) AS revenue_cents FROM fact_shipments"
           " WHERE ship_date >= ? AND ship_date < ?")


# The question for the partitions: one SELECT per month touched, glued with UNION ALL.
# Returns (sql, params). Table names come from partition_name (digits only).
def partition_query(start, end):
    parts = [f"SELECT amount_cents FROM {name} WHERE ship_date >= ? AND ship_date < ?"
             for name in partitions_for_range(start, end)]
    sql = ("SELECT COUNT(*) AS shipments, SUM(amount_cents) AS revenue_cents FROM ("
           + " UNION ALL ".join(parts) + ")")
    return sql, (start, end) * len(parts)


# Time the three ways to answer one date-range question and check they agree:
# 1. big table, no index  2. big table with a covering index  3. monthly partitions
# Returns a dict with the partitions touched, row counts and one entry per way.
def compare_partitions(conn, start, end, runs=5):
    build_partitions(conn)
    touched = partitions_for_range(start, end)
    part_sql, part_params = partition_query(start, end)
    ways = [("big table, no index", BIG_SQL, (start, end), []),
            ("big table + covering index", BIG_SQL, (start, end), [COVERING_INDEX]),
            (f"{len(touched)} monthly partition(s)", part_sql, part_params, [])]
    results = []
    for label, sql, params, setup in ways:
        db.drop_lab_indexes(conn)
        db.run_statements(conn, setup)
        results.append({"label": label, "ms": measure(conn, sql, params, runs),
                        "plan": plan_lines(conn, sql, params),
                        "answer": tuple(conn.execute(sql, params).fetchone())})
    db.drop_lab_indexes(conn)
    return {"touched": touched, "rows_touched": sum(db.table_count(conn, name) for name in touched),
            "rows_total": db.table_count(conn, "fact_shipments"), "ways": results,
            "same_answer": len({way["answer"] for way in results}) == 1}


# The text printed for the partition demo.
def format_partitions(start, end, report):
    lines = [f"Question: shipments and revenue for {start} up to (not including) {end}",
             f"Partitions touched: {', '.join(report['touched'])}",
             f"Rows in those partitions: {report['rows_touched']:,} of {report['rows_total']:,}",
             f"Same answer from all three ways: {'yes' if report['same_answer'] else 'NO'}  "
             f"(shipments, revenue_cents) = {report['ways'][0]['answer']}", ""]
    for way in report["ways"]:
        lines.append(f"{way['label']:<30}{way['ms']:>10.3f} ms")
        lines += [f"    plan: {line}" for line in way["plan"]]
    return "\n".join(lines)
