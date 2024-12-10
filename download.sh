#!/bin/sh
wget -r https://data.everef.net/market-orders/history/2023/2023-01-01/ --accept-regex='.*bz2'
wget https://www.fuzzwork.co.uk/dump/sde-20241112-TRANQUILITY/mapSolarSystemJumps.csv
wget https://www.fuzzwork.co.uk/dump/sde-20241112-TRANQUILITY/invTypes.csv
