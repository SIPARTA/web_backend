import os
import joblib
import numpy as np
import tensorflow as tf
import logging

logger = logging.getLogger(__name__)

# Initialize global variables
MODEL_PATH = os.path.join(os.path.dirname(__file__), "../models/siparta_ann.h5")
SCALER_PATH = os.path.join(os.path.dirname(__file__), "../models/siparta_scaler.pkl")

ann_model = None
scaler = None
ai_load_error = None

def load_ai_models():
    """Called once at startup to load models into memory"""
    global ann_model, scaler, ai_load_error
    if ann_model is not None and scaler is not None:
        return
        
    try:
        logger.info(f"⏳ [AI Service] Loading JST Model from {MODEL_PATH}...")
        ann_model = tf.keras.models.load_model(MODEL_PATH)
        logger.info(f"⏳ [AI Service] Loading Scaler from {SCALER_PATH}...")
        scaler = joblib.load(SCALER_PATH)
        ai_load_error = None
        logger.info("✅ [AI Service] JST Model & Scaler successfully loaded into memory!")
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        ai_load_error = f"{str(e)} | Details: {error_details}"
        logger.error(f"❌ [AI Service] Failed to load model: {error_details}")

def predict_gas_risk(features: list) -> dict:
    """
    Predict risk based on sensor data.
    features: [pemutih, amonia, cuka, sabun, hcl, air]
    """
    if ann_model is None or scaler is None:
        raise Exception("AI Model has not been loaded!")
        
    try:
        # 1. Convert to Numpy Array and Reshape (1, n_features)
        input_data = np.array(features).reshape(1, -1)
        
        # 2. Scale the data
        scaled_data = scaler.transform(input_data)
        
        # 3. Predict with JST
        prediction = ann_model.predict(scaled_data, verbose=0)
        
        # 4. Get the class with highest probability
        predicted_class = int(np.argmax(prediction, axis=1)[0])
        confidence = float(np.max(prediction))
        
        # 5. Result mapping
        risk_labels = {
            0: "Aman - Tidak menghasilkan gas beracun",
            1: "Sedang - Potensi iritasi ringan",
            2: "Tinggi - Menghasilkan gas beracun berbahaya"
        }
        
        return {
            "risk_level": predicted_class,
            "description": risk_labels.get(predicted_class, "Unknown"),
            "confidence": round(confidence * 100, 2)
        }
    except Exception as e:
        raise Exception(f"Failed to process prediction: {e}")

def is_ai_loaded() -> bool:
    """Returns True if the AI models are successfully loaded in memory."""
    global ann_model, scaler
    if ann_model is None or scaler is None:
        load_ai_models()
    return ann_model is not None and scaler is not None
