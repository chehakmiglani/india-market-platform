"""End-of-day pipeline, runnable without Airflow (the Airflow DAG calls the same steps).

    python -m src.pipeline.daily                       # today
    python -m src.pipeline.daily --date 2026-10-06
    python -m src.pipeline.daily --date 2026-10-06 --from-step silver   # resume

Steps: calendar -> extract -> silver -> dbt -> surveillance -> quality -> alerts.
A weekend or official NSE holiday ends the run early with status SKIPPED (exit 0).
A trading day without a bhavcopy yet exits 3 (not published: the scheduler waits and retries);
any other failure exits 1; data-quality FAILs exit 2 after the digest is sent.
"""
import argparse
import logging
import os
import subprocess
import sys
import time
import uuid
from datetime import date, datetime, timedelta

import duckdb
from dotenv import load_dotenv

from src.extractors import amfi, nse
from src.extractors.base import NotAvailable
from src.extractors.cli import DEFAULT_SYMBOLS, fund_watchlist
from src.pipeline.calendar import is_trading_day, official_holidays

log = logging.getLogger("pipeline")
DB = os.getenv("DUCKDB_PATH", "data/warehouse/market.duckdb")
STEPS = ["calendar", "extract", "silver", "dbt", "surveillance", "quality", "alerts"]


class Skip(Exception):
    """Not a trading day: stop cleanly."""


class NotPublished(Exception):
    """Trading day, but NSE has not published the bhavcopy yet: worth retrying later."""


# ---------- steps ----------

def step_calendar(d: date, ctx: dict) -> str:
    try:
        nse.extract_holidays(d)
    except Exception as e:  # stale calendar is acceptable; weekends still handled
        log.warning("holiday refresh failed (%s); using last snapshot", e)
    holidays = official_holidays()
    if not is_trading_day(d, holidays):
        raise Skip(holidays.get(d, "weekend"))
    return f"{d} is a trading day"


def step_extract(d: date, ctx: dict) -> str:
    try:
        nse.extract_prices_with_fallback(d, DEFAULT_SYMBOLS)
    except NotAvailable as e:
        raise NotPublished(f"trading day but bhavcopy not available yet: {e}") from e
    nse.extract_indices(d)
    amfi.extract_navall(d)
    for code in fund_watchlist():
        amfi.extract_mfapi_history(code, d)
    # Splits are announced ahead of the ex-date; look back for late filings, ahead for new ones
    nse.extract_corporate_actions(d - timedelta(days=30), d + timedelta(days=60), d)
    # Context for surveillance triage; 3-day lookback catches filings made over a weekend
    nse.extract_announcements(d - timedelta(days=3), d, d)
    if d == date.today():  # the lists are "as of now": a backfilled day must not get today's list
        try:  # a missed snapshot only loses one day of ASM/GSM history; don't fail the run
            nse.extract_surveillance_lists(d)
        except Exception as e:
            log.warning("ASM/GSM snapshot failed (%s)", e)
    if d.weekday() == 0 or ctx.get("force_reference"):  # equity master weekly (Mondays)
        nse.extract_reference(d)
    return "prices, indices, NAVs, corporate actions"


def _run(cmd: list[str]) -> str:
    env = {**os.environ, "PYTHONUTF8": "1"}
    p = subprocess.run(cmd, capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    tail = "\n".join((p.stdout + p.stderr).strip().splitlines()[-15:])
    if p.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:4])} exited {p.returncode}\n{tail}")
    return tail


def step_silver(d: date, ctx: dict) -> str:
    out = _run([sys.executable, "-m", "src.spark_jobs.silver", "--date", d.isoformat()])
    return out.splitlines()[-1] if out else "ok"


def step_dbt(d: date, ctx: dict) -> str:
    out = _run(["dbt", "build", "--project-dir", "dbt", "--profiles-dir", "dbt"])
    return next((l for l in reversed(out.splitlines()) if "Done." in l), "ok")


def step_surveillance(d: date, ctx: dict) -> str:
    from src.surveillance.engine import run_surveillance
    alerts = run_surveillance(d, DB)
    ctx["alerts"] = alerts
    return f"{len(alerts)} alerts"


def step_quality(d: date, ctx: dict) -> str:
    from src.quality.checks import run_checks
    results = run_checks(d, DB)
    ctx["dq"] = results
    bad = [r for r in results if r.status == "FAIL"]
    if bad:  # don't stop: alerts step still reports them
        ctx["dq_failed"] = True
    return ", ".join(f"{r.check}={r.status}" for r in results)


def step_alerts(d: date, ctx: dict) -> str:
    from src.alerts.notify import send_daily_digest
    return send_daily_digest(d, ctx.get("alerts", []), ctx.get("dq", []), DB)


STEP_FUNCS = {"calendar": step_calendar, "extract": step_extract, "silver": step_silver,
              "dbt": step_dbt, "surveillance": step_surveillance, "quality": step_quality,
              "alerts": step_alerts}


# ---------- run log ----------

def _record(run_id, d, step, status, started, detail):
    try:
        with duckdb.connect(DB) as con:
            con.execute("create schema if not exists ops")
            con.execute("""create table if not exists ops.pipeline_runs (
                run_id varchar, run_date date, step varchar, status varchar,
                started_at timestamp, ended_at timestamp, duration_s double, detail varchar)""")
            con.execute("insert into ops.pipeline_runs values (?,?,?,?,?,?,?,?)",
                        [run_id, d, step, status, started, datetime.now(),
                         round((datetime.now() - started).total_seconds(), 1), detail[:2000]])
    except duckdb.Error as e:
        log.warning("could not record run step: %s", e)


def run(d: date, from_step: str = "calendar", only: list[str] | None = None,
        force_reference: bool = False) -> int:
    run_id = uuid.uuid4().hex[:12]
    ctx = {"force_reference": force_reference}
    steps = only or STEPS[STEPS.index(from_step):]
    log.info("run %s for %s: %s", run_id, d, " -> ".join(steps))
    for step in steps:
        started, t0 = datetime.now(), time.time()
        try:
            detail = STEP_FUNCS[step](d, ctx)
            _record(run_id, d, step, "SUCCESS", started, detail)
            log.info("%-12s SUCCESS %5.1fs  %s", step, time.time() - t0, detail.splitlines()[0] if detail else "")
        except Skip as e:
            _record(run_id, d, step, "SKIPPED", started, f"not a trading day: {e}")
            log.info("%s is not a trading day (%s); nothing to do", d, e)
            return 0
        except NotPublished as e:
            _record(run_id, d, step, "FAILED", started, str(e))
            log.warning("%-12s WAITING %5.1fs  %s", step, time.time() - t0, e)
            return 3
        except Exception as e:
            _record(run_id, d, step, "FAILED", started, str(e))
            log.error("%-12s FAILED  %5.1fs  %s", step, time.time() - t0, e)
            return 1
    return 2 if ctx.get("dq_failed") else 0


def main():
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--date", type=date.fromisoformat, default=date.today())
    p.add_argument("--from-step", choices=STEPS, default="calendar")
    p.add_argument("--only", nargs="+", choices=STEPS)
    p.add_argument("--force-reference", action="store_true")
    a = p.parse_args()
    sys.exit(run(a.date, a.from_step, a.only, a.force_reference))


if __name__ == "__main__":
    main()
