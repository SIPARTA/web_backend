import tensorflow as tf

print(f"TensorFlow version: {tf.__version__}")

# Load the Keras 3 model
model = tf.keras.models.load_model("models/siparta_ann.keras")
print("Model loaded successfully!")

# Save as .h5 (legacy format, highly compatible)
model.save("models/siparta_ann.h5", save_format='h5')
print("Model saved to siparta_ann.h5")
