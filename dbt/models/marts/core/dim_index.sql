with names as (select distinct index_name from {{ ref('stg_index_daily') }})
select
    md5(index_name) as index_sk,
    index_name,
    case
        when regexp_matches(index_name, '^Nifty (50|Next 50|100|200|500|Midcap \d+|Smallcap \d+|Microcap 250|Total Market|LargeMidcap 250|MidSmallcap 400)$')
            then 'Broad Market'
        when regexp_matches(index_name, '(?i)bank|financial|IT$|pharma|auto|fmcg|metal|realty|energy|media|oil|healthcare|consumer durables|chemicals|services sector')
            then 'Sectoral'
        when regexp_matches(index_name, '(?i)vix') then 'Volatility'
        when regexp_matches(index_name, '(?i)g-sec|sdl|bond|gilt|t-bill|aaa|composite|gs ') then 'Fixed Income'
        else 'Strategy / Thematic'
    end as index_family
from names
