# warehouse-query-tuning

A command-line tuning lab for SQL. It builds a fake sales and shipments warehouse in SQLite (one big fact table with 1,000,000 rows and three small dimension tables), then runs ten slow queries. For each one it shows the query plan, applies a fix, shows the plan again, checks that both versions return the same rows, and measures the real speed-up.

It uses only the Python standard library (`sqlite3`, `json`, `time`, `statistics`, `random`, `argparse`, `unittest`). There is nothing to install. Python 3.13 was used; any recent Python 3 should work.

> Built with AI assistance (Kiro). I designed the rules, reviewed the code, and ran the tests.
> This is a learning project. It has not been used in production.

## What it does

- **`seed`** builds a star-style schema: `fact_shipments` (1,000,000 rows, fixed random seed, so the data is the same every time) plus `dim_customer`, `dim_product` and `dim_warehouse`. A 100,000-row mode is used by the tests.
- **`run`** goes through ten cases. Each case has a slow query, a fixed query, the schema change (a new index, or a rewrite), and a plain-words explanation. It prints `EXPLAIN QUERY PLAN` before and after, the median time of warm runs, whether the results match, and a table.
- **`costs`** measures what indexes cost: slower inserts and a bigger file.
- **`partitions`** compares one big table with monthly tables (a local imitation of date partitions).

One case is there to show an index that does **not** help (`low_selectivity`). The lab reports it as "no real change" instead of hiding it.

## Run it (3 commands)

Run these from the project folder. If `python` is not on your PATH, use `py` or the full path to `python.exe`.

```powershell
python -m tuning seed         # builds warehouse.db with 1,000,000 fake shipments (about 10 seconds)
python -m tuning run          # runs the ten cases (about 2 minutes at 1,000,000 rows)
python -m unittest discover -s tests -t .   # runs the tests (about 6 seconds)
```

Real output of the first command:

```
dim_customer: 1,000 rows
dim_product: 500 rows
dim_warehouse: 20 rows
fact_shipments: 1,000,000 rows
Built warehouse.db (84.0 MB) in 8.1 s
```

More commands:

```powershell
python -m tuning seed --small                       # 100,000 rows, builds in about a second
python -m tuning run --case offset_pagination --explain   # one case, with the plain-words reason
python -m tuning run --runs 9 --json results.json   # more timed runs, and save the numbers
python -m tuning costs                              # insert speed and file size with 0 to 6 indexes
python -m tuning partitions --start 2025-02-15 --end 2025-04-15
```

`run` adds and drops indexes while it works, and it removes them all at the end, so `warehouse.db` is left in its starting state. Delete `warehouse.db` to start fresh.

## The ten cases

| # | Case | Business question | What makes it slow | The fix |
|---|---|---|---|---|
| 1 | `full_scan_filter` | Order history for one customer | no index on `customer_id`: full table scan | add an index |
| 2 | `function_on_column` | Shipments on one day | `date(ship_date) = ?` hides the column from the index | compare the bare column (no new index) |
| 3 | `select_star` | Date and amount for one customer | `SELECT *` reads the whole wide row | name two columns, use a covering index |
| 4 | `like_leading_wildcard` | Tracking codes starting with `EU-00123` | `LIKE '%EU-00123%'` cannot use an index | drop the leading `%`, index with `COLLATE NOCASE` |
| 5 | `missing_join_index` | Count and revenue for one product | join column on the big table has no index | add an index on `product_id` |
| 6 | `composite_column_order` | One warehouse, one month | index is `(ship_date, warehouse_id)`: range column first | rebuild as `(warehouse_id, ship_date)` |
| 7 | `offset_pagination` | A page 90% of the way down a list | `OFFSET` walks past every skipped row | keyset: `WHERE shipment_id > ?` (no new index) |
| 8 | `correlated_subquery` | Latest ship date per customer | subquery repeats once per customer | group once, then join (no new index) |
| 9 | `count_distinct_range` | Distinct customers in a quarter | `COUNT(DISTINCT)` over 250,000 rows | ask the small table with `EXISTS` and add an index |
| 10 | `low_selectivity` | Revenue for delivered shipments | `status = 'delivered'` matches 70% of rows | add an index on `status` (**does not help**) |

## Real results

Full run on a Windows laptop (Python 3.13.5, SQLite 3.49.1, 1,000,000 fact rows). Times are the **median of 5 warm runs** in milliseconds. "Warm" means each query runs once first and that run is thrown away, so the file is already in memory. Slow queries that take over a second get 3 timed runs instead of 5, to keep the lab quick.

I ran the full lab three times. The first run gives the milliseconds. The last three columns show the speed-up from each run, to show how much the numbers move.

| Case | Slow (ms) | Fast (ms) | Run 1 | Run 2 | Run 3 | Verdict |
|---|---:|---:|---:|---:|---:|---|
| `full_scan_filter` | 103.1 | 6.0 | 17.1x | 18.2x | 19.4x | faster |
| `function_on_column` | 306.1 | 15.9 | 19.3x | 16.3x | 11.6x | faster |
| `select_star` | 14.4 | 0.7 | 20.1x | 10.5x | 16.2x | faster |
| `like_leading_wildcard` | 285.3 | 0.096 | 2,974.7x | 1,461.0x | 1,104.8x | faster |
| `missing_join_index` | 418.3 | 15.4 | 27.2x | 43.6x | 51.5x | faster |
| `composite_column_order` | 6.2 | 0.5 | 12.4x | 18.0x | 18.9x | faster |
| `offset_pagination` | 124.3 | 0.2 | 625.8x | 945.5x | 937.5x | faster |
| `correlated_subquery` | 10,104.6 | 699.1 | 14.5x | 15.6x | 14.4x | faster |
| `count_distinct_range` | 217.2 | 4.6 | 46.8x | 43.2x | 65.6x | faster |
| `low_selectivity` | 568.8 | 630.5 | 0.9x | 1.1x | 0.6x | no gain, can be slower |
How to read it, honestly:

- The speed-up numbers move a lot between runs, especially when the fast query takes under a millisecond. Trust the order of magnitude, not the decimals.
- `low_selectivity` is the case where the index does not pay. Seven rows in ten match, so there is almost nothing to skip. In three full runs at 1,000,000 rows it gave 0.9x, 1.1x and 0.6x: sometimes even, sometimes clearly slower (at 100,000 rows it was 0.6x too). Never a gain, and the index still costs space and insert time. The verdict column says 
o real change when the ratio is between 0.8x and 1.5x, and slower below 0.8x, so the third run was labelled slower.
- `like_leading_wildcard` is large because the fixed query touches 27 rows. The speed-up is real, and it is also the most flattering number in the table.
- Cases 2, 7 and 8 need no new index. A better query was enough.

### What an index costs

`python -m tuning costs` inserts 100,000 rows into a new database with 0, 1, 3 and 6 indexes (median of 5 runs). The last row builds the same six indexes after loading the rows.

```
        indexes  insert s     rows/s   file MB   slower
              0      0.12    835,661       8.4     1.0x
              1      0.20    505,288       9.6     1.7x
              3      0.54    184,430      12.8     4.5x
              6      1.07     93,094      19.2     9.0x
  6, after load      0.55    182,042      18.1     4.6x
```

Every index must be updated on every insert, so six indexes made inserts about 9 to 10 times slower in two runs, and the file more than twice as big (8.4 MB to 19.2 MB). Building the indexes once after the load was about twice as fast as maintaining them row by row. This run gives SQLite a 64 MB page cache. With SQLite's small default cache (about 2 MB) the cost looked much worse (about 59x for six indexes in one early run), because the index pages kept being swapped out. A server database has a bigger cache, so I used the fairer setting.

### Partitions (a local simulation)

`python -m tuning partitions` copies the fact table into 12 monthly tables (`fact_2025_01` to `fact_2025_12`) and asks one question three ways: shipments and revenue for March 2025.

```
Partitions touched: fact_2025_03
Rows in those partitions: 85,092 of 1,000,000
Same answer from all three ways: yes  (shipments, revenue_cents) = (85092, 10662852087)

big table, no index              100.986 ms
    plan: SCAN fact_shipments
big table + covering index         7.336 ms
    plan: SEARCH fact_shipments USING COVERING INDEX idx_fact_date_amount (ship_date>? AND ship_date<?)
1 monthly partition(s)            18.855 ms
    plan: SCAN fact_2025_03
```

The idea is the same as date partitions in S3, Hive and Athena: data is split into folders such as `year=2025/month=03/`, and a query that filters on month reads only that folder and skips the rest (partition pruning). Here the "folders" are SQLite tables. **This is a simulation on one machine, not a copy of how Redshift or Athena work.** Two honest points from the numbers:

- Reading one monthly table (about 19 ms) was about 5 times faster than scanning the whole table (about 101 ms).
- In SQLite a good index (about 7 ms) beat the partitions. Partitions matter most where there are no indexes, such as files in object storage, because skipping files is the main way to read less data. A query that crosses months touches several partitions and loses part of the gain (the Feb 15 to Apr 15 run: 59 ms for three partitions versus 21 ms for the indexed table).

## How to read a query plan

Put `EXPLAIN QUERY PLAN` in front of a query and SQLite tells you how it will run it. The lab does this for you. The words that matter:

| You see | It means |
|---|---|
| `SCAN fact_shipments` | reads every row of the table (a full table scan). Slow on a big table. |
| `SEARCH fact_shipments USING INDEX idx_fact_customer (customer_id=?)` | jumps through an index straight to the rows where `customer_id` matches. |
| `SEARCH ... USING COVERING INDEX ...` | the index alone holds every column the query needs, so the table is never touched. |
| `SEARCH ... USING INTEGER PRIMARY KEY (rowid>?)` | uses the table's own primary key order. |
| `(customer_id=? AND ship_date>? AND ship_date<?)` | which index columns were used, in order. A column missing from this list was not used to narrow the search. |
| `SEARCH f` with nothing after it | no index named, so no index is used. In case 8 SQLite prints this for a subquery that still reads the whole table every time. Look for the word `USING`. |
| `USE TEMP B-TREE FOR GROUP BY` | SQLite has to sort or group rows in a temporary structure. |
| `CORRELATED SCALAR SUBQUERY` | a subquery that runs again for every outer row. |

Real example, case 1. Before the index:

```
SCAN fact_shipments
```

After `CREATE INDEX idx_fact_customer ON fact_shipments(customer_id)`:

```
SEARCH fact_shipments USING INDEX idx_fact_customer (customer_id=?)
```

Read it as: before, check all 1,000,000 rows to find the 1,062 for one customer. After, go to the customer in the sorted index and read only those rows.

## Limits (read these)

- **SQLite is not Redshift.** Redshift is a distributed column store with sort keys, distribution keys and different internals. This lab teaches the habits (read the plan, filter early, do not wrap columns, measure) but none of the Redshift-specific tuning.
- The partition demo is a local imitation. It does not touch S3, Glue or Athena.
- Timings vary by machine, by what else is running, and by run. The tables above are real, from one laptop, and they will not match yours.
- The data is fake and evenly spread (customers, products and dates are random with no skew). Real data is lumpier, and lumpy data changes which index is best.
- The planner is SQLite's, with no statistics. A server database with fresh statistics can pick a different plan.
- Case 7 matches only because shipment ids have no gaps. Case 9 matches only because every customer in the fact table exists in `dim_customer`. Both are explained in the case text.
- Foreign keys are written in the schema but are not enforced (to keep inserts fast). The tests check that the fake data is consistent.
- Single connection, single process, one query at a time. There is no test of concurrent users.
- Tests assert plans and results. They never assert how long anything takes.

## Run the tests

```powershell
python -m unittest discover -s tests -t .
```

Real result: `Ran 45 tests ... OK`. The tests build a 100,000-row database once and check:

- the seed is repeatable, the right size, and the data is consistent;
- for every case, the slow and fast SQL return identical results;
- the plan changes where it should (`SCAN` becomes `SEARCH`, a covering index appears, a correlated subquery disappears);
- the timing helper (median, warm-up, speed-up and verdict rules);
- partition routing (a date goes to its month, a bad date is refused, ranges touch the right months) and that partitions give the same answer as the big table;
- the index-cost measurement and the command line.

## Files

```
tuning/db.py          the star schema, the connection, and index cleanup
tuning/seed.py        builds the fake data (repeatable)
tuning/cases.py       the ten cases: slow SQL, fixed SQL, the change, the explanation
tuning/timing.py      median timing, query plan text, result comparison
tuning/runner.py      runs the cases and prints the plans and the table
tuning/costs.py       insert speed and file size with 0 to 6 indexes
tuning/partitions.py  monthly partition tables and routing (local simulation)
tuning/cli.py         the four commands: seed, run, costs, partitions
tests/                unittest tests
```

## License

MIT. See `LICENSE`.
