# India Market Intelligence and Surveillance Platform

Daily data pipeline on real Indian market data: NSE + AMFI -> Bronze (MinIO) -> Silver (PySpark/Delta)
-> Gold (dbt/Postgres) -> Surveillance -> Telegram -> Power BI. Orchestrated by Airflow, runs on Docker.

Status: **Phase 2 – Silver layer** done. Next: dbt Gold star schema.

## Quick start (no Docker: local lake on disk)
Needs Python 3.11+ and Java 17. On Windows, Spark also needs `HADOOP_HOME` with `winutils.exe`.
```bat
copy .env.example .env
:: in .env set LAKE_BACKEND=local
pip install -r requirements.txt
python -m src.extractors.cli --start 2026-08-17 --end 2026-10-06 --source nse
python -m src.extractors.cli --date 2026-10-06 --source amfi
python -m src.extractors.cli --date 2026-10-07 --source corp_actions
python -m src.spark_jobs.silver --all
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
| `fund_nav` | scheme_code, nav_date | AMFI NAVs with AMC and category |

Surveillance flags are analytical signals, not accusations.
