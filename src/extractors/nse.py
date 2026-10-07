"""NSE extractors: full bhavcopy (prices + delivery %), indices. Falls back to yfinance."""
import io
import logging
from datetime import date

from .base import NotAvailable, make_session, polite_get, write_bronze

log = logging.getLogger("extractors.nse")

# Full bhavcopy incl. DELIV_QTY / DELIV_PER
BHAV_FULL_URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
INDEX_URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{ddmmyyyy}.csv"


def _fetch(url: str, d: date) -> bytes:
    s = make_session()
    s.get("https://www.nseindia.com/", timeout=30)  # warm cookies
    r = polite_get(s, url)
    if r.status_code == 404:
        raise NotAvailable(f"{url} -> 404 (holiday or not published)")
    r.raise_for_status()
    if not r.content or r.content[:1] == b"<":  # HTML block page, not CSV
        raise RuntimeError("NSE returned HTML (likely blocked)")
    return r.content


def extract_bhavcopy(d: date, client=None) -> str:
    url = BHAV_FULL_URL.format(ddmmyyyy=d.strftime("%d%m%Y"))
    content = _fetch(url, d)
    return write_bronze("nse_bhavcopy", d, f"sec_bhavdata_full_{d:%d%m%Y}.csv", content, client)


def extract_indices(d: date, client=None) -> str:
    url = INDEX_URL.format(ddmmyyyy=d.strftime("%d%m%Y"))
    content = _fetch(url, d)
    return write_bronze("nse_indices", d, f"ind_close_all_{d:%d%m%Y}.csv", content, client)


def extract_prices_with_fallback(d: date, symbols: list[str], client=None) -> str:
    """Try NSE; if blocked (not a holiday), fall back to yfinance for given symbols."""
    try:
        return extract_bhavcopy(d, client)
    except NotAvailable:
        raise
    except Exception as e:  # blocked / network
        log.warning("NSE failed (%s); falling back to yfinance", e)
        from .yfinance_fallback import extract_yf
        return extract_yf(d, symbols, client)
