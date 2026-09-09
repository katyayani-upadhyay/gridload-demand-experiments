select
    load_hour_key,
    country_code,
    utc_timestamp,
    local_timestamp,
    local_date,
    local_hour,
    day_of_week,
    is_weekend,
    load_mw,
    is_imputed,
    ingested_at
from {{ ref('int_load_hourly_local') }}
