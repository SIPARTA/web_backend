import tensorflow as tf
import h5py

print(f"TensorFlow version: {tf.__version__}")

# We will read the weights from the keras model, and build a new model from scratch
# using standard Keras API without quantization_config, then save it as .keras and .h5

model_keras3 = tf.keras.models.load_model("models/siparta_ann.keras")

# Create a fresh model
model = tf.keras.Sequential([
    tf.keras.layers.Dense(16, activation='relu', input_shape=(4,)),
    tf.keras.layers.Dropout(0.2),
    tf.keras.layers.Dense(8, activation='relu'),
    tf.keras.layers.Dense(3, activation='softmax')
])

# Transfer weights
model.set_weights(model_keras3.get_weights())

model.compile(optimizer='adam', loss='categorical_crossentropy', metrics=['accuracy'])

# Save it as .h5
model.save("models/siparta_ann.h5")
print("Saved clean model as .h5")
