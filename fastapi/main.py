import os
from pathlib import Path


import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from api import incidents, devices, camera, predict, simulation
from core.config import settings
from services.supabase_service import _get_client as get_supabase_client
from services.ai_service import load_ai_models, is_ai_loaded, MODEL_PATH
import services.ai_service as ai_service

logger = logging.getLogger("siparta")

async def monitor_device_status():
    """Background task to mark devices as offline if heartbeat is missing for > 2 minutes."""
    logger.info("[BACKGROUND] IoT Device heartbeat monitor started (timeout: 2 minutes).")
    while True:
        try:
            db = get_supabase_client()
            if db:
                res = db.table("iot_devices").select("id, last_seen").eq("is_active", True).execute()
                devices_data = res.data or []
                
                from datetime import datetime, timezone, timedelta
                now = datetime.now(timezone.utc)
                
                for dev in devices_data:
                    last_seen_str = dev.get("last_seen")
                    is_offline = True
                    if last_seen_str:
                        try:
                            last_seen_dt = datetime.fromisoformat(last_seen_str.replace("Z", "+00:00"))
                            diff = now - last_seen_dt
                            if diff <= timedelta(minutes=2):
                                is_offline = False
                        except Exception:
                            pass
                    
                    if is_offline:
                        db.table("iot_devices").update({"is_active": False}).eq("id", dev["id"]).execute()
                        logger.info(f"[HEARTBEAT] Device {dev['id']} missed heartbeat and marked OFFLINE.")
        except Exception as e:
            logger.error(f"[HEARTBEAT] Background monitor error: {e}")
        
        await asyncio.sleep(60) # Check every 60 seconds

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validasi credential kritis saat server startup."""
    # Load AI Models (JST)
    load_ai_models()
    
    missing = settings.validate()
    if missing:
        logger.warning(f"[STARTUP] ⚠️  Missing env vars: {', '.join(missing)}")
    else:
        logger.info("[STARTUP] ✅ Semua environment variable tervalidasi.")
    logger.info(f"[STARTUP] Supabase URL: {settings.SUPABASE_URL}")
    logger.info(f"[STARTUP] Blockchain Dir: {settings.BLOCKCHAIN_DIR}")
    
    # Start the background task
    monitor_task = asyncio.create_task(monitor_device_status())
    
    yield
    monitor_task.cancel()
    logger.info("[SHUTDOWN] SIPARTA Backend shutting down.")

app = FastAPI(
    title="SIPARTA Backend API",
    description="Backend services for SIPARTA Real-Time Gas Detection and Web3 Logging",
    version="1.0.0",
    lifespan=lifespan
)

# Konfigurasi CORS agar frontend (Next.js) bisa mengakses API
allowed_origins_env = os.getenv("ALLOWED_ORIGINS")
if allowed_origins_env:
    allowed_origins = [o.strip() for o in allowed_origins_env.split(",") if o.strip()]
else:
    allowed_origins = [
        "https://siparta.my.id",
        "https://www.siparta.my.id",
        "http://localhost:3000"
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mounting router dari module api
app.include_router(incidents.router, prefix="/api/v1")
app.include_router(devices.router, prefix="/api/v1")
app.include_router(camera.router, prefix="/api/v1")
app.include_router(predict.router, prefix="/api/v1")
app.include_router(simulation.router, prefix="/api/v1")


@app.get("/")
def read_root():
    import sys
    import tensorflow as tf
    return {
        "status": "Online",
        "message": "Welcome to SIPARTA Backend API! Engine is running.",
        "services": ["Supabase", "Gemini AI", "Thirdweb Blockchain"],
        "debug": {
            "python_version": sys.version,
            "tensorflow_version": tf.__version__
        }
    }


@app.get("/health")
def health_check(response: Response):
    """Health check untuk deployment platform (Render)."""
    health_status = {
        "status": "ok",
        "components": {
            "supabase": "ok" if settings.SUPABASE_URL else "missing_config",
            "gemini": "ok" if settings.GEMINI_API_KEY else "missing_config",
            "blockchain": "ok" if os.getenv("POLYGON_AMOY_PRIVATE_KEY") or os.getenv("RELAYER_PRIVATE_KEY") else "missing_config",
            "iot_auth": "ok" if settings.DEVICE_API_KEY else "missing_config"
        }
    }
    
    if any(v == "missing_config" for v in health_status["components"].values()):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        health_status["status"] = "degraded"
        
    return health_status


@app.get("/api/v1/system-status")
def system_status():
    """Endpoint untuk mendapatkan status integrasi AI & Perangkat (Real-time dashboard)."""
    from datetime import datetime, timezone
    
    now_iso = datetime.now(timezone.utc).isoformat()
    
    # 1. AI JST Status
    ai_jst_loaded = is_ai_loaded()
    model_exists = os.path.exists(MODEL_PATH)
    
    error_msg = None
    if not model_exists:
        error_msg = f"File model tidak ditemukan di: {MODEL_PATH}"
    elif not ai_jst_loaded:
        error_msg = f"Gagal memuat artefak model ke dalam memory (RAM). Error: {ai_service.ai_load_error}"

    ai_jst_info = {
        "name": "AI JST",
        "version": "v1.0",
        "deployment_status": "deployed" if model_exists else "not_deployed",
        "model_loaded": "loaded" if ai_jst_loaded else "failed",
        "inference_readiness": "ready" if ai_jst_loaded else "not_ready",
        "last_checked": now_iso,
        "error_message": error_msg
    }
    
    # Tentukan Path Dataset (Single Source of Truth)
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) # SIPARTA root
    ai_models_dataset = os.path.join(base_dir, "ai_models", "Dataset Sensor SIPARTA.csv")
    local_dataset = os.path.abspath(os.path.join(os.path.dirname(__file__), "models/Dataset Sensor SIPARTA.csv"))
    
    if os.path.exists(ai_models_dataset):
        dataset_path = ai_models_dataset
    else:
        dataset_path = local_dataset
    dataset_info = {
        "name": "Sensor Dataset",
        "source": "CSV",
        "availability": "unverified",
        "sample_count": None,
        "feature_count": None,
        "version_or_updated": None,
        "preprocessing_match": "unverified",
        "last_checked": now_iso,
        "error_message": None
    }
    
    if os.path.exists(dataset_path):
        try:
            # We don't want to load all 3000 rows into memory on every ping, just get info
            import csv
            
            with open(dataset_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader)
                rows_count = sum(1 for _ in reader)
                
            dataset_info["availability"] = "available"
            dataset_info["sample_count"] = rows_count
            dataset_info["feature_count"] = len(header) - 1 if "Status" in header else len(header)
            
            mtime = os.path.getmtime(dataset_path)
            dataset_info["version_or_updated"] = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
            
            expected_features = {"adc_mics5524", "adc_tgs2600", "adc_mq2", "adc_mq135"}
            cols_lower = set(col.lower() for col in header)
            if expected_features.issubset(cols_lower):
                dataset_info["preprocessing_match"] = "matched"
            else:
                dataset_info["preprocessing_match"] = "unmatched"
                dataset_info["error_message"] = f"Fitur tidak lengkap. Dibutuhkan: {expected_features}"
                
        except Exception as e:
            dataset_info["availability"] = "unavailable"
            dataset_info["error_message"] = f"Error membaca dataset: {e}"
    else:
        dataset_info["availability"] = "unavailable"
        dataset_info["error_message"] = "File dataset 'Dataset Sensor SIPARTA.csv' tidak ditemukan di direktori ai_models."
        
    return {
        "ai_jst": ai_jst_info,
        "dataset": dataset_info
    }
