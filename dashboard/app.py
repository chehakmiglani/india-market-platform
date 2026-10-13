"""Dashboard on the Gold tables.   streamlit run dashboard/app.py   (from the repo root)

Read-only on the warehouse. Each query opens and closes its own connection so the daily
pipeline (which needs the write lock) is never blocked by an open dashboard.
Hover any mark for its details; click a dot or a table row to open the stock.
The paper portfolio is virtual money, kept in data/local/ (not committed).
"""
import json
import os
from datetime import date
from html import escape
from pathlib import Path

import duckdb
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)  # staging views read the lake by relative path
DB = os.getenv("DUCKDB_PATH", "data/warehouse/market.duckdb")
PAPER = ROOT / "data" / "local" / "paper_portfolio.json"

# Colour by job: band = status (always shown with its label), blue = the data series, grey = context.
BAND = {"HIGH": "#d03b3b", "MEDIUM": "#eda100", "LOW": "#a6a49c"}
BLUE, GREY, UP, DOWN = "#2a78d6", "#a6a49c", "#1baf7a", "#e34948"
INK, INK2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
RULES = {"pts_volume": "Volume spike", "pts_price_shock": "Price shock", "pts_pump": "Pump pattern",
         "pts_dump": "Dump after pump", "pts_delivery": "Delivery anomaly", "pts_circuit": "Circuit streak",
         "pts_gap": "Gap move", "pts_illiquid": "Thinly traded"}
VERDICT = {"EXPLAINED": ("Explained by news", "ok"), "UNCLEAR": ("Partly explained", "warn"),
           "UNEXPLAINED": ("Unexplained", "bad")}
DISCLAIMER = ("Virtual money on past data. Surveillance flags are signals for analysis, not accusations, "
              "and nothing here is investment advice.")
NOBAR = {"displayModeBar": False}
LABEL_POS = ["top center", "middle left", "bottom center", "middle right", "top left", "bottom right"]

st.set_page_config(page_title="NSE surveillance", page_icon="📈", layout="wide")
st.markdown("""<style>
.block-container {padding-top: 3.2rem; max-width: 1280px;}
h1 {font-size: 1.55rem !important; font-weight: 600 !important; margin-bottom: 0 !important;}
h3 {font-size: 1.02rem !important; font-weight: 600 !important; padding-bottom: .2rem !important;}
.sub {color: #52514e; font-size: .9rem; margin: .1rem 0 1rem;}
.tiles {display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin: .4rem 0 1.1rem;}
.tile {background: #fcfcfb; border: 1px solid rgba(11,11,11,.10); border-radius: 10px; padding: 14px 16px;}
.tl {color: #52514e; font-size: .78rem; letter-spacing: .01em;}
.tv {color: #0b0b0b; font-size: 1.7rem; font-weight: 600; line-height: 1.25;}
.tsub {color: #898781; font-size: .78rem;}
.tsub.bad {color: #a32d2d;} .tsub.ok {color: #006300;}
.pill {display: inline-block; border-radius: 999px; padding: 1px 9px; font-size: .74rem; font-weight: 600; white-space: nowrap;}
.pill.HIGH {background: #fcebeb; color: #791f1f;} .pill.MEDIUM {background: #faeeda; color: #633806;}
.pill.LOW {background: #f1efe8; color: #444441;}
.pill.ok {background: #eaf3de; color: #27500a;} .pill.warn {background: #faeeda; color: #633806;}
.pill.bad {background: #fcebeb; color: #791f1f;}
.card {background: #fcfcfb; border: 1px solid rgba(11,11,11,.10); border-radius: 10px; padding: 11px 14px; margin-bottom: 8px;}
.card .nm {font-weight: 600; color: #0b0b0b;} .card .co {color: #52514e; font-size: .84rem;}
.card .why {color: #52514e; font-size: .82rem; margin-top: 4px; line-height: 1.4;}
.note {color: #898781; font-size: .8rem;}
div[data-testid="stDialog"] div[role="dialog"] {width: min(1080px, 94vw);}
</style>""", unsafe_allow_html=True)


# ---------- data ----------

@st.cache_data(ttl=300, show_spinner=False)
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    with duckdb.connect(DB, read_only=True) as con:
        return con.execute(sql, list(params)).df()


def alert_days() -> list[date]:
    return q("select distinct trade_date from gold.fact_surveillance_alert order by 1 desc")["trade_date"].dt.date.tolist()


def alerts_on(d: date) -> pd.DataFrame:
    return q("""select a.*, t.verdict, t.line as triage
                from gold.fact_surveillance_alert a left join ops.alert_triage t using (alert_id)
                where a.trade_date = ? order by a.risk_score desc, a.symbol""", (d,))


# ---------- small UI pieces ----------

def tile(label: str, value: str, sub: str = "", tone: str = "") -> str:
    return (f'<div class="tile"><div class="tl">{escape(label)}</div><div class="tv">{escape(value)}</div>'
            f'<div class="tsub {tone}">{escape(sub)}</div></div>')


def tiles(*items: str) -> None:
    st.markdown('<div class="tiles">' + "".join(items) + "</div>", unsafe_allow_html=True)


def pill(text: str, kind: str) -> str:
    return f'<span class="pill {kind}">{escape(text)}</span>'


def rupees(x: float) -> str:
    return f"{'-' if x < 0 else ''}₹{abs(x):,.0f}"


def style(fig: go.Figure, height: int, legend: bool = True, l: int = 62, b: int = 50) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=l, r=22, t=40 if legend else 14, b=b), paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif', size=12, color=INK2),
        showlegend=legend, legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, font=dict(color=INK2)),
        hoverlabel=dict(bgcolor="#ffffff", bordercolor=AXIS, font=dict(color=INK, size=12)))
    fig.update_xaxes(gridcolor=GRID, linecolor=AXIS, zeroline=False, tickfont=dict(color=MUTED), title_font=dict(color=INK2))
    fig.update_yaxes(gridcolor=GRID, linecolor=AXIS, zeroline=False, tickfont=dict(color=MUTED), title_font=dict(color=INK2))
    return fig


def clicked(event, key: str) -> str | None:
    """Symbol of a newly clicked plotly point (None if the selection is unchanged or empty)."""
    pts = event.selection.points if event and event.selection else []
    sym = pts[0]["customdata"][0] if pts and pts[0].get("customdata") else None
    if sym == st.session_state.get(f"_seen_{key}"):
        return None
    st.session_state[f"_seen_{key}"] = sym
    return sym


def picked(event, frame: pd.DataFrame, key: str) -> str | None:
    """Symbol of a newly selected dataframe row."""
    rows = event.selection.rows if event and event.selection else []
    sym = frame.iloc[rows[0]].symbol if rows else None
    if sym == st.session_state.get(f"_seen_{key}"):
        return None
    st.session_state[f"_seen_{key}"] = sym
    return sym


# ---------- paper portfolio (virtual money) ----------

def load_paper() -> list[dict]:
    return json.loads(PAPER.read_text(encoding="utf-8")) if PAPER.exists() else []


def save_paper(rows: list[dict]) -> None:
    PAPER.parent.mkdir(parents=True, exist_ok=True)
    PAPER.write_text(json.dumps(rows, indent=1), encoding="utf-8")


# ---------- stock detail (dialog and page share this) ----------

def price_chart(pxd: pd.DataFrame, al: pd.DataFrame, height: int = 400) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(
        x=pxd.trade_date, open=pxd.open, high=pxd.high, low=pxd.low, close=pxd.close, name="Price",
        increasing=dict(line=dict(color=UP, width=1.5), fillcolor=UP),
        decreasing=dict(line=dict(color=DOWN, width=1.5), fillcolor=DOWN)), 1, 1)
    for band in ("LOW", "MEDIUM", "HIGH"):
        g = al[al.risk_band == band]
        if g.empty:
            continue
        hi = g.merge(pxd[["trade_date", "high"]], on="trade_date")
        fig.add_trace(go.Scatter(
            x=hi.trade_date, y=hi.high * 1.035, mode="markers", name=f"{band.title()} alert",
            marker=dict(symbol="triangle-down", size=13, color=BAND[band], line=dict(color=SURFACE, width=2)),
            customdata=hi[["risk_score", "rules_triggered"]].values,
            hovertemplate="<b>%{x|%d %b}</b> · score %{customdata[0]:.0f}<br>%{customdata[1]}<extra></extra>"), 1, 1)
    ratio = pxd.volume_ratio_20d.fillna(1)
    fig.add_trace(go.Bar(
        x=pxd.trade_date, y=pxd.volume, name="Volume", showlegend=False,
        marker=dict(color=[BLUE if r >= 5 else "#b7d3f6" for r in ratio], line=dict(width=0)),
        customdata=ratio.values, hovertemplate="<b>%{x|%d %b}</b><br>%{y:,.0f} shares · %{customdata:.1f}x its 20-day average<extra></extra>"), 2, 1)
    style(fig, height, b=44)
    fig.update_layout(xaxis_rangeslider_visible=False, bargap=0.25, hovermode="x")
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])], showspikes=True, spikemode="across",
                     spikethickness=1, spikecolor=AXIS, spikedash="solid")
    fig.update_yaxes(title_text="Price (₹)", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)
    return fig


def breakdown_chart(a: pd.Series) -> go.Figure:
    parts = [(RULES[k], float(a[k])) for k in RULES if float(a[k]) > 0]
    parts.sort(key=lambda p: p[1])
    fig = go.Figure(go.Bar(
        x=[p[1] for p in parts], y=[p[0] for p in parts], orientation="h", marker=dict(color=BLUE, cornerradius=4),
        width=0.55, text=[f"{p[1]:.0f}" for p in parts], textposition="outside", textfont=dict(color=INK),
        hovertemplate="<b>%{y}</b><br>%{x:.0f} points before weighting<extra></extra>"))
    style(fig, 30 + 34 * len(parts), legend=False, l=128, b=10)
    fig.update_xaxes(range=[0, 48], showgrid=False, showticklabels=False)
    fig.update_yaxes(showgrid=False, tickfont=dict(color=INK2, size=12))
    return fig


def stock_detail(sym: str, on: date | None = None, key: str = "d") -> None:
    pxd = q("""select trade_date, open, high, low, close, volume, deliv_pct, return_pct, volume_ratio_20d
               from gold.fact_stock_daily where symbol = ? order by trade_date""", (sym,))
    al = q("""select a.*, t.verdict, t.line as triage from gold.fact_surveillance_alert a
              left join ops.alert_triage t using (alert_id) where a.symbol = ? order by a.trade_date""", (sym,))
    if pxd.empty:
        st.info("No price history for this stock.")
        return
    last = pxd.iloc[-1]
    focus = al[al.trade_date.dt.date == on] if on is not None else al.tail(1)
    a = focus.iloc[0] if not focus.empty else None
    name = q("select max(company_name) as n from gold.dim_stock where symbol = ?", (sym,)).n.iloc[0] or ""
    head = f'<span style="font-size:1.25rem;font-weight:600;color:{INK}">{escape(sym)}</span> <span class="co" style="color:{INK2}">{escape(name)}</span>'
    if a is not None:
        head += f' &nbsp;{pill(a.risk_band + " · " + format(a.risk_score, ".0f"), a.risk_band)}'
        if isinstance(a.verdict, str):
            head += f' {pill(*VERDICT[a.verdict])}'
        if a.exchange_query:
            head += f' {pill("NSE queried the company", "warn")}'
    st.markdown(head, unsafe_allow_html=True)
    tiles(tile("Last close", f"₹{last.close:,.2f}", f"{last.return_pct:+.1f}% on {last.trade_date:%d %b}",
               "ok" if last.return_pct > 0 else "bad"),
          tile("Volume", f"{last.volume_ratio_20d:.1f}x" if pd.notna(last.volume_ratio_20d) else "n/a", "of its 20-day average"),
          tile("Delivery", f"{last.deliv_pct:.0f}%" if pd.notna(last.deliv_pct) else "n/a", "of traded shares actually delivered"),
          tile("Days flagged", str(len(al)), f"since {pxd.trade_date.min():%d %b}"))
    left, right = st.columns([3, 2], gap="medium")
    with left:
        st.plotly_chart(price_chart(pxd, al), width="stretch", config=NOBAR, key=f"px_{key}", theme=None)
        st.markdown('<div class="note">Triangles mark alert days. Darker volume bars are 5x the average or more. '
                    'Hover for the numbers.</div>', unsafe_allow_html=True)
    with right:
        if a is None:
            st.info("This stock has not been flagged in the window loaded.")
        else:
            st.markdown(f"### Why it was flagged on {a.trade_date:%d %b}")
            for part in a.reason.split("; "):
                st.markdown(f"- {part}")
            if isinstance(a.triage, str):
                st.markdown(f"**News check:** {a.triage}")
            st.markdown("### Where the score comes from")
            st.plotly_chart(breakdown_chart(a), width="stretch", config=NOBAR, key=f"bd_{key}", theme=None)
            st.markdown(f'<div class="note">Strongest rule counts in full, the others at half, capped at 100: '
                        f'<b>{a.risk_score:.0f}</b>.</div>', unsafe_allow_html=True)
    t1, t2, t3 = st.tabs(["Alert history", "Company filings", "Paper invest"])
    with t1:
        if al.empty:
            st.caption("Never flagged.")
        else:
            st.dataframe(al[["trade_date", "risk_score", "risk_band", "rules_triggered", "triage"]].iloc[::-1],
                         hide_index=True, width="stretch", column_config={
                             "trade_date": st.column_config.DateColumn("Day", format="DD MMM"),
                             "risk_score": st.column_config.ProgressColumn("Risk", min_value=0, max_value=100, format="%d"),
                             "risk_band": "Band", "rules_triggered": "Rules", "triage": "News check"})
    with t2:
        try:
            fl = q("""select announced_at, category, summary, attachment_url from staging.stg_announcements
                      where symbol = ? and news_type <> 'ROUTINE' order by announced_at desc limit 12""", (sym,))
            if fl.empty:
                st.caption("No non-routine filings in the window loaded.")
            else:
                st.dataframe(fl, hide_index=True, width="stretch", column_config={
                    "announced_at": st.column_config.DatetimeColumn("When", format="DD MMM HH:mm"),
                    "category": "Type", "summary": "Summary",
                    "attachment_url": st.column_config.LinkColumn("Filing", display_text="open PDF")})
        except Exception:
            st.caption("Filings need the Delta lake on this machine (data/lake).")
    with t3:
        c1, c2 = st.columns([1, 2])
        amount = c1.number_input("Virtual amount (₹)", 1000, 1_000_000, 10_000, 1000, key=f"amt_{key}")
        c2.markdown(f'<div class="note" style="margin-top:1.9rem">Buys at the last close loaded (₹{last.close:,.2f} on '
                    f'{last.trade_date:%d %b}) and tracks it in the paper portfolio. {DISCLAIMER}</div>', unsafe_allow_html=True)
        if st.button(f"Paper invest {rupees(amount)} in {sym}", type="primary", key=f"buy_{key}"):
            rows = load_paper()
            rows.append({"symbol": sym, "date": str(last.trade_date.date()), "price": round(float(last.close), 2),
                         "amount": float(amount), "qty": round(amount / float(last.close), 4)})
            save_paper(rows)
            st.success(f"Added {amount / last.close:,.2f} virtual shares of {sym}.")


@st.dialog("Stock detail", width="large")
def stock_dialog(sym: str, on: date | None = None) -> None:
    stock_detail(sym, on, key="dlg")


# ---------- pages ----------

def market_map(al: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for band in ("LOW", "MEDIUM", "HIGH"):
        g = al[al.risk_band == band]
        if g.empty:
            continue
        news = g.triage.where(g.triage.notna(), g.news_types.map(
            lambda n: f"Filings: {n.replace('_', ' ').lower()}" if isinstance(n, str) else "No company news in 3 days"))
        fig.add_trace(go.Scatter(
            x=g.return_pct, y=g.volume_ratio_20d.fillna(1).clip(lower=0.2), name=f"{band.title()} ({len(g)})",
            mode="markers+text" if band == "HIGH" else "markers",
            text=g.symbol if band == "HIGH" else None, textfont=dict(color=INK, size=11),
            textposition=[LABEL_POS[i % len(LABEL_POS)] for i in range(len(g))] if band == "HIGH" else None,
            marker=dict(size=(9 + g.risk_score / 7).round(), color=BAND[band], opacity=0.9 if band == "HIGH" else 0.75,
                        line=dict(color=SURFACE, width=2)),
            customdata=pd.DataFrame({"s": g.symbol, "c": g.company_name.fillna(""), "r": g.risk_score,
                                     "rules": g.rules_triggered.str.replace("_", " ").str.lower(), "n": news}).values,
            hovertemplate=("<b>%{customdata[0]}</b> · %{customdata[1]}<br>Score <b>%{customdata[2]:.0f}</b> · "
                           "%{x:+.1f}% on %{y:.1f}x volume<br>%{customdata[3]}<br><i>%{customdata[4]}</i>"
                           "<extra></extra>")))
    style(fig, 430)
    fig.update_layout(dragmode=False, hoverdistance=30)
    fig.update_xaxes(title_text="Price move on the day (%)", zeroline=True, zerolinecolor=AXIS, ticksuffix="%")
    ticks = [0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200]
    fig.update_yaxes(title_text="Volume vs its 20-day average", type="log", tickvals=ticks,
                     ticktext=[f"{t:g}x" for t in ticks])
    return fig


def page_overview() -> None:
    days = alert_days()
    top = st.columns([3, 1])
    top[0].title("Market surveillance")
    d = top[1].selectbox("Trading day", days, format_func=lambda x: x.strftime("%a %d %b %Y"), label_visibility="collapsed")
    al = alerts_on(d)
    prev = alerts_on(days[days.index(d) + 1]) if days.index(d) + 1 < len(days) else None
    high = al[al.risk_band == "HIGH"]
    st.markdown(f'<div class="sub">{d:%A %d %B %Y} · every NSE stock scored against 7 rules after the close</div>',
                unsafe_allow_html=True)
    delta = f"{len(al) - len(prev):+d} vs previous day" if prev is not None else ""
    unexplained = int(high.news_types.isna().sum())
    tiles(tile("Stocks flagged", str(len(al)), delta),
          tile("High risk", str(len(high)), "score 70 or more", "bad" if len(high) else ""),
          tile("High risk with no news", str(unexplained), "nothing filed in 3 days", "bad" if unexplained else ""),
          tile("Also queried by NSE", str(int(al.exchange_query.sum())), "exchange asked the company why"))
    opened = None
    left, right = st.columns([5, 3], gap="medium")
    with left:
        st.markdown("### Market map: how far and on how much volume")
        ev = st.plotly_chart(market_map(al), width="stretch", config=NOBAR, on_select="rerun",
                             selection_mode="points", key=f"map_{d}", theme=None)
        st.markdown('<div class="note">Each dot is a flagged stock; bigger means a higher score. '
                    'Hover for details, click a dot to open it.</div>', unsafe_allow_html=True)
        opened = clicked(ev, f"map_{d}")
    with right:
        st.markdown("### High-risk alerts")
        if high.empty:
            st.info("No high-risk alerts on this day.")
        for r in high.itertuples():
            verdict = pill(*VERDICT[r.verdict]) if isinstance(r.verdict, str) else ""
            why = r.triage if isinstance(r.triage, str) else r.reason.split("; ")[0]
            st.markdown(f'<div class="card"><span class="nm">{escape(r.symbol)}</span> '
                        f'{pill(format(r.risk_score, ".0f"), "HIGH")} {verdict}<br>'
                        f'<span class="co">{escape(r.company_name or "")}</span>'
                        f'<div class="why">{escape(why)}</div></div>', unsafe_allow_html=True)
        choice = st.selectbox("Open a stock", [""] + al.symbol.tolist(), label_visibility="collapsed",
                              format_func=lambda s: s or "Open any flagged stock…", key=f"open_{d}")
        if choice and st.session_state.get("_seen_pick") != (d, choice):
            st.session_state["_seen_pick"] = (d, choice)
            opened = opened or choice

    st.markdown("### All flagged stocks")
    f1, f2, f3 = st.columns([2, 3, 2])
    bands = f1.multiselect("Band", ["HIGH", "MEDIUM", "LOW"], default=["HIGH", "MEDIUM"])
    rules = sorted({x for s in al.rules_triggered for x in s.split(", ")})
    pick = f2.multiselect("Rule", rules, format_func=lambda s: s.replace("_", " ").title())
    only = f3.selectbox("Company news", ["Any", "No news", "Has news"])
    view = al[al.risk_band.isin(bands)]
    if pick:
        view = view[view.rules_triggered.apply(lambda s: any(p in s.split(", ") for p in pick))]
    if only != "Any":
        view = view[view.news_types.isna()] if only == "No news" else view[view.news_types.notna()]
    table = view[["symbol", "company_name", "risk_score", "risk_band", "return_pct", "volume_ratio_20d",
                  "rules_triggered", "news_types", "exchange_query"]].reset_index(drop=True)
    table["rules_triggered"] = table.rules_triggered.str.replace("_", " ").str.lower()
    table["news_types"] = table.news_types.str.replace("_", " ").str.lower()
    table["risk_band"] = table.risk_band.str.title()
    ev2 = st.dataframe(table, hide_index=True, width="stretch", height=320, on_select="rerun",
                       selection_mode="single-row", key=f"tbl_{d}", column_config={
                           "symbol": "Symbol", "company_name": "Company",
                           "risk_score": st.column_config.ProgressColumn("Risk", min_value=0, max_value=100, format="%d"),
                           "risk_band": "Band", "return_pct": st.column_config.NumberColumn("Day move", format="%+.1f%%"),
                           "volume_ratio_20d": st.column_config.NumberColumn("Volume", format="%.1fx"),
                           "rules_triggered": "Rules", "news_types": "Filings",
                           "exchange_query": st.column_config.CheckboxColumn("NSE query")})
    st.markdown(f'<div class="note">{len(table)} stocks. Click a row to open the stock.</div>', unsafe_allow_html=True)
    opened = opened or picked(ev2, table, f"tbl_{d}")
    if opened:
        stock_dialog(opened, d)


def page_stock() -> None:
    names = q("""select f.symbol, max(d.company_name) as company_name from gold.fact_stock_daily f
                 join gold.dim_stock d using (stock_sk) group by 1 order by 1""")
    label = dict(zip(names.symbol, names.company_name))
    symbols = names.symbol.tolist()
    top = st.columns([3, 2])
    top[0].title("Stock explorer")
    default = st.session_state.get("symbol", "TRENT")
    sym = top[1].selectbox("Stock", symbols, index=symbols.index(default) if default in symbols else 0,
                           format_func=lambda s: f"{s} · {label.get(s) or ''}", label_visibility="collapsed")
    st.session_state["symbol"] = sym
    st.markdown('<div class="sub">Search any of the stocks loaded: price, volume, every alert and the filings behind it</div>',
                unsafe_allow_html=True)
    stock_detail(sym, key="page")


def page_after() -> None:
    st.title("What happened after an alert?")
    st.markdown('<div class="sub">Buy at the next day\'s open (an alert is only known after the close) and sell at the '
                'close N trading days later, against doing the same in the median stock.</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    n = c1.slider("Hold for (trading days)", 1, 10, 5)
    bands = c2.multiselect("Alert band", ["HIGH", "MEDIUM", "LOW"], default=["HIGH"])
    news = c3.selectbox("Company news", ["Any", "No news (unexplained)", "Has news"])
    stake = c4.number_input("Virtual ₹ per alert", 1000, 1_000_000, 10_000, 1000)
    df = q(f"""
        with px as (select symbol, trade_date, lead(open, 1) over w as entry, lead(close, {int(n)}) over w as exit
                    from gold.fact_stock_daily window w as (partition by symbol order by trade_date)),
             mkt as (select trade_date, median((exit / entry - 1) * 100) as market_ret
                     from px where entry > 0 and exit is not null group by 1)
        select a.trade_date, a.symbol, a.company_name, a.risk_band, a.risk_score, a.rules_triggered,
               a.news_types, (p.exit / p.entry - 1) * 100 as ret, m.market_ret
        from gold.fact_surveillance_alert a join px p using (symbol, trade_date) join mkt m using (trade_date)
        where p.entry > 0 and p.exit is not null""")
    df = df[df.risk_band.isin(bands)]
    if news != "Any":
        df = df[df.news_types.isna()] if news.startswith("No") else df[df.news_types.notna()]
    if df.empty:
        st.info("No alerts match yet (the most recent days have no 'after').")
        return
    pnl, mkt = (df.ret / 100 * stake).sum(), (df.market_ret / 100 * stake).sum()
    edge = df.ret.mean() - df.market_ret.mean()
    tiles(tile("Alerts followed", f"{len(df):,}", f"{df.trade_date.nunique()} alert days"),
          tile("Average move", f"{df.ret.mean():+.1f}%", f"{edge:+.1f} pts vs the median stock", "bad" if edge < 0 else "ok"),
          tile("Went up", f"{(df.ret > 0).mean() * 100:.0f}%", f"of alerts after {n} days"),
          tile("Virtual profit / loss", rupees(pnl), f"{rupees(pnl - mkt)} vs the median stock", "bad" if pnl < mkt else "ok"))
    left, right = st.columns(2, gap="medium")
    with left:
        st.markdown(f"### Every alert: score vs move after {n} days")
        fig = go.Figure()
        for band in ("LOW", "MEDIUM", "HIGH"):
            g = df[df.risk_band == band]
            if g.empty:
                continue
            fig.add_trace(go.Scatter(
                x=g.risk_score, y=g.ret, mode="markers", name=f"{band.title()} ({len(g)})",
                marker=dict(size=10, color=BAND[band], opacity=0.8, line=dict(color=SURFACE, width=2)),
                customdata=pd.DataFrame({"s": g.symbol, "c": g.company_name.fillna(""), "d": g.trade_date.dt.strftime("%d %b"),
                                         "r": g.rules_triggered.str.replace("_", " ").str.lower()}).values,
                hovertemplate=("<b>%{customdata[0]}</b> · %{customdata[1]}<br>Flagged %{customdata[2]}, score %{x:.0f}<br>"
                               "<b>%{y:+.1f}%</b> after " + str(n) + " days<br>%{customdata[3]}<extra></extra>")))
        fig.add_hline(y=0, line_color=AXIS, line_width=1)
        style(fig, 360)
        fig.update_layout(dragmode=False, hoverdistance=30)
        fig.update_xaxes(title_text="Risk score on the alert day")
        fig.update_yaxes(title_text=f"Move after {n} days", ticksuffix="%")
        ev = st.plotly_chart(fig, width="stretch", config=NOBAR, on_select="rerun", selection_mode="points",
                             key=f"after_{n}_{news}", theme=None)
        st.markdown('<div class="note">Hover a dot for the stock; click to open it.</div>', unsafe_allow_html=True)
    with right:
        st.markdown("### Running virtual profit / loss")
        daily = df.groupby("trade_date").agg(you=("ret", lambda s: (s / 100 * stake).sum()),
                                             market=("market_ret", lambda s: (s / 100 * stake).sum())).cumsum().reset_index()
        line = go.Figure()
        line.add_trace(go.Scatter(x=daily.trade_date, y=daily.market, name="Median stock, same days", mode="lines",
                                  line=dict(color=GREY, width=2, dash="dash"), hovertemplate="%{y:,.0f}<extra>Median stock</extra>"))
        line.add_trace(go.Scatter(x=daily.trade_date, y=daily.you, name="Following the alerts", mode="lines+markers",
                                  line=dict(color=BLUE, width=2), marker=dict(size=8, line=dict(color=SURFACE, width=2)),
                                  hovertemplate="%{y:,.0f}<extra>Following the alerts</extra>"))
        line.add_hline(y=0, line_color=AXIS, line_width=1)
        style(line, 360)
        line.update_layout(hovermode="x unified")
        line.update_yaxes(title_text="Cumulative ₹", tickprefix="₹", tickformat=",.0f")
        st.plotly_chart(line, width="stretch", config=NOBAR, key="after_line", theme=None)
        st.markdown('<div class="note">Alert day on the x-axis; each point adds that day\'s alerts.</div>', unsafe_allow_html=True)
    st.warning("Read this before believing the number: a few weeks of data, no brokerage or taxes, and many of these "
               "stocks are thinly traded or locked at a price band, so you often could not have traded at these prices. "
               + DISCLAIMER)
    sym = clicked(ev, f"after_{n}_{news}")
    if sym:
        stock_dialog(sym)


def page_paper() -> None:
    st.title("Paper portfolio")
    st.markdown(f'<div class="sub">{DISCLAIMER}</div>', unsafe_allow_html=True)
    rows = load_paper()
    if not rows:
        st.info("Nothing yet. Open any stock and use the 'Paper invest' tab.")
        return
    df = pd.DataFrame(rows)
    latest = q("""select symbol, close as last_close, trade_date as as_of from gold.fact_stock_daily
                  qualify row_number() over (partition by symbol order by trade_date desc) = 1""")
    df = df.merge(latest, on="symbol", how="left")
    df["value"] = df.qty * df.last_close
    df["pnl"] = df.value - df.amount
    df["pnl_pct"] = df.pnl / df.amount * 100
    total = df.pnl.sum()
    tiles(tile("Invested (virtual)", rupees(df.amount.sum()), f"{len(df)} positions"),
          tile("Worth now", rupees(df.value.sum()), f"prices as of {df.as_of.max():%d %b}"),
          tile("Profit / loss", rupees(total), f"{total / df.amount.sum() * 100:+.2f}%", "ok" if total >= 0 else "bad"))
    table = df[["symbol", "date", "price", "amount", "last_close", "value", "pnl", "pnl_pct"]]
    ev = st.dataframe(table, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                      key="paper_tbl", column_config={
                          "symbol": "Symbol", "date": "Bought on",
                          "price": st.column_config.NumberColumn("Buy price", format="₹%.2f"),
                          "amount": st.column_config.NumberColumn("Invested", format="₹%d"),
                          "last_close": st.column_config.NumberColumn("Last close", format="₹%.2f"),
                          "value": st.column_config.NumberColumn("Worth now", format="₹%d"),
                          "pnl": st.column_config.NumberColumn("Profit / loss", format="₹%d"),
                          "pnl_pct": st.column_config.NumberColumn("%", format="%+.1f%%")})
    c1, c2 = st.columns([3, 1])
    drop = c1.selectbox("Remove a position", [""] + [f"{i}: {r['symbol']} bought {r['date']}" for i, r in enumerate(rows)],
                        label_visibility="collapsed", format_func=lambda s: s or "Remove a position…")
    if c2.button("Remove", disabled=not drop, width="stretch"):
        rows.pop(int(drop.split(":")[0]))
        save_paper(rows)
        st.rerun()
    sym = picked(ev, table, "paper_tbl")
    if sym:
        stock_dialog(sym)


def page_validation() -> None:
    st.title("Does it work?")
    st.markdown('<div class="sub">Our alerts compared with what NSE itself did: asked the company to explain a move, '
                'or put the stock on its short-term surveillance list.</div>', unsafe_allow_html=True)
    v = q("select * from gold.mart_surveillance_validation order by sort_order")
    high, anyv = v[v.segment == "HIGH"].iloc[0], v[v.segment == "ANY_ALERT"].iloc[0]
    allv = v[v.segment == "ALL_STOCKS"].iloc[0]
    on_time = anyv.flagged_before_query + anyv.flagged_same_day
    total = on_time + anyv.flagged_after_query
    tiles(tile("High-risk alerts on NSE's list", f"{high.stasm_pct:.1f}%", f"{high.stasm_lift:.1f}x the average stock", "ok"),
          tile("High-risk alerts NSE queried", f"{high.queried_pct:.1f}%", f"{high.queried_lift:.1f}x the average stock", "ok"),
          tile("NSE-queried stocks we caught", f"{anyv.queried / allv.queried * 100:.0f}%", f"{int(anyv.queried)} of {int(allv.queried)}"),
          tile("Flagged on or before NSE", f"{on_time / total * 100:.0f}%", f"{int(on_time)} of {int(total)} stocks", "ok"))
    names = {"HIGH": "High alert", "MEDIUM": "Medium alert", "LOW": "Low alert", "NOT_ALERTED": "Not alerted",
             "ALL_STOCKS": "All stocks"}
    main = v[v.segment.isin(names)].iloc[::-1]
    labels = [f"{names[s]} ({n:,})" for s, n in zip(main.segment, main.stocks)]
    left, right = st.columns(2, gap="medium")
    for col, field, title in ((left, "stasm_pct", "On NSE's short-term surveillance list"),
                              (right, "queried_pct", "Queried by NSE about a volume or price move")):
        with col:
            st.markdown(f"### {title}")
            colors = [GREY if s in ("ALL_STOCKS", "NOT_ALERTED") else BLUE for s in main.segment]
            fig = go.Figure(go.Bar(
                x=main[field], y=labels, orientation="h", width=0.55, marker=dict(color=colors, cornerradius=4),
                text=[f"{x:.1f}%" for x in main[field]], textposition="outside", textfont=dict(color=INK),
                hovertemplate="<b>%{y}</b><br>%{x:.1f}% of these stocks<extra></extra>"))
            style(fig, 300, legend=False, l=150)
            fig.update_xaxes(range=[0, max(main[field]) * 1.25], ticksuffix="%", title_text="Share of stocks in the group")
            fig.update_yaxes(showgrid=False, tickfont=dict(color=INK2))
            st.plotly_chart(fig, width="stretch", config=NOBAR, key=f"val_{field}", theme=None)
    st.markdown("### Who was first: us or NSE?")
    o = q("""select symbol, best_band, max_risk_score, first_alert_date, first_query_date, query_lead_days, on_stasm
             from intermediate.int_alert_outcomes where exchange_queried and best_band <> 'NOT_ALERTED'""")
    lo, hi_ = -3, 7
    o["bucket"] = o.query_lead_days.clip(lo, hi_)
    grp = o.groupby("bucket").symbol
    lead = pd.DataFrame({"bucket": range(lo, hi_ + 1)})
    lead["n"] = lead.bucket.map(grp.size()).fillna(0).astype(int)
    lead["names"] = lead.bucket.map(grp.agg(lambda s: ", ".join(sorted(s)[:8]) + (" and more" if len(s) > 8 else ""))).fillna("")
    text = {lo: f"{-lo}+ days late", -1: "1 day late", 0: "Same day", 1: "1 day early", hi_: f"{hi_}+ days early"}
    lead["label"] = [text.get(b, f"{abs(b)} days {'early' if b > 0 else 'late'}") for b in lead.bucket]
    fig = go.Figure(go.Bar(
        x=lead.label, y=lead.n, width=0.6, customdata=lead.names.values, text=lead.n.where(lead.n > 0, ""),
        textposition="outside", textfont=dict(color=INK),
        marker=dict(color=[BLUE if b >= 0 else GREY for b in lead.bucket], cornerradius=4),
        hovertemplate="<b>%{y} stocks</b> · %{x}<br>%{customdata}<extra></extra>"))
    style(fig, 280, legend=False)
    fig.update_xaxes(title_text="When we first flagged the stock, relative to NSE's query", showgrid=False)
    fig.update_yaxes(title_text="Stocks", range=[0, lead.n.max() * 1.18])
    st.plotly_chart(fig, width="stretch", config=NOBAR, key="val_lead", theme=None)
    st.markdown("### High-risk stocks NSE also acted on")
    hi = o[o.best_band == "HIGH"].sort_values("first_alert_date", ascending=False).reset_index(drop=True)
    ev = st.dataframe(hi[["symbol", "max_risk_score", "first_alert_date", "first_query_date", "query_lead_days", "on_stasm"]],
                      hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row", key="val_tbl",
                      column_config={
                          "symbol": "Symbol", "max_risk_score": st.column_config.NumberColumn("Top score", format="%d"),
                          "first_alert_date": st.column_config.DateColumn("We flagged", format="DD MMM"),
                          "first_query_date": st.column_config.DateColumn("NSE queried", format="DD MMM"),
                          "query_lead_days": st.column_config.NumberColumn("Days ahead of NSE"),
                          "on_stasm": st.column_config.CheckboxColumn("On short-term list")})
    st.markdown('<div class="note">A few weeks of data and a small high-risk group, so the multiples will move. NSE\'s own '
                'triggers use volume and price too, so some agreement is expected: this shows the engine matches NSE\'s '
                'screening, not that any stock was manipulated.</div>', unsafe_allow_html=True)
    sym = picked(ev, hi, "val_tbl")
    if sym:
        stock_dialog(sym)


def page_health() -> None:
    st.title("Pipeline health")
    st.markdown('<div class="sub">Is the data fresh, did the last run finish, and did the checks pass?</div>', unsafe_allow_html=True)
    fresh = q("select max(trade_date) as d, count(distinct trade_date) as days, count(distinct symbol) as stocks from gold.fact_stock_daily").iloc[0]
    runs = q("select run_id, run_date, step, status, started_at, duration_s, detail from ops.pipeline_runs order by started_at desc limit 60")
    dq = q("""select check_name, status, value, detail, checked_at from ops.dq_results
              where checked_at >= (select max(checked_at) - interval 1 minute from ops.dq_results) order by check_name""")
    failed = int((runs.head(7).status == "FAILED").sum())
    passed = int((dq.status == "PASS").sum())
    tiles(tile("Latest trading day loaded", f"{fresh.d:%d %b %Y}", f"{int(fresh.days)} trading days in total"),
          tile("Stocks covered", f"{int(fresh.stocks):,}", "NSE equities"),
          tile("Last run", "Failed" if failed else "Succeeded", f"{runs.started_at.max():%d %b %H:%M}", "bad" if failed else "ok"),
          tile("Data-quality checks", f"{passed} / {len(dq)}", "passed in the latest run", "ok" if passed == len(dq) else "bad"))
    left, right = st.columns([3, 2], gap="medium")
    with left:
        st.markdown("### How long each step takes")
        ok = runs[runs.status == "SUCCESS"]
        avg = ok.groupby("step").duration_s.agg(["mean", "count"]).reindex(
            ["calendar", "extract", "silver", "dbt", "surveillance", "quality", "alerts"]).dropna().iloc[::-1]
        fig = go.Figure(go.Bar(
            x=avg["mean"], y=[s.title() for s in avg.index], orientation="h", width=0.55,
            marker=dict(color=BLUE, cornerradius=4), text=[f"{x:.0f}s" for x in avg["mean"]], textposition="outside",
            textfont=dict(color=INK), customdata=avg["count"].values,
            hovertemplate="<b>%{y}</b><br>%{x:.0f} seconds on average over %{customdata} runs<extra></extra>"))
        style(fig, 300, legend=False, l=110)
        fig.update_xaxes(range=[0, avg["mean"].max() * 1.2], title_text="Average seconds", showgrid=True)
        fig.update_yaxes(showgrid=False, tickfont=dict(color=INK2))
        st.plotly_chart(fig, width="stretch", config=NOBAR, key="health_steps", theme=None)
    with right:
        st.markdown("### Data-quality checks")
        dq["result"] = dq.status.map({"PASS": "✓ pass", "WARN": "! warn", "FAIL": "✗ fail"})
        st.dataframe(dq[["check_name", "result", "detail"]], hide_index=True, width="stretch", height=300,
                     column_config={"check_name": "Check", "result": "Result", "detail": "Detail"})
    st.markdown("### Recent pipeline steps")
    runs["result"] = runs.status.map({"SUCCESS": "✓ success", "FAILED": "✗ failed", "SKIPPED": "– skipped"})
    st.dataframe(runs[["started_at", "run_date", "step", "result", "duration_s", "detail"]], hide_index=True,
                 width="stretch", height=320, column_config={
                     "started_at": st.column_config.DatetimeColumn("Started", format="DD MMM HH:mm"),
                     "run_date": st.column_config.DateColumn("For day", format="DD MMM"), "step": "Step", "result": "Result",
                     "duration_s": st.column_config.NumberColumn("Seconds", format="%.0f"), "detail": "Detail"})


nav = st.navigation([
    st.Page(page_overview, title="Overview", icon=":material/radar:", url_path="overview", default=True),
    st.Page(page_stock, title="Stock explorer", icon=":material/candlestick_chart:", url_path="stock"),
    st.Page(page_after, title="After the alert", icon=":material/timeline:", url_path="after"),
    st.Page(page_paper, title="Paper portfolio", icon=":material/account_balance_wallet:", url_path="paper"),
    st.Page(page_validation, title="Does it work", icon=":material/verified:", url_path="validation"),
    st.Page(page_health, title="Pipeline health", icon=":material/monitor_heart:", url_path="health"),
], position="top")
try:
    nav.run()
except duckdb.IOException:
    st.warning("The warehouse is busy (the daily pipeline is probably writing to it). Try again in a minute.")
