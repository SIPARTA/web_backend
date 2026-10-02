-- ==========================================
-- MIGRATION: ADD METAMASK ADDRESS COLUMN
-- ==========================================

ALTER TABLE users 
ADD COLUMN IF NOT EXISTS metamask_address VARCHAR(42) UNIQUE;

-- Add comment explaining usage
COMMENT ON COLUMN users.metamask_address IS 'Explicitly linked MetaMask wallet. Prevents account overwrite when linking with Email/Google Auth.';
