-- Point-to-point returns, risk and drawdown for funds with real history (>= 1 year of NAVs).
{% set rf = var('risk_free_rate') %}
{% set tdy = var('trading_days_per_year') %}
with nav as (
    select scheme_code, nav_date, nav, return_pct / 100 as r
    from {{ ref('fact_fund_nav') }}
    where scheme_code in (
        select scheme_code from {{ ref('fact_fund_nav') }} group by 1 having count(*) >= 250
    )
),
latest as (
    select scheme_code, max(nav_date) as as_of_date, arg_max(nav, nav_date) as nav_now
    from nav group by 1
),
horizons(label, days) as (
    values ('1M', 30), ('3M', 91), ('6M', 182), ('1Y', 365), ('3Y', 1095), ('5Y', 1826)
),
targets as (
    select l.scheme_code, l.as_of_date, l.nav_now, h.label, h.days,
           l.as_of_date - h.days * interval 1 day as target_date
    from latest l cross join horizons h
),
pit as (  -- NAV on or before each horizon start (handles weekends and holidays)
    select t.*, n.nav as nav_then, n.nav_date as then_date
    from targets t
    asof join nav n on n.scheme_code = t.scheme_code and n.nav_date <= t.target_date
),
returns as (
    select
        scheme_code,
        max(case when label = '1M' then nav_now / nav_then - 1 end) as ret_1m,
        max(case when label = '3M' then nav_now / nav_then - 1 end) as ret_3m,
        max(case when label = '6M' then nav_now / nav_then - 1 end) as ret_6m,
        max(case when label = '1Y' then nav_now / nav_then - 1 end) as ret_1y,
        -- > 1 year: annualised (CAGR)
        max(case when label = '3Y' then power(nav_now / nav_then, 365.0 / (as_of_date - then_date)) - 1 end) as cagr_3y,
        max(case when label = '5Y' then power(nav_now / nav_then, 365.0 / (as_of_date - then_date)) - 1 end) as cagr_5y
    from pit
    group by 1
),
risk_1y as (
    select n.scheme_code,
           stddev_samp(n.r) * sqrt({{ tdy }}) as vol_1y,
           count(*)                         as obs_1y
    from nav n join latest l using (scheme_code)
    where n.nav_date > l.as_of_date - interval 365 day
    group by 1
),
dd as (  -- drawdown from running peak, last 3 years
    select n.scheme_code,
           n.nav / max(n.nav) over (partition by n.scheme_code order by n.nav_date
                                    rows between unbounded preceding and current row) - 1 as dd_point
    from nav n join latest l using (scheme_code)
    where n.nav_date > l.as_of_date - interval 1095 day
),
max_dd as (select scheme_code, min(dd_point) as max_drawdown_3y from dd group by 1),
rolling as (  -- 1-year rolling returns, sampled daily over the last 3 years
    select a.scheme_code, a.nav / b.nav - 1 as roll_1y
    from nav a
    join latest l using (scheme_code)
    asof join nav b on b.scheme_code = a.scheme_code and b.nav_date <= a.nav_date - interval 365 day
    where a.nav_date > l.as_of_date - interval 1095 day
),
roll_stats as (
    select scheme_code,
           avg(roll_1y) as roll_1y_avg, min(roll_1y) as roll_1y_min, max(roll_1y) as roll_1y_max,
           avg(case when roll_1y > 0 then 1.0 else 0.0 end) as roll_1y_pct_positive
    from rolling group by 1
)
select
    l.scheme_code,
    f.scheme_name, f.amc, f.category, f.asset_class, f.plan, f.option_type,
    l.as_of_date,
    l.nav_now                                       as latest_nav,
    round(r.ret_1m * 100, 2)   as return_1m_pct,
    round(r.ret_3m * 100, 2)   as return_3m_pct,
    round(r.ret_6m * 100, 2)   as return_6m_pct,
    round(r.ret_1y * 100, 2)   as return_1y_pct,
    round(r.cagr_3y * 100, 2)  as cagr_3y_pct,
    round(r.cagr_5y * 100, 2)  as cagr_5y_pct,
    round(k.vol_1y * 100, 2)   as volatility_1y_pct,
    round((r.ret_1y - {{ rf }}) / nullif(k.vol_1y, 0), 2) as sharpe_1y,
    round(m.max_drawdown_3y * 100, 2) as max_drawdown_3y_pct,
    round(s.roll_1y_avg * 100, 2) as rolling_1y_avg_pct,
    round(s.roll_1y_min * 100, 2) as rolling_1y_min_pct,
    round(s.roll_1y_max * 100, 2) as rolling_1y_max_pct,
    round(s.roll_1y_pct_positive * 100, 1) as rolling_1y_positive_pct
from latest l
left join returns    r using (scheme_code)
left join risk_1y    k using (scheme_code)
left join max_dd     m using (scheme_code)
left join roll_stats s using (scheme_code)
left join {{ ref('dim_fund') }} f using (scheme_code)
