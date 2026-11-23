"""The command line: python -m tuning seed | run | costs | partitions"""

import argparse
import os
import time

from tuning import costs, db, partitions, runner, seed

DEFAULT_DB = "warehouse.db"


# Describe the four commands and their options.
def build_parser():
    parser = argparse.ArgumentParser(prog="python -m tuning", description="SQL query tuning lab")
    commands = parser.add_subparsers(dest="command", required=True)

    seed_cmd = commands.add_parser("seed", help="build the fake warehouse database")
    seed_cmd.add_argument("--db", default=DEFAULT_DB)
    seed_cmd.add_argument("--rows", type=int, default=seed.FULL_ROWS, help="fact rows (default 1,000,000)")
    seed_cmd.add_argument("--small", action="store_true", help="100,000 rows (the size the tests use)")

    run_cmd = commands.add_parser("run", help="run the tuning cases")
    run_cmd.add_argument("--db", default=DEFAULT_DB)
    run_cmd.add_argument("--case", action="append", help="run only this case (repeat for more)")
    run_cmd.add_argument("--runs", type=int, default=5, help="timed runs per query (default 5)")
    run_cmd.add_argument("--explain", action="store_true", help="print the plain-words explanation")
    run_cmd.add_argument("--json", help="also write the results to this JSON file")

    costs_cmd = commands.add_parser("costs", help="measure what indexes cost on insert")
    costs_cmd.add_argument("--rows", type=int, default=100_000)

    part_cmd = commands.add_parser("partitions", help="monthly partitions demo")
    part_cmd.add_argument("--db", default=DEFAULT_DB)
    part_cmd.add_argument("--start", default="2025-03-01", help="first date (included)")
    part_cmd.add_argument("--end", default="2025-04-01", help="end date (not included)")
    part_cmd.add_argument("--runs", type=int, default=5)
    return parser


# Open a database that must already exist. sqlite3 would quietly create an
# empty file for a wrong name, so we check first and say what to do.
def open_existing(path):
    if not os.path.exists(path):
        raise SystemExit(f"{path} not found. Build it first: python -m tuning seed")
    return db.connect(path)


# `seed`: delete any old file, build the schema and rows, print what we made.
def command_seed(args):
    rows = seed.SMALL_ROWS if args.small else args.rows
    if os.path.exists(args.db):
        os.remove(args.db)
    start = time.perf_counter()
    conn = db.connect(args.db)
    seed.build(conn, rows)
    for table in ("dim_customer", "dim_product", "dim_warehouse"):
        print(f"{table}: {db.table_count(conn, table):,} rows")
    print(f"fact_shipments: {db.table_count(conn, 'fact_shipments'):,} rows")
    conn.close()
    print(f"Built {args.db} ({os.path.getsize(args.db) / 1_000_000:.1f} MB) "
          f"in {time.perf_counter() - start:.1f} s")


# `run`: run the cases against an existing database.
def command_run(args):
    conn = open_existing(args.db)
    try:
        runner.run_all(conn, args.case, args.runs, args.explain, args.json)
    except ValueError as error:
        raise SystemExit(str(error))
    finally:
        conn.close()


# `costs`: insert speed and file size with 0, 1, 3 and 6 indexes.
def command_costs(args):
    print(f"Inserting {args.rows:,} rows into a new database (median of 5 runs each)\n")
    print(costs.format_costs(costs.measure_costs(args.rows)))


# `partitions`: build monthly tables and compare three ways to read one range.
def command_partitions(args):
    conn = open_existing(args.db)
    try:
        report = partitions.compare_partitions(conn, args.start, args.end, args.runs)
    except ValueError as error:
        raise SystemExit(str(error))
    finally:
        conn.close()
    print(partitions.format_partitions(args.start, args.end, report))


# Read the command line and run the chosen command.
def main(argv=None):
    args = build_parser().parse_args(argv)
    {"seed": command_seed, "run": command_run, "costs": command_costs,
     "partitions": command_partitions}[args.command](args)
