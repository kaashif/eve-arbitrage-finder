# Profiling notes

## Full arbitrage export, one snapshot

Command:

```sh
uv run python -m cProfile -o profile_all_arb_1snap.prof \
  export_all_arbitrages.py \
  --wallet 1000000000 \
  --per-type-candidate-limit 25 \
  --max-snapshots 1 \
  --out /tmp/all_arb_profile_1snap.csv
```

Result:

* Wall time under cProfile: 49.808s
* Function calls: 255,689,617 total, 250,779,046 primitive
* Output rows for one snapshot: 167,220
* Unique item types represented: 2,386
* Unique system pairs represented: 31,190
* Output CSV size: 52 MiB
* Feasible rows: 0 in this particular bounded profile because `--max-snapshots 1`
  leaves no later snapshot for arrival validation.

Top cumulative-time hotspots:

```text
48.066s  build_arbitrage_table
12.328s  pandas.DataFrame.iterrows
 9.310s  pandas.Series.__getitem__
 8.019s  pandas.Series construction
 7.392s  networkx.shortest_path_length
 7.236s  networkx bidirectional BFS internals
 6.377s  pandas.DataFrame.__getitem__
 5.665s  pandas block manager reindexing
 4.391s  pandas.DataFrame.sort_values
 2.585s  pandas.read_csv
```

Interpretation:

* The largest avoidable cost is row-wise pandas iteration and scalar Series
  access inside the nested sell/buy candidate loops.
* Shortest-path lookup is also significant: 32,926 NetworkX shortest path calls
  took about 7.4s despite per-snapshot pair caching.
* Keeping all candidate rows creates large output quickly: one snapshot with
  `per_type_candidate_limit=25` wrote 167k rows / 52 MiB.
* A full 48-snapshot day at this breadth is expected to be slow unless the
  inner loop is vectorized, candidate rows are filtered earlier, or route
  distances are cached/precomputed across snapshots.

Likely next optimizations:

* Replace `iterrows()` with `itertuples()` or NumPy arrays in the candidate
  pair loop.
* Cache shortest-path lengths across all snapshots, not only within one
  snapshot.
* Precompute all-pairs shortest paths for only systems appearing in candidate
  orders.
* Filter obviously useless rows before constructing full output rows.
* Avoid sorting full sell/buy DataFrames repeatedly where `nsmallest` /
  `nlargest` is enough.

## Rust rewrite check

Command:

```sh
target/release/eve-arb-rs export \
  --max-snapshots 1 \
  --per-type-candidate-limit 25 \
  --out /tmp/rust_arbs_1snap.bin \
  --csv-out /tmp/rust_arbs_1snap.csv
```

Result after the first order cache existed:

* Wall time: 0.583s
* User CPU: 0.28s
* Output rows: 167,268
* The binary output is fixed-width `ArbitrageRecord` data behind a small header.
* Order input is fixed-width `OrderRecord` data in `.cache/eve-arb/*.orders.bin`
  and is memory-mapped on later runs.

This is not a perfect apples-to-apples benchmark because the Python number was
under cProfile and the Rust command also wrote CSV, but it confirms the main
profile finding: pandas row iteration and NetworkX path calls dominated the old
path.
