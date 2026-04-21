UPDATE transactions
SET type = 'LiabilityPayment'
WHERE type = 'Debt';

UPDATE recurring_transactions
SET type = 'LiabilityPayment'
WHERE type = 'Debt';
