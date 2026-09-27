import os
from pathlib import Path


import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from api import incidents, devices, camera
from core.config import settings
from services.supabase_service import _get_client as get_supabase_client

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
        "https://siparta.id",
        "https://www.siparta.id",
        "https://siparta.vercel.app",
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


@app.get("/")
def read_root():
    return {
        "status": "Online",
        "message": "Welcome to SIPARTA Backend API! Engine is running.",
        "services": ["Supabase", "Gemini AI", "Thirdweb Blockchain"]
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

