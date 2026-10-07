-- Calendar from 2013 (start of mfapi history). NSE holidays are *derived from data*:
-- a weekday inside the loaded range with no bhavcopy = exchange holiday.
with trading as (
    select distinct trade_date from {{ ref('stg_stock_daily') }}
),
bounds as (
    select min(trade_date) as first_trade, max(trade_date) as last_trade from trading
),
spine as (
    select cast(d as date) as date_day
    from bounds,
         unnest(generate_series(date '2013-01-01',
                                greatest(current_date, last_trade),
                                interval 1 day)) as t(d)
)
select
    cast(strftime(s.date_day, '%Y%m%d') as integer)       as date_key,
    s.date_day                                            as "date",
    year(s.date_day)                                      as "year",
    quarter(s.date_day)                                   as "quarter",
    month(s.date_day)                                     as "month",
    strftime(s.date_day, '%b')                            as month_name,
    strftime(s.date_day, '%Y-%m')                         as year_month,
    weekofyear(s.date_day)                                as iso_week,
    isodow(s.date_day)                                    as day_of_week,
    strftime(s.date_day, '%a')                            as day_name,
    isodow(s.date_day) in (6, 7)                          as is_weekend,
    -- Indian financial year runs April-March: 2026-10-07 is FY27
    'FY' || right(cast(case when month(s.date_day) >= 4 then year(s.date_day) + 1
                            else year(s.date_day) end as varchar), 2) as fiscal_year,
    case when month(s.date_day) >= 4 then (month(s.date_day) - 4) // 3 + 1
         else (month(s.date_day) + 8) // 3 + 1 end        as fiscal_quarter,
    t.trade_date is not null                              as is_trading_day,
    (t.trade_date is null
        and isodow(s.date_day) not in (6, 7)
        and s.date_day between b.first_trade and b.last_trade) as is_nse_holiday,
    s.date_day between b.first_trade and b.last_trade     as in_loaded_range
from spine s
cross join bounds b
left join trading t on t.trade_date = s.date_day
