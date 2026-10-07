select
    cast(strftime(i.trade_date, '%Y%m%d') as integer) as date_key,
    i.trade_date,
    d.index_sk,
    i.index_name,
    i.open, i.high, i.low, i.close,
    i.points_change,
    i.pct_change,
    i.volume,
    i.turnover_cr,
    i.pe, i.pb, i.div_yield
from {{ ref('stg_index_daily') }} i
join {{ ref('dim_index') }} d using (index_name)
