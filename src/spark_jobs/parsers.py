"""Pure-Python parsers for messy source formats (unit-tested, no Spark needed)."""
import re
from datetime import date, datetime

_SPLIT = re.compile(r"From\s+R[es]\.?\s*([\d.]+).*?To\s+R[es]\.?\s*([\d.]+)", re.I)
_BONUS = re.compile(r"Bonus\s+(\d+)\s*:\s*(\d+)", re.I)


def adjustment_factor(subject: str) -> tuple[str, float] | None:
    """Return (action_type, factor) for price-changing actions, else None.

    Prices before the ex-date are divided by `factor`, volumes multiplied.
      "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share" -> 10.0
      "Bonus 2:1"  (2 new for every 1 held)  -> 3.0
    """
    if not subject:
        return None
    m = _SPLIT.search(subject)
    if m and "split" in subject.lower():
        old, new = float(m.group(1)), float(m.group(2))
        if old > 0 and new > 0 and old != new:
            return "SPLIT", old / new
    m = _BONUS.search(subject)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a > 0 and b > 0:
            return "BONUS", (a + b) / b
    return None


def parse_navall(text: str) -> list[dict]:
    """AMFI NAVAll.txt -> rows. The file interleaves section headers with data:

        Open Ended Schemes(Equity Scheme - Large Cap Fund)   <- category
        Aditya Birla Sun Life Mutual Fund                    <- AMC
        119551;INF209K01YM8;-;Scheme name;...;123.45;06-Oct-2026
    """
    rows, category, amc = [], None, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("Scheme Code"):
            continue
        parts = line.split(";")
        if len(parts) >= 6 and parts[0].strip().isdigit():
            # Newer files: code;isin_growth;isin_reinv;name;nav;date
            # Older files carry extra Plan/Option columns; NAV and date are always last two.
            nav_s, date_s = parts[-2].strip(), parts[-1].strip()
            try:
                nav = float(nav_s)
            except ValueError:
                nav = None  # "N.A." etc.
            try:
                nav_date = datetime.strptime(date_s, "%d-%b-%Y").date()
            except ValueError:
                continue
            rows.append({
                "scheme_code": int(parts[0]),
                "isin_growth": _nz(parts[1]),
                "isin_reinvest": _nz(parts[2]),
                "scheme_name": parts[3].strip(),
                "nav": nav,
                "nav_date": nav_date,
                "amc": amc,
                "category": category,
            })
        elif ";" not in line:
            if "Schemes" in line and "(" in line:
                category = line[line.index("(") + 1:].rstrip(")").strip()
            else:
                amc = line
    return rows


def parse_mfapi(payload: dict) -> list[dict]:
    """mfapi.in /mf/{code} -> rows. Dates are dd-mm-yyyy, NAVs are strings."""
    meta = payload.get("meta") or {}
    code = int(meta["scheme_code"])
    rows = []
    for r in payload.get("data") or []:
        try:
            nav = float(r["nav"])
            d = datetime.strptime(r["date"], "%d-%m-%Y").date()
        except (KeyError, ValueError):
            continue
        if nav > 0:
            rows.append({"scheme_code": code, "nav_date": d, "nav": nav,
                         "scheme_name": meta.get("scheme_name"), "amc": meta.get("fund_house"),
                         "category": meta.get("scheme_category")})
    return rows


def _nz(s: str) -> str | None:
    s = s.strip()
    return None if s in ("", "-") else s


def parse_nse_date(s: str) -> date:
    return datetime.strptime(s.strip(), "%d-%b-%Y").date()
