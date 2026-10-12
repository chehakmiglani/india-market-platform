"""Daily Telegram digest: every HIGH alert with its triage line, plus a short watchlist of
new MEDIUM names. 1-2 messages a day instead of ~85 raw alerts.

Without TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID the digest is written to logs/ instead.
"""
import logging
import os
from datetime import date
from pathlib import Path

import duckdb
import requests

log = logging.getLogger("alerts.notify")

WATCHLIST_SIZE = 10
REPEAT_LOOKBACK_DAYS = 5   # trading days; names alerted recently are not repeated in the watchlist
TELEGRAM_LIMIT = 4000      # API max is 4096 chars per message
ICON = {"EXPLAINED": "✅", "UNCLEAR": "❔", "UNEXPLAINED": "🔎"}


def recently_alerted(d: date, db_path: str) -> set[str]:
    with duckdb.connect(db_path, read_only=True) as con:
        rows = con.execute("""
            with days as (select distinct trade_date from gold.fact_surveillance_alert
                          where trade_date < ? order by trade_date desc limit ?)
            select distinct symbol from gold.fact_surveillance_alert
            where trade_date in (select trade_date from days)""", [d, REPEAT_LOOKBACK_DAYS]).fetchall()
    return {r[0] for r in rows}


def build_digest(d: date, alerts: list[dict], dq: list, seen: set[str]) -> str:
    high = [a for a in alerts if a["risk_band"] == "HIGH"]
    medium = [a for a in alerts if a["risk_band"] == "MEDIUM" and a["symbol"] not in seen]
    lines = [f"📊 NSE surveillance: {d:%d %b %Y}",
             f"{len(alerts)} flagged · {len(high)} HIGH · "
             f"{sum(a['risk_band'] == 'MEDIUM' for a in alerts)} MEDIUM", ""]

    lines.append(f"🚨 HIGH ({len(high)})" if high else "🚨 No HIGH alerts today")
    for a in high:
        lines += [f"• {a['symbol']} ({a['risk_score']:.0f}) {a.get('company_name') or ''}".rstrip(),
                  f"  {a['reason']}"]
        if a.get("triage"):
            lines.append(f"  {ICON.get(a.get('verdict'), '•')} {a['triage']}")
    lines.append("")

    if medium:
        lines.append(f"👀 Watchlist: top {min(WATCHLIST_SIZE, len(medium))} new MEDIUM names")
        for a in medium[:WATCHLIST_SIZE]:
            news = f" · news: {a['news_types'].replace('_', ' ').lower()}" if a.get("news_types") else ""
            query = " · NSE query" if a.get("exchange_query") else ""
            lines.append(f"• {a['symbol']} ({a['risk_score']:.0f}) {a['rules_triggered'].lower()}{news}{query}")
        lines.append("")

    bad = [r for r in dq if r.status != "PASS"]
    lines.append("🩺 Data quality: " + ("not checked in this run" if not dq else
                 "all checks passed" if not bad else
                 "; ".join(f"{r.check}={r.status}" for r in bad)))
    lines.append("Signals for analysis, not accusations.")
    return "\n".join(lines)


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Split on line boundaries so no alert is cut in half."""
    chunks, cur = [], ""
    for line in text.splitlines(keepends=True):
        if len(cur) + len(line) > limit and cur:
            chunks.append(cur)
            cur = ""
        cur += line
    return chunks + [cur] if cur else chunks


def send_telegram(text: str, token: str, chat_id: str) -> int:
    chunks = split_message(text)
    for chunk in chunks:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True},
                          timeout=30)
        r.raise_for_status()
    return len(chunks)


def send_daily_digest(d: date, alerts: list[dict], dq: list, db_path: str) -> str:
    text = build_digest(d, alerts, dq, recently_alerted(d, db_path))
    out = Path("logs") / f"digest_{d}.txt"
    out.parent.mkdir(exist_ok=True)
    out.write_text(text, encoding="utf-8")
    token, chat_id = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        return f"Telegram not configured; digest written to {out}"
    n = send_telegram(text, token, chat_id)
    return f"sent {n} Telegram message(s); copy in {out}"
