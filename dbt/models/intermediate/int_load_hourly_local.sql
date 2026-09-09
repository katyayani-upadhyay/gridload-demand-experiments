{#-
  Adds local wall-clock time per country and fills the handful of missing
  hours. UTC stays the primary key: local timestamps repeat once a year at the
  autumn DST change and skip an hour in spring, so they are attributes, not keys.
  Missing hours are filled with the mean of the same hour one week before and
  after, falling back to whichever neighbour exists, then to the adjacent day.
-#}

with hourly as (

    select * from {{ ref('stg_opsd__load_hourly') }}

),

countries as (

    select * from {{ ref('countries') }}

),

neighbours as (

    select
        h.*,
        lag(h.load_mw, 168) over w as load_prev_week,
        lead(h.load_mw, 168) over w as load_next_week,
        lag(h.load_mw, 24) over w as load_prev_day,
        lead(h.load_mw, 24) over w as load_next_day
    from hourly as h
    window w as (partition by h.country_code order by h.utc_timestamp)

),

filled as (

    select
        n.load_hour_key,
        n.country_code,
        n.utc_timestamp,
        timezone(c.timezone, timezone('UTC', n.utc_timestamp)) as local_timestamp,
        coalesce(
            n.load_mw,
            (n.load_prev_week + n.load_next_week) / 2.0,
            n.load_prev_week,
            n.load_next_week,
            (n.load_prev_day + n.load_next_day) / 2.0,
            n.load_prev_day,
            n.load_next_day
        ) as load_mw,
        n.load_mw is null as is_imputed,
        n.ingested_at
    from neighbours as n
    inner join countries as c on n.country_code = c.country_code

)

select
    load_hour_key,
    country_code,
    utc_timestamp,
    local_timestamp,
    cast(local_timestamp as date) as local_date,
    hour(local_timestamp) as local_hour,
    dayofweek(local_timestamp) as day_of_week,
    dayofweek(local_timestamp) in (0, 6) as is_weekend,
    load_mw,
    is_imputed,
    ingested_at
from filled
