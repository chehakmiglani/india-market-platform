-- Does the surveillance engine catch what NSE catches?
-- For each alert band: share of stocks NSE queried or put on ASM/GSM, versus all stocks.
-- lift = band rate / all-stock rate (1.0 = no better than picking stocks at random).
with o as (select * from {{ ref('int_alert_outcomes') }}),
segments as (
    select best_band as segment, * exclude (best_band) from o
    union all
    select 'ANY_ALERT', * exclude (best_band) from o where best_band <> 'NOT_ALERTED'
    union all
    select 'ALL_STOCKS', * exclude (best_band) from o
),
agg as (
    select segment,
        count(*)                                                   as stocks,
        count(*) filter (where exchange_queried)                   as queried,
        count(*) filter (where on_stasm)                           as on_stasm,
        count(*) filter (where on_any_list)                        as on_any_list,
        -- of the stocks NSE queried, how many did we flag first / same day / only after
        count(*) filter (where query_lead_days > 0)                as flagged_before_query,
        count(*) filter (where query_lead_days = 0)                as flagged_same_day,
        count(*) filter (where query_lead_days < 0)                as flagged_after_query,
        median(query_lead_days)                                    as median_query_lead_days
    from segments group by 1
),
base as (select * from agg where segment = 'ALL_STOCKS')
select
    a.segment,
    case a.segment when 'HIGH' then 1 when 'MEDIUM' then 2 when 'LOW' then 3
                   when 'ANY_ALERT' then 4 when 'NOT_ALERTED' then 5 else 6 end  as sort_order,
    a.stocks,
    a.queried,       round(100.0 * a.queried / a.stocks, 1)       as queried_pct,
    round((a.queried / a.stocks) / nullif(b.queried / b.stocks, 0), 1)          as queried_lift,
    a.on_stasm,      round(100.0 * a.on_stasm / a.stocks, 1)      as stasm_pct,
    round((a.on_stasm / a.stocks) / nullif(b.on_stasm / b.stocks, 0), 1)        as stasm_lift,
    a.on_any_list,   round(100.0 * a.on_any_list / a.stocks, 1)   as any_list_pct,
    round((a.on_any_list / a.stocks) / nullif(b.on_any_list / b.stocks, 0), 1)  as any_list_lift,
    a.flagged_before_query, a.flagged_same_day, a.flagged_after_query, a.median_query_lead_days
from agg a cross join base b
order by sort_order
