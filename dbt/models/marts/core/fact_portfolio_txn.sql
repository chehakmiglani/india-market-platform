-- quantity: + bought / - sold.  cash_flow: - money out / + money in (XIRR convention).
-- Mutual fund units = amount / NAV on or before the transaction date (weekends -> Friday's NAV).
with t as (
    select * from {{ ref('stg_portfolio_txn') }}
),
mf as (
    select t.txn_id, n.nav, n.nav_date
    from t
    asof join {{ ref('stg_fund_nav') }} n
        on n.scheme_code = try_cast(t.instrument_id as bigint)
       and n.nav_date <= t.txn_date
    where t.asset_class = 'MUTUAL_FUND'
      and n.nav_date >= t.txn_date - interval 10 day
),
priced as (
    select
        t.*,
        mf.nav_date                                                  as nav_date_used,
        case when t.txn_type in ('SELL', 'REDEEM', 'SWP') then -1 else 1 end as direction,
        case when t.asset_class = 'MUTUAL_FUND' then mf.nav else t.price end   as unit_price
    from t
    left join mf using (txn_id)
)
select
    txn_id,
    owner,
    cast(strftime(txn_date, '%Y%m%d') as integer)                    as date_key,
    txn_date,
    txn_type,
    asset_class,
    instrument_id,
    unit_price,
    nav_date_used,
    direction * coalesce(quantity, amount / nullif(unit_price, 0))   as quantity,
    coalesce(amount, quantity * unit_price)                          as gross_amount,
    -direction * coalesce(amount, quantity * unit_price)             as cash_flow
from priced
