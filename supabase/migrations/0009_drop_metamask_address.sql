-- Drop metamask_address column as it's no longer used
ALTER TABLE users DROP COLUMN IF EXISTS metamask_address;
