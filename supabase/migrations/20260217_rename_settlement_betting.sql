-- Rename market_making → settlement_betting across all tables
-- The strategy buys cheap YES contracts hoping for settlement, not actual market making.

UPDATE deepstack_strategy_status SET name = 'settlement_betting' WHERE name = 'market_making' AND NOT EXISTS (SELECT 1 FROM deepstack_strategy_status WHERE name = 'settlement_betting');
UPDATE deepstack_trades SET strategy = 'settlement_betting' WHERE strategy = 'market_making';
