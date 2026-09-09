{% test recency(model, column_name, at_least) %}
{#- Fails when the newest value in the column is older than `at_least`.
    The OPSD release is frozen, so recency is checked against the documented
    coverage end rather than the wall clock; a truncated download fails here. -#}
select max({{ column_name }}) as newest_value
from {{ model }}
having max({{ column_name }}) < '{{ at_least }}'::timestamp
{% endtest %}
