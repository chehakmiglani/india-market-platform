"""NSE trading calendar: weekends + official holidays (landed in bronze/nse_holidays)."""
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path


def lake_root() -> Path:
    return Path(os.getenv("LAKE_ROOT", "data/lake"))


def official_holidays(root: Path | None = None) -> dict[date, str]:
    """{date: description} from every holiday snapshot landed so far."""
    out: dict[date, str] = {}
    base = (root or lake_root()) / "bronze" / "nse_holidays"
    for f in sorted(base.glob("dt=*/holidays.json")):
        for h in json.loads(f.read_text(encoding="utf-8")).get("CM", []):
            try:
                out[datetime.strptime(h["tradingDate"], "%d-%b-%Y").date()] = h.get("description", "")
            except (KeyError, ValueError):
                continue
    return out


def is_trading_day(d: date, holidays: dict[date, str]) -> bool:
    return d.weekday() < 5 and d not in holidays


def previous_trading_day(d: date, holidays: dict[date, str]) -> date:
    d -= timedelta(days=1)
    while not is_trading_day(d, holidays):
        d -= timedelta(days=1)
    return d


def expected_trading_days(start: date, end: date, holidays: dict[date, str]) -> list[date]:
    return [start + timedelta(n) for n in range((end - start).days + 1)
            if is_trading_day(start + timedelta(n), holidays)]
