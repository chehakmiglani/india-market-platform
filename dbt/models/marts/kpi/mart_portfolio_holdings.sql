-- Current holdings and P&L per owner and instrument (average-cost method).
with txn as (
    select * from {{ ref('fact_portfolio_txn') }}
),
agg as (
    select
        owner, asset_class, instrument_id,
        min(txn_date)                                              as first_txn_date,
        count(*)                                                   as txn_count,
        sum(quantity)                                              as held_qty,
        sum(quantity)     filter (where quantity > 0)              as bought_qty,
        sum(gross_amount) filter (where quantity > 0)              as bought_amount,
        coalesce(-sum(quantity) filter (where quantity < 0), 0)    as sold_qty,
        coalesce(sum(gross_amount) filter (where quantity < 0), 0) as sold_amount
    from txn
    group by all
),
last_stock as (
    select symbol as instrument_id, close as current_price, trade_date as price_date
    from {{ ref('fact_stock_daily') }}
    qualify row_number() over (partition by symbol order by trade_date desc) = 1
),
last_nav as (
    select cast(scheme_code as varchar) as instrument_id, nav as current_price, nav_date as price_date
    from {{ ref('fact_fund_nav') }}
    qualify row_number() over (partition by scheme_code order by nav_date desc) = 1
),
priced as (
    select
        a.*,
        a.bought_amount / nullif(a.bought_qty, 0)                  as avg_cost,
        coalesce(s.current_price, n.current_price)                 as current_price,
        coalesce(s.price_date, n.price_date)                       as price_date
    from agg a
    left join last_stock s on a.asset_class = 'STOCK'       and s.instrument_id = a.instrument_id
    left join last_nav   n on a.asset_class = 'MUTUAL_FUND' and n.instrument_id = a.instrument_id
)
select
    p.owner,
    p.asset_class,
    p.instrument_id,
    coalesce(ds.company_name, df.scheme_name)                     as instrument_name,
    coalesce(ds.industry, df.category)                            as sector_or_category,
    p.first_txn_date,
    p.txn_count,
    round(p.held_qty, 4)                                          as held_qty,
    round(p.avg_cost, 4)                                          as avg_cost,
    p.current_price,
    p.price_date,
    round(p.avg_cost * p.held_qty, 2)                             as invested_value,
    round(p.current_price * p.held_qty, 2)                        as current_value,
    round(p.current_price * p.held_qty - p.avg_cost * p.held_qty, 2) as unrealized_pnl,
    round((p.current_price / nullif(p.avg_cost, 0) - 1) * 100, 2) as unrealized_pnl_pct,
    round(p.sold_amount - p.avg_cost * p.sold_qty, 2)             as realized_pnl,
    round(p.current_price * p.held_qty
          / sum(p.current_price * p.held_qty) over (partition by p.owner) * 100, 2) as weight_pct
from priced p
left join {{ ref('dim_stock') }} ds on p.asset_class = 'STOCK' and ds.symbol = p.instrument_id and ds.is_current
left join {{ ref('dim_fund') }}  df on p.asset_class = 'MUTUAL_FUND' and cast(df.scheme_code as varchar) = p.instrument_id
