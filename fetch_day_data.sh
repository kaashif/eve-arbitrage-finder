#!/bin/sh
set -eu

DATE="${DATE:-2023-01-01}"
MAX_BYTES="${MAX_BYTES:-1073741824}"
BASE_URL="https://data.everef.net/market-orders/history/2023/$DATE"
MARKET_DIR="data.everef.net/market-orders/history/2023/$DATE"

content_length() {
    url="$1"
    length="$(curl -fsSIL "$url" | tr -d '\r' | awk 'tolower($1) == "content-length:" { value=$2 } END { print value }')"
    if [ -z "$length" ]; then
        echo "Could not determine Content-Length for $url" >&2
        exit 1
    fi
    echo "$length"
}

files="$(curl -fsSL "$BASE_URL/" | grep -Eo "market-orders-$DATE"'_[0-9-]+\.v3\.csv\.bz2' | sort -u)"
if [ -z "$files" ]; then
    echo "No market snapshot files found at $BASE_URL/" >&2
    exit 1
fi

total_size=0
for file in $files; do
    size="$(content_length "$BASE_URL/$file")"
    total_size=$((total_size + size))
done

echo "Snapshots: $(printf '%s\n' "$files" | wc -l | tr -d ' ')"
echo "Planned download size: $total_size bytes"
echo "Maximum allowed size:  $MAX_BYTES bytes"

if [ "$total_size" -gt "$MAX_BYTES" ]; then
    echo "Refusing to download: planned size exceeds MAX_BYTES." >&2
    exit 1
fi

mkdir -p "$MARKET_DIR"
for file in $files; do
    out="$MARKET_DIR/$file"
    if [ -s "$out" ]; then
        echo "present $file"
    else
        echo "download $file"
        curl -L --fail --show-error --progress-bar -C - -o "$out" "$BASE_URL/$file"
    fi
done

find "$MARKET_DIR" -name "*.csv.bz2" | wc -l
du -sh "$MARKET_DIR"
