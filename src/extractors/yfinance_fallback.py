"""yfinance fallback when NSE blocks automated downloads."""
from datetime import date, timedelta

from .base import NotAvailable, write_bronze


def extract_yf(d: date, symbols: list[str], client=None) -> str:
    import yfinance as yf

    tickers = [f"{s}.NS" for s in symbols]
    df = yf.download(tickers, start=d.isoformat(), end=(d + timedelta(days=1)).isoformat(),
                     auto_adjust=False, group_by="ticker", progress=False)
    if df.empty:
        raise NotAvailable(f"yfinance has no data for {d}")
    long = df.stack(level=0, future_stack=True).reset_index()
    long.columns = [str(c).lower().replace(" ", "_") for c in long.columns]
    return write_bronze("yfinance_prices", d, f"yf_{d:%Y%m%d}.csv",
                        long.to_csv(index=False).encode(), client)
