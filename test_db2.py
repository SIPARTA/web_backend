import os
from dotenv import load_dotenv
import requests

load_dotenv()
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

headers = {
    "apikey": key,
    "Authorization": f"Bearer {key}"
}

response = requests.get(f"{url}/rest/v1/incident_events?select=*&limit=1", headers=headers)
print("Status Code:", response.status_code)
print("Data:", response.json())
