import pytest

from src.spark_jobs.parsers import adjustment_factor, parse_navall


@pytest.mark.parametrize("subject,expected", [
    ("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share", ("SPLIT", 5.0)),
    ("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share", ("SPLIT", 10.0)),
    ("Face Value Split (Sub-Division) - From Rs 5/- Per Share To Re 1/- Per Share", ("SPLIT", 5.0)),
    ("Bonus 1:1", ("BONUS", 2.0)),
    ("Bonus 2:1", ("BONUS", 3.0)),
    ("Bonus 7:5", ("BONUS", 2.4)),
    ("Interim Dividend - Rs 5 Per Share", None),
    ("Annual General Meeting", None),
    ("", None),
])
def test_adjustment_factor(subject, expected):
    got = adjustment_factor(subject)
    if expected is None:
        assert got is None
    else:
        assert got[0] == expected[0]
        assert got[1] == pytest.approx(expected[1])


NAVALL = """Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date

Open Ended Schemes(Equity Scheme - Large Cap Fund)

Aditya Birla Sun Life Mutual Fund

119551;INF209K01YM8;-;ABSL Frontline Equity Fund - Growth;512.3456;06-Oct-2026
119552;INF209K01YN6;INF209K01YO4;ABSL Frontline Equity Fund - IDCW;N.A.;06-Oct-2026

Open Ended Schemes(Debt Scheme - Liquid Fund)

HDFC Mutual Fund

100001;INF179K01AB1;-;HDFC Liquid Fund - Growth;4800.1;03-Oct-2026
"""


def test_parse_navall_tracks_category_and_amc():
    rows = parse_navall(NAVALL)
    assert len(rows) == 3
    assert rows[0]["scheme_code"] == 119551
    assert rows[0]["nav"] == pytest.approx(512.3456)
    assert rows[0]["amc"] == "Aditya Birla Sun Life Mutual Fund"
    assert rows[0]["category"] == "Equity Scheme - Large Cap Fund"
    assert rows[0]["isin_reinvest"] is None
    assert rows[1]["nav"] is None  # N.A.
    assert rows[2]["category"] == "Debt Scheme - Liquid Fund"
    assert rows[2]["amc"] == "HDFC Mutual Fund"
    assert str(rows[2]["nav_date"]) == "2026-10-03"
