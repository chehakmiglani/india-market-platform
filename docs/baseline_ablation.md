# Flat vs per-stock baselines: which rules agree best with NSE?

**Question.** Should "unusual volume" mean *5x the 20-day average for every stock* (flat), or
*3 standard deviations above this stock's own normal* (per-stock)? Per-stock sounds smarter.
Does it match what NSE itself acts on?

**Method.** Alerts for 21 Sep - 9 Oct 2026 (14 trading days, 3,431 stocks) were rebuilt under three
settings of `surveillance.baseline` and compared with NSE's own actions: exchange queries on
volume / price moves (84 stocks) and the short-term ASM list (66 stocks). Thresholds (z = 3) were
fixed before looking at the results and not tuned afterwards.

| | flat | hybrid | per_stock |
|---|---|---|---|
| Alerts per day | 83.9 | 67.9 | 88.1 |
| Stocks alerted | 650 | 562 | 794 |
| NSE-queried stocks we alerted on (recall) | 72.6% | 67.9% | 66.7% |
| Short-term ASM stocks we alerted on (recall) | 63.6% | 57.6% | 56.1% |
| Lift of any alert vs all stocks (queried) | 3.8x | 4.1x | 2.9x |
| Each day's top 10 alerts that NSE also acted on | 29.5% | 28.9% | 24.2% |
| HIGH-band stocks (count; % queried by NSE) | 30; 13.3% | 16; 18.8% | 14; 14.3% |

**Result.** Per-stock baselines alone agree *less* with NSE: a 5x spike in a small, volatile stock
is "normal for that stock", so it is suppressed, yet those are the stocks NSE watches, while 4%
moves in steady large caps get flagged and NSE ignores them. The hybrid (flat rule AND unusual for
the stock) trades about 19% fewer alerts for about 5 points of recall; its quality gains are within
noise at this sample size.

**Decision.** `flat` stays the default. All three remain selectable in `dbt_project.yml` so the
comparison can be repeated as history accumulates.

**Limits.** Three weeks of data; 14-30 stocks in the HIGH band. NSE's triggers are themselves based
on fixed multiples, so agreement with NSE favours flat rules by construction: this measures
"matches NSE's screening", not "finds manipulation".

Reproduce: `dbt build -s int_surveillance_signals+ --vars '{surveillance: {baseline: hybrid, ...}}'`
then query `gold.mart_surveillance_validation`.
