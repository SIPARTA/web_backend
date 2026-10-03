"""
SIPARTA Backend — Simulation API Router
=========================================
Menyediakan data simulasi dari Dataset Sensor SIPARTA.csv
untuk demonstrasi website tanpa perangkat IoT fisik.

SEMUA data yang dikembalikan diberi label "SIMULATION" / "DEMO MODE".
Endpoint ini TIDAK mengubah status perangkat IoT, tabel insiden aktual,
atau indikator konektivitas apapun.
"""

import os
import csv
import random
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from services.ai_service import predict_gas_risk, is_ai_loaded

logger = logging.getLogger("siparta.simulation")

router = APIRouter(
    prefix="/simulation",
    tags=["Simulation — Demo Mode"]
)

# ── Locate Dataset ──────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
AI_MODELS_DATASET = os.path.join(BASE_DIR, "ai_models", "Dataset Sensor SIPARTA.csv")
LOCAL_DATASET = os.path.abspath(os.path.join(os.path.dirname(__file__), "../models/Dataset Sensor SIPARTA.csv"))

DATASET_PATH = AI_MODELS_DATASET if os.path.exists(AI_MODELS_DATASET) else LOCAL_DATASET

_cached_rows: list = []


def _load_dataset() -> list:
    """Load dataset sekali dan cache ke memory."""
    global _cached_rows
    if _cached_rows:
        return _cached_rows

    if not os.path.exists(DATASET_PATH):
        logger.error(f"[SIMULATION] Dataset tidak ditemukan: {DATASET_PATH}")
        return []

    try:
        with open(DATASET_PATH, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            _cached_rows = list(reader)
        logger.info(f"[SIMULATION] Loaded {len(_cached_rows)} rows dari dataset.")
    except Exception as e:
        logger.error(f"[SIMULATION] Gagal membaca dataset: {e}")
        _cached_rows = []

    return _cached_rows


@router.get("/sample")
async def get_simulation_sample(
    bahan: Optional[str] = Query(None, description="Filter berdasarkan Bahan_Uji_Aktual"),
    count: int = Query(1, ge=1, le=10, description="Jumlah sampel (1-10)"),
    random_pick: bool = Query(True, description="Ambil secara acak")
):
    """
    Mengambil sampel data dari Dataset Sensor SIPARTA.csv dan menjalankan
    inferensi JST secara real-time.

    Response selalu ditandai dengan source="SIMULATION" dan mode="DEMO".
    """
    rows = _load_dataset()
    if not rows:
        raise HTTPException(
            status_code=503,
            detail="Dataset Sensor SIPARTA.csv tidak tersedia untuk simulasi."
        )

    # Filter berdasarkan bahan uji jika diminta
    filtered = rows
    if bahan:
        bahan_lower = bahan.lower()
        filtered = [r for r in rows if bahan_lower in r.get("Bahan_Uji_Aktual", "").lower()]
        if not filtered:
            raise HTTPException(
                status_code=404,
                detail=f"Tidak ditemukan data dengan Bahan_Uji_Aktual mengandung '{bahan}'."
            )

    # Pilih sampel
    if random_pick:
        samples = random.sample(filtered, min(count, len(filtered)))
    else:
        samples = filtered[:count]

    results = []
    for row in samples:
        adc_mics5524 = float(row.get("ADC_MiCS5524", 0))
        adc_tgs2600 = float(row.get("ADC_TGS2600", 0))
        adc_mq2 = float(row.get("ADC_MQ2", 0))
        adc_mq135 = float(row.get("ADC_MQ135", 0))

        # Inferensi JST real-time
        jst_result = None
        jst_status = "INFERENCE_UNAVAILABLE"
        if is_ai_loaded():
            try:
                jst_result = predict_gas_risk([adc_mics5524, adc_tgs2600, adc_mq2, adc_mq135])
                jst_status = jst_result.get("status", "MODEL_ERROR")
            except Exception as e:
                logger.error(f"[SIMULATION] Inference gagal: {e}")
                jst_result = {"status": "INFERENCE_FAILED", "confidence": 0.0, "error": str(e)}
                jst_status = "INFERENCE_FAILED"
        else:
            jst_result = {"status": "INFERENCE_UNAVAILABLE", "confidence": 0.0}

        results.append({
            # ─── Penanda Simulasi (WAJIB) ───
            "source": "SIMULATION",
            "mode": "DEMO",
            "disclaimer": "Data ini berasal dari Dataset Sensor SIPARTA.csv, bukan pembacaan sensor real-time.",

            # ─── Data Sensor ───
            "sensor_data": {
                "mics5524": adc_mics5524,
                "tgs2600": adc_tgs2600,
                "mq2": adc_mq2,
                "mq135": adc_mq135,
            },

            # ─── Metadata Dataset ───
            "bahan_uji": row.get("Bahan_Uji_Aktual", "Unknown"),
            "label_aktual": row.get("Label_Aktual_Risiko", "Unknown"),
            "prediksi_dataset": row.get("Prediksi_JST", "Unknown"),
            "akurasi_sesuai": row.get("Akurasi_Sesuai", "Unknown"),

            # ─── Hasil Inferensi Real-time ───
            "jst_realtime": jst_result,
            "jst_status": jst_status,
        })

    return {
        "source": "SIMULATION",
        "mode": "DEMO",
        "dataset_path": os.path.basename(DATASET_PATH),
        "total_rows_in_dataset": len(rows),
        "samples_returned": len(results),
        "ai_model_loaded": is_ai_loaded(),
        "results": results
    }


@router.get("/scenarios")
async def list_available_scenarios():
    """
    Mengembalikan daftar skenario gas yang tersedia di dataset
    beserta jumlah sampel tiap skenario.
    """
    rows = _load_dataset()
    if not rows:
        raise HTTPException(
            status_code=503,
            detail="Dataset tidak tersedia."
        )

    # Hitung distribusi
    scenario_counts: dict = {}
    for row in rows:
        bahan = row.get("Bahan_Uji_Aktual", "Unknown")
        if bahan not in scenario_counts:
            scenario_counts[bahan] = {"count": 0, "risk_distribution": {}}
        scenario_counts[bahan]["count"] += 1
        risk = row.get("Label_Aktual_Risiko", "Unknown")
        scenario_counts[bahan]["risk_distribution"][risk] = \
            scenario_counts[bahan]["risk_distribution"].get(risk, 0) + 1

    return {
        "source": "SIMULATION",
        "mode": "DEMO",
        "total_rows": len(rows),
        "scenarios": [
            {
                "bahan_uji": bahan,
                "sample_count": info["count"],
                "risk_distribution": info["risk_distribution"]
            }
            for bahan, info in sorted(scenario_counts.items())
        ]
    }
