-- Fix the trades ID sequence after backfill inserted rows with explicit IDs.
-- The auto-increment sequence was stuck at ~103 while MAX(id) is 329+.
-- setval with true means the NEXT nextval() call returns max+1.
SELECT setval(
  pg_get_serial_sequence('deepstack_trades', 'id'),
  (SELECT MAX(id) FROM deepstack_trades),
  true
);
