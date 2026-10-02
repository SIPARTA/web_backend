-- ========================================================================================
-- Migration: Add user_id to incident_events and transaction_logs for Data Isolation
-- ========================================================================================

-- 1. Add user_id (UUID) to incident_events
ALTER TABLE incident_events
ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE;

-- 2. Add user_id (UUID) to transactions_logs
ALTER TABLE transactions_logs
ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE;

-- 3. Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_incident_events_user_id ON incident_events(user_id);
CREATE INDEX IF NOT EXISTS idx_transactions_logs_user_id ON transactions_logs(user_id);

-- Note: We do not enable RLS here because the backend API currently uses SUPABASE_SERVICE_ROLE_KEY 
-- which bypasses RLS. The data isolation will be enforced at the Backend/API layer first.
-- However, if Supabase RLS is desired, uncomment the following:
/*
ALTER TABLE incident_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can only view their own incidents" 
ON incident_events FOR SELECT 
USING (user_id = (SELECT id FROM users WHERE wallet_address = current_setting('request.jwt.claims', true)::json->>'address' OR 'google:' || current_setting('request.jwt.claims', true)::json->>'sub'));
*/
