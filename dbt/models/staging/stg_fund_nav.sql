-- AMFI daily file (all ~14k schemes, latest NAV) + mfapi history (watchlist funds).
-- Where both have a NAV for the same day, AMFI wins.
with unioned as (
    select scheme_code, nav_date, nav, scheme_name, amc, category, isin_growth, 0 as src_priority
    from {{ source('silver', 'fund_nav') }}
    union all
    select scheme_code, nav_date, nav, scheme_name, amc, category, null as isin_growth, 1 as src_priority
    from {{ source('silver', 'fund_nav_history') }}
)
select *
from unioned
qualify row_number() over (partition by scheme_code, nav_date order by src_priority) = 1
