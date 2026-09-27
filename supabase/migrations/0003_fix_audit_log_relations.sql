-- Migration 0003: Perbaikan relasi incident_events ke audit_log
-- Sesuai dengan instruksi, memastikan struktur PK/FK sesuai standar IoT SIPARTA

-- 1. Karena tabel yang eksis di Supabase saat ini adalah `audit_log` (singular) 
--    dan di skema awal ditulis `audit_logs` (plural), kita standarisasi menjadi `audit_log`.
--    Kita asumsikan tabel `audit_log` sudah ada berdasarkan skema terbaru di Supabase.

-- 2. Rename kolom 'incident_id' menjadi 'incident_event_id' untuk kejelasan relasi FK
ALTER TABLE audit_log 
RENAME COLUMN incident_id TO incident_event_id;

-- 3. Menambahkan kolom audit yang spesifik (action, encrypted_data_reference, created_at)
--    Pastikan tidak bertabrakan dengan data yang sudah ada (tambah IF NOT EXISTS melalui prosedur opsional, tapi standar ALTER COLUMN cukup aman)
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS action VARCHAR(100) DEFAULT 'CREATE';
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS encrypted_data_reference VARCHAR(255);
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- 4. Memastikan relasi Foreign Key benar-benar mengarah ke incident_events.id
-- Hapus constraint FK lama (jika namanya audit_log_incident_id_fkey) lalu buat ulang
DO $$ 
BEGIN
    IF EXISTS (
        SELECT 1 
        FROM information_schema.table_constraints 
        WHERE constraint_name = 'audit_log_incident_id_fkey' 
          AND table_name = 'audit_log'
    ) THEN
        ALTER TABLE audit_log DROP CONSTRAINT audit_log_incident_id_fkey;
    END IF;

    -- Aturan UNIQUE tetap dijaga agar tidak terjadi redundansi anchor per incident
    -- (kecuali jika 1 incident bisa diaudit berkali-kali, maka UNIQUE dicabut. Berdasarkan arsitektur awal, 1 incident = 1 audit_log di blockchain)
    ALTER TABLE audit_log 
    ADD CONSTRAINT audit_log_incident_event_id_fkey 
    FOREIGN KEY (incident_event_id) REFERENCES incident_events(id) ON DELETE CASCADE;
END $$;

-- 5. Memperbaiki iot_devices (menambahkan field yang hilang dari skema aslinya)
ALTER TABLE iot_devices ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE iot_devices ADD COLUMN IF NOT EXISTS last_seen TIMESTAMPTZ;
