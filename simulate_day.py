import argparse
import heapq
import sys
from dataclasses import dataclass

import pandas as pd

from arbitrage_time_analysis import (
    AnalysisConfig,
    build_arbitrage_table,
    market_snapshots,
    read_jump_graph,
    read_type_names,
)


class LazyBuyOrderSnapshots:
    def __init__(self, snapshots):
        self.path_by_time = {snapshot_time: path for snapshot_time, path in snapshots}
        self.cache = {}

    def __getitem__(self, snapshot_time):
        if snapshot_time not in self.cache:
            path = self.path_by_time[snapshot_time]
            df = pd.read_csv(
                path,
                usecols=["order_id", "is_buy_order", "price", "volume_remain", "min_volume"],
            )
            self.cache[snapshot_time] = df[df["is_buy_order"]].set_index(
                "order_id", drop=False
            )
        return self.cache[snapshot_time]


@dataclass(frozen=True)
class Trip:
    start_time: pd.Timestamp
    arrival_time: pd.Timestamp
    arrival_snapshot_time: pd.Timestamp
    item_name: str
    mispricing_type: str
    from_system: int
    to_system: int
    gate_jumps: int
    quantity: int
    sell_price: float
    buy_price: float
    investment: float
    profit: float
    wallet_before: float
    wallet_after: float
    sell_order_id: int
    buy_order_id: int


def best_trade_at_snapshot(
    snapshot_file,
    wallet_amount,
    top_n,
    per_type_candidate_limit,
    snapshots,
    buy_orders_by_snapshot,
    graph,
    type_names,
):
    config = AnalysisConfig(
        market_file=snapshot_file,
        wallet_amount=int(wallet_amount),
        top_n=top_n,
        per_type_candidate_limit=per_type_candidate_limit,
    )
    table = build_arbitrage_table(
        config,
        snapshots=snapshots,
        buy_orders_by_snapshot=buy_orders_by_snapshot,
        graph=graph,
        type_names=type_names,
    )
    if table.empty:
        return None

    feasible = table[table["can_take_advantage"]].copy()
    if feasible.empty:
        return None

    return feasible.sort_values("profit", ascending=False).iloc[0]


def simulate_greedy_day(
    starting_wallet=1_000_000_000,
    top_n=200,
    per_type_candidate_limit=25,
):
    base_config = AnalysisConfig()
    snapshots = market_snapshots(base_config)
    buy_orders_by_snapshot = LazyBuyOrderSnapshots(snapshots)
    graph = read_jump_graph(base_config.jumps_file)
    type_names = read_type_names(base_config.types_file)
    wallet = float(starting_wallet)
    available_time = snapshots[0][0]
    trips = []

    while True:
        candidates = []
        for snapshot_time, snapshot_file in snapshots:
            if snapshot_time < available_time:
                continue
            trade = best_trade_at_snapshot(
                snapshot_file,
                wallet,
                top_n=top_n,
                per_type_candidate_limit=per_type_candidate_limit,
                snapshots=snapshots,
                buy_orders_by_snapshot=buy_orders_by_snapshot,
                graph=graph,
                type_names=type_names,
            )
            if trade is None:
                continue

            # Prefer the next best executable profit. This is deliberately greedy:
            # it answers "what is the best trip I can take now?" at each step.
            heapq.heappush(
                candidates,
                (
                    -float(trade["profit"]),
                    snapshot_time,
                    snapshot_file,
                    trade,
                ),
            )

        if not candidates:
            break

        _, snapshot_time, _, trade = heapq.heappop(candidates)
        wallet_before = wallet
        wallet += float(trade["profit"])
        arrival_snapshot_time = trade["arrival_snapshot_time"]
        available_time = arrival_snapshot_time

        trips.append(
            Trip(
                start_time=snapshot_time,
                arrival_time=trade["arrival_time"],
                arrival_snapshot_time=arrival_snapshot_time,
                item_name=trade["item_name"],
                mispricing_type=trade["mispricing_type"],
                from_system=int(trade["from_system"]),
                to_system=int(trade["to_system"]),
                gate_jumps=int(trade["gate_jumps"]),
                quantity=int(trade["executable_quantity"]),
                sell_price=float(trade["sell_price"]),
                buy_price=float(trade["buy_price"]),
                investment=float(trade["investment"]),
                profit=float(trade["profit"]),
                wallet_before=wallet_before,
                wallet_after=wallet,
                sell_order_id=int(trade["sell_order_id"]),
                buy_order_id=int(trade["buy_order_id"]),
            )
        )

        if available_time >= snapshots[-1][0]:
            break

    return pd.DataFrame([trip.__dict__ for trip in trips])


def best_single_trip(
    starting_wallet=1_000_000_000,
    top_n=100,
    per_type_candidate_limit=15,
):
    base_config = AnalysisConfig()
    snapshots = market_snapshots(base_config)
    buy_orders_by_snapshot = LazyBuyOrderSnapshots(snapshots)
    graph = read_jump_graph(base_config.jumps_file)
    type_names = read_type_names(base_config.types_file)

    best_rows = []
    for index, (snapshot_time, snapshot_file) in enumerate(snapshots, start=1):
        print(f"analyzing snapshot {index}/{len(snapshots)} {snapshot_time}", file=sys.stderr)
        trade = best_trade_at_snapshot(
            snapshot_file,
            starting_wallet,
            top_n=top_n,
            per_type_candidate_limit=per_type_candidate_limit,
            snapshots=snapshots,
            buy_orders_by_snapshot=buy_orders_by_snapshot,
            graph=graph,
            type_names=type_names,
        )
        if trade is not None:
            best_rows.append(trade)

    if not best_rows:
        return pd.DataFrame()

    table = pd.DataFrame(best_rows)
    table["wallet_before"] = float(starting_wallet)
    table["wallet_after"] = table["wallet_before"] + table["profit"]
    return table.sort_values("profit", ascending=False).reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wallet", type=float, default=1_000_000_000)
    parser.add_argument("--top-n", type=int, default=200)
    parser.add_argument("--per-type-candidate-limit", type=int, default=25)
    parser.add_argument("--out", default="day_simulation_1b.csv")
    parser.add_argument("--mode", choices=["single", "greedy"], default="single")
    args = parser.parse_args()

    if args.mode == "single":
        trips = best_single_trip(
            starting_wallet=args.wallet,
            top_n=args.top_n,
            per_type_candidate_limit=args.per_type_candidate_limit,
        )
    else:
        trips = simulate_greedy_day(
            starting_wallet=args.wallet,
            top_n=args.top_n,
            per_type_candidate_limit=args.per_type_candidate_limit,
        )
    trips.to_csv(args.out, index=False)

    if trips.empty:
        print("No feasible trips found")
        return

    if args.mode == "single":
        best = trips.iloc[0]
        final_wallet = best["wallet_after"]
        total_profit = best["profit"]
        total_return_pct = 100 * total_profit / args.wallet

        print(f"candidate_snapshots={len(trips)}")
        print(f"starting_wallet={args.wallet:,.2f}")
        print(f"best_final_wallet={final_wallet:,.2f}")
        print(f"best_trip_profit={total_profit:,.2f}")
        print(f"best_trip_return_pct={total_return_pct:,.2f}")
        print(trips.head(20).to_string(index=False))
        return

    final_wallet = trips.iloc[-1]["wallet_after"]
    total_profit = final_wallet - args.wallet
    total_return_pct = 100 * total_profit / args.wallet

    print(f"trips={len(trips)}")
    print(f"starting_wallet={args.wallet:,.2f}")
    print(f"final_wallet={final_wallet:,.2f}")
    print(f"total_profit={total_profit:,.2f}")
    print(f"total_return_pct={total_return_pct:,.2f}")
    print(trips.to_string(index=False))


if __name__ == "__main__":
    main()
