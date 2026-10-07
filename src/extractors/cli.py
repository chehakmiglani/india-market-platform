"""Usage: python -m src.extractors.cli --date 2026-10-07 [--source all|nse|amfi]"""
import argparse
import logging
from datetime import date

from dotenv import load_dotenv

from . import amfi, nse
from .base import NotAvailable

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("cli")

DEFAULT_SYMBOLS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--date", type=date.fromisoformat, default=date.today())
    p.add_argument("--source", choices=["all", "nse", "amfi"], default="all")
    a = p.parse_args()

    if a.source in ("all", "nse"):
        try:
            nse.extract_prices_with_fallback(a.date, DEFAULT_SYMBOLS)
            nse.extract_indices(a.date)
        except NotAvailable as e:
            log.info("NSE skipped: %s", e)
    if a.source in ("all", "amfi"):
        amfi.extract_navall(a.date)


if __name__ == "__main__":
    main()
