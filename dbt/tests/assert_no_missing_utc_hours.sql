-- Every country must have exactly one row for every UTC hour between its
-- first and last observation. Any gap or duplicate hour returns rows here.
with bounds as (

    select
        country_code,
        min(utc_timestamp) as first_hour,
        max(utc_timestamp) as last_hour,
        count(*) as n_rows,
        count(distinct utc_timestamp) as n_distinct_hours
    from {{ ref('fct_load_hourly') }}
    group by country_code

)

select
    country_code,
    n_rows,
    n_distinct_hours,
    date_diff('hour', first_hour, last_hour) + 1 as expected_hours
from bounds
where n_rows <> date_diff('hour', first_hour, last_hour) + 1
   or n_distinct_hours <> n_rows
