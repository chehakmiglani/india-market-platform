select symbol, ex_date, action_type, factor, subject
from {{ source('silver', 'corporate_actions') }}
