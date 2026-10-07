select
    row_number() over (order by owner, "date", symbol, "type", quantity, amount) as txn_id,
    trim(owner)                         as owner,
    cast("date" as date)                as txn_date,
    upper(trim("type"))                 as txn_type,
    upper(trim(cast(symbol as varchar))) as instrument_id,
    upper(trim(asset_class))            as asset_class,
    cast(quantity as double)            as quantity,
    cast(price as double)               as price,
    cast(amount as double)              as amount
from {{ source('portfolio', 'portfolio_txn') }}
