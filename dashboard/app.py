"""Dashboard on the Gold tables.   streamlit run dashboard/app.py   (from the repo root)

Read-only on the warehouse. Each query opens and closes its own connection so the daily
pipeline (which needs the write lock) is never blocked by an open dashboard.
The paper portfolio is virtual money, kept in data/local/ (not committed).
"""
import json
import os
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)  # staging views read the lake by relative path
DB = os.getenv("DUCKDB_PATH", "data/warehouse/market.duckdb")
PAPER = ROOT / "data" / "local" / "paper_portfolio.json"
BAND_COLOR = {"HIGH": "#e34948", "MEDIUM": "#eda100", "LOW": "#b4b2a9"}
VERDICT = {"EXPLAINED": "✅", "UNCLEAR": "❔", "UNEXPLAINED": "🔎"}
DISCLAIMER = "Simulation on past data with virtual money. Surveillance flags are signals for analysis, not accusations, and nothing here is investment advice."

st.set_page_config(page_title="NSE surveillance", page_icon="📊", layout="wide")


@st.cache_data(ttl=300, show_spinner=False)
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    with duckdb.connect(DB, read_only=True) as con:
        return con.execute(sql, list(params)).df()


def rupees(x: float) -> str:
    return f"{'-' if x < 0 else ''}₹{abs(x):,.0f}"


def go_to_stock(symbol: str) -> None:
    st.session_state["symbol"] = symbol
    st.session_state["page"] = "Stock explorer"


# ---------- paper portfolio (virtual money) ----------

def load_paper() -> list[dict]:
    return json.loads(PAPER.read_text(encoding="utf-8")) if PAPER.exists() else []


def save_paper(rows: list[dict]) -> None:
    PAPER.parent.mkdir(parents=True, exist_ok=True)
    PAPER.write_text(json.dumps(rows, indent=1), encoding="utf-8")


def paper_invest(symbol: str, on: date, price: float, amount: float) -> None:
    rows = load_paper()
    rows.append({"symbol": symbol, "date": str(on), "price": round(price, 2), "amount": amount,
                 "qty": round(amount / price, 4)})
    save_paper(rows)


# ---------- pages ----------

def page_today() -> None:
    days = q("select distinct trade_date from gold.fact_surveillance_alert order by 1 desc")["trade_date"].dt.date.tolist()
    d = st.sidebar.selectbox("Trading day", days, format_func=lambda x: x.strftime("%a %d %b %Y"))
    alerts = q("""select a.symbol, a.company_name, a.industry, a.risk_score, a.risk_band, a.rules_triggered,
                         a.reason, a.return_pct, a.volume_ratio_20d, a.news_types, a.exchange_query,
                         t.verdict, t.line as triage
                  from gold.fact_surveillance_alert a left join ops.alert_triage t using (alert_id)
                  where a.trade_date = ? order by a.risk_score desc, a.symbol""", (d,))
    st.title(f"Surveillance: {d:%d %b %Y}")
    high = alerts[alerts.risk_band == "HIGH"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Stocks flagged", len(alerts))
    c2.metric("HIGH", len(high))
    c3.metric("MEDIUM", int((alerts.risk_band == "MEDIUM").sum()))
    c4.metric("NSE also queried", int(alerts.exchange_query.sum()))

    st.subheader("HIGH alerts")
    if high.empty:
        st.info("No HIGH alerts on this day.")
    for r in high.itertuples():
        with st.container(border=True):
            left, right = st.columns([5, 1])
            left.markdown(f"**{r.symbol}** · {r.company_name} · score **{r.risk_score:.0f}**")
            left.caption(r.reason)
            if isinstance(r.triage, str):
                left.markdown(f"{VERDICT.get(r.verdict, '•')} {r.triage}")
            right.button("Open stock", key=f"open_{r.symbol}", on_click=go_to_stock, args=(r.symbol,),
                         width="stretch")

    st.subheader("All flagged stocks")
    f1, f2 = st.columns([1, 3])
    bands = f1.multiselect("Band", ["HIGH", "MEDIUM", "LOW"], default=["HIGH", "MEDIUM"])
    rules = sorted({x for s in alerts.rules_triggered for x in s.split(", ")})
    pick = f2.multiselect("Rule", rules)
    view = alerts[alerts.risk_band.isin(bands)]
    if pick:
        view = view[view.rules_triggered.apply(lambda s: any(p in s for p in pick))]
    sel = st.dataframe(
        view[["symbol", "company_name", "risk_score", "risk_band", "return_pct", "volume_ratio_20d",
              "rules_triggered", "news_types", "exchange_query"]],
        hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
        column_config={"risk_score": st.column_config.ProgressColumn("Risk", min_value=0, max_value=100, format="%d"),
                       "return_pct": st.column_config.NumberColumn("Day %", format="%.1f"),
                       "volume_ratio_20d": st.column_config.NumberColumn("Volume x", format="%.1f"),
                       "exchange_query": st.column_config.CheckboxColumn("NSE query")})
    if sel.selection.rows:
        st.button(f"Open {view.iloc[sel.selection.rows[0]].symbol} in the stock explorer",
                  on_click=go_to_stock, args=(view.iloc[sel.selection.rows[0]].symbol,))
    else:
        st.caption("Select a row to open that stock.")


def page_stock() -> None:
    names = q("""select f.symbol, max(d.company_name) as company_name from gold.fact_stock_daily f
                 join gold.dim_stock d using (stock_sk) group by 1 order by 1""")
    symbols = names.symbol.tolist()
    label = dict(zip(names.symbol, names.company_name))
    default = st.session_state.get("symbol", "TRENT")
    sym = st.sidebar.selectbox("Stock", symbols, index=symbols.index(default) if default in symbols else 0,
                               format_func=lambda s: f"{s} · {label.get(s) or ''}")
    st.session_state["symbol"] = sym
    pxd = q("""select trade_date, open, high, low, close, volume, deliv_pct, return_pct, volume_ratio_20d
               from gold.fact_stock_daily where symbol = ? order by trade_date""", (sym,))
    al = q("""select trade_date, risk_score, risk_band, rules_triggered, reason, close
              from gold.fact_surveillance_alert where symbol = ? order by trade_date""", (sym,))
    st.title(f"{sym} · {label.get(sym) or ''}")
    last = pxd.iloc[-1]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Last close", f"₹{last.close:,.2f}", f"{last.return_pct:+.1f}%")
    c2.metric("Volume vs 20-day avg", f"{last.volume_ratio_20d:.1f}x" if pd.notna(last.volume_ratio_20d) else "n/a")
    c3.metric("Delivery", f"{last.deliv_pct:.0f}%" if pd.notna(last.deliv_pct) else "n/a")
    c4.metric("Days flagged", len(al))

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.04)
    fig.add_trace(go.Candlestick(x=pxd.trade_date, open=pxd.open, high=pxd.high, low=pxd.low, close=pxd.close,
                                 name="Price", increasing_line_color="#1baf7a", decreasing_line_color="#e34948"), 1, 1)
    for band, grp in al.groupby("risk_band"):
        fig.add_trace(go.Scatter(x=grp.trade_date, y=grp.close * 1.04, mode="markers", name=f"{band} alert",
                                 marker=dict(symbol="triangle-down", size=12, color=BAND_COLOR[band]),
                                 text=grp.rules_triggered, hovertemplate="%{x|%d %b}<br>%{text}<extra></extra>"), 1, 1)
    fig.add_trace(go.Bar(x=pxd.trade_date, y=pxd.volume, name="Volume", marker_color="#85b7eb"), 2, 1)
    fig.update_layout(height=520, margin=dict(l=10, r=10, t=10, b=10), xaxis_rangeslider_visible=False,
                      legend=dict(orientation="h", y=1.06))
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    st.plotly_chart(fig, width="stretch")

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Alert history")
        if al.empty:
            st.info("Never flagged in the window loaded.")
        else:
            st.dataframe(al[["trade_date", "risk_score", "risk_band", "reason"]].iloc[::-1], hide_index=True,
                         width="stretch",
                         column_config={"trade_date": st.column_config.DateColumn("Day", format="DD MMM")})
        st.subheader("Company filings")
        try:
            fl = q("""select announced_at, category, summary, attachment_url from staging.stg_announcements
                      where symbol = ? and news_type <> 'ROUTINE' order by announced_at desc limit 12""", (sym,))
            if fl.empty:
                st.caption("No non-routine filings in the window loaded.")
            else:
                st.dataframe(fl, hide_index=True, width="stretch", column_config={
                    "announced_at": st.column_config.DatetimeColumn("When", format="DD MMM HH:mm"),
                    "attachment_url": st.column_config.LinkColumn("PDF", display_text="open")})
        except Exception:
            st.caption("Filings need the Delta lake on this machine (data/lake).")
    with right:
        st.subheader("Paper invest")
        st.caption("Virtual money: buys at the last close loaded and tracks what happens next.")
        amount = st.number_input("Amount (₹)", min_value=1000, max_value=1_000_000, value=10_000, step=1000)
        if st.button(f"Paper invest {rupees(amount)} in {sym}", type="primary", width="stretch"):
            paper_invest(sym, last.trade_date.date(), float(last.close), float(amount))
            st.success(f"Bought {amount / last.close:,.2f} virtual shares at ₹{last.close:,.2f}. See 'Paper portfolio'.")
        st.caption(DISCLAIMER)


def page_what_next() -> None:
    st.title("What happened after an alert?")
    st.caption("Buy at the next day's open (an alert is only known after the close), sell at the close N trading "
               "days later. Compared with doing the same in the median stock on the same days.")
    c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
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
        st.info("No alerts match (the most recent days have no 'after' yet).")
        return
    pnl, mkt_pnl = (df.ret / 100 * stake).sum(), (df.market_ret / 100 * stake).sum()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Alerts followed", len(df))
    m2.metric("Average move", f"{df.ret.mean():+.2f}%", f"{df.ret.mean() - df.market_ret.mean():+.2f} pts vs median stock")
    m3.metric("Went up", f"{(df.ret > 0).mean() * 100:.0f}%")
    m4.metric("Virtual profit / loss", rupees(pnl), f"{rupees(pnl - mkt_pnl)} vs median stock")

    left, right = st.columns(2)
    hist = px.histogram(df, x="ret", nbins=40, color="risk_band", color_discrete_map=BAND_COLOR,
                        labels={"ret": f"Return after {n} days (%)", "risk_band": "Band"})
    hist.add_vline(x=0, line_dash="dot")
    hist.update_layout(height=340, margin=dict(l=10, r=10, t=30, b=10), title="How the outcomes were spread")
    left.plotly_chart(hist, width="stretch")
    daily = df.groupby("trade_date").agg(alerts=("ret", "size"), you=("ret", lambda s: (s / 100 * stake).sum()),
                                         market=("market_ret", lambda s: (s / 100 * stake).sum())).cumsum().reset_index()
    line = go.Figure()
    line.add_trace(go.Scatter(x=daily.trade_date, y=daily.you, name="Following the alerts", line=dict(color="#2a78d6", width=2)))
    line.add_trace(go.Scatter(x=daily.trade_date, y=daily.market, name="Median stock, same days",
                              line=dict(color="#898781", width=2, dash="dash")))
    line.update_layout(height=340, margin=dict(l=10, r=10, t=30, b=10), title="Running virtual profit / loss (₹)",
                       legend=dict(orientation="h", y=-0.2))
    right.plotly_chart(line, width="stretch")

    st.subheader("Biggest moves")
    best = pd.concat([df.nlargest(5, "ret"), df.nsmallest(5, "ret")])
    st.dataframe(best[["trade_date", "symbol", "company_name", "risk_band", "rules_triggered", "ret", "market_ret"]],
                 hide_index=True, width="stretch", column_config={
                     "trade_date": st.column_config.DateColumn("Alert day", format="DD MMM"),
                     "ret": st.column_config.NumberColumn(f"After {n}d %", format="%.1f"),
                     "market_ret": st.column_config.NumberColumn("Median stock %", format="%.1f")})
    st.warning("Read this before believing the number: a few weeks of data, no brokerage or taxes, and many of these "
               "stocks are thinly traded or locked at a price band, so you often could not have bought or sold at "
               "these prices. " + DISCLAIMER)


def page_paper() -> None:
    st.title("Paper portfolio")
    rows = load_paper()
    if not rows:
        st.info("Nothing yet. Open a stock in the stock explorer and press 'Paper invest'.")
        st.caption(DISCLAIMER)
        return
    df = pd.DataFrame(rows)
    latest = q("""select symbol, close as last_close, trade_date as as_of from gold.fact_stock_daily
                  qualify row_number() over (partition by symbol order by trade_date desc) = 1""")
    df = df.merge(latest, on="symbol", how="left")
    df["value"] = df.qty * df.last_close
    df["pnl"] = df.value - df.amount
    df["pnl_pct"] = df.pnl / df.amount * 100
    c1, c2, c3 = st.columns(3)
    c1.metric("Invested (virtual)", rupees(df.amount.sum()))
    c2.metric("Worth now", rupees(df.value.sum()))
    c3.metric("Profit / loss", rupees(df.pnl.sum()), f"{df.pnl.sum() / df.amount.sum() * 100:+.2f}%")
    st.dataframe(df[["symbol", "date", "price", "amount", "last_close", "value", "pnl", "pnl_pct"]], hide_index=True,
                 width="stretch", column_config={
                     "date": "Bought on", "price": st.column_config.NumberColumn("Buy price", format="₹%.2f"),
                     "amount": st.column_config.NumberColumn("Invested", format="₹%d"),
                     "last_close": st.column_config.NumberColumn("Last close", format="₹%.2f"),
                     "value": st.column_config.NumberColumn("Worth now", format="₹%d"),
                     "pnl": st.column_config.NumberColumn("P/L", format="₹%d"),
                     "pnl_pct": st.column_config.NumberColumn("P/L %", format="%.1f")})
    bar = px.bar(df, x="symbol", y="pnl", color=df.pnl.ge(0).map({True: "Gain", False: "Loss"}),
                 color_discrete_map={"Gain": "#1baf7a", "Loss": "#e34948"}, labels={"pnl": "Profit / loss (₹)", "color": ""})
    bar.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(bar, width="stretch")
    drop = st.selectbox("Remove a position", [""] + [f"{i}: {r['symbol']} on {r['date']}" for i, r in enumerate(rows)])
    if drop and st.button("Remove it"):
        rows.pop(int(drop.split(":")[0]))
        save_paper(rows)
        st.rerun()
    st.caption(f"Prices as of {df.as_of.max():%d %b %Y}. " + DISCLAIMER)


def page_validation() -> None:
    st.title("Does it work? Our alerts vs NSE's own actions")
    v = q("select * from gold.mart_surveillance_validation order by sort_order")
    names = {"HIGH": "High alert", "MEDIUM": "Medium alert", "LOW": "Low alert", "NOT_ALERTED": "Not alerted",
             "ALL_STOCKS": "All stocks", "ANY_ALERT": "Any alert"}
    v["label"] = v.segment.map(names) + " (" + v.stocks.map("{:,}".format) + ")"
    main = v[v.segment != "ANY_ALERT"]
    high, anyv = v[v.segment == "HIGH"].iloc[0], v[v.segment == "ANY_ALERT"].iloc[0]
    c1, c2, c3 = st.columns(3)
    c1.metric("HIGH alerts on NSE's short-term list", f"{high.stasm_pct:.1f}%", f"{high.stasm_lift:.1f}x the average stock")
    c2.metric("HIGH alerts NSE queried", f"{high.queried_pct:.1f}%", f"{high.queried_lift:.1f}x the average stock")
    on_time = anyv.flagged_before_query + anyv.flagged_same_day
    total = on_time + anyv.flagged_after_query
    c3.metric("Flagged on or before NSE's query", f"{on_time / total * 100:.0f}%", f"{int(on_time)} of {int(total)} stocks")
    long = main.melt(id_vars="label", value_vars=["stasm_pct", "queried_pct"], var_name="measure", value_name="pct")
    long["measure"] = long.measure.map({"stasm_pct": "On NSE short-term surveillance list", "queried_pct": "Queried by NSE"})
    fig = px.bar(long, y="label", x="pct", color="measure", barmode="group", orientation="h",
                 color_discrete_sequence=["#2a78d6", "#eb6834"], labels={"pct": "% of stocks in the group", "label": "", "measure": ""})
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(autorange="reversed"),
                      legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig, width="stretch")
    st.subheader("HIGH-alert stocks NSE also acted on")
    o = q("""select symbol, max_risk_score, first_alert_date, first_query_date, query_lead_days, on_stasm
             from intermediate.int_alert_outcomes where best_band = 'HIGH' and (exchange_queried or on_stasm)
             order by first_alert_date desc""")
    st.dataframe(o, hide_index=True, width="stretch", column_config={
        "max_risk_score": st.column_config.NumberColumn("Top score", format="%d"),
        "first_alert_date": st.column_config.DateColumn("We flagged", format="DD MMM"),
        "first_query_date": st.column_config.DateColumn("NSE queried", format="DD MMM"),
        "query_lead_days": st.column_config.NumberColumn("Days ahead of NSE"),
        "on_stasm": st.column_config.CheckboxColumn("On short-term list")})
    st.caption("A few weeks of data and a small HIGH group, so the multiples will move. NSE's own triggers use volume "
               "and price too, so some agreement is expected: this shows the engine matches NSE's screening.")


def page_health() -> None:
    st.title("Pipeline health")
    fresh = q("select max(trade_date) as d, count(distinct trade_date) as days, count(distinct symbol) as stocks from gold.fact_stock_daily").iloc[0]
    c1, c2, c3 = st.columns(3)
    c1.metric("Latest trading day loaded", f"{fresh.d:%d %b %Y}")
    c2.metric("Trading days", int(fresh.days))
    c3.metric("Stocks", f"{int(fresh.stocks):,}")
    runs = q("""select run_date, step, status, started_at, duration_s, detail from ops.pipeline_runs
                order by started_at desc limit 40""")
    st.subheader("Recent pipeline steps")
    st.dataframe(runs, hide_index=True, width="stretch", column_config={
        "started_at": st.column_config.DatetimeColumn("Started", format="DD MMM HH:mm"),
        "duration_s": st.column_config.NumberColumn("Seconds", format="%.0f")})
    st.subheader("Data-quality checks (latest run)")
    dq = q("""select check_name, status, value, detail, checked_at from ops.dq_results
              where checked_at >= (select max(checked_at) - interval 1 minute from ops.dq_results) order by check_name""")
    st.dataframe(dq, hide_index=True, width="stretch")


PAGES = {"Today's alerts": page_today, "Stock explorer": page_stock, "What happened next": page_what_next,
         "Paper portfolio": page_paper, "Does it work": page_validation, "Pipeline health": page_health}
st.sidebar.title("📊 NSE surveillance")
page = st.sidebar.radio("Page", list(PAGES), key="page")
try:
    PAGES[page]()
except duckdb.IOException:
    st.warning("The warehouse is busy (the daily pipeline is probably writing to it). Try again in a minute.")
st.sidebar.caption("Signals for analysis, not accusations.")
