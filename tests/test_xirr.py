from datetime import date

import pytest

from src.analytics.xirr import xirr


def test_one_year_ten_percent():
    assert xirr([(date(2025, 1, 1), -1000), (date(2026, 1, 1), 1100)]) == pytest.approx(0.10, abs=1e-6)


def test_matches_excel_reference():
    # Excel XIRR example: -10000, 2750, 4250, 3250, 2750 -> 37.34%
    flows = [(date(2008, 1, 1), -10000), (date(2008, 3, 1), 2750), (date(2008, 10, 30), 4250),
             (date(2009, 2, 15), 3250), (date(2009, 4, 1), 2750)]
    assert xirr(flows) == pytest.approx(0.373363, abs=1e-5)


def test_loss_is_negative():
    assert xirr([(date(2025, 1, 1), -1000), (date(2026, 1, 1), 800)]) == pytest.approx(-0.20, abs=1e-6)


def test_monthly_sip():
    flows = [(date(2025, m, 1), -5000) for m in range(1, 13)] + [(date(2026, 1, 1), 64000)]
    r = xirr(flows)
    assert 0.12 < r < 0.15


def test_no_sign_change_returns_none():
    assert xirr([(date(2025, 1, 1), -1000), (date(2025, 6, 1), -500)]) is None
    assert xirr([]) is None
