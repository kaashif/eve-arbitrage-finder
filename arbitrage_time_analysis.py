import bz2
import csv
import heapq
import re
from dataclasses import dataclass
from bisect import bisect_left
from pathlib import Path

import networkx as nx
import pandas as pd


DEFAULT_MARKET_FILE = (
    "data.everef.net/market-orders/history/2023/2023-01-01/"
    "market-orders-2023-01-01_00-15-03.v3.csv.bz2"
)
DEFAULT_JUMPS_FILE = "mapSolarSystemJumps.csv"
DEFAULT_TYPES_FILE = "invTypes.csv"


@dataclass(frozen=True)
class AnalysisConfig:
    market_file: str = DEFAULT_MARKET_FILE
    market_glob: str = (
        "data.everef.net/market-orders/history/2023/2023-01-01/"
        "market-orders-2023-01-01_*.v3.csv.bz2"
    )
    jumps_file: str = DEFAULT_JUMPS_FILE
    types_file: str = DEFAULT_TYPES_FILE
    wallet_amount: int = 100_000_000
    seconds_per_jump: int = 45
    top_n: int = 100
    per_type_candidate_limit: int = 25


def read_jump_graph(filename):
    opener = bz2.open if filename.endswith(".bz2") else open
    mode = "rt"

    with opener(filename, mode=mode, newline="") as f:
        reader = csv.DictReader(f)
        graph = nx.Graph()
        for row in reader:
            graph.add_edge(int(row["fromSolarSystemID"]), int(row["toSolarSystemID"]))
    return graph


def read_type_names(filename):
    with open(filename, newline="") as f:
        return {
            int(row["typeID"]): row["typeName"]
            for row in csv.DictReader(f)
            if row["typeID"].isdigit()
        }


def snapshot_time_from_filename(filename):
    match = re.search(r"market-orders-(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})", filename)
    if match is None:
        return None
    return pd.to_datetime(match.group(1), format="%Y-%m-%d_%H-%M-%S", utc=True)


def market_snapshots(config):
    paths = sorted(Path().glob(config.market_glob))
    if not paths:
        paths = [Path(config.market_file)]

    snapshots = []
    for path in paths:
        snapshot_time = snapshot_time_from_filename(str(path))
        if snapshot_time is not None:
            snapshots.append((snapshot_time, str(path)))

    return sorted(snapshots, key=lambda item: item[0])


def round_up_snapshot(snapshots, arrival_time):
    times = [snapshot_time for snapshot_time, _ in snapshots]
    index = bisect_left(times, arrival_time)
    if index == len(snapshots):
        return None, None
    return snapshots[index]


def load_buy_order_snapshots(snapshots):
    orders_by_snapshot = {}
    for snapshot_time, path in snapshots:
        df = pd.read_csv(
            path,
            usecols=["order_id", "is_buy_order", "price", "volume_remain", "min_volume"],
        )
        buys = df[df["is_buy_order"]].set_index("order_id", drop=False)
        orders_by_snapshot[snapshot_time] = buys
    return orders_by_snapshot


def classify_mispricing(sell_price, buy_price, market_average_price):
    sell_is_low = sell_price < market_average_price
    buy_is_high = buy_price > market_average_price

    if sell_is_low and buy_is_high:
        return "both_low_sell_and_high_buy"
    if sell_is_low:
        return "low_sell_price"
    if buy_is_high:
        return "high_buy_price"
    return "unclear_vs_average"


def build_arbitrage_table(config=AnalysisConfig()):
    orders = pd.read_csv(config.market_file)
    orders = orders[orders["universe_id"] == "eve"].copy()
    snapshots = market_snapshots(config)
    buy_orders_by_snapshot = load_buy_order_snapshots(snapshots)

    market_average = (
        orders.assign(volume_x_price=orders["volume_remain"] * orders["price"])
        .groupby("type_id", as_index=True)
        .agg(total_volume=("volume_remain", "sum"), total_value=("volume_x_price", "sum"))
    )
    market_average["market_average_price"] = (
        market_average["total_value"] / market_average["total_volume"]
    )

    graph = read_jump_graph(config.jumps_file)
    type_names = read_type_names(config.types_file)
    snapshot_time = snapshot_time_from_filename(config.market_file)

    best = []

    for type_id, group in orders.groupby("type_id", sort=False):
        sells = group[~group["is_buy_order"]].sort_values("price", ascending=True)
        buys = group[group["is_buy_order"]].sort_values("price", ascending=False)

        if sells.empty or buys.empty:
            continue
        if sells.iloc[0]["price"] >= buys.iloc[0]["price"]:
            continue

        avg_price = market_average.at[type_id, "market_average_price"]
        candidate_sells = sells[sells["price"] < buys.iloc[0]["price"]].head(
            config.per_type_candidate_limit
        )
        candidate_buys = buys[buys["price"] > sells.iloc[0]["price"]].head(
            config.per_type_candidate_limit
        )

        for _, sell in candidate_sells.iterrows():
            for _, buy in candidate_buys.iterrows():
                if sell["price"] >= buy["price"]:
                    continue
                if sell["volume_remain"] <= buy["min_volume"]:
                    continue
                if not graph.has_node(sell["system_id"]) or not graph.has_node(buy["system_id"]):
                    continue
                try:
                    jumps = nx.shortest_path_length(
                        graph, int(sell["system_id"]), int(buy["system_id"])
                    )
                except nx.NetworkXNoPath:
                    continue

                max_quantity = min(int(sell["volume_remain"]), int(buy["volume_remain"]))
                affordable_quantity = int(config.wallet_amount // sell["price"])
                executed_quantity = min(max_quantity, affordable_quantity)
                if executed_quantity <= 0:
                    continue

                investment = float(executed_quantity * sell["price"])
                profit = float(executed_quantity * (buy["price"] - sell["price"]))
                charged_travel_legs = max(1, jumps)
                route_seconds = int(charged_travel_legs * config.seconds_per_jump)
                arrival_time = snapshot_time + pd.Timedelta(seconds=route_seconds)
                arrival_snapshot_time, arrival_snapshot_path = round_up_snapshot(
                    snapshots, arrival_time
                )
                isk_per_hour = profit / route_seconds * 3600 if route_seconds else float("inf")
                total_return_pct = 100 * profit / investment if investment else 0
                wallet_return_pct = 100 * profit / config.wallet_amount
                buy_order_still_available = False
                arrival_buy_price = None
                arrival_buy_volume_remain = None
                feasibility_note = "no snapshot at or after arrival time"

                if arrival_snapshot_time is not None:
                    arrival_buys = buy_orders_by_snapshot[arrival_snapshot_time]
                    if buy["order_id"] in arrival_buys.index:
                        arrival_buy_order = arrival_buys.loc[buy["order_id"]]
                        arrival_buy_price = float(arrival_buy_order["price"])
                        arrival_buy_volume_remain = int(arrival_buy_order["volume_remain"])
                        buy_order_still_available = (
                            arrival_buy_price >= buy["price"]
                            and arrival_buy_volume_remain >= executed_quantity
                            and executed_quantity >= int(arrival_buy_order["min_volume"])
                        )
                        feasibility_note = (
                            "destination buy order still covers the trade"
                            if buy_order_still_available
                            else "destination buy order changed or lacks enough volume"
                        )
                    else:
                        feasibility_note = "destination buy order is gone by arrival snapshot"

                can_take_advantage = buy_order_still_available and profit > 0

                row = {
                    "snapshot_time": snapshot_time,
                    "arrival_time": arrival_time,
                    "arrival_snapshot_time": arrival_snapshot_time,
                    "arrival_snapshot_file": arrival_snapshot_path,
                    "type_id": int(type_id),
                    "item_name": type_names.get(int(type_id), str(type_id)),
                    "mispricing_type": classify_mispricing(
                        sell["price"], buy["price"], avg_price
                    ),
                    "sell_is_below_average": bool(sell["price"] < avg_price),
                    "buy_is_above_average": bool(buy["price"] > avg_price),
                    "market_average_price": float(avg_price),
                    "sell_price": float(sell["price"]),
                    "buy_price": float(buy["price"]),
                    "spread": float(buy["price"] - sell["price"]),
                    "from_system": int(sell["system_id"]),
                    "to_system": int(buy["system_id"]),
                    "gate_jumps": int(jumps),
                    "charged_travel_legs": int(charged_travel_legs),
                    "route_seconds": route_seconds,
                    "route_minutes": route_seconds / 60,
                    "buy_order_still_available_at_arrival": buy_order_still_available,
                    "arrival_buy_price": arrival_buy_price,
                    "arrival_buy_volume_remain": arrival_buy_volume_remain,
                    "can_take_advantage": can_take_advantage,
                    "feasibility_note": feasibility_note,
                    "executable_quantity": int(executed_quantity),
                    "investment": investment,
                    "profit": profit,
                    "isk_per_hour": isk_per_hour,
                    "total_return_pct": total_return_pct,
                    "wallet_return_pct": wallet_return_pct,
                    "sell_order_id": int(sell["order_id"]),
                    "buy_order_id": int(buy["order_id"]),
                }

                score = row["isk_per_hour"]
                if len(best) < config.top_n:
                    heapq.heappush(best, (score, row["sell_order_id"], row["buy_order_id"], row))
                elif score > best[0][0]:
                    heapq.heapreplace(
                        best, (score, row["sell_order_id"], row["buy_order_id"], row)
                    )

    table = pd.DataFrame([row for _, _, _, row in best])
    if table.empty:
        return table

    return table.sort_values(
        ["can_take_advantage", "isk_per_hour"],
        ascending=[False, False],
    ).reset_index(drop=True)


def summarize_table(table):
    if table.empty:
        return pd.DataFrame()

    return (
        table.groupby(["can_take_advantage", "mispricing_type"])
        .size()
        .rename("count")
        .reset_index()
        .sort_values(["can_take_advantage", "count"], ascending=[False, False])
    )


if __name__ == "__main__":
    config = AnalysisConfig()
    result = build_arbitrage_table(config)
    print(result.head(25).to_string(index=False))
