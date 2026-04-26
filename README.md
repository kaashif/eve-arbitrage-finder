# eve-arbitrage-finder
Arbitrage finder for EVE Online but with more useful financial analytics.

The repo does not include market data. Use `fetch_sample_data.sh` to download a
small historical sample of consecutive snapshots and the static EVE data files
needed by the scripts.

Currently I've only done some analysis on historical data, see the notebook
`find_arbitrages.ipynb`. `arbitrage_time_analysis.ipynb` ranks opportunities
with a 45 second per jump travel-time model, checks whether the destination buy
order is still present in the first snapshot at or after arrival, and classifies
whether the sell or buy side looks mispriced against the market average.

# Quick start

Install the dependencies:

```sh
uv sync
```

For the Spark notebook and plotting dependencies, install the analysis extra:

```sh
uv sync --extra analysis
```

Download two consecutive historical market-order snapshots plus static lookup
data:

```sh
./fetch_sample_data.sh
```

The script checks `Content-Length` before downloading and refuses to fetch more
than 1 GiB by default. To use a different cap:

```sh
MAX_BYTES=500000000 ./fetch_sample_data.sh
```

Run the plain Python arbitrage finder against the sample snapshot:

```sh
uv run python find_best_arb.py \
  data.everef.net/market-orders/history/2023/2023-01-01/market-orders-2023-01-01_00-15-03.v3.csv.bz2
```

The output is CSV-like:

```text
snapshot_index,wallet_amount,adj_return_per_jump,adj_return
```

`find_best_arb.py` currently prints the rows without that header.

To convert the sample snapshot to parquet:

```sh
uv run python convert_file_to_parquet.py \
  data.everef.net/market-orders/history/2023/2023-01-01/market-orders-2023-01-01_00-15-03.v3.csv.bz2
```

# Notes from a fresh run

These were the main things that needed working out:

* `download.sh` recursively downloads a whole Everef directory, which is easy to
  make much larger than intended. `fetch_sample_data.sh` downloads one known
  snapshot and checks the size first.
* `find_best_arb.py` expects `mapSolarSystemJumps.csv.bz2`, while Fuzzwork
  serves `mapSolarSystemJumps.csv`. The sample-data script downloads the CSV and
  creates the `.bz2` copy.
* The script dependencies are listed in `pyproject.toml`; Spark and plotting
  packages are available through the `analysis` extra.
* `find_best_arb.py` accepts `.csv.bz2` and `.avro` inputs. The local variable
  name says `parquet_filenames`, but parquet input is not implemented there yet.

# Why are you working on this?

It's neat. I'm also not allowed to do this stuff in real life, so doing it in a
video game is the next best thing :)

<https://www.eve-trading.net/> already exists, but some things that are
missing:

* Historical analysis so you can look at whether markets are getting more or
  less efficient and where, historically, there are a lot of mispricings.

* More sophisticated returns analysis - a 20% return on 100M is a lot better
  than a 100% return on 10M if you actually have the capital to invest! And the
  profit per jump metric isn't exactly useful - sorting by that means the 10B
  investment with a 1M profit per jump shows up at the top even though it's only
  a 1% return in total or something.

* Cool visualizations of the universe graph and mispricing hotspots!

I think all of this is really cool. Honestly I spend more time on data analysis
than actually playing EVE.

There might also be weird patterns around e.g. time of day, day of week.

# What's missing?

The big one is hooking this up to live market data from
<https://esi.evetech.net/ui/#/Market>. Then this'll actually be useful for
something other than retrospective analysis.

Also, I think it'd be cool to get an email notification if I'm hanging out at
Jita and there's a 1000% return opportunity that pops up. Then I could quickly
login, 11x my money, then log out.

I also feel like my palms get sweaty when I've put all my money into an
investment where I've bought at a reasonable price and someone has a
ridiculously highly priced buy order I'm chasing. What if they cancel it? It
would be nice to know which end of the trade is mispriced (i.e. significantly
different from the regional average price).

Are mispriced buys more common than mispriced sells? Or vice versa? Why might
that be? I really don't know.

# What's the end goal?

Of course, I'll make some ISK, but these opportunities will only be actually
worth doing while I get started.

If I get something polished enough, maybe I'll release something just as an
exercise.

Most people playing EVE aren't doing it to high frequency trade tiny orders
though, so the use to the community at large would likely be limited.
