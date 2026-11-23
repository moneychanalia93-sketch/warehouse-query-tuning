"""Run the tuning cases: plan before and after, timing, same-result check, summary table."""

import json
import sqlite3
import sys

from tuning import db
from tuning.cases import CASES, get_case
from tuning.timing import measure, plan_lines, same_results, speedup, verdict


# The values for the ? marks. A case may give a fixed tuple, or a function
# that takes the number of fact rows (used to ask for "a deep page" at any size).
def case_params(case, rows):
    params = case["params"]
    return params(rows) if callable(params) else params


# Run one case from a clean start. Returns a dict of everything we learned.
# Steps: remove lab indexes, set up the "before" state, plan and time the slow
# query, apply the change, plan and time the fixed query, compare results.
def run_case(conn, case, rows, runs=5):
    db.drop_lab_indexes(conn)
    db.run_statements(conn, case["before"])
    params = case_params(case, rows)
    plan_before = plan_lines(conn, case["slow_sql"], params)
    slow_ms = measure(conn, case["slow_sql"], params, runs)
    db.run_statements(conn, case["change"])
    plan_after = plan_lines(conn, case["fast_sql"], params)
    fast_ms = measure(conn, case["fast_sql"], params, runs)
    same, row_count = same_results(conn, case["slow_sql"], case["fast_sql"], params)
    ratio = speedup(slow_ms, fast_ms)
    return {"name": case["name"], "slow_ms": slow_ms, "fast_ms": fast_ms, "speedup": ratio,
            "verdict": verdict(ratio), "same_results": same, "row_count": row_count,
            "plan_before": plan_before, "plan_after": plan_after}


# Pick the cases to run: all of them, or the names given (in the order given).
def select_cases(names):
    return [get_case(name) for name in names] if names else list(CASES)


# The text printed for one finished case: plans, row count, times, verdict.
def format_block(number, total, case, result, explain=False):
    lines = [f"[{number}/{total}] {case['name']} - {case['title']}",
             f"  problem: {case['problem']}", f"  fix:     {case['fix']}"]
    lines += [f"  plan before: {line}" for line in result["plan_before"]]
    lines += [f"  plan after:  {line}" for line in result["plan_after"]]
    same = "yes" if result["same_results"] else "NO - DIFFERENT RESULTS"
    lines.append(f"  rows returned: {result['row_count']:,}   same results: {same}")
    lines.append(f"  slow {result['slow_ms']:.3f} ms   fast {result['fast_ms']:.3f} ms   "
                 f"{result['speedup']:.1f}x   {result['verdict']}")
    if explain:
        lines.append(f"  why: {case['explanation']}")
    return "\n".join(lines)


# The summary table: one line per case.
def format_table(results):
    lines = [f"{'case':<24}{'slow ms':>12}{'fast ms':>12}{'speed-up':>11}  verdict"]
    for r in results:
        lines.append(f"{r['name']:<24}{r['slow_ms']:>12.3f}{r['fast_ms']:>12.3f}"
                     f"{r['speedup']:>10.1f}x  {r['verdict']}")
    return "\n".join(lines)


# Run the chosen cases, print each block and then the table.
# At the end the lab indexes are dropped again, so the database is left clean.
def run_all(conn, names=None, runs=5, explain=False, json_path=None, out=print):
    rows = db.table_count(conn, "fact_shipments")
    cases = select_cases(names)
    out(f"SQLite {sqlite3.sqlite_version}, Python {sys.version.split()[0]}, "
        f"{rows:,} fact rows, median of {runs} warm runs per query\n")
    results = []
    for number, case in enumerate(cases, start=1):
        result = run_case(conn, case, rows, runs)
        results.append(result)
        out(format_block(number, len(cases), case, result, explain) + "\n")
    db.drop_lab_indexes(conn)
    out(format_table(results))
    if json_path:
        with open(json_path, "w", encoding="utf-8") as file:
            json.dump(results, file, indent=2)
    return results
