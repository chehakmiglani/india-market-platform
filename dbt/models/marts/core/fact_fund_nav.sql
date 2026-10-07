select
    cast(strftime(nav_date, '%Y%m%d') as integer)                         as date_key,
    nav_date,
    scheme_code,
    nav,
    round((nav / nullif(lag(nav) over (partition by scheme_code order by nav_date), 0) - 1) * 100, 6)
                                                                           as return_pct
from {{ ref('stg_fund_nav') }}
