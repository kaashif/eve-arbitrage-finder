import argparse
import sys

import pandas as pd

from arbitrage_time_analysis import (
    AnalysisConfig,
    build_arbitrage_table,
    market_snapshots,
    read_jump_graph,
    read_type_names,
)
from simulate_day import LazyBuyOrderSnapshots


def export_all_arbitrages(
    wallet,
    per_type_candidate_limit,
    out,
    max_snapshots=None,
):
    base_config = AnalysisConfig(wallet_amount=int(wallet), top_n=0)
    snapshots = market_snapshots(base_config)
    if max_snapshots is not None:
        snapshots = snapshots[:max_snapshots]

    buy_orders_by_snapshot = LazyBuyOrderSnapshots(snapshots)
    graph = read_jump_graph(base_config.jumps_file)
    type_names = read_type_names(base_config.types_file)
    tables = []

    for index, (snapshot_time, snapshot_file) in enumerate(snapshots, start=1):
        print(f"analyzing snapshot {index}/{len(snapshots)} {snapshot_time}", file=sys.stderr)
        config = AnalysisConfig(
            market_file=snapshot_file,
            wallet_amount=int(wallet),
            top_n=0,
            per_type_candidate_limit=per_type_candidate_limit,
        )
        table = build_arbitrage_table(
            config,
            snapshots=snapshots,
            buy_orders_by_snapshot=buy_orders_by_snapshot,
            graph=graph,
            type_names=type_names,
        )
        if not table.empty:
            tables.append(table)

    if tables:
        result = pd.concat(tables, ignore_index=True)
        result = result.sort_values(
            ["snapshot_time", "can_take_advantage", "total_return_pct", "profit"],
            ascending=[True, False, False, False],
        )
    else:
        result = pd.DataFrame()

    result.to_csv(out, index=False)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wallet", type=float, default=1_000_000_000)
    parser.add_argument("--per-type-candidate-limit", type=int, default=25)
    parser.add_argument("--out", default="day_arbitrages_all.csv")
    parser.add_argument("--max-snapshots", type=int, default=None)
    args = parser.parse_args()

    result = export_all_arbitrages(
        wallet=args.wallet,
        per_type_candidate_limit=args.per_type_candidate_limit,
        out=args.out,
        max_snapshots=args.max_snapshots,
    )
    print(f"rows={len(result)}")
    if not result.empty:
        feasible = result[result["can_take_advantage"]]
        print(f"feasible_rows={len(feasible)}")
        print(result.head(20).to_string(index=False))


if __name__ == "__main__":
    main()
