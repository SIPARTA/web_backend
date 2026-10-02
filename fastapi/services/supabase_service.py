"""
SIPARTA Backend — Supabase Service Layer
==========================================
Menangani seluruh operasi CRUD ke Supabase PostgreSQL.
Menggunakan supabase-py client library.

Tabel yang dikelola:
  - incident_events  : Data insiden real-time dari RPi
  - transaction_logs: Status transaksi blockchain
  - audit_log       : Anchor kriptografis ke Polygon

Catatan Desain:
  - Semua fungsi mengembalikan dict atau None, tidak raise exception ke caller.
  - Error di-log dan di-handle secara graceful agar pipeline tidak terputus.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

import os

logger = logging.getLogger(__name__)

# Lazy-load Supabase client agar tidak crash saat env belum diset
_supabase_client = None


def _get_client():
    """Return singleton Supabase client, init on first call. Retry if previously failed."""
    global _supabase_client
    if _supabase_client is None:
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        if not url or not key:
            logger.warning(
                "[SUPABASE] SUPABASE_URL atau SUPABASE_SERVICE_ROLE_KEY belum diset. "
                "Operasi DB akan di-skip. (Akan mencoba ulang di request berikutnya)"
            )
            return None
        try:
            from supabase import create_client, Client
            _supabase_client = create_client(url, key)
            logger.info("[SUPABASE] Client berhasil diinisialisasi.")
        except Exception as e:
            logger.error(f"[SUPABASE] Gagal membuat client: {e}. (Akan mencoba ulang di request berikutnya)")
            return None
    return _supabase_client


# ============================================================
# INCIDENT EVENTS
# ============================================================

def insert_incident_event(
    device_id: str,
    incident_type: str,
    severity: str,
    sensor_data: dict,
    image_url: Optional[str] = None,
    ai_analysis_text: Optional[str] = None,
) -> Optional[dict]:
    """
    Menyimpan satu record insiden ke tabel incident_events.

    # Args:
    #     device_id       : UUID perangkat IoT dari tabel iot_devices.
    #     incident_type   : Klasifikasi insiden, e.g. 'GAS_LEAK', 'SAFE'.
    #     severity        : Tingkat bahaya: 'AMAN', 'WASPADA', 'BAHAYA'.
    #     sensor_data     : Dict berisi nilai sensor (mics5524, tgs2600, mq2, mq135).
    #     image_url       : URL foto bukti (Supabase Storage / Cloudinary).
    #     ai_analysis_text: Teks analisis mitigasi dari Google Gemini.

    # Returns:
    #     Dict data yang berhasil di-insert, atau None jika gagal.
    """
    client = _get_client()
    if not client:
        return None

    user_id = None
    if device_id:
        try:
            device_res = client.table("iot_devices").select("user_id").eq("id", device_id).execute()
            if device_res.data and len(device_res.data) > 0:
                user_id = device_res.data[0].get("user_id")
        except Exception as e:
            logger.error(f"[SUPABASE] Gagal ambil user_id dari device_id: {e}")

    record = {
        "device_id": device_id,
        "user_id": user_id,
        "incident_type": incident_type,
        "severity": severity,
        "status": severity,
        "image_url": image_url,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "is_anchored": False,
    }
    # NOTE: sensor_data and ai_analysis_text are intentionally omitted
    # because they do not exist in the current Supabase schema cache.
    # They are still safely encrypted and stored in Pinata/IPFS.

    try:
        response = client.table("incident_events").insert(record).execute()
        if response.data:
            inserted = response.data[0]
            logger.info(f"[SUPABASE] Incident saved: {inserted.get('id')}")
            return inserted
        logger.warning(f"[SUPABASE] Insert incident_events: response kosong. {response}")
        return None
    except Exception as e:
        logger.error(f"[SUPABASE] Gagal insert incident_events: {e}")
        return None


# ============================================================
# TRANSACTIONS LOGS
# ============================================================

def insert_transaction_log(
    incident_event_id: str,
    tx_hash: Optional[str] = None,
    status: str = "PENDING",
) -> Optional[dict]:
    """
    Mencatat intent transaksi blockchain baru dengan membuat record audit_log (pending) 
    terlebih dahulu, lalu merelasikan transaction_logs ke audit_log tersebut.

    # Args:
    #     incident_event_id : UUID dari incident_events.id.
    #     tx_hash           : Hash transaksi Polygon (bisa None jika masih PENDING).
    #     status            : 'PENDING', 'SUCCESS', atau 'FAILED'.

    Returns:
        Dict data transaction_logs yang berhasil di-insert, atau None jika gagal.
    """
    client = _get_client()
    if not client:
        return None

    try:
        # Fetch user_id from incident_events
        user_id = None
        if incident_event_id:
            incident_res = client.table("incident_events").select("user_id").eq("id", incident_event_id).execute()
            if incident_res.data and len(incident_res.data) > 0:
                user_id = incident_res.data[0].get("user_id")
        
        # 1. Create audit_log first
        audit_res = client.table("audit_log").insert({
            "incident_event_id": incident_event_id,
            "action": "UPLOAD_AND_ANCHOR",
            "encrypted_data_reference": "aes-256-gcm (Pinata IPFS)"
        }).execute()
        
        if not audit_res.data:
            return None
            
        audit_id = audit_res.data[0]["id"]
        
        # 2. Create transaction_logs
        tx_res = client.table("transaction_logs").insert({
            "audit_log_id": audit_id,
            "tx_hash": tx_hash,
            "status": status,
            "retry_count": 0,
            "user_id": user_id,
        }).execute()

        if tx_res.data:
            inserted = tx_res.data[0]
            logger.info(f"[SUPABASE] Tx log saved: {inserted.get('id')} | status={status}")
            return inserted
        return None
    except Exception as e:
        logger.error(f"[SUPABASE] Gagal insert transaction_logs: {e}")
        return None




def update_transaction_status(
    tx_log_id: str,
    tx_hash: str,
    status: str,
) -> Optional[dict]:
    """
    Update status transaksi setelah konfirmasi dari blockchain.

    Args:
        tx_log_id   : UUID dari transaction_logs.id.
        tx_hash     : Hash transaksi Polygon yang sudah dikonfirmasi.
        status      : 'SUCCESS' atau 'FAILED'.
    """
    client = _get_client()
    if not client:
        return None

    updates: dict = {"tx_hash": tx_hash, "status": status}

    try:
        response = (
            client.table("transaction_logs")
            .update(updates)
            .eq("id", tx_log_id)
            .execute()
        )
        if response.data:
            logger.info(f"[SUPABASE] Tx status updated: {tx_log_id} → {status}")
            return response.data[0]
        return None
    except Exception as e:
        logger.error(f"[SUPABASE] Gagal update transaction_logs: {e}")
        return None


# ============================================================
# AUDIT LOGS (On-chain Anchor)
# ============================================================

def insert_audit_log(
    incident_id: str,
    tx_log_id: str,
    ipfs_cid: Optional[str] = None,
    block_number: Optional[int] = None,
) -> Optional[dict]:
    """
    Update data ipfs_cid dan block_number pada audit_log yang sudah dibuat saat PENDING.
    
    Karena di Migration 0005 relasinya dibalik (transaction_logs menunjuk ke audit_log_id),
    maka fungsi ini sekarang bertugas meng-UPDATE audit_log berdasarkan tx_log_id tersebut.
    """
    client = _get_client()
    if not client:
        return None

    try:
        # Cari audit_log_id dari transaction_logs
        tx_res = client.table("transaction_logs").select("audit_log_id").eq("id", tx_log_id).execute()
        if not tx_res.data:
            return None
            
        audit_log_id = tx_res.data[0].get("audit_log_id")
        if not audit_log_id:
            return None

        # Update audit_log
        audit_update = {}
        if ipfs_cid:
            audit_update["ipfs_cid"] = ipfs_cid
        if block_number:
            audit_update["block_number"] = block_number
            
        if audit_update:
            response = client.table("audit_log").update(audit_update).eq("id", audit_log_id).execute()
            
            if response.data:
                updated = response.data[0]
                logger.info(f"[SUPABASE] Audit log updated: {updated.get('id')}")
                # Mark incident as anchored
                mark_incident_anchored(incident_id)
                return updated
        return None
    except Exception as e:
        logger.error(f"[SUPABASE] Gagal update audit_log: {e}")
        return None


def mark_incident_anchored(incident_id: str) -> None:
    """Set is_anchored=true pada incident setelah audit_log berhasil dibuat."""
    client = _get_client()
    if not client:
        return
    try:
        client.table("incident_events").update({"is_anchored": True}).eq("id", incident_id).execute()
        logger.info(f"[SUPABASE] Incident {incident_id} marked as anchored.")
    except Exception as e:
        logger.error(f"[SUPABASE] Gagal mark incident sebagai anchored: {e}")

def update_incident_ai_analysis(incident_id: str, ai_analysis_text: str) -> None:
    """Update field ai_analysis_text pada tabel incident_events."""
    client = _get_client()
    if not client:
        return
    try:
        client.table("incident_events").update(
            {"ai_analysis_text": ai_analysis_text}
        ).eq("id", incident_id).execute()
        logger.info(f"[SUPABASE] AI Analysis updated untuk incident {incident_id}.")
    except Exception as e:
        logger.error(f"[SUPABASE] Gagal update AI analysis ke DB: {e}")

def check_device_web3_access(device_id: str) -> bool:
    """
    Memeriksa apakah user yang memiliki device ini memiliki akses Premium (Web3/MetaMask).
    Premium diberikan jika wallet_address-nya adalah address Web3 yang valid (bukan 'google:...' atau 'email:...').
    """
    if not device_id:
        return False
        
    client = _get_client()
    if not client:
        return False
        
    try:
        # Ambil user_id dari device
        res = client.table("iot_devices").select("user_id").eq("id", device_id).execute()
        if not res.data or not res.data[0].get("user_id"):
            return False
            
        user_id = res.data[0]["user_id"]
        
        # Ambil wallet data dari user
        u_res = client.table("users").select("wallet_address").eq("id", user_id).execute()
        if not u_res.data:
            return False
            
        u = u_res.data[0]
        
        # Jika wallet_address adalah alamat EVM (mulai dari 0x)
        w = u.get("wallet_address") or ""
        if w.startswith("0x"):
            return True
            
        return False
    except Exception as e:
        logger.error(f"[SUPABASE] Error checking web3 access: {e}")
        return False
