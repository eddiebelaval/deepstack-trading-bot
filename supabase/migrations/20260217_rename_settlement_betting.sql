-- Rename market_making → settlement_betting across all tables
-- The strategy buys cheap YES contracts hoping for settlement, not actual market making.

UPDATE deepstack_strategy_status SET name = 'settlement_betting' WHERE name = 'market_making';
UPDATE deepstack_trades SET strategy = 'settlement_betting' WHERE strategy = 'market_making';
