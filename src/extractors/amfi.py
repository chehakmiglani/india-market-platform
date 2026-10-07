"""AMFI daily NAVAll (all funds) and mfapi.in (per-scheme history)."""
import json
import logging
from datetime import date

from .base import make_session, polite_get, write_bronze

log = logging.getLogger("extractors.amfi")

NAVALL_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"
MFAPI_URL = "https://api.mfapi.in/mf/{code}"


def extract_navall(d: date, client=None) -> str:
    """NAVAll is a snapshot of the latest NAV; stored under the run date."""
    r = polite_get(make_session(), NAVALL_URL)
    r.raise_for_status()
    if b"Scheme Code" not in r.content[:500]:
        raise RuntimeError("Unexpected NAVAll format (schema change?)")
    return write_bronze("amfi_navall", d, "NAVAll.txt", r.content, client)


def extract_mfapi_history(code: int, d: date, client=None) -> str:
    r = polite_get(make_session(), MFAPI_URL.format(code=code))
    r.raise_for_status()
    payload = r.json()
    if payload.get("status") == "ERROR" or not payload.get("data"):
        raise RuntimeError(f"mfapi: no data for scheme {code}")
    return write_bronze("mfapi_history", d, f"{code}.json",
                        json.dumps(payload).encode(), client)
