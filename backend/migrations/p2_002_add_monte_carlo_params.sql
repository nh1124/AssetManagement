ALTER TABLE simulation_configs
ADD COLUMN IF NOT EXISTS volatility FLOAT DEFAULT 15.0;

ALTER TABLE simulation_configs
ADD COLUMN IF NOT EXISTS inflation_rate FLOAT DEFAULT 2.0;
