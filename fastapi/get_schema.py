from dotenv import load_dotenv
load_dotenv()
from services import supabase_service as db
r = db._get_client().table("incident_events").select("*").limit(1).execute()
print(list(r.data[0].keys()) if r.data else "No rows")
