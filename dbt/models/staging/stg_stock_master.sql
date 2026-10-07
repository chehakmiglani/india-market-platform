-- Latest reference snapshot only; history comes from the dbt snapshot (SCD2).
select
    symbol,
    company_name,
    series,
    listing_date,
    isin,
    face_value,
    coalesce(industry, 'Unclassified') as industry,
    in_nifty500,
    snapshot_date
from {{ source('silver', 'stock_master') }}
where snapshot_date = (select max(snapshot_date) from {{ source('silver', 'stock_master') }})
