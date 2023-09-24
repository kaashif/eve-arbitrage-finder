#!/usr/bin/env python3.11

import bz2
import csv
import datetime
import networkx as nx
from io import StringIO

def read_jump_graph():
    with bz2.open("mapSolarSystemJumps.csv.bz2", mode="r") as data_csv:
        route_contents = data_csv.read()

    route_contents_f = StringIO(bytes.decode(route_contents, "utf-8"))
    route_reader = csv.DictReader(route_contents_f)
    G = nx.Graph()

    for row in route_reader:
        G.add_edge(row["fromSolarSystemID"], row["toSolarSystemID"])

    return G

G = read_jump_graph()

start = datetime.datetime.now()

def read_order_file():
    filename = "data.everef.net/market-orders/history/2023/2023-01-01/market-orders-2023-01-01_00-15-03.v3.csv.bz2"

    with bz2.open(filename, mode="r") as data_csv:
        contents = data_csv.read()

    contents_f = StringIO(bytes.decode(contents, "utf-8"))
    reader = csv.DictReader(contents_f)
    return reader

reader = read_order_file()

type_id_to_buys_and_sells = {}

for row in reader:
    row["price"] = float(row["price"])
    row["volume_remain"] = int(row["volume_remain"])
    row["min_volume"] = int(row["min_volume"])
    type_id = row["type_id"]
    if type_id not in type_id_to_buys_and_sells:
        buys_and_sells = {"buys": [], "sells": []}
        type_id_to_buys_and_sells[type_id] = buys_and_sells
    else:
        buys_and_sells = type_id_to_buys_and_sells[type_id]

    if row["is_buy_order"] == 'true':
        buys_and_sells["buys"].append(row)
    else:
        buys_and_sells["sells"].append(row)

arbitrages = []

for type_id, buys_and_sells in type_id_to_buys_and_sells.items():
    sells = buys_and_sells["sells"]
    buys = buys_and_sells["buys"]

    if len(sells) == 0 or len(buys) == 0:
        continue

    # We only need consider the order pairs that could possibly yield a profit
    # i.e. buy orders higher than the min sell price and sell orders lower than the max buy price.
    min_sell_price = min(sell["price"] for sell in sells)
    max_buy_price = max(buy["price"] for buy in buys)

    good_sells = (sell for sell in sells if sell["price"] < max_buy_price)
    good_buys = (buy for buy in buys if buy["price"] > min_sell_price)

    for buy in good_buys:
        for sell in good_sells:
            # conditions for valid arbitrage:
            # 1. sell order lower than buy order
            # (i.e. we buy from the sell order low, and sell into the buy order high)
            # 2. sell volume remain is higher than buy min_volume
            if sell["price"] < buy["price"] and sell["volume_remain"] > buy["min_volume"]:
                # arbitrage found!
                arbitrages.append((sell, buy))


def arbitrage_stats(arbitrage, wallet_amount):
    max_quantity = min(arbitrage[0]["volume_remain"], arbitrage[1]["volume_remain"])
    sell_price = arbitrage[0]["price"]
    buy_price = arbitrage[1]["price"]

    # you can only invest as much as you can afford
    quantity = min(max_quantity, wallet_amount / sell_price)
    real_investment = sell_price * quantity
    profit = quantity * (buy_price - sell_price)
    total_return = 100 * profit / real_investment

    # If you have money in your wallet you can't invest because the opportunity is too small
    # then it's like you did invest it, but with no return.
    # The return considering ALL the money we had available may be much, much lower.
    # This captures the idea that there's no point pursuing opportunities to make 600% on like $5
    adj_return = 100 * profit / wallet_amount

    # TODO: this considers each investment to take the same amount of time, which isn't true
    # We should be calculating the return per jump (with compounding).
    # We definitely need to filter out completely SHIT investments that wouldn't even be worth
    # doing if they took only one jump.

    return {
        "total_return": total_return,
        "adj_return": adj_return,
        "type_id": arbitrage[0]["type_id"],
        "from_system": arbitrage[0]["system_id"],
        "to_system": arbitrage[1]["system_id"],
        "real_investment": real_investment,
        "profit": profit
    }

def get_sorted_arb_stats(wallet_amount):
    return sorted([arbitrage_stats(arb, wallet_amount) for arb in arbitrages], key=lambda arb: arb["adj_return"], reverse=True)

wallet_amt_to_arb_stats = {k:get_sorted_arb_stats(k) for k in [1_000_000, 10_000_000, 100_000_000, 1_000_000_000]}

# We need to annotate each arbitrage with its distance
amt_to_valid_arbitrages = {amt: [] for amt in wallet_amt_to_arb_stats.keys()}

for amt, arbs in wallet_amt_to_arb_stats.items():
    for arb in arbs:
        if not G.has_node(arb["from_system"]) or not G.has_node(arb["to_system"]):
            break
        if not nx.has_path(G, arb["from_system"], arb["to_system"]):
            # There are a lot of arbitrages in this list between
            # different universes and stuff like that
            break

        arb["jumps"] = len(nx.shortest_path(G, arb["from_system"], arb["to_system"]))

        # return per jump, considering compounding
        # i.e. a 100% return per jump with 2 jumps means you double your money
        # twice for a total of 300% return for the whole trip

        arb["adj_return_per_jump"] = 100 * ((1 + (arb["adj_return"] / 100)) ** (1 / arb["jumps"]) - 1)

        amt_to_valid_arbitrages[amt].append(arb)

    amt_to_valid_arbitrages[amt].sort(key=lambda a: a["adj_return_per_jump"], reverse=True)

for amt, arbs in amt_to_valid_arbitrages.items():
    print(str(amt) + "," + str(arbs[0]["adj_return_per_jump"]))

end = datetime.datetime.now()

print(end-start)