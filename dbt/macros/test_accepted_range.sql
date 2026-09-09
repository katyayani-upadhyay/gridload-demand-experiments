{% test accepted_range(model, column_name, min_value=none, max_value=none, inclusive=true) %}
{#- Rows whose value falls outside [min_value, max_value] fail the test. -#}
select {{ column_name }}
from {{ model }}
where {{ column_name }} is not null
{%- if min_value is not none %}
  and {{ column_name }} {{ '<' if inclusive else '<=' }} {{ min_value }}
{%- endif %}
{%- if max_value is not none %}
  and {{ column_name }} {{ '>' if inclusive else '>=' }} {{ max_value }}
{%- endif %}
{% endtest %}
