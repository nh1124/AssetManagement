INSERT INTO monthly_budgets (id, client_id, account_id, target_period, amount)
SELECT
    md5(random()::text || clock_timestamp()::text)::uuid,
    b.client_id,
    a.id,
    b.month,
    b.proposed_amount
FROM budgets b
JOIN accounts a ON a.name = b.category AND a.client_id = b.client_id
ON CONFLICT (account_id, target_period) DO NOTHING;

DROP TABLE IF EXISTS budgets;
