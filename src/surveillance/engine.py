"""Surveillance step: dbt has already scored every stock-day; this loads the day's alerts
and adds a one-line news triage to the HIGH ones."""
import logging
from datetime import date

import duckdb

from src.alerts.triage import triage_alerts

log = logging.getLogger("surveillance")


def load_alerts(d: date, db_path: str) -> list[dict]:
    with duckdb.connect(db_path, read_only=True) as con:
        cur = con.execute("""
            select alert_id, trade_date, symbol, company_name, industry, risk_score, risk_band,
                   rules_triggered, reason, news_types, material_news_count, exchange_query
            from gold.fact_surveillance_alert where trade_date = ?
            order by risk_score desc, symbol""", [d])
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def run_surveillance(d: date, db_path: str) -> list[dict]:
    alerts = load_alerts(d, db_path)
    high = [a for a in alerts if a["risk_band"] == "HIGH"]
    for a_id, t in triage_alerts(high, db_path).items():
        a = next(x for x in high if x["alert_id"] == a_id)
        a.update(verdict=t.verdict, triage=t.line, triage_source=t.source)
    log.info("%d alerts (%d HIGH) for %s", len(alerts), len(high), d)
    return alerts
