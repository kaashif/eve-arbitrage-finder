#!/bin/sh
set -eu

MAX_BYTES="${MAX_BYTES:-1073741824}"

MARKET_DIR="data.everef.net/market-orders/history/2023/2023-01-01"
MARKET_FILE="$MARKET_DIR/market-orders-2023-01-01_00-15-03.v3.csv.bz2"
MARKET_URL="https://data.everef.net/market-orders/history/2023/2023-01-01/market-orders-2023-01-01_00-15-03.v3.csv.bz2"
NEXT_MARKET_FILE="$MARKET_DIR/market-orders-2023-01-01_00-45-03.v3.csv.bz2"
NEXT_MARKET_URL="https://data.everef.net/market-orders/history/2023/2023-01-01/market-orders-2023-01-01_00-45-03.v3.csv.bz2"

JUMPS_FILE="mapSolarSystemJumps.csv"
JUMPS_BZ2_FILE="mapSolarSystemJumps.csv.bz2"
JUMPS_URL="https://www.fuzzwork.co.uk/dump/sde-20241112-TRANQUILITY/mapSolarSystemJumps.csv"

TYPES_FILE="invTypes.csv"
TYPES_URL="https://www.fuzzwork.co.uk/dump/sde-20241112-TRANQUILITY/invTypes.csv"

content_length() {
    url="$1"
    length="$(curl -fsSIL "$url" | tr -d '\r' | awk 'tolower($1) == "content-length:" { value=$2 } END { print value }')"
    if [ -z "$length" ]; then
        echo "Could not determine Content-Length for $url" >&2
        exit 1
    fi
    echo "$length"
}

market_size="$(content_length "$MARKET_URL")"
next_market_size="$(content_length "$NEXT_MARKET_URL")"
jumps_size="$(content_length "$JUMPS_URL")"
types_size="$(content_length "$TYPES_URL")"
total_size=$((market_size + next_market_size + jumps_size + types_size))

echo "Planned download size: $total_size bytes"
echo "Maximum allowed size:  $MAX_BYTES bytes"

if [ "$total_size" -gt "$MAX_BYTES" ]; then
    echo "Refusing to download: planned size exceeds MAX_BYTES." >&2
    exit 1
fi

mkdir -p "$MARKET_DIR"

curl -L --fail --show-error --progress-bar -o "$MARKET_FILE" "$MARKET_URL"
curl -L --fail --show-error --progress-bar -o "$NEXT_MARKET_FILE" "$NEXT_MARKET_URL"
curl -L --fail --show-error --progress-bar -o "$JUMPS_FILE" "$JUMPS_URL"
curl -L --fail --show-error --progress-bar -o "$TYPES_FILE" "$TYPES_URL"

# find_best_arb.py currently expects this compressed filename.
bzip2 -k -f "$JUMPS_FILE"

echo "Downloaded:"
ls -lh "$MARKET_FILE" "$NEXT_MARKET_FILE" "$JUMPS_FILE" "$JUMPS_BZ2_FILE" "$TYPES_FILE"
