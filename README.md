# India Market Intelligence and Surveillance Platform

Daily data pipeline on real Indian market data: NSE + AMFI -> Bronze (MinIO) -> Silver (PySpark/Delta)
-> Gold (dbt on DuckDB) -> Surveillance -> Telegram -> Power BI. Orchestrated by Airflow, runs on Docker.

Status: **Phase 3 – Gold star schema** done. Next: Airflow DAGs.

## Quick start (no Docker: local lake on disk)
Needs Python 3.11+ and Java 17. On Windows, Spark also needs `HADOOP_HOME` with `winutils.exe`.
```bat
copy .env.example .env
:: in .env set LAKE_BACKEND=local
pip install -r requirements.txt
python -m src.extractors.cli --start 2026-08-17 --end 2026-10-06 --source nse
python -m src.extractors.cli --date 2026-10-06 --source amfi
python -m src.extractors.cli --date 2026-10-07 --source corp_actions
python -m src.extractors.cli --date 2026-10-07 --source reference
python -m src.extractors.cli --date 2026-10-07 --source mfapi
python -m src.spark_jobs.silver --all
dbt build --project-dir dbt --profiles-dir dbt
pytest
```
With Docker, keep `LAKE_BACKEND=s3` and run `docker compose up -d` first (MinIO console on :9001).

## Silver tables (Delta, idempotent MERGE)
| Table | Grain | Notes |
|---|---|---|
| `stock_daily` | trade_date, symbol, series | Raw OHLC, volume, delivery %; bad rows go to `_quarantine_stock_daily` |
| `stock_daily_adjusted` | same | `adj_*` prices/volume after splits and bonuses; fully rebuilt each run |
| `corporate_actions` | symbol, ex_date, action_type | Split/bonus factors parsed from NSE text |
| `index_daily` | trade_date, index_name | All NSE indices, incl. P/E, P/B |
| `fund_nav` | scheme_code, nav_date | AMFI daily NAVs (all schemes) with AMC and category |
| `fund_nav_history` | scheme_code, nav_date | Full history from mfapi.in for `config/fund_watchlist.csv` |
| `stock_master` | snapshot_date, symbol | NSE equity list + Nifty 500 industry |

## Gold (dbt, schema `gold` in `data/warehouse/market.duckdb`)
DuckDB reads the Delta tables in place (`delta_scan`), so there is no copy step between Silver and Gold.

| Model | What it is |
|---|---|
| `dim_date` | Calendar from 2013, Indian FY (`FY27`), trading days; NSE holidays **derived from data** |
| `dim_stock` | SCD Type 2 via dbt snapshot (name / ISIN / face value / industry changes) + `unknown` member |
| `dim_fund`, `dim_index` | Fund plan / option / asset class; index family (broad, sectoral, thematic...) |
| `fact_stock_daily` | Adjusted OHLCV, delivery %, return, gap, 20-day avg volume / delivery / volatility |
| `fact_index_daily`, `fact_fund_nav` | Daily index levels; NAVs with daily return |
| `fact_portfolio_txn` | Signed quantities and cash flows; fund units from NAV on/before the date |
| `mart_portfolio_holdings` | Holdings, average cost, unrealised / realised P&L, weights |
| `mart_portfolio_xirr` | XIRR per portfolio and holding (absolute return shown under 1 year) |
| `mart_sip_tracker` | SIP installments, regularity, lapse flag |
| `mart_fund_performance` | 1M..1Y returns, 3Y/5Y CAGR, volatility, Sharpe, max drawdown, rolling 1Y |
| `mart_sector_performance` | Daily breadth and returns per industry |

54 dbt tests run on every build, including: split-adjusted prices are continuous on ex-dates,
no truncated trading day, OHLC sanity, delivery % in 0–100, SCD2 validity ranges, fact→dim integrity.

Use your own portfolio without committing it: put it in `data/local/portfolio.csv` and set
`PORTFOLIO_CSV=data/local/portfolio.csv`.

Surveillance flags are analytical signals, not accusations.
