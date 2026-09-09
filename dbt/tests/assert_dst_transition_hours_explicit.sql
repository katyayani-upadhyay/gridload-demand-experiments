-- The EU changes clocks at 01:00 UTC. In each country that instant is local
-- hour (1 + standard offset): that hour must be absent on the spring date and
-- present twice on the autumn date. On every other day each local hour must
-- appear exactly once. This pins the local-time derivation itself, not just
-- the daily totals.
with hourly as (

    select
        h.country_code,
        h.local_date,
        h.local_hour,
        c.standard_utc_offset_hours + 1 as transition_hour,
        count(*) as n_rows
    from {{ ref('fct_load_hourly') }} as h
    inner join {{ ref('dim_country') }} as c on h.country_code = c.country_code
    group by h.country_code, h.local_date, h.local_hour, c.standard_utc_offset_hours

),

expected as (

    select
        *,
        case
            when local_date = {{ dst_spring_forward_date('local_date') }}
                 and local_hour = transition_hour then 0
            when local_date = {{ dst_fall_back_date('local_date') }}
                 and local_hour = transition_hour then 2
            else 1
        end as expected_rows
    from hourly

),

edges as (

    select
        country_code,
        min(local_date) as first_date,
        max(local_date) as last_date
    from hourly
    group by country_code

),

missing_spring_hour as (

    -- count(*) never yields 0 rows for an absent hour, so check presence directly
    select
        c.country_code,
        d.local_date,
        c.standard_utc_offset_hours + 1 as local_hour,
        0 as n_rows,
        0 as expected_rows
    from (select distinct country_code, local_date from hourly) as d
    inner join {{ ref('dim_country') }} as c on d.country_code = c.country_code
    where d.local_date = {{ dst_spring_forward_date('d.local_date') }}
      and exists (
          select 1 from hourly as h
          where h.country_code = d.country_code
            and h.local_date = d.local_date
            and h.local_hour = c.standard_utc_offset_hours + 1
      )

)

select
    e.country_code,
    e.local_date,
    e.local_hour,
    e.n_rows,
    e.expected_rows
from expected as e
inner join edges as b on e.country_code = b.country_code
where e.local_date > b.first_date
  and e.local_date < b.last_date
  and e.n_rows <> e.expected_rows

union all

select * from missing_spring_hour
