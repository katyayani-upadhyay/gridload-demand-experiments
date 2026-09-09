{% macro dst_spring_forward_date(date_expr) -%}
    {#- Last Sunday of March; dayofweek() returns 0 for Sunday. -#}
    (make_date(year({{ date_expr }}), 3, 31) - dayofweek(make_date(year({{ date_expr }}), 3, 31))::integer)
{%- endmacro %}

{% macro dst_fall_back_date(date_expr) -%}
    {#- Last Sunday of October. -#}
    (make_date(year({{ date_expr }}), 10, 31) - dayofweek(make_date(year({{ date_expr }}), 10, 31))::integer)
{%- endmacro %}

{% macro expected_hours_in_local_day(date_expr) -%}
    case
        when {{ date_expr }} = {{ dst_spring_forward_date(date_expr) }} then 23
        when {{ date_expr }} = {{ dst_fall_back_date(date_expr) }} then 25
        else 24
    end
{%- endmacro %}
