import os
from dotenv import load_dotenv

# Load from .env in web_backend
load_dotenv("../../web_backend/.env")

from services.gemini_service import analyze_incident_with_gemini

data = {
    'status': 'WASPADA',
    'timestamp': '2023-10-27T10:00:00Z',
    'sensors': {
        'mics5524': 1.5,
        'tgs2600': 0.8,
        'mq2': 1.2,
        'mq135': 1.1
    }
}

print("Running Gemini API verification...")
response = analyze_incident_with_gemini(data, None)
print("\n--- RESPONSE ---")
print(response)
