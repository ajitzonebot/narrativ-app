"""Tunable settings. Values in INR unless noted."""
import os

CRORE = 1e7

BENCHMARK = "^NSEI"

# Stage 0 sweep (NSE + BSE via Yahoo screener)
MIN_MCAP = 200 * CRORE
MAX_MCAP = None                        # no upper cap
MIN_TRADED_VALUE = 0.5 * CRORE        # average daily traded value (₹50 lakh)
MIN_PRICE = 20                         # avoid penny stocks
MIN_QPTS_ILLIQUID = 6                  # illiquid / penny stocks kept only if quality points >= this (of 9)
MAX_RET_52W = 150                      # % ; above this the stock has already run

# Fundamentals cache refresh
FUND_MAX_AGE_DAYS = 30                 # re-pull sooner when a results checkpoint is due
FUND_MAX_PER_RUN = int(os.environ.get("FUND_MAX_PER_RUN", 150))
CAPEX_MAX_INTENSITY = 0.15
FUND_SLEEP_SEC = 0.6

# Company filings (NSE XBRL): primary source for financial numbers
FILINGS_MAX_PER_RUN = int(os.environ.get("FILINGS_MAX_PER_RUN", 150))
FILINGS_MAX_MINUTES = int(os.environ.get("FILINGS_MAX_MINUTES", 35))
FILINGS_SLEEP_SEC = 0.35

# Output
TOP_N_CHARTS = 60                      # chart JSON files written for top N
RESEARCH_TOP_N = 20                    # top N eligible for Claude research

# Score weights (outlook + sentiment redistributed when a stock has no research yet)
WEIGHTS = {"outlook": 0.25, "inflection": 0.20, "undiscovered": 0.15, "valuation": 0.15,
           "momentum": 0.15, "sentiment": 0.10}
SCAN_GAP_PER_DAY = 15                  # researched stocks with drivers but no outlook scan queued per day (consistency K3)
RESEARCH_PER_DAY = 60                  # cap on the queue: full reviews first, then rechecks with a reason, then enrich (60 lasts a
                                       # weekend at ~25 items a day: 22-23 Nov 2026 the 45-item Friday queue ran out and 6 runs idled)
ENRICH_PER_DAY = 20                    # forward-driver hunts for stocks one driver away from a Buy / Hold call; reader-found dated
                                       # rows first (Claude only confirms them). 8 until 23 Nov 2026: 52 top-scoring stocks sat Not rated
RECENT_RESEARCH_DAYS = 30              # an enrich is skipped if Claude researched the stock this recently
OVERDUE_COOLDOWN_DAYS = 3              # an overdue recheck / scan-gap enrich is skipped if researched this recently (unless a new document arrived)
FIRST_STUDY_PACKS = 40                 # live feed (narrativ/next.py, owner 28 Nov 2026): never-studied stocks that pass every check get a
                                       # pack each day and are served when the queue's top work is done (full packs for the best 40)
SPILL_MAX = 60                         # items that missed the 60 cap: kept in backlog.json for the live feed, in queue order
CLAIM_MINUTES = 90                     # a stock taken by one research run is not served to another for this long
GAP_ENRICH_PER_DAY = 5                 # enrich tasks that fill kill switches / must-go-right items missing a quote, source or due date

# Bands (MAX_STOP_PCT and TARGET_R are unused since 20 Nov 2026: the one exit level is funnel.setup's stop)
BUY_ZONE_PCT = 0.05
MAX_STOP_PCT = 0.08
TARGET_R = 3.0

# Memory / checkpoints
SNAPSHOTS_KEEP = 400
CHECKPOINT_TOP_N = 40                  # auto results/shareholding checkpoints for top N + researched
CHECKPOINT_EXPIRE_DAYS = 21            # unresolved past due by this many days -> expired
THESIS_STALE_DAYS = 90
