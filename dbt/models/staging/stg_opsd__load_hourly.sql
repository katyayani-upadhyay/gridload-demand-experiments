with source as (

    select * from {{ source('opsd', 'opsd_load_hourly') }}

),

unpivoted as (

    select utc_timestamp, 'ES' as country_code, es_load_mw as load_mw, ingested_at from source
    union all
    select utc_timestamp, 'PT' as country_code, pt_load_mw as load_mw, ingested_at from source

)

select
    country_code || '_' || strftime(utc_timestamp, '%Y%m%d%H') as load_hour_key,
    country_code,
    utc_timestamp,
    load_mw,
    ingested_at
from unpivoted
