"""
SIPARTA Backend — Incidents API Router
========================================
Endpoint utama untuk penerimaan data sensor dari IoT Edge dan DroidCam.
Terintegrasi dengan Gemini AI, Supabase, dan Polygon Amoy.
"""

import os
import uuid
import logging
from fastapi import APIRouter, File, UploadFile, Form, BackgroundTasks, Depends, HTTPException, Header
from typing import Optional
from datetime import datetime

from core.config import settings
from services.gemini_service import analyze_incident_with_gemini
from services.web3_service import log_incident_to_blockchain
from services import supabase_service as db

logger = logging.getLogger("siparta.incidents")

router = APIRouter(
    prefix="/incidents",
    tags=["Incidents — IoT Ingestion & AI/Web3 Pipeline"]
)

# ============================================================
# AUTH: Simple API Key validation untuk perangkat IoT
# ============================================================

def verify_device_api_key(x_api_key: Optional[str] = Header(None)):
    """
    Validasi kredensial perangkat melalui X-API-Key.
    Dilewati jika DEVICE_API_KEY tidak dikonfigurasi (mode development).
    """
    if not settings.DEVICE_API_KEY:
        # Mode dev: tanpa auth key
        return True
    if x_api_key != settings.DEVICE_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")
    return True


# ============================================================
# ENDPOINT UTAMA: Report Incident dari RPi
# ============================================================

@router.post("/report")
async def report_incident(
    background_tasks: BackgroundTasks,
    source_type: str = Form("iot", description="Sumber data: 'iot' atau 'droidcam'"),
    status: str = Form("AMAN", description="Klasifikasi ANN: 'AMAN', 'WASPADA', atau 'BAHAYA'"),
    adc_mics5524: float = Form(0.0, description="Nilai ADC sensor MICS-5524"),
    adc_tgs2600: float = Form(0.0, description="Nilai ADC sensor TGS2600"),
    adc_mq2: float = Form(0.0, description="Nilai ADC sensor MQ-2"),
    adc_mq135: float = Form(0.0, description="Nilai ADC sensor MQ-135"),
    timestamp: Optional[str] = Form(None, description="ISO 8601 timestamp"),
    device_id: Optional[str] = Form(None, description="UUID perangkat"),
    file: Optional[UploadFile] = File(None, description="Foto bukti dari RPi Camera atau DroidCam"),
    _auth: bool = Depends(verify_device_api_key),
):
    """
    Endpoint Ingestion Utama untuk IoT dan DroidCam.
    """
    from datetime import datetime, timezone
    if not timestamp:
        timestamp = datetime.now(timezone.utc).isoformat()
        
    image_path: Optional[str] = None
    if file:
        os.makedirs("/tmp/siparta", exist_ok=True)
        image_path = f"/tmp/siparta/{uuid.uuid4()}_{file.filename}"
        content = await file.read()
        with open(image_path, "wb") as buffer:
            buffer.write(content)
        logger.info(f"[INCIDENTS] Gambar tersimpan sementara: {image_path}")

    sensor_data = {}
    
    if source_type == "droidcam":
        if file and image_path:
            from services.gemini_service import extract_sensor_data_from_image
            try:
                sensor_data = extract_sensor_data_from_image(image_path)
            except Exception as e:
                logger.error(f"[INCIDENTS] OCR Error: {e}")
                sensor_data = {"adc_mics5524": 0.0, "adc_tgs2600": 0.0, "adc_mq2": 0.0, "adc_mq135": 0.0}
        else:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Image file is required for droidcam source")
    else:
        sensor_data = {
            "adc_mics5524": adc_mics5524,
            "adc_tgs2600": adc_tgs2600,
            "adc_mq2": adc_mq2,
            "adc_mq135": adc_mq135,
        }

    from services.ai_service import predict_gas_risk, is_ai_loaded
    try:
        if not is_ai_loaded():
            logger.warning("[INCIDENTS] Model AI JST belum dimuat, mencoba memuat saat runtime.")
            from services.ai_service import load_ai_models
            load_ai_models()
            
        features_list = [
            sensor_data.get("adc_mics5524", 0.0),
            sensor_data.get("adc_tgs2600", 0.0),
            sensor_data.get("adc_mq2", 0.0),
            sensor_data.get("adc_mq135", 0.0),
        ]
        
        prediction = predict_gas_risk(features_list)
        status_upper = prediction.get("status", "AMAN")
        logger.info(f"[INCIDENTS] Backend AI Inference: {status_upper} (Confidence: {prediction.get('confidence')}%)")
    except Exception as e:
        logger.error(f"[INCIDENTS] Backend Inference Error: {e}")
        status_upper = "AMAN"

    if status_upper not in ("AMAN", "WASPADA", "BAHAYA"):
        status_upper = "AMAN"
        
    classification_lower = status_upper.lower()

    valid_device_id = None
    if device_id:
        try:
            val = uuid.UUID(device_id)
            valid_device_id = str(val)
        except ValueError:
            logger.warning(f"[INCIDENTS] Invalid device_id format '{device_id}', setting to None.")
            valid_device_id = None

    payload = {
        "source": source_type,
        "status": status_upper,
        "classification": classification_lower,
        "sensors": sensor_data,
        "timestamp": timestamp,
        "device_id": valid_device_id,
    }

    incident_type_value = "VISUAL_AUDIT" if source_type == "droidcam" else f"GAS_{status_upper}"
    incident_record = db.insert_incident_event(
        device_id=valid_device_id,
        incident_type=incident_type_value,
        severity=status_upper,
        sensor_data=sensor_data,
        image_url=None,  # akan diisi setelah upload di background
        ai_analysis_text=None,  # akan diisi setelah Gemini analisis
    )
    
    incident_id = incident_record.get("id") if incident_record else None
    
    if source_type == "droidcam" and incident_id:
        try:
            db._get_client().table("incident_event_media").insert({
                "incident_event_id": incident_id,
                "device_id": valid_device_id,
                "source": "droidcam",
                "capture_status": "success",
                "image_reference": "local:pending",
                "timestamp": timestamp
            }).execute()
        except Exception as e:
            logger.error(f"[INCIDENTS] Gagal menyimpan incident_event_media: {e}")

    incident_id = incident_record.get("id") if incident_record else None
    payload["incident_id"] = incident_id

    background_tasks.add_task(
        process_incident_pipeline,
        payload=payload,
        image_path=image_path,
        incident_id=incident_id,
    )

    logger.info(f"[INCIDENTS] Incident diterima: {incident_id} | Status: {status_upper}")
    return {
        "success": True,
        "message": "Incident payload received. AI & Blockchain Pipeline triggered.",
        "incident_id": incident_id,
        "data_ack": {
            "status": status_upper,
            "timestamp": timestamp,
            "sensors": sensor_data,
        }
    }


# ============================================================
# BACKGROUND PIPELINE WORKER
# ============================================================

async def process_incident_pipeline(
    payload: dict,
    image_path: Optional[str],
    incident_id: Optional[str],
):
    """
    Eksekusi background pipeline:
      1. Gemini AI 
      2. Blockchain (Polygon Amoy)
      3. Update status transaksi dan audit logs di Supabase
    """
    logger.info(f"\n[PIPELINE] Memulai pipeline untuk incident: {incident_id}")

    # ── A. Google Gemini AI Analysis ────────────────────────────────────────
    gemini_analysis: Optional[str] = None
    if image_path and os.path.exists(image_path):
        try:
            logger.info("[PIPELINE] Memanggil Gemini AI...")
            gemini_analysis = analyze_incident_with_gemini(payload, image_path)
            logger.info(f"[PIPELINE] Gemini selesai: {str(gemini_analysis)[:100]}...")
        except Exception as e:
            logger.error(f"[PIPELINE] Gemini error: {e}")

    blockchain_result: Optional[dict] = None
    
    has_web3_access = db.check_device_web3_access(payload.get("device_id"))
    
    should_anchor = has_web3_access and (payload.get("status", "") in ("BAHAYA", "WASPADA") or payload.get("source") == "droidcam")

    if not has_web3_access:
        logger.info(f"[PIPELINE] Skipping Web3/IPFS for device {payload.get('device_id')} (Standard Tier)")

    if should_anchor and incident_id:
        tx_log = db.insert_transaction_log(
            incident_event_id=incident_id,
            tx_hash=None,
            status="PENDING",
        )
        tx_log_id = tx_log.get("id") if tx_log else None

        try:
            logger.info("[PIPELINE] Mengirim ke Blockchain Relay...")
            payload_with_sensors = {
                **payload,
                "incident_id": incident_id,
                "mics5524": payload["sensors"].get("adc_mics5524", 0.0),
                "tgs2600": payload["sensors"].get("adc_tgs2600", 0.0),
                "mq2": payload["sensors"].get("adc_mq2", 0.0),
                "mq135": payload["sensors"].get("adc_mq135", 0.0),
                "image_url": image_path or "",
                "ai_analysis": gemini_analysis or "N/A",
            }
            blockchain_result = await log_incident_to_blockchain(payload_with_sensors)
            tx_hash = blockchain_result.get("txHash") or blockchain_result.get("tx_hash")
            block_number = blockchain_result.get("blockNumber") or blockchain_result.get("block_number")

            if tx_hash and tx_log_id:
                db.update_transaction_status(
                    tx_log_id=tx_log_id,
                    tx_hash=tx_hash,
                    status="SUCCESS",
                )
                ipfs_cid = blockchain_result.get("ipfsCid") or blockchain_result.get("ipfs_cid", "")
                db.insert_audit_log(
                    incident_id=incident_id,
                    tx_log_id=tx_log_id,
                    ipfs_cid=ipfs_cid,
                    block_number=block_number,
                )
            elif tx_hash and not tx_log_id:
                logger.warning("[PIPELINE] tx_hash ada tetapi tx_log_id None. Fallback anchoring.")
                try:
                    db.mark_incident_anchored(incident_id)
                except Exception as fb_err:
                    logger.error(f"[PIPELINE] Fallback anchoring gagal: {fb_err}")
                logger.info(f"[PIPELINE] Blockchain anchored: {tx_hash}")
            else:
                logger.error(f"[PIPELINE] Relay mengembalikan hasil gagal tanpa txHash: {blockchain_result}")
                if tx_log_id:
                    db.update_transaction_status(tx_log_id, "", "FAILED")
                    # Tetap simpan IPFS CID jika berhasil di-upload
                    ipfs_cid = blockchain_result.get("ipfsCid") or blockchain_result.get("ipfs_cid", "")
                    if ipfs_cid:
                        db.insert_audit_log(
                            incident_id=incident_id,
                            tx_log_id=tx_log_id,
                            ipfs_cid=ipfs_cid,
                            block_number=0,
                        )

        except Exception as e:
            logger.error(f"[PIPELINE] Blockchain error: {e}")
            if tx_log_id:
                db.update_transaction_status(tx_log_id, "", "FAILED")

    pass

    if image_path and os.path.exists(image_path):
        try:
            os.remove(image_path)
        except Exception:
            pass

    logger.info(f"[PIPELINE] Selesai! incident_id={incident_id}")
    logger.info(f"  → Web3 Result : {blockchain_result}")
    logger.info(f"  → AI Analysis : {str(gemini_analysis)[:80] if gemini_analysis else 'N/A'}")


# ============================================================
# ENDPOINT TAMBAHAN: Verifikasi On-Chain
# ============================================================

@router.get("/{incident_id}/verify-onchain")
async def verify_incident_onchain(incident_id: str):
    """
    Verifikasi apakah insiden sudah tercatat di Polygon Amoy.
    Frontend dapat memanggil endpoint ini untuk Audit Trail UI.
    """
    from services.web3_service import verify_incident_on_chain
    try:
        is_verified = await verify_incident_on_chain(incident_id)
        return {
            "incident_id": incident_id,
            "on_chain": is_verified,
            "message": "Insiden terverifikasi di blockchain." if is_verified else "Belum tercatat di blockchain.",
        }
    except Exception as e:
        logger.error(f"[INCIDENTS] Verification error: {e}")
        return {"incident_id": incident_id, "on_chain": False, "error": str(e)}

@router.get("/decrypted/{cid}")
async def get_decrypted_incident(cid: str):
    """
    Fetch IPFS data by CID and decrypt the payload.
    """
    import requests
    from services.encryption_service import decrypt_payload
    
    gateway_url = f"https://gateway.pinata.cloud/ipfs/{cid}"
    try:
        r = requests.get(gateway_url, timeout=10)
        r.raise_for_status()
        data = r.json()
        encrypted_token = data.get("encrypted_payload")
        if not encrypted_token:
            return {"error": "No encrypted payload found in IPFS data"}
        
        decrypted = decrypt_payload(encrypted_token)
        return {"decrypted_data": decrypted}
    except Exception as e:
        logger.error(f"Failed to fetch or decrypt {cid}: {e}")
        return {"error": str(e)}
