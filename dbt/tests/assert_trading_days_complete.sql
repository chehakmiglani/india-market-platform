-- A trading day with far fewer stocks than usual means a truncated / partial bhavcopy.
select trade_date, count(*) as stocks
from {{ ref('fact_stock_daily') }}
group by trade_date
having count(*) < {{ var('min_stocks_per_trading_day') }}
