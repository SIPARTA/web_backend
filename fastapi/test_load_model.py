import os
import sys
import logging

logging.basicConfig(level=logging.INFO)

print("Python version:", sys.version)

try:
    import tensorflow as tf
    print("TensorFlow version:", tf.__version__)
except Exception as e:
    print("TensorFlow import error:", e)

try:
    from services.ai_service import load_ai_models, is_ai_loaded
    load_ai_models()
    if is_ai_loaded():
        print("Models loaded successfully.")
    else:
        print("Models failed to load.")
except Exception as e:
    print("AI service error:", e)
