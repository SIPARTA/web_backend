-- Migration 0006: Camera Integration Schema
-- Membuat tabel incident_event_media dan menambahkan device_type pada iot_devices

-- 1. Tambahkan device_type pada iot_devices jika belum ada
ALTER TABLE iot_devices 
ADD COLUMN IF NOT EXISTS device_type VARCHAR(50) DEFAULT 'real_iot';

-- 2. Buat tabel incident_event_media untuk menyimpan data capture kamera
CREATE TABLE IF NOT EXISTS incident_event_media (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_event_id UUID REFERENCES incident_events(id) ON DELETE CASCADE,
    device_id UUID REFERENCES iot_devices(id) ON DELETE SET NULL,
    source VARCHAR(50) NOT NULL, -- e.g., 'droidcam', 'cctv'
    capture_status VARCHAR(50) NOT NULL DEFAULT 'success',
    image_reference TEXT NOT NULL, -- URL/Path ke gambar (Supabase Storage)
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexing untuk mempercepat query
CREATE INDEX IF NOT EXISTS idx_incident_event_media_incident_id 
ON incident_event_media(incident_event_id);

CREATE INDEX IF NOT EXISTS idx_incident_event_media_device_id 
ON incident_event_media(device_id);