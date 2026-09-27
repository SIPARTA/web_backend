import os
import uuid
from fastapi import APIRouter, File, UploadFile, Form, HTTPException
from supabase import create_client, Client
import tempfile
from datetime import datetime, timezone

router = APIRouter()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

_supabase_client = None

def _get_supabase():
    global _supabase_client
    if _supabase_client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise HTTPException(status_code=503, detail="Supabase not configured for camera service")
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase_client

@router.post("/capture")
async def receive_camera_capture(
    file: UploadFile = File(...),
    incident_event_id: str = Form(None),
    device_id: str = Form("11111111-1111-1111-1111-111111111111"), # Default mobile test device
    source: str = Form("droidcam")
):
    try:
        # 1. Upload to Supabase Storage
        file_ext = file.filename.split(".")[-1]
        file_name = f"capture_{uuid.uuid4()}.{file_ext}"
        bucket_name = "incident_images"
        
        file_content = await file.read()
        
        res_upload = supabase.storage.from_(bucket_name).upload(file_name, file_content, {"content-type": file.content_type})
        
        # URL of the uploaded image
        image_url = supabase.storage.from_(bucket_name).get_public_url(file_name)
        
        # 2. Extract Data via Gemini OCR & Inference if source is droidcam
        severity_result = "AMAN"
        sensor_data_extracted = {}
        ipfs_cid = None
        
        # Save temp file for OCR
        temp_image_path = None
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_ext}") as tmp:
            tmp.write(file_content)
            temp_image_path = tmp.name

        try:
            if source == "droidcam":
                from services.gemini_service import extract_sensor_data_from_image
                import sys
                import os
                # Add ai_models to sys.path to import inference
                ai_models_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "ai_models")
                if ai_models_path not in sys.path:
                    sys.path.append(ai_models_path)
                from inference import run_inference
                
                # A. Scraping
                try:
                    sensor_data_extracted = extract_sensor_data_from_image(temp_image_path)
                except Exception as ocr_err:
                    print(f"[OCR ERROR] Gagal ekstrak data: {ocr_err}")
                    sensor_data_extracted = {"mics5524": 0.0, "tgs2600": 0.0, "mq2": 0.0, "mq135": 0.0}
                
                # B. Inference
                sensor_values_list = [
                    sensor_data_extracted.get("mics5524", 0.0),
                    sensor_data_extracted.get("tgs2600", 0.0),
                    sensor_data_extracted.get("mq2", 0.0),
                    sensor_data_extracted.get("mq135", 0.0),
                ]
                severity_result = run_inference(sensor_values_list)
                
                # C. Encryption
                try:
                    from services.encryption_service import encrypt_payload
                    from services.pinata_service import upload_json_to_ipfs
                    
                    payload_to_encrypt = {
                        "source": source,
                        "device_id": device_id,
                        "sensor_data": sensor_data_extracted,
                        "severity": severity_result,
                        "image_url": image_url,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                    
                    encrypted_token = encrypt_payload(payload_to_encrypt)
                    
                    # D. Pinata IPFS
                    pinata_metadata = {
                        "encrypted_payload": encrypted_token,
                        "encryption_method": "fernet",
                        "device_id": device_id
                    }
                    ipfs_cid = upload_json_to_ipfs(pinata_metadata, name=f"siparta-droidcam-{uuid.uuid4().hex[:8]}")
                except Exception as ipfs_err:
                    print(f"[IPFS ERROR] Gagal upload ke Pinata: {ipfs_err}")
                    ipfs_cid = None
                    
        finally:
            if temp_image_path and os.path.exists(temp_image_path):
                os.remove(temp_image_path)

        # 3. Handle missing incident_event_id (Manual Capture)
        if not incident_event_id:
            # Create a manual "Visual Audit" incident so it appears on the dashboard
            from services import supabase_service as db
            
            # Since the user requested "source=droidcam", we insert it as incident_type VISUAL_AUDIT or DROIDCAM_TEST
            # But the UI expects VISUAL_AUDIT, we just use the scraped severity
            incident_record = db.insert_incident_event(
                device_id=device_id,
                incident_type="VISUAL_AUDIT",
                severity=severity_result,
                sensor_data=sensor_data_extracted,
                image_url=image_url,
                ai_analysis_text="Hasil pemotretan manual via DroidCam (TKP Audit)."
            )
            incident_event_id = incident_record.get("id") if incident_record else None
            
        # 4. Insert into incident_event_media
        media_data = {
            "device_id": device_id,
            "source": source,
            "capture_status": "success",
            "image_reference": image_url
        }
        
        if incident_event_id:
            media_data["incident_event_id"] = incident_event_id
            
        res_insert = supabase.table("incident_event_media").insert(media_data).execute()
        
        # Insert audit_log record for IPFS tracking if cid exists
        if ipfs_cid and incident_event_id:
            try:
                # Cari audit_log yang sudah dibuat untuk incident ini
                existing = supabase.table("audit_log").select("id").eq("incident_event_id", incident_event_id).execute()
                if existing.data and len(existing.data) > 0:
                    # Update existing audit_log dengan IPFS CID
                    supabase.table("audit_log").update({"ipfs_cid": ipfs_cid}).eq("id", existing.data[0]["id"]).execute()
                else:
                    # Insert new audit_log langsung (tanpa transaction)
                    supabase.table("audit_log").insert({
                        "incident_event_id": incident_event_id,
                        "action": "UPLOAD_IPFS",
                        "ipfs_cid": ipfs_cid,
                        "encrypted_data_reference": "fernet (Pinata IPFS)"
                    }).execute()
            except Exception as audit_err:
                print(f"[AUDIT_LOG] Gagal menyimpan CID: {audit_err}")

        
        # 5. Update Device Heartbeat (Status Koneksi)
        # Agar UI mendeteksi perangkat sebagai "Terhubung" saat berhasil memotret
        now_str = datetime.now(timezone.utc).isoformat()
        supabase.table("iot_devices").update({"last_seen": now_str, "is_active": True}).eq("id", device_id).execute()

        
        # Return response mimicking Browser Console JSON output requested by user
        return {
            "device_id": device_id,
            "source": source,
            "capture_status": "success",
            "image_reference": image_url,
            "incident_event_id": incident_event_id or "unlinked_capture",
            "timestamp": res_insert.data[0]['timestamp'] if res_insert.data else None,
            "scraped_data": sensor_data_extracted,
            "classification": severity_result,
            "ipfs_cid": ipfs_cid
        }

    except Exception as e:
        print(f"[API/camera] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
