from functools import lru_cache
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from arbitrage_time_analysis import read_jump_graph, read_type_names


ROOT = Path(__file__).parent
DEFAULT_SOURCES = {
    "all": ROOT / "day_arbitrages_all.bin",
    "day": ROOT / "day_simulation_1b.csv",
    "top100": ROOT / "arbitrage_time_analysis_top100.csv",
}

SOURCE_LABELS = {
    "all": "All day arbitrage candidates",
    "day": "Greedy day simulation",
    "top100": "Top 100 snapshot arbitrages",
}
ARBITRAGE_MAGIC = b"EVEARB_ARBS___01"
ARBITRAGE_DTYPE = np.dtype(
    [
        ("snapshot_ts", "<i8"),
        ("arrival_ts", "<i8"),
        ("arrival_snapshot_ts", "<i8"),
        ("sell_order_id", "<u8"),
        ("buy_order_id", "<u8"),
        ("type_id", "<u4"),
        ("from_system", "<u4"),
        ("to_system", "<u4"),
        ("gate_jumps", "<u2"),
        ("can_take_advantage", "u1"),
        ("_pad0", "u1"),
        ("quantity", "<u4"),
        ("route_seconds", "<u4"),
        ("sell_price", "<f8"),
        ("buy_price", "<f8"),
        ("investment", "<f8"),
        ("profit", "<f8"),
        ("isk_per_hour", "<f8"),
        ("total_return_pct", "<f8"),
        ("wallet_return_pct", "<f8"),
    ],
    align=True,
)
NO_SNAPSHOT_TS = np.iinfo(np.int64).min

app = FastAPI(title="EVE Arbitrage Explorer")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def source_path(source: str) -> Path:
    if source not in DEFAULT_SOURCES:
        raise HTTPException(status_code=404, detail=f"unknown source {source!r}")
    path = DEFAULT_SOURCES[source]
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"{path.name} does not exist. Run simulate_day.py or arbitrage_time_analysis.py first.",
        )
    return path


@lru_cache(maxsize=1)
def jump_graph():
    graph_file = ROOT / "mapSolarSystemJumps.csv"
    if not graph_file.exists():
        graph_file = ROOT / "mapSolarSystemJumps.csv.bz2"
    if not graph_file.exists():
        raise HTTPException(
            status_code=404,
            detail="mapSolarSystemJumps.csv is missing. Run fetch_sample_data.py first.",
        )
    return read_jump_graph(str(graph_file))


@lru_cache(maxsize=1)
def read_solar_systems():
    systems_file = ROOT / "mapSolarSystems.csv"
    if not systems_file.exists():
        raise HTTPException(
            status_code=404,
            detail="mapSolarSystems.csv is missing. Run fetch_sample_data.py first.",
        )
    df = pd.read_csv(
        systems_file,
        usecols=[
            "regionID",
            "constellationID",
            "solarSystemID",
            "solarSystemName",
            "x",
            "y",
            "z",
            "security",
        ],
    )
    return df.set_index("solarSystemID", drop=False)


@lru_cache(maxsize=1)
def type_names():
    types_file = ROOT / "invTypes.csv"
    if not types_file.exists():
        return {}
    return read_type_names(str(types_file))


@lru_cache(maxsize=8)
def read_source(source: str):
    df = pd.read_csv(source_path(source))
    time_columns = ["snapshot_time", "arrival_time", "arrival_snapshot_time"]
    for column in time_columns:
        if column in df.columns:
            df[column] = pd.to_datetime(df[column], utc=True, errors="coerce")
    return df


@lru_cache(maxsize=2)
def read_binary_source(source: str):
    path = source_path(source)
    with open(path, "rb") as f:
        header = f.read(32)
    if len(header) != 32 or header[:16] != ARBITRAGE_MAGIC:
        raise HTTPException(status_code=500, detail=f"{path.name} is not an arbitrage binary file")
    record_size = int.from_bytes(header[16:24], "little")
    count = int.from_bytes(header[24:32], "little")
    if record_size != ARBITRAGE_DTYPE.itemsize:
        raise HTTPException(
            status_code=500,
            detail=f"{path.name} record size {record_size} does not match API dtype {ARBITRAGE_DTYPE.itemsize}",
        )
    return np.memmap(path, dtype=ARBITRAGE_DTYPE, mode="r", offset=32, shape=(count,))


def timestamp_iso(seconds):
    if seconds is None or int(seconds) == int(NO_SNAPSHOT_TS):
        return None
    return pd.to_datetime(int(seconds), unit="s", utc=True).isoformat()


def field(row, name, default=None):
    if isinstance(row, np.void):
        return row[name] if name in row.dtype.names else default
    return row.get(name, default)


def route_record(index, row, graph, names):
    from_system = int(field(row, "from_system"))
    to_system = int(field(row, "to_system"))
    type_id = int(field(row, "type_id", 0))
    try:
        path = [int(system_id) for system_id in nx.shortest_path(graph, from_system, to_system)]
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        path = [from_system, to_system]

    profit = float(field(row, "profit", 0))
    investment = float(field(row, "investment", 0))

    if isinstance(row, np.void):
        snapshot_time = timestamp_iso(row["snapshot_ts"])
        arrival_time = timestamp_iso(row["arrival_ts"])
        arrival_snapshot_time = timestamp_iso(row["arrival_snapshot_ts"])
    else:
        snapshot_time = row["snapshot_time"].isoformat() if pd.notna(row.get("snapshot_time")) else None
        arrival_time = row["arrival_time"].isoformat() if pd.notna(row.get("arrival_time")) else None
        arrival_snapshot_time = (
            row["arrival_snapshot_time"].isoformat()
            if pd.notna(row.get("arrival_snapshot_time"))
            else None
        )

    return {
        "id": int(index),
        "snapshotTime": snapshot_time,
        "arrivalTime": arrival_time,
        "arrivalSnapshotTime": arrival_snapshot_time,
        "itemName": str(field(row, "item_name", names.get(type_id, type_id))),
        "mispricingType": str(field(row, "mispricing_type", "unknown")),
        "fromSystem": from_system,
        "toSystem": to_system,
        "gateJumps": int(field(row, "gate_jumps", max(0, len(path) - 1))),
        "routeMinutes": float(field(row, "route_minutes", field(row, "route_seconds", 0) / 60)),
        "profit": profit,
        "investment": investment,
        "walletReturnPct": float(field(row, "wallet_return_pct", 0)),
        "totalReturnPct": float(field(row, "total_return_pct", 0)),
        "iskPerHour": float(field(row, "isk_per_hour", 0)),
        "quantity": int(field(row, "executable_quantity", field(row, "quantity", 0))),
        "sellPrice": float(field(row, "sell_price", 0)),
        "buyPrice": float(field(row, "buy_price", 0)),
        "canTakeAdvantage": bool(field(row, "can_take_advantage", True)),
        "feasibilityNote": str(field(row, "feasibility_note", "")),
        "path": path,
    }


@app.get("/api/sources")
def sources():
    return {
        "sources": [
            {
                "id": source,
                "label": SOURCE_LABELS[source],
                "exists": path.exists(),
                "rows": int(len(read_binary_source(source)) if source == "all" and path.exists() else len(pd.read_csv(path))) if path.exists() else 0,
            }
            for source, path in DEFAULT_SOURCES.items()
        ]
    }


@app.get("/api/arbitrages")
def arbitrages(
    source: str = "all",
    limit: int = Query(3000, ge=1, le=10000),
    min_profit: float = Query(0, ge=0),
    feasible_only: bool = True,
):
    graph = jump_graph()
    systems = read_solar_systems()
    names = type_names()
    if source == "all":
        records = read_binary_source(source)
        mask = records["profit"] >= min_profit
        if feasible_only:
            mask &= records["can_take_advantage"] != 0
        selected_indices = np.flatnonzero(mask)[:limit]
        selected_rows = records[selected_indices]
        routes = [route_record(int(index), row, graph, names) for index, row in zip(selected_indices, selected_rows)]
    else:
        df = read_source(source).copy()
        if "profit" in df.columns:
            df = df[df["profit"] >= min_profit]
        if feasible_only and "can_take_advantage" in df.columns:
            df = df[df["can_take_advantage"].astype(bool)]
        df = df.sort_values(["snapshot_time", "profit"], ascending=[True, False]).head(limit)
        routes = [route_record(index, row, graph, names) for index, row in df.iterrows()]

    directed_edges = {}
    node_stats = {}
    for route in routes:
        path = route["path"]
        for system_id in path:
            node_stats.setdefault(system_id, {"systemId": system_id, "routeCount": 0, "profit": 0})
        for system_id in {route["fromSystem"], route["toSystem"]}:
            node_stats[system_id]["routeCount"] += 1
            node_stats[system_id]["profit"] += route["profit"]
        for source_id, target_id in zip(path, path[1:]):
            key = (source_id, target_id)
            directed_edges.setdefault(
                key,
                {"source": source_id, "target": target_id, "routeIds": [], "profit": 0, "count": 0},
            )
            directed_edges[key]["routeIds"].append(route["id"])
            directed_edges[key]["profit"] += route["profit"]
            directed_edges[key]["count"] += 1

    nodes = []
    for system_id in graph.nodes:
        system_id = int(system_id)
        if system_id not in systems.index:
            continue
        system = systems.loc[system_id]
        stats = node_stats.get(system_id, {"systemId": system_id, "routeCount": 0, "profit": 0})
        nodes.append(
            {
                **stats,
                "name": str(system["solarSystemName"]),
                "regionId": int(system["regionID"]),
                "constellationId": int(system["constellationID"]),
                "security": float(system["security"]),
                "universeX": float(system["x"]),
                "universeY": float(system["y"]),
                "universeZ": float(system["z"]),
                "x": float(system["x"]),
                "y": float(system["z"]),
                "isOrigin": any(route["fromSystem"] == system_id for route in routes),
                "isDestination": any(route["toSystem"] == system_id for route in routes),
            }
        )
    galaxy_edges = [
        {"source": int(source_id), "target": int(target_id)}
        for source_id, target_id in graph.edges
    ]

    profits = [route["profit"] for route in routes]
    returns = [route["totalReturnPct"] for route in routes]
    snapshots = sorted(
        {
            route_time
            for route in routes
            for route_time in [route["snapshotTime"], route["arrivalSnapshotTime"]]
            if route_time
        }
    )
    return {
        "source": source,
        "summary": {
            "routeCount": len(routes),
            "nodeCount": graph.number_of_nodes(),
            "edgeCount": len(directed_edges),
            "galaxyEdgeCount": graph.number_of_edges(),
            "totalProfit": float(sum(profits)),
            "maxProfit": float(max(profits)) if profits else 0,
            "maxTotalReturnPct": float(max(returns)) if returns else 0,
            "minTime": min((route["snapshotTime"] for route in routes if route["snapshotTime"]), default=None),
            "maxTime": max((route["arrivalSnapshotTime"] for route in routes if route["arrivalSnapshotTime"]), default=None),
        },
        "snapshots": snapshots,
        "nodes": nodes,
        "galaxyEdges": galaxy_edges,
        "edges": list(directed_edges.values()),
        "routes": routes,
    }
