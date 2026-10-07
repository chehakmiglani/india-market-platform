# India Market Intelligence and Surveillance Platform

Daily data pipeline on real Indian market data: NSE + AMFI -> Bronze (MinIO) -> Silver (PySpark/Delta)
-> Gold (dbt/Postgres) -> Surveillance -> Telegram -> Power BI. Orchestrated by Airflow, runs on Docker.

Status: **Phase 1 – scaffold and extractors** (in progress).

## Quick start
```bash
cp .env.example .env        # set passwords
docker compose up -d        # MinIO (9001 console), Postgres
pip install -r requirements.txt
python -m src.extractors.cli --date 2026-10-07
pytest
```

Surveillance flags are analytical signals, not accusations.
