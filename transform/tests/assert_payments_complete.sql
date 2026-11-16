-- No charge may be lost between staging and the payments fact (e.g. through the subscription join).
select
    (select count(*) from {{ ref('stg_billing__payments') }}) as staged,
    (select count(*) from {{ ref('fct_payments') }})          as modelled
where (select count(*) from {{ ref('stg_billing__payments') }})
   <> (select count(*) from {{ ref('fct_payments') }})
