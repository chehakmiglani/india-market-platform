-- SIP discipline per fund: installments made vs months elapsed since the first one.
with sip as (
    select *
    from {{ ref('fact_portfolio_txn') }}
    where asset_class = 'MUTUAL_FUND' and txn_type = 'SIP'
),
as_of as (select max(nav_date) as as_of_date from {{ ref('fact_fund_nav') }})
select
    s.owner,
    s.instrument_id                                              as scheme_code,
    f.scheme_name,
    count(*)                                                     as installments,
    min(s.txn_date)                                              as first_sip_date,
    max(s.txn_date)                                              as last_sip_date,
    mode(s.gross_amount)                                         as typical_amount,
    sum(s.gross_amount)                                          as total_invested,
    round(sum(s.quantity), 4)                                    as units_accumulated,
    datediff('month', min(s.txn_date), a.as_of_date) + 1         as months_since_start,
    round(count(*) / (datediff('month', min(s.txn_date), a.as_of_date) + 1) * 100, 1)
                                                                 as regularity_pct,
    max(s.txn_date) + interval 1 month                           as next_expected_date,
    a.as_of_date - max(s.txn_date) > 45                          as is_lapsed
from sip s
cross join as_of a
left join {{ ref('dim_fund') }} f on cast(f.scheme_code as varchar) = s.instrument_id
group by s.owner, s.instrument_id, f.scheme_name, a.as_of_date
