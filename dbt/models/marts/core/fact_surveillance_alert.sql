-- Risk score 0-100 = strongest rule + half the rest + illiquidity bump (capped).
-- News columns give context (filings in the 3 days up to the alert); they don't change the score.
-- Flags are signals for analysis, not accusations.
{% set v = var('surveillance') %}
with s as (
    select * from {{ ref('int_surveillance_signals') }}
),
scored as (
    select
        s.*,
        {% if v.baseline == 'per_stock' %}
        -- points scale with how unusual the day is for this stock: 3 sd -> 24 pts, 5 sd+ -> 40
        case when r_volume_spike     then least(40, round(8 * volume_z)) else 0 end             as pts_volume,
        case when r_price_shock      then least(30, round(6 * price_z)) else 0 end              as pts_price_shock,
        {% else %}
        -- volume: 5x -> 23 pts, 10x -> 33, 16x+ -> 40
        case when r_volume_spike     then least(40, round(10 * log2(volume_ratio_20d))) else 0 end as pts_volume,
        case when r_price_shock      then least(30, round(2 * abs(return_pct - peer_return_pct))) else 0 end as pts_price_shock,
        {% endif %}
        case when r_pump             then 25 else 0 end                                         as pts_pump,
        case when r_dump_after_pump  then 30 else 0 end                                         as pts_dump,
        case when r_delivery_anomaly then 15 else 0 end                                         as pts_delivery,
        case when r_circuit_streak   then least(30, 10 * circuit_streak) else 0 end             as pts_circuit,
        case when r_gap_move         then least(20, round(2 * abs(gap_pct))) else 0 end         as pts_gap,
        -- thinly traded stocks are easier to move
        case when avg_turnover_cr_20d < {{ v.illiquid_turnover_cr }} then 10 else 0 end         as pts_illiquid
    from s
    where r_volume_spike or r_price_shock or r_pump or r_dump_after_pump
       or r_delivery_anomaly or r_circuit_streak or r_gap_move
),
final as (
    -- Rules are correlated (a news day trips volume + price + delivery together), so plain
    -- addition triple-counts one event: strongest rule counts fully, the rest at half weight.
    select *,
        least(100, round(
            greatest(pts_volume, pts_price_shock, pts_pump, pts_dump, pts_delivery, pts_circuit, pts_gap)
            + 0.5 * (pts_volume + pts_price_shock + pts_pump + pts_dump + pts_delivery + pts_circuit + pts_gap
                     - greatest(pts_volume, pts_price_shock, pts_pump, pts_dump, pts_delivery, pts_circuit, pts_gap))
            + pts_illiquid))                                                    as risk_score
    from scored
),
news as (
    select f.trade_date, f.symbol,
        string_agg(distinct a.news_type, ', ' order by a.news_type)
            filter (where a.news_type not in ('ROUTINE', 'EXCHANGE_QUERY'))      as news_types,
        count(*) filter (where a.news_type not in ('ROUTINE', 'EXCHANGE_QUERY')) as material_news_count,
        bool_or(a.news_type = 'EXCHANGE_QUERY')                                   as exchange_query
    from final f
    join {{ ref('stg_announcements') }} a
      on a.symbol = f.symbol
     and a.announced_date between f.trade_date - interval 3 day and f.trade_date
    group by 1, 2
)
select
    md5(cast(trade_date as varchar) || '|' || symbol)                             as alert_id,
    date_key, trade_date, symbol, stock_sk, company_name, industry,
    risk_score,
    case when risk_score >= 70 then 'HIGH' when risk_score >= 40 then 'MEDIUM' else 'LOW' end as risk_band,
    concat_ws(', ',
        case when r_volume_spike     then 'VOLUME_SPIKE' end,
        case when r_price_shock      then 'PRICE_SHOCK' end,
        case when r_pump             then 'PUMP_PATTERN' end,
        case when r_dump_after_pump  then 'DUMP_AFTER_PUMP' end,
        case when r_delivery_anomaly then 'DELIVERY_ANOMALY' end,
        case when r_circuit_streak   then 'CIRCUIT_STREAK' end,
        case when r_gap_move         then 'GAP_MOVE' end)                          as rules_triggered,
    concat_ws('; ',
        {% if v.baseline == 'per_stock' %}
        case when r_volume_spike then format('Volume {:.1f}x its 20-day average ({:.1f} sd above its own normal)', volume_ratio_20d, volume_z) end,
        case when r_price_shock then format('Moved {:+.1f}% while its sector moved {:+.1f}% ({:.1f}x its usual daily swing)', return_pct, peer_return_pct, price_z) end,
        {% else %}
        case when r_volume_spike then format('Volume {:.1f}x its 20-day average', volume_ratio_20d) end,
        case when r_price_shock then format('Moved {:+.1f}% while its sector moved {:+.1f}%', return_pct, peer_return_pct) end,
        {% endif %}
        case when r_pump then format('Up {:.1f}% in 5 days on {:.1f}x volume with delivery only {:.0f}% (usual {:.0f}%)',
                                     return_5d_pct, volume_ratio_5d, deliv_pct_5d, deliv_pct_20d_avg) end,
        case when r_dump_after_pump then format('Fell {:.1f}% (3-day {:.1f}%) after a recent pump pattern', return_pct, return_3d_pct) end,
        case when r_delivery_anomaly then format('Delivery {:.0f}% vs usual {:.0f}% on {:.1f}x volume', deliv_pct, deliv_pct_20d_avg, volume_ratio_20d) end,
        case when r_circuit_streak then format('{} consecutive closes at a price-band limit', circuit_streak) end,
        case when r_gap_move then format('Opened {:+.1f}% from previous close and held the gap', gap_pct) end,
        case when pts_illiquid > 0 then format('Thinly traded (avg turnover Rs {:.2f} cr/day)', avg_turnover_cr_20d) end
    )                                                                              as reason,
    close, return_pct, gap_pct, return_5d_pct, volume, volume_ratio_20d, deliv_pct, deliv_pct_20d_avg,
    peer_return_pct, avg_turnover_cr_20d, circuit_streak, volume_z, price_z,
    pts_volume, pts_price_shock, pts_pump, pts_dump, pts_delivery, pts_circuit, pts_gap, pts_illiquid,
    news.news_types,
    coalesce(news.material_news_count, 0)                                          as material_news_count,
    coalesce(news.exchange_query, false)                                           as exchange_query
from final
left join news using (trade_date, symbol)
where risk_score >= {{ v.min_alert_score }}
