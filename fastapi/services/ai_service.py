import os
import joblib
import numpy as np
import tensorflow as tf
import logging

logger = logging.getLogger("siparta.ai_service")

def get_ai_models_dir():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5): # search up to 5 levels up
        potential_path = os.path.join(current_dir, "ai_models")
        if os.path.exists(potential_path) and os.path.isdir(potential_path):
            return potential_path
        current_dir = os.path.dirname(current_dir)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../ai_models"))

AI_MODELS_DIR = get_ai_models_dir()
MODEL_PATH = os.path.join(AI_MODELS_DIR, "model/siparta_ann.h5")
SCALER_PATH = os.path.join(AI_MODELS_DIR, "model/siparta_scaler.pkl")

ann_model = None
scaler = None
ai_load_error = None

class SafeDense(tf.keras.layers.Dense):
    """
    A custom wrapper around Dense to safely ignore Keras 3 specific keys
    when loading Keras 3 models in Keras 2 (TF 2.15) environments.
    """
    @classmethod
    def from_config(cls, config):
        if 'quantization_config' in config:
            del config['quantization_config']
        for init_key in ['kernel_initializer', 'bias_initializer']:
            if init_key in config and isinstance(config[init_key], dict):
                init_config = config[init_key].get('config', {})
                if 'input_axes' in init_config:
                    del init_config['input_axes']
                if 'output_axes' in init_config:
                    del init_config['output_axes']
        return super().from_config(config)

def load_ai_models():
    """Called once at startup to load models into memory"""
    global ann_model, scaler, ai_load_error
    if ann_model is not None and scaler is not None:
        return
        
    try:
        logger.info(f"⏳ [AI Service] Loading JST Model from {MODEL_PATH}...")
        with tf.keras.utils.custom_object_scope({'Dense': SafeDense}):
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
    features: [mics5524, tgs2600, mq2, mq135]
    """
    if ann_model is None or scaler is None:
        raise Exception("AI Model has not been loaded!")
        
    try:
        # Preprocessing (Konsisten dengan Notebook)
        # Clamping input to 0.0 - 5.0
        clamped_features = [max(0.0, min(5.0, v)) for v in features]
        input_data = np.array(clamped_features, dtype=np.float32).reshape(1, -1)
        
        # Scaling
        scaled_data = scaler.transform(input_data).astype(np.float32)
        
        # Inference
        prediction = ann_model.predict(scaled_data, verbose=0)
        
        predicted_class = int(np.argmax(prediction, axis=1)[0])
        confidence = float(np.max(prediction))
        
        # Mapping 
        # Sesuai training: 0=AMAN, 1=WASPADA, 2=BAHAYA
        risk_labels = {
            0: "AMAN",
            1: "WASPADA",
            2: "BAHAYA"
        }
        status = risk_labels.get(predicted_class, "AMAN")
        
        return {
            "status": status,
            "confidence": round(confidence * 100, 2)
        }
    except Exception as e:
        raise Exception(f"Failed to process prediction: {e}")

def is_ai_loaded() -> bool:
    global ann_model, scaler
    if ann_model is None or scaler is None:
        load_ai_models()
    return ann_model is not None and scaler is not None
