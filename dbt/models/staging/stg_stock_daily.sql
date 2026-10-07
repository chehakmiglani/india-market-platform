-- One row per (trade_date, symbol). Split/bonus-adjusted prices are the default;
-- raw_* keep what actually printed on the exchange.
select
    trade_date,
    symbol,
    series,
    adj_open        as open,
    adj_high        as high,
    adj_low         as low,
    adj_close       as close,
    adj_prev_close  as prev_close,
    adj_vwap        as vwap,
    adj_volume      as volume,
    close           as raw_close,
    volume          as raw_volume,
    adj_factor,
    turnover_lacs,
    num_trades,
    deliv_qty,
    deliv_pct,
    _ingested_at
from {{ source('silver', 'stock_daily_adjusted') }}
where series in ('EQ', 'BE', 'BZ', 'SM', 'ST')
-- a symbol can move between series (e.g. EQ -> BE); keep the main one
qualify row_number() over (
    partition by trade_date, symbol
    order by case series when 'EQ' then 0 when 'BE' then 1 else 2 end
) = 1
