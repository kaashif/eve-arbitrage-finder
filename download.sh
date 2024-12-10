#!/bin/sh
wget -r https://data.everef.net/market-orders/history/2023/2023-01-01/ --accept-regex='.*bz2'
