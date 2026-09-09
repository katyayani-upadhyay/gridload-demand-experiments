-- Hourly load must sit inside each country's plausible band from the seed.
select
    h.country_code,
    h.utc_timestamp,
    h.load_mw,
    c.min_plausible_load_mw,
    c.max_plausible_load_mw
from {{ ref('fct_load_hourly') }} as h
inner join {{ ref('dim_country') }} as c on h.country_code = c.country_code
where h.load_mw < c.min_plausible_load_mw
   or h.load_mw > c.max_plausible_load_mw
