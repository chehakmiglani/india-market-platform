"""XIRR per owner (whole portfolio) and per holding: all dated cash flows plus
today's market value as a final inflow. Solver lives in src/analytics/xirr.py (unit-tested).

XIRR annualises, so on a 3-week-old holding a 4% move shows as ~80% a year. Like
Indian broker apps, `display_return_pct` shows absolute return under 1 year, XIRR after.
"""
import os
import sys

import pandas as pd

MIN_DAYS_FOR_XIRR = 365


def model(dbt, session):
    dbt.config(materialized="table")
    sys.path.insert(0, os.getcwd())  # dbt runs from the repo root
    from src.analytics.xirr import xirr

    txn = dbt.ref("fact_portfolio_txn").df()
    hold = dbt.ref("mart_portfolio_holdings").df()

    def row(owner, level, ac, inst, t, h, as_of):
        flows = [(pd.Timestamp(d).date(), float(cf)) for d, cf in zip(t["txn_date"], t["cash_flow"])]
        current_value = float(h["current_value"].fillna(0).sum())
        invested = -sum(cf for _, cf in flows if cf < 0)
        received = sum(cf for _, cf in flows if cf > 0)
        first = min(d for d, _ in flows)
        holding_days = (as_of - first).days
        r = xirr(flows + [(as_of, current_value)])
        abs_ret = (current_value + received - invested) / invested * 100 if invested else None
        meaningful = holding_days >= MIN_DAYS_FOR_XIRR
        return {
            "owner": owner, "level": level, "asset_class": ac, "instrument_id": inst,
            "as_of_date": as_of, "first_txn_date": first, "holding_days": holding_days,
            "total_invested": round(invested, 2), "total_received": round(received, 2),
            "current_value": round(current_value, 2),
            "absolute_return_pct": None if abs_ret is None else round(abs_ret, 2),
            "xirr_pct": None if r is None else round(r * 100, 2),
            "xirr_is_meaningful": meaningful,
            "display_return_pct": (None if r is None else round(r * 100, 2)) if meaningful
                                  else (None if abs_ret is None else round(abs_ret, 2)),
            "display_return_type": "XIRR" if meaningful else "ABSOLUTE",
        }

    rows = []
    for owner, h_owner in hold.groupby("owner"):
        as_of = pd.to_datetime(h_owner["price_date"]).max().date()
        t_owner = txn[txn["owner"] == owner]
        rows.append(row(owner, "PORTFOLIO", None, None, t_owner, h_owner, as_of))
        for (ac, inst), h in h_owner.groupby(["asset_class", "instrument_id"]):
            t = t_owner[(t_owner["asset_class"] == ac) & (t_owner["instrument_id"] == inst)]
            rows.append(row(owner, "HOLDING", ac, inst, t, h, as_of))
    return pd.DataFrame(rows)
