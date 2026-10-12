-- One row per stock-day with every surveillance rule evaluated.
-- Thresholds live in dbt_project.yml vars so they can be tuned without code changes.
-- Everything uses split/bonus-adjusted data, so corporate actions don't look like crashes.
{% set v = var('surveillance') %}

with f as (
    select f.*, d.industry, d.company_name
    from {{ ref('fact_stock_daily') }} f
    join {{ ref('dim_stock') }} d on d.stock_sk = f.stock_sk
    where f.symbol not like '%BEES' and f.symbol not like '%ETF%'   -- ETFs aren't manipulation targets
),

-- what did the stock's sector (or the whole market, for unclassified stocks) do that day?
sector_day as (
    select trade_date, industry, median(return_pct) as sector_median_return
    from f where industry <> 'Unclassified' group by 1, 2
),
market_day as (
    select trade_date, median(return_pct) as market_median_return from f group by 1
),

w as (
    select
        f.*,
        coalesce(s.sector_median_return, m.market_median_return)               as peer_return_pct,
        -- 5-day window vs the 20 days before it
        avg(volume)    over w5  / nullif(avg(volume)    over w20_before5, 0)    as volume_ratio_5d,
        avg(deliv_pct) over w5                                                  as deliv_pct_5d,
        avg(deliv_pct) over w20_before5                                         as deliv_pct_base,
        stddev_samp(deliv_pct) over w20_before5                                 as deliv_pct_std,
        close / nullif(lag(close, 3) over w, 0) - 1                             as return_3d,
        avg(turnover_lacs) over w20_before5 / 100                               as avg_turnover_cr_20d,
        -- near-circuit close: closed at the day's extreme after a move close to an NSE price band.
        -- The 2% band is skipped: those stocks hit it constantly and NSE already watches them (ASM/GSM).
        (close = high and return_pct > 0 or close = low and return_pct < 0)
          and (abs(abs(return_pct) - 5) < 0.15
               or abs(abs(return_pct) - 10) < 0.15 or abs(abs(return_pct) - 20) < 0.15) as at_circuit,
        sign(return_pct)                                                        as direction
    from f
    left join sector_day s on s.trade_date = f.trade_date and s.industry = f.industry
    left join market_day m on m.trade_date = f.trade_date
    window
        w            as (partition by f.symbol order by f.trade_date),
        w5           as (partition by f.symbol order by f.trade_date rows between 4 preceding and current row),
        w20_before5  as (partition by f.symbol order by f.trade_date rows between 24 preceding and 5 preceding)
),

rules as (
    select
        *,
        history_days >= 25                                                      as has_history,
        volume_ratio_20d >= {{ v.volume_spike_x }}
            and turnover_lacs >= {{ v.min_spike_turnover_cr }} * 100            as r_volume_spike,
        abs(return_pct) >= {{ v.price_shock_pct }}
            and abs(peer_return_pct) < {{ v.sector_calm_pct }}                  as r_price_shock,
        return_5d_pct >= {{ v.pump_return_5d_pct }}
            and volume_ratio_5d >= {{ v.pump_volume_x }}
            and deliv_pct_5d < deliv_pct_base * {{ v.pump_low_delivery_ratio }} as r_pump,
        abs(gap_pct) >= {{ v.gap_pct }} and sign(close - open) = sign(gap_pct)  as r_gap,
        (deliv_pct >= deliv_pct_base + {{ v.delivery_z }} * deliv_pct_std and volume_ratio_20d >= 2)
          or (deliv_pct <= deliv_pct_base * 0.4 and volume_ratio_20d >= 3)    as r_delivery_anomaly
    from w
),

streaks as (  -- consecutive near-circuit closes in the same direction
    select *,
        sum(case when at_circuit then 1 else 0 end) over (
            partition by symbol, circuit_grp order by trade_date
            rows between unbounded preceding and current row)                   as circuit_streak
    from (
        select *,
            sum(case when at_circuit then 0 else 1 end) over (
                partition by symbol order by trade_date
                rows between unbounded preceding and current row)               as circuit_grp
        from rules
    )
),

pump_memory as (
    select *,
        max(case when r_pump then 1 else 0 end) over (
            partition by symbol order by trade_date
            rows between {{ v.dump_lookback_days }} preceding and 1 preceding) = 1 as pumped_recently
    from streaks
)

select
    trade_date, date_key, symbol, stock_sk, company_name, industry, series,
    close, return_pct, gap_pct, return_5d_pct, round(return_3d * 100, 2) as return_3d_pct,
    volume, volume_ratio_20d, round(volume_ratio_5d, 2) as volume_ratio_5d,
    deliv_pct, round(deliv_pct_5d, 2) as deliv_pct_5d, round(deliv_pct_base, 2) as deliv_pct_20d_avg,
    round(peer_return_pct, 2) as peer_return_pct,
    round(avg_turnover_cr_20d, 2) as avg_turnover_cr_20d,
    circuit_streak, history_days,
    has_history and coalesce(r_volume_spike, false)                         as r_volume_spike,
    has_history and coalesce(r_price_shock, false)                          as r_price_shock,
    has_history and coalesce(r_pump, false)                                 as r_pump,
    has_history and pumped_recently
        and (return_pct <= -{{ v.dump_return_pct }} or return_3d <= -{{ v.dump_return_3d_pct }} / 100.0)
                                                                            as r_dump_after_pump,
    has_history and coalesce(r_delivery_anomaly, false)                     as r_delivery_anomaly,
    has_history and circuit_streak >= {{ v.circuit_streak_days }}           as r_circuit_streak,
    has_history and coalesce(r_gap, false)                                  as r_gap_move
from pump_memory
