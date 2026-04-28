#!/usr/bin/env python3

import bz2
import argparse
import os
import shutil
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


MARKET_DIR = Path("data.everef.net/market-orders/history/2023/2023-01-01")

DOWNLOADS = [
    (
        "market-orders-2023-01-01_00-15-03.v3.csv.bz2",
        "https://data.everef.net/market-orders/history/2023/2023-01-01/market-orders-2023-01-01_00-15-03.v3.csv.bz2",
        MARKET_DIR / "market-orders-2023-01-01_00-15-03.v3.csv.bz2",
    ),
    (
        "market-orders-2023-01-01_00-45-03.v3.csv.bz2",
        "https://data.everef.net/market-orders/history/2023/2023-01-01/market-orders-2023-01-01_00-45-03.v3.csv.bz2",
        MARKET_DIR / "market-orders-2023-01-01_00-45-03.v3.csv.bz2",
    ),
    (
        "mapSolarSystemJumps.csv",
        "https://www.fuzzwork.co.uk/dump/sde-20241112-TRANQUILITY/mapSolarSystemJumps.csv",
        Path("mapSolarSystemJumps.csv"),
    ),
    (
        "mapSolarSystems.csv",
        "https://www.fuzzwork.co.uk/dump/sde-20241112-TRANQUILITY/mapSolarSystems.csv",
        Path("mapSolarSystems.csv"),
    ),
    (
        "invTypes.csv",
        "https://www.fuzzwork.co.uk/dump/sde-20241112-TRANQUILITY/invTypes.csv",
        Path("invTypes.csv"),
    ),
]


def content_length(url):
    request = Request(url, method="HEAD")
    with urlopen(request) as response:
        length = response.headers.get("Content-Length")
    if not length:
        raise RuntimeError(f"Could not determine Content-Length for {url}")
    return int(length)


def download(url, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url)
    with urlopen(request) as response, destination.open("wb") as out:
        shutil.copyfileobj(response, out)


def compress_jumps():
    source = Path("mapSolarSystemJumps.csv")
    destination = Path("mapSolarSystemJumps.csv.bz2")
    with source.open("rb") as src, bz2.open(destination, "wb") as dst:
        shutil.copyfileobj(src, dst)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download sample EVE market snapshots and static SDE lookup data."
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=int(os.environ.get("MAX_BYTES", "1073741824")),
        help="Refuse to download if the planned total exceeds this many bytes.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        sizes = [(name, content_length(url), url, destination) for name, url, destination in DOWNLOADS]
    except (HTTPError, URLError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1

    total_size = sum(size for _, size, _, _ in sizes)
    print(f"Planned download size: {total_size} bytes")
    print(f"Maximum allowed size:  {args.max_bytes} bytes")

    if total_size > args.max_bytes:
        print("Refusing to download: planned size exceeds MAX_BYTES.", file=sys.stderr)
        return 1

    for name, size, url, destination in sizes:
        print(f"download {name} ({size:,} bytes)")
        download(url, destination)

    compress_jumps()

    print("Downloaded:")
    for _, _, _, destination in sizes:
        print(f"{destination} {destination.stat().st_size:,} bytes")
    compressed = Path("mapSolarSystemJumps.csv.bz2")
    print(f"{compressed} {compressed.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
