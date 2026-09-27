from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from services.supabase_service import _get_client as get_supabase_client
import logging

logger = logging.getLogger("siparta")
router = APIRouter(prefix="/devices", tags=["Devices"])

class HeartbeatRequest(BaseModel):
    device_id: str

@router.post("/heartbeat")
async def device_heartbeat(payload: HeartbeatRequest):
    """
    Endpoint untuk perangkat IoT melaporkan bahwa mereka sedang online.
    Ini akan memperbarui field `last_seen` di tabel `iot_devices`.
    """
    db = get_supabase_client()
    if not db:
        raise HTTPException(status_code=503, detail="Supabase not configured")

    try:
        # Perbarui last_seen menjadi sekarang dan pastikan is_active true
        res = db.table("iot_devices").update({"last_seen": "now()", "is_active": True}).eq("id", payload.device_id).execute()
        if not res.data:
            # Mungkin perangkat belum ada, biarkan gagal atau kembalikan 404
            raise HTTPException(status_code=404, detail="Device not found")
            
        return {"status": "success", "message": "Heartbeat updated"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[HEARTBEAT] Error updating heartbeat: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/status")
async def get_device_status():
    """
    Mengembalikan status koneksi IoT secara keseluruhan.
    Dianggap online jika ada setidaknya satu perangkat yang 'last_seen' < 60 detik lalu.
    """
    db = get_supabase_client()
    if not db:
        raise HTTPException(status_code=503, detail="Supabase not configured")

    try:
        # Karena keterbatasan filter datetime di Supabase Python, kita ambil data devices lalu cek di memory
        # Atau bisa menggunakan raw RPC, tapi untuk saat ini mem-fetch lebih mudah
        res = db.table("iot_devices").select("id, name, is_active, last_seen, device_type").execute()
        devices = res.data or []
        
        from datetime import datetime, timezone, timedelta
        
        is_online = False
        now = datetime.now(timezone.utc)
        
        device_list = []
        for dev in devices:
            last_seen_str = dev.get("last_seen")
            dev_is_active = dev.get("is_active", False)
            if last_seen_str:
                try:
                    last_seen_dt = datetime.fromisoformat(last_seen_str.replace("Z", "+00:00"))
                    diff = now - last_seen_dt
                    if timedelta(seconds=-60) < diff < timedelta(minutes=2):
                        is_online = True
                        dev_is_active = True
                except Exception:
                    pass
            
            device_list.append({
                "id": dev.get("id"),
                "name": dev.get("name"),
                "is_active": dev_is_active,
                "last_seen": last_seen_str,
                "device_type": dev.get("device_type", "real_iot")
            })
                    
        return {"online": is_online, "devices": device_list}
    except Exception as e:
        logger.error(f"[DEVICE STATUS] Error checking status: {e}")
        return {"online": False, "devices": []}

