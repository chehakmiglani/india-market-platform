-- Daily breadth and returns per industry (Nifty 500 classification).
select
    f.date_key,
    f.trade_date,
    d.industry,
    count(*)                                              as stocks,
    round(avg(f.return_pct), 3)                           as avg_return_pct,
    round(median(f.return_pct), 3)                        as median_return_pct,
    -- turnover-weighted: what the money actually did
    round(sum(f.return_pct * f.turnover_lacs) / nullif(sum(f.turnover_lacs), 0), 3) as weighted_return_pct,
    count(*) filter (where f.return_pct > 0)              as advancers,
    count(*) filter (where f.return_pct < 0)              as decliners,
    round(sum(f.turnover_lacs) / 100, 2)                  as turnover_cr,
    round(avg(f.deliv_pct), 2)                            as avg_deliv_pct
from {{ ref('fact_stock_daily') }} f
join {{ ref('dim_stock') }} d on d.stock_sk = f.stock_sk
where f.return_pct is not null
group by all
