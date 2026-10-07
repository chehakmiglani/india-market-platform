-- Full rebuild on purpose: a new split rewrites every earlier adjusted price for that
-- symbol, so an incremental fact would keep stale history.
with px as (
    select * from {{ ref('stg_stock_daily') }}
),
metrics as (
    select
        px.*,
        round((close / nullif(prev_close, 0) - 1) * 100, 4)                  as return_pct,
        round((open  / nullif(prev_close, 0) - 1) * 100, 4)                  as gap_pct,
        round((high - low) / nullif(prev_close, 0) * 100, 4)                 as range_pct,
        avg(volume)    over w20                                              as avg_volume_20d,
        avg(deliv_pct) over w20                                              as avg_deliv_pct_20d,
        stddev_samp(close / nullif(prev_close, 0) - 1) over w20 * 100        as volatility_20d_pct,
        close / nullif(lag(close, 5) over w, 0) - 1                          as return_5d,
        count(*) over (partition by symbol order by trade_date
                       rows between unbounded preceding and current row)     as history_days
    from px
    window
        w   as (partition by symbol order by trade_date),
        w20 as (partition by symbol order by trade_date rows between 20 preceding and 1 preceding)
)
select
    cast(strftime(m.trade_date, '%Y%m%d') as integer)        as date_key,
    m.trade_date,
    m.symbol,
    coalesce(d.stock_sk, 'unknown')                          as stock_sk,
    m.series,
    m.open, m.high, m.low, m.close, m.prev_close, m.vwap,
    m.volume,
    m.raw_close, m.raw_volume, m.adj_factor,
    m.turnover_lacs,
    m.num_trades,
    m.deliv_qty,
    m.deliv_pct,
    m.return_pct,
    m.gap_pct,
    m.range_pct,
    round(m.return_5d * 100, 4)                              as return_5d_pct,
    m.avg_volume_20d,
    round(m.volume / nullif(m.avg_volume_20d, 0), 3)         as volume_ratio_20d,
    m.avg_deliv_pct_20d,
    round(m.volatility_20d_pct, 4)                           as volatility_20d_pct,
    m.history_days
from metrics m
left join {{ ref('dim_stock') }} d
    on d.symbol = m.symbol
   and m.trade_date >= d.valid_from
   and m.trade_date <  d.valid_to
