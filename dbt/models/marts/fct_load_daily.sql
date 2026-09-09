{#-
  One row per country and complete local day. A day is complete when its hour
  count matches the calendar: 24 normally, 23 on the spring DST date and 25 on
  the autumn one. Partial days at the edges of the dataset are dropped.
-#}

with hourly as (

    select * from {{ ref('fct_load_hourly') }}

),

daily as (

    select
        country_code,
        local_date,
        count(*) as n_hours,
        sum(load_mw) as total_mwh,
        avg(load_mw) as mean_load_mw,
        max(load_mw) as peak_load_mw,
        min(load_mw) as min_load_mw,
        arg_max(local_hour, load_mw) as peak_local_hour,
        sum(case when is_imputed then 1 else 0 end) as n_imputed_hours,
        max(case when is_weekend then 1 else 0 end) = 1 as is_weekend
    from hourly
    group by country_code, local_date

),

with_expected as (

    select
        *,
        {{ expected_hours_in_local_day('local_date') }} as expected_hours
    from daily

)

select
    country_code || '_' || strftime(local_date, '%Y%m%d') as load_day_key,
    country_code,
    local_date,
    n_hours,
    total_mwh,
    mean_load_mw,
    peak_load_mw,
    min_load_mw,
    peak_local_hour,
    n_imputed_hours,
    is_weekend
from with_expected
where n_hours = expected_hours
