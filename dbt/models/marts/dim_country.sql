select
    country_code,
    country_name,
    timezone,
    standard_utc_offset_hours,
    min_plausible_load_mw,
    max_plausible_load_mw
from {{ ref('countries') }}
