from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List
import logging
from services.ai_service import predict_gas_risk
from core.config import settings

logger = logging.getLogger("siparta")

router = APIRouter()

class SensorDataInput(BaseModel):
    mics5524: float
    tgs2600: float
    mq2: float
    mq135: float

@router.post("/predict", tags=["AI Prediction"])
async def predict_risk(data: SensorDataInput):
    """
    Predict risk based on 4 IoT gas sensor voltages.
    Used by IoT or Web Frontend.
    """
    try:
        features = [
            data.mics5524,
            data.tgs2600,
            data.mq2,
            data.mq135
        ]
        
        result = predict_gas_risk(features)
        return {
            "success": True,
            "input": data.model_dump(),
            "ai_analysis": result
        }
    except Exception as e:
        logger.error(f"[PREDICT] AI Engine error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
