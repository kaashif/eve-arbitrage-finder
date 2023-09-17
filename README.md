# eve-arbitrage-finder
Arbitrage finder for EVE Online but with more useful financial analytics.

This repo as-is is non-functional, it's missing all of the data files and any
instructions.

Currently I've only done some analysis on historical data, see the notebook
`find_arbitrages.ipynb`.

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
