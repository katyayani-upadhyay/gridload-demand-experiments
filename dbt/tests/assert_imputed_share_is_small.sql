-- Imputation covers a few dozen hours per country. If more than 0.5 percent of
-- a country's hours are imputed, the source has changed and needs a look.
select
    country_code,
    avg(case when is_imputed then 1.0 else 0.0 end) as imputed_share
from {{ ref('fct_load_hourly') }}
group by country_code
having imputed_share > 0.005
