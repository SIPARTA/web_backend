from core.config import settings
from services.supabase_service import _get_client
client = _get_client()
res = client.rpc("get_triggers").execute()
print(res)
