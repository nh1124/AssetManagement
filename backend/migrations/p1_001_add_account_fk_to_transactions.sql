ALTER TABLE transactions
ADD COLUMN IF NOT EXISTS from_account_id INTEGER REFERENCES accounts(id);

ALTER TABLE transactions
ADD COLUMN IF NOT EXISTS to_account_id INTEGER REFERENCES accounts(id);

UPDATE transactions t
SET from_account_id = a.id
FROM accounts a
WHERE a.name = t.from_account
  AND a.client_id = t.client_id
  AND t.from_account_id IS NULL;

UPDATE transactions t
SET to_account_id = a.id
FROM accounts a
WHERE a.name = t.to_account
  AND a.client_id = t.client_id
  AND t.to_account_id IS NULL;
