-- Ground truth for our alerts: what did NSE itself do about each stock?
-- One row per stock in the surveillance universe over the alert window.
--   * exchange query: NSE asked the company to explain a volume/price move (dated, from announcements)
--   * ASM / GSM list: on NSE's surveillance lists in the latest snapshot. first_listed_date is only
--     a real inclusion date when the stock was absent from the first snapshot (history starts 2026-10-09).
with win as (
    select min(trade_date) as start_date, max(trade_date) as end_date
    from {{ ref('fact_surveillance_alert') }}
),
universe as (
    select distinct s.symbol
    from {{ ref('int_surveillance_signals') }} s, win
    where s.trade_date between win.start_date and win.end_date
),
alerts as (
    select symbol,
        max(risk_score)                                                       as max_risk_score,
        case max(case risk_band when 'HIGH' then 3 when 'MEDIUM' then 2 else 1 end)
            when 3 then 'HIGH' when 2 then 'MEDIUM' else 'LOW' end            as best_band,
        min(trade_date)                                                       as first_alert_date,
        min(trade_date) filter (where risk_band = 'HIGH')                    as first_high_date,
        count(*)                                                              as alert_days
    from {{ ref('fact_surveillance_alert') }}
    group by 1
),
queries as (
    -- queries from a few days before the window too, so "NSE was first" cases are counted
    select a.symbol, min(a.announced_date) as first_query_date, count(*) as queries
    from {{ ref('stg_announcements') }} a, win
    where a.news_type = 'EXCHANGE_QUERY'
      and a.announced_date between win.start_date - interval 5 day and win.end_date + interval 1 day
    group by 1
),
lists as (
    select symbol,
        bool_or(list_type = 'STASM' and snapshot_date = latest)                as on_stasm,
        bool_or(list_type = 'LTASM' and snapshot_date = latest)                as on_ltasm,
        bool_or(list_type = 'GSM'   and snapshot_date = latest)                as on_gsm,
        min(snapshot_date)                                                     as first_listed_date,
        min(snapshot_date) > min(first_snapshot)                               as listing_date_known
    from (select *, max(snapshot_date) over () as latest, min(snapshot_date) over () as first_snapshot
          from {{ ref('stg_surveillance_lists') }})
    group by 1
)
select
    u.symbol,
    coalesce(a.best_band, 'NOT_ALERTED')                                       as best_band,
    a.max_risk_score, a.first_alert_date, a.first_high_date, coalesce(a.alert_days, 0) as alert_days,
    q.first_query_date, coalesce(q.queries, 0)                                 as exchange_queries,
    q.first_query_date is not null                                             as exchange_queried,
    -- positive = we flagged it before NSE queried the company
    datediff('day', a.first_alert_date, q.first_query_date)                    as query_lead_days,
    coalesce(l.on_stasm, false)                                                as on_stasm,
    coalesce(l.on_ltasm, false)                                                as on_ltasm,
    coalesce(l.on_gsm, false)                                                  as on_gsm,
    coalesce(l.on_stasm or l.on_ltasm or l.on_gsm, false)                      as on_any_list,
    l.first_listed_date,
    coalesce(l.listing_date_known, false)                                      as listing_date_known
from universe u
left join alerts a using (symbol)
left join queries q using (symbol)
left join lists l using (symbol)
