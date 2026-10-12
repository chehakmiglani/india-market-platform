select snapshot_date, symbol, list_type, stage, description
from {{ source('silver', 'surveillance_lists') }}
