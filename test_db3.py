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

# Get OpenAPI specification to see all tables and columns
response = requests.get(f"{url}/rest/v1/", headers=headers)
print("Status Code:", response.status_code)
openapi = response.json()
if 'definitions' in openapi:
    for table, schema in openapi['definitions'].items():
        print(f"\nTable: {table}")
        if 'properties' in schema:
            for col, details in schema['properties'].items():
                print(f"  - {col}: {details.get('type', 'unknown')}")
