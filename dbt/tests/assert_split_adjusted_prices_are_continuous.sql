-- On a split/bonus ex-date the *adjusted* close must not jump by the split factor.
-- Fails if adjusted close moved more than 40% vs the previous trading day on an ex-date.
with px as (
    select symbol, trade_date, close,
           lag(close) over (partition by symbol order by trade_date) as prev_row_close
    from {{ ref('fact_stock_daily') }}
)
select ca.symbol, ca.ex_date, ca.factor, px.prev_row_close, px.close
from {{ ref('stg_corporate_actions') }} ca
join px on px.symbol = ca.symbol and px.trade_date = ca.ex_date
where px.prev_row_close is not null
  and abs(px.close / px.prev_row_close - 1) > 0.40
