"""Usage:
    python -m src.extractors.cli --date 2026-10-07 [--source all|nse|amfi]
    python -m src.extractors.cli --start 2026-09-01 --end 2026-10-06 --source nse
    python -m src.extractors.cli --date 2026-10-07 --source corp_actions
    python -m src.extractors.cli --date 2026-10-07 --source reference   # equity list + industries
    python -m src.extractors.cli --date 2026-10-07 --source mfapi       # NAV history for watchlist
"""
import argparse
import csv
import logging
from datetime import date, timedelta

from dotenv import load_dotenv

from . import amfi, nse
from .base import NotAvailable

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("cli")

DEFAULT_SYMBOLS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]


def fund_watchlist(path: str = "config/fund_watchlist.csv") -> list[int]:
    with open(path, newline="", encoding="utf-8") as f:
        return [int(r["scheme_code"]) for r in csv.DictReader(f)]


def run_day(d: date, source: str) -> None:
    if source in ("all", "nse"):
        try:
            nse.extract_prices_with_fallback(d, DEFAULT_SYMBOLS)
            nse.extract_indices(d)
        except NotAvailable as e:
            log.info("NSE skipped %s: %s", d, e)
    if source in ("all", "amfi"):
        amfi.extract_navall(d)


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--date", type=date.fromisoformat, default=date.today())
    p.add_argument("--start", type=date.fromisoformat)
    p.add_argument("--end", type=date.fromisoformat)
    p.add_argument("--source", default="all",
                   choices=["all", "nse", "amfi", "corp_actions", "reference", "mfapi"])
    a = p.parse_args()

    if a.source == "corp_actions":
        start = a.start or a.date - timedelta(days=365)
        nse.extract_corporate_actions(start, a.end or a.date, a.date)
        return
    if a.source == "reference":
        nse.extract_reference(a.date)
        return
    if a.source == "mfapi":
        for code in fund_watchlist():
            amfi.extract_mfapi_history(code, a.date)
        return

    days = [a.date]
    if a.start:
        end = a.end or a.date
        days = [a.start + timedelta(n) for n in range((end - a.start).days + 1)]
    for d in days:
        if d.weekday() >= 5:  # weekends; exchange holidays are handled via NotAvailable
            continue
        run_day(d, a.source)


if __name__ == "__main__":
    main()
