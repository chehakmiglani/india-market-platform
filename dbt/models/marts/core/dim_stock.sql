-- SCD Type 2. The first version of each symbol is back-dated to 1900 so facts loaded
-- before the snapshot existed still find a row. stock_sk = 'unknown' catches ETFs/SME
-- symbols that trade in the bhavcopy but are not in NSE's equity master.
with versions as (
    select
        dbt_scd_id                                   as stock_sk,
        symbol, company_name, isin, series, face_value, listing_date, industry, in_nifty500,
        cast(dbt_valid_from as date)                 as valid_from_raw,
        cast(dbt_valid_to as date)                   as valid_to,
        row_number() over (partition by symbol order by dbt_valid_from) as version_no
    from {{ ref('snap_stock_master') }}
)
select
    stock_sk, symbol, company_name, isin, series, face_value, listing_date, industry, in_nifty500,
    case when version_no = 1 then date '1900-01-01' else valid_from_raw end as valid_from,
    coalesce(valid_to, date '9999-12-31')                                  as valid_to,
    valid_to is null                                                       as is_current,
    version_no
from versions

union all

select 'unknown', 'UNKNOWN', 'Not in NSE equity master (ETF / SME / other)', null, null, null, null,
       'Unclassified', false, date '1900-01-01', date '9999-12-31', true, 1
