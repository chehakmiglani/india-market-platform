select
    trade_date,
    index_name,
    open, high, low, close,
    points_change,
    pct_change,
    volume,
    turnover_cr,
    pe, pb, div_yield
from {{ source('silver', 'index_daily') }}
