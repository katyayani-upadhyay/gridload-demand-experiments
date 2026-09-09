-- Local days must have 24 hours, except 23 on the spring DST date and 25 on
-- the autumn one. The first and last local date per country are excluded
-- because the dataset boundary falls mid-day in local time.
with daily as (

    select
        country_code,
        local_date,
        count(*) as n_hours
    from {{ ref('fct_load_hourly') }}
    group by country_code, local_date

),

edges as (

    select
        country_code,
        min(local_date) as first_date,
        max(local_date) as last_date
    from daily
    group by country_code

)

select
    d.country_code,
    d.local_date,
    d.n_hours,
    {{ expected_hours_in_local_day('d.local_date') }} as expected_hours
from daily as d
inner join edges as e on d.country_code = e.country_code
where d.local_date > e.first_date
  and d.local_date < e.last_date
  and d.n_hours <> {{ expected_hours_in_local_day('d.local_date') }}
