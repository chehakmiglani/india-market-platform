import json
from datetime import date

from src.pipeline.calendar import (expected_trading_days, is_trading_day, official_holidays,
                                   previous_trading_day)

HOL = {date(2026, 10, 2): "Gandhi Jayanti"}


def test_weekend_and_holiday_are_not_trading_days():
    assert not is_trading_day(date(2026, 10, 3), HOL)   # Saturday
    assert not is_trading_day(date(2026, 10, 2), HOL)   # holiday
    assert is_trading_day(date(2026, 10, 1), HOL)


def test_previous_trading_day_skips_weekend_and_holiday():
    # Mon 5 Oct -> skips Sun, Sat, and Fri 2 Oct (holiday) -> Thu 1 Oct
    assert previous_trading_day(date(2026, 10, 5), HOL) == date(2026, 10, 1)


def test_expected_trading_days():
    days = expected_trading_days(date(2026, 9, 28), date(2026, 10, 6), HOL)
    assert date(2026, 10, 2) not in days and date(2026, 10, 3) not in days
    assert len(days) == 6


def test_official_holidays_reads_bronze(tmp_path):
    p = tmp_path / "bronze" / "nse_holidays" / "dt=2026-10-08"
    p.mkdir(parents=True)
    (p / "holidays.json").write_text(json.dumps(
        {"CM": [{"tradingDate": "02-Oct-2026", "description": "Gandhi Jayanti"}, {"tradingDate": "bad"}]}))
    assert official_holidays(tmp_path) == HOL
