import os
import joblib
import numpy as np
import tensorflow as tf
import logging

logger = logging.getLogger("siparta.ai_service")

# Tentukan Path Model berdasarkan Single Source of Truth
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))) # SIPARTA root
AI_MODELS_DIR = os.path.join(BASE_DIR, "ai_models", "model")
LOCAL_MODELS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../models"))

# Cek apakah arsitektur ai_models tersedia (Development / Monorepo)
if os.path.exists(AI_MODELS_DIR) and os.path.exists(os.path.join(AI_MODELS_DIR, "siparta_ann.h5")):
    MODELS_DIR = AI_MODELS_DIR
    logger.info(f"[AI Service] Terintegrasi dengan ai_models: {MODELS_DIR}")
else:
    MODELS_DIR = LOCAL_MODELS_DIR
    logger.info(f"[AI Service] Menggunakan local fallback directory: {MODELS_DIR}")

MODEL_PATH = os.path.join(MODELS_DIR, "siparta_ann.h5")
SCALER_PATH = os.path.join(MODELS_DIR, "siparta_scaler.pkl")

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


class SafeBatchNormalization(tf.keras.layers.BatchNormalization):
    """
    Wrapper untuk BatchNormalization yang menangani perbedaan config antara
    Keras 3 (TF ≥2.16) dan Keras 2 legacy (TF ≤2.15).

    Keras 3 menyimpan parameter: 'synchronized', 'renorm', 'renorm_clipping',
    'renorm_momentum' ke dalam config JSON model (.h5/.keras).
    Keras 2 legacy tidak mengenali parameter tersebut → TypeError saat
    deserialisasi.

    Wrapper ini HANYA membuang parameter yang tidak dikenali, tanpa mengubah
    arsitektur atau bobot layer BatchNormalization.
    """
    # Parameter Keras 3 yang tidak ada di Keras 2
    _KERAS3_ONLY_KEYS = {
        'synchronized', 'renorm', 'renorm_clipping', 'renorm_momentum'
    }

    @classmethod
    def from_config(cls, config):
        # Deteksi parameter asing dengan introspeksi parent __init__
        import inspect
        parent_init_params = set(
            inspect.signature(tf.keras.layers.BatchNormalization.__init__).parameters.keys()
        )

        cleaned_config = {}
        removed_keys = []
        for key, value in config.items():
            if key in parent_init_params or key in ('name', 'trainable', 'dtype'):
                cleaned_config[key] = value
            elif key in cls._KERAS3_ONLY_KEYS:
                removed_keys.append(key)
                # Tidak di-include, tapi di-log
            else:
                # Parameter tidak dikenal dan bukan dari daftar Keras 3 yang diketahui
                # Tetap masukkan agar error aslinya tetap muncul (jangan sembunyikan)
                cleaned_config[key] = value

        if removed_keys:
            logger.info(
                f"[SafeBatchNormalization] Stripped Keras 3-only keys "
                f"not supported by runtime: {removed_keys}"
            )

        # Handle 'dtype' DTypePolicy format dari Keras 3
        if 'dtype' in cleaned_config:
            dtype_val = cleaned_config['dtype']
            if isinstance(dtype_val, dict) and 'config' in dtype_val:
                cleaned_config['dtype'] = dtype_val['config'].get('name', 'float32')

        return super().from_config(cleaned_config)


def load_ai_models():
    """Called once at startup to load models into memory"""
    global ann_model, scaler, ai_load_error
    if ann_model is not None and scaler is not None:
        return
        
    try:
        logger.info(f"⏳ [AI Service] Loading JST Model from {MODEL_PATH}...")
        custom_objects = {
            'Dense': SafeDense,
            'BatchNormalization': SafeBatchNormalization,
        }
        with tf.keras.utils.custom_object_scope(custom_objects):
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
        # Clamping input to 0.0 - 65535.0 (RAW ADC)
        clamped_features = [max(0.0, min(65535.0, v)) for v in features]
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
        status = risk_labels.get(predicted_class, "MODEL_ERROR")
        
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
