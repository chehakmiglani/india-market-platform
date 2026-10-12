"""Pipeline data-quality checks -> ops.dq_results (feeds the Data Health dashboard).

Complements dbt tests (row-level rules) with pipeline-level checks: missing files,
stale data, partial loads, quarantined rows, unexplained price moves.
"""
import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import duckdb

from src.pipeline.calendar import expected_trading_days, lake_root, official_holidays

log = logging.getLogger("quality")

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


@dataclass
class CheckResult:
    check: str
    status: str
    value: float | None
    detail: str


def _scalar(con, sql, params=None):
    r = con.execute(sql, params or []).fetchone()
    return r[0] if r else None


def check_missing_files(run_date: date, root: Path, holidays) -> CheckResult:
    days = expected_trading_days(run_date - timedelta(days=14), run_date, holidays)
    base = root / "bronze" / "nse_bhavcopy"
    missing = [d for d in days if not (base / f"dt={d}").exists()]
    return CheckResult("missing_bhavcopy_files", FAIL if missing else PASS, len(missing),
                       "missing: " + ", ".join(map(str, missing)) if missing
                       else f"all {len(days)} trading days in the last 14 days present")


def check_stale_prices(con, run_date: date, holidays) -> CheckResult:
    latest = _scalar(con, "select max(trade_date) from gold.fact_stock_daily")
    expected = max(expected_trading_days(run_date - timedelta(days=10), run_date, holidays))
    lag = len(expected_trading_days(latest + timedelta(days=1), expected, holidays)) if latest else 99
    status = PASS if lag == 0 else WARN if lag == 1 else FAIL
    return CheckResult("stale_stock_prices", status, lag,
                       f"latest trade_date {latest}, expected {expected} ({lag} trading days behind)")


def check_stale_nav(con, run_date: date) -> CheckResult:
    latest = _scalar(con, "select max(nav_date) from gold.fact_fund_nav")
    age = (run_date - latest).days if latest else 99
    status = PASS if age <= 4 else WARN if age <= 7 else FAIL
    return CheckResult("stale_fund_nav", status, age, f"latest NAV date {latest} ({age} days old)")


def check_row_count(con, run_date: date) -> CheckResult:
    r = con.execute("""
        with c as (select trade_date, count(*) n from gold.fact_stock_daily
                   where trade_date <= ? group by 1 order by 1 desc limit 21)
        select (select n from c order by trade_date desc limit 1),
               (select avg(n) from (select n from c order by trade_date desc offset 1))
    """, [run_date]).fetchone()
    today, avg20 = r if r else (None, None)
    if not today or not avg20:
        return CheckResult("row_count_vs_20d_avg", WARN, None, "not enough history")
    ratio = today / avg20
    status = PASS if ratio >= 0.9 else WARN if ratio >= 0.8 else FAIL
    return CheckResult("row_count_vs_20d_avg", status, round(ratio, 3),
                       f"{today} stocks vs 20-day avg {avg20:.0f}")


def check_quarantine(run_date: date, root: Path) -> CheckResult:
    q = root / "silver" / "_quarantine_stock_daily"
    if not q.exists():
        return CheckResult("quarantined_price_rows", PASS, 0, "no quarantine table (no bad rows ever)")
    con = duckdb.connect()
    con.execute("load delta")
    n = _scalar(con, f"select count(*) from delta_scan('{q.as_posix()}') where trade_date = ?", [run_date])
    status = PASS if n == 0 else WARN if n < 20 else FAIL
    return CheckResult("quarantined_price_rows", status, n, f"{n} bad price rows on {run_date}")


def check_unexplained_moves(con, run_date: date) -> CheckResult:
    n, examples = con.execute("""
        select count(*), string_agg(symbol || ' ' || round(return_pct, 1) || '%', ', ')
        from (
            select f.symbol, f.return_pct from gold.fact_stock_daily f
            left join staging.stg_corporate_actions ca
              on ca.symbol = f.symbol and ca.ex_date = f.trade_date
            where f.trade_date = ? and abs(f.return_pct) > 25 and ca.symbol is null
            order by abs(f.return_pct) desc limit 50)
    """, [run_date]).fetchone()
    status = PASS if n <= 10 else WARN
    return CheckResult("moves_over_25pct_without_corp_action", status, n, examples or "none")


def check_dbt_results(target: Path = Path("dbt/target/run_results.json")) -> CheckResult:
    if not target.exists():
        return CheckResult("dbt_build", WARN, None, "no dbt run_results.json")
    res = json.loads(target.read_text(encoding="utf-8"))["results"]
    bad = [r["unique_id"].split(".")[-1] for r in res if r["status"] in ("error", "fail")]
    warn = [r["unique_id"].split(".")[-1] for r in res if r["status"] == "warn"]
    status = FAIL if bad else WARN if warn else PASS
    return CheckResult("dbt_build", status, len(bad),
                       f"{len(res)} nodes; failed: {', '.join(bad) or 'none'}; warned: {', '.join(warn) or 'none'}")


def run_checks(run_date: date, db_path: str = "data/warehouse/market.duckdb",
               root: Path | None = None) -> list[CheckResult]:
    root = root or lake_root()
    holidays = official_holidays(root)
    results = [check_missing_files(run_date, root, holidays), check_quarantine(run_date, root),
               check_dbt_results()]
    with duckdb.connect(db_path) as con:
        results += [check_stale_prices(con, run_date, holidays), check_stale_nav(con, run_date),
                    check_row_count(con, run_date), check_unexplained_moves(con, run_date)]
        con.execute("create schema if not exists ops")
        con.execute("""create table if not exists ops.dq_results (
            run_date date, check_name varchar, status varchar, value double, detail varchar,
            checked_at timestamp default current_timestamp)""")
        con.execute("delete from ops.dq_results where run_date = ?", [run_date])  # idempotent
        con.executemany("insert into ops.dq_results (run_date, check_name, status, value, detail) values (?,?,?,?,?)",
                        [[run_date, r.check, r.status, r.value, r.detail] for r in results])
    for r in results:
        log.log(logging.WARNING if r.status != PASS else logging.INFO,
                "[%s] %s = %s | %s", r.status, r.check, r.value, r.detail)
    return results
