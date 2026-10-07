with latest as (
    select *
    from {{ ref('stg_fund_nav') }}
    qualify row_number() over (partition by scheme_code order by nav_date desc, src_priority) = 1
)
select
    scheme_code,
    scheme_name,
    amc,
    category,
    case
        when category ilike 'Equity%'   then 'Equity'
        when category ilike 'Debt%'     then 'Debt'
        when category ilike 'Hybrid%'   then 'Hybrid'
        when category ilike 'Solution%' then 'Solution Oriented'
        else 'Other'
    end                                                       as asset_class,
    trim(split_part(category, ' - ', 2))                      as sub_category,
    case when scheme_name ilike '%direct%' then 'Direct' else 'Regular' end as plan,
    case
        when scheme_name ilike '%idcw%' or scheme_name ilike '%dividend%' then 'IDCW'
        when scheme_name ilike '%growth%' then 'Growth'
        else 'Other'
    end                                                       as option_type,
    isin_growth,
    nav_date                                                  as latest_nav_date,
    nav                                                       as latest_nav
from latest
