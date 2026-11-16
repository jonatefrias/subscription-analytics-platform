select
    experiment_id,
    customer_id,
    variant,
    cast(assigned_at as timestamp) as assigned_at
from {{ source('raw', 'experiments_assignments') }}
